import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from enum import Enum
from src.storage.base import BaseStorage
from src.models import (
    TransactionRequest,
    TransactionRecord,
    AccountRecord,
    TransactionStatus,
    TransactionType,
    ProcessingSummary
)
from src.engine.validator import TransactionValidator
from src.engine.idempotency_manager import IdempotencyManager
from src.engine.sequence_buffer import SequenceBuffer
from src.engine.retry_handler import RetryHandler
from src.adapters.base import BaseIngestionAdapter

logger = logging.getLogger("TransactionProcessor")


class OrderingScope(str, Enum):
    GLOBAL = "GLOBAL"                # Global sequence across the input batch (matches Section 9.8 test data)
    ACCOUNT = "ACCOUNT"              # Partitioned sequence per individual account


class TransactionProcessor:
    """
    Core Enterprise Background Transaction Processing Service.
    Coordinates Ingestion, Validation, Idempotency, Out-of-Order Sequence Resolution,
    Ledger Execution, and Transient Failure Retries.
    """

    def __init__(
        self,
        storage: BaseStorage,
        sequence_buffer: Optional[SequenceBuffer] = None,
        retry_handler: Optional[RetryHandler] = None,
        ordering_scope: OrderingScope = OrderingScope.GLOBAL
    ):
        self.storage = storage
        self.sequence_buffer = sequence_buffer or SequenceBuffer()
        self.retry_handler = retry_handler or RetryHandler(max_retries=3)
        self.idempotency_manager = IdempotencyManager(storage)
        self.ordering_scope = ordering_scope
        self.last_global_sequence: int = 0
        self.summary = ProcessingSummary()

    def process_batch(self, adapter: BaseIngestionAdapter) -> ProcessingSummary:
        """Processes all transaction requests from the provided ingestion adapter."""
        for raw_payload in adapter.read_requests():
            self.process_single_raw(raw_payload)

        # Build final report
        self._compile_summary()
        return self.summary

    def process_single_raw(self, raw_payload: Dict[str, Any]) -> TransactionRecord:
        """Processes a single raw request dictionary through the pipeline."""
        self.summary.totalReceived += 1
        txn_id = raw_payload.get("transactionId", "UNKNOWN")
        req_id = raw_payload.get("requestId", "UNKNOWN")
        seq = raw_payload.get("sequenceNumber", 0) or 0

        # 1. Validation (L2-FR-02)
        req, err = TransactionValidator.validate_raw(raw_payload)
        if err or not req:
            logger.warning(f"[REJECTED] Validation failed for {txn_id}: {err}")
            failed_record = TransactionRecord(
                transactionId=txn_id,
                requestId=req_id,
                accountId=raw_payload.get("accountId", "UNKNOWN"),
                sequenceNumber=seq,
                transactionType=TransactionType.CREDIT if raw_payload.get("transactionType") == "CREDIT" else TransactionType.DEBIT,
                amount=float(raw_payload.get("amount", 0.0) or 0.0),
                currency=raw_payload.get("currency", "USD"),
                status=TransactionStatus.FAILED,
                failureReason=err
            )
            self.storage.save_transaction(failed_record)
            self.summary.failedCount += 1

            # If global sequence was waiting on this sequence, advance to prevent deadlocks
            if self.ordering_scope == OrderingScope.GLOBAL and seq == self.last_global_sequence + 1:
                self.last_global_sequence = seq
                self._drain_buffered(account=None)

            return failed_record

        # 2. Idempotency Check (L2-FR-05, L2-FR-06)
        is_dup, dup_reason = self.idempotency_manager.check_duplicate(req)
        if is_dup:
            logger.info(f"[DUPLICATE] Request {req.requestId} for {req.transactionId}: {dup_reason}")
            dup_record = TransactionRecord(
                transactionId=req.transactionId,
                requestId=req.requestId,
                accountId=req.accountId,
                sequenceNumber=req.sequenceNumber,
                transactionType=req.transactionType,
                amount=req.amount,
                currency=req.currency,
                status=TransactionStatus.DUPLICATE,
                failureReason=dup_reason
            )
            self.summary.duplicateCount += 1
            return dup_record

        # 3. Register In-Flight Idempotency lock
        self.idempotency_manager.register_in_flight(req)

        # 4. Create Initial Transaction Record in RECEIVED state
        record = TransactionRecord(
            transactionId=req.transactionId,
            requestId=req.requestId,
            accountId=req.accountId,
            sequenceNumber=req.sequenceNumber,
            transactionType=req.transactionType,
            amount=req.amount,
            currency=req.currency,
            status=TransactionStatus.RECEIVED
        )
        self.storage.save_transaction(record)

        # 5. Route through Ordering Engine (L2-FR-07)
        return self._route_or_buffer(req, record)

    def _route_or_buffer(self, req: TransactionRequest, record: TransactionRecord) -> TransactionRecord:
        """Determines whether to execute immediately or buffer pending missing sequences."""
        account = self.storage.get_account(req.accountId)
        if not account:
            account = AccountRecord(
                accountId=req.accountId,
                currency=req.currency,
                currentBalance=0.0,
                lastProcessedSequence=0
            )
            self.storage.save_account(account)

        if self.ordering_scope == OrderingScope.GLOBAL:
            expected_sequence = self.last_global_sequence + 1
            buffer_key = "__GLOBAL__"
        else:
            expected_sequence = account.lastProcessedSequence + 1
            buffer_key = account.accountId

        if req.sequenceNumber == expected_sequence:
            # Expected sequence arrived! Execute ledger update
            executed_record = self._execute_transaction(req, record, account)
            # After executing, drain any buffered subsequent sequences
            self._drain_buffered(account if self.ordering_scope == OrderingScope.ACCOUNT else None)
            return executed_record

        elif req.sequenceNumber > expected_sequence:
            # Out-of-order gap: buffer request until missing sequence arrives
            logger.info(f"[OUT_OF_ORDER] {req.transactionId} (Seq {req.sequenceNumber}) arrived early. Expected: {expected_sequence}. Buffering.")
            record.status = TransactionStatus.PENDING
            record.failureReason = f"Waiting for sequence {expected_sequence}"
            self.storage.save_transaction(record)
            # Store in buffer
            req_copy = req.model_copy()
            if self.ordering_scope == OrderingScope.GLOBAL:
                req_copy.accountId = buffer_key
            self.sequence_buffer.buffer_request(req_copy)
            self.summary.pendingCount += 1
            return record

        else:
            # Sequence already superseded: duplicate / stale event
            record.status = TransactionStatus.DUPLICATE
            record.failureReason = f"Sequence {req.sequenceNumber} already superseded by {expected_sequence - 1}"
            self.storage.save_transaction(record)
            self.summary.duplicateCount += 1
            return record

    def _execute_transaction(self, req: TransactionRequest, record: TransactionRecord, account: AccountRecord) -> TransactionRecord:
        """Executes business state transition, balance arithmetic, and resilience handling."""
        record.status = TransactionStatus.PROCESSING
        self.storage.save_transaction(record)

        # 6. Resilience Simulation (L2-FR-08, L2-FR-09)
        if req.simulateTransientError and record.retryCount == 0:
            logger.warning(f"[TRANSIENT_FAILURE] Simulating failure for {req.transactionId} (Attempt 1)")
            record.retryCount += 1
            record.status = TransactionStatus.RETRY_PENDING
            record.failureReason = "Simulated transient network timeout"
            self.storage.save_transaction(record)
            self.summary.retryPendingCount += 1

            # Auto-retry once to simulate successful recovery
            return self.retry_transaction(req, record, account)

        # Apply Balance Mutation
        old_balance = account.currentBalance
        if req.transactionType == TransactionType.CREDIT:
            account.currentBalance += req.amount
        elif req.transactionType == TransactionType.DEBIT:
            account.currentBalance -= req.amount
        elif req.transactionType == TransactionType.REVERSAL:
            account.currentBalance -= req.amount

        account.currentBalance = round(account.currentBalance, 4)
        account.lastProcessedSequence = req.sequenceNumber
        account.updatedAt = datetime.utcnow()
        self.storage.save_account(account)

        if self.ordering_scope == OrderingScope.GLOBAL:
            self.last_global_sequence = req.sequenceNumber

        # Finalize Transaction
        record.status = TransactionStatus.PROCESSED
        record.failureReason = None
        record.updatedAt = datetime.utcnow()
        self.storage.save_transaction(record)

        # Finalize Idempotency record
        self.idempotency_manager.mark_completed(req, {
            "transactionId": req.transactionId,
            "status": "PROCESSED",
            "previousBalance": old_balance,
            "newBalance": account.currentBalance
        })

        self.summary.processedCount += 1
        logger.info(f"[PROCESSED] {req.transactionId} (Seq {req.sequenceNumber}) for {account.accountId}: {req.transactionType.value} {req.amount} {req.currency}. New Balance: {account.currentBalance}")
        return record

    def retry_transaction(self, req: TransactionRequest, record: TransactionRecord, account: AccountRecord) -> TransactionRecord:
        """Retries a transiently failed transaction safely without duplicate side-effects."""
        logger.info(f"[RETRYING] Attempt {record.retryCount + 1} for {req.transactionId}")
        record.retryCount += 1
        self.summary.retryPendingCount = max(0, self.summary.retryPendingCount - 1)

        # For the simulation test data, retry succeeds
        req.simulateTransientError = False
        return self._execute_transaction(req, record, account)

    def _drain_buffered(self, account: Optional[AccountRecord]) -> None:
        """Cascading drain: processes all consecutive pending sequence numbers from the buffer."""
        buffer_key = account.accountId if account else "__GLOBAL__"

        while True:
            if self.ordering_scope == OrderingScope.GLOBAL:
                next_seq = self.last_global_sequence + 1
            else:
                next_seq = account.lastProcessedSequence + 1

            buffered_req = self.sequence_buffer.pop_buffered(buffer_key, next_seq)
            if not buffered_req:
                break

            logger.info(f"[UNBLOCKING] Sequence {next_seq} unblocked from buffer!")
            buffered_record = self.storage.get_transaction(buffered_req.transactionId)
            if buffered_record and buffered_record.status == TransactionStatus.PENDING:
                self.summary.pendingCount = max(0, self.summary.pendingCount - 1)
                # Recover original account if was mapped to __GLOBAL__
                original_acc_id = buffered_record.accountId
                target_account = self.storage.get_account(original_acc_id)
                if not target_account:
                    target_account = AccountRecord(accountId=original_acc_id, currency=buffered_record.currency)
                    self.storage.save_account(target_account)
                buffered_req.accountId = original_acc_id
                self._execute_transaction(buffered_req, buffered_record, target_account)

    def _compile_summary(self) -> None:
        """Populates account states and transaction audit in the final summary."""
        accounts = self.storage.list_accounts()
        self.summary.accounts = {
            acc.accountId: {
                "currency": acc.currency,
                "currentBalance": acc.currentBalance,
                "lastProcessedSequence": acc.lastProcessedSequence
            }
            for acc in accounts
        }
        txns = self.storage.list_transactions()
        self.summary.transactionAudit = [
            {
                "transactionId": t.transactionId,
                "requestId": t.requestId,
                "accountId": t.accountId,
                "sequence": t.sequenceNumber,
                "type": t.transactionType.value,
                "amount": t.amount,
                "status": t.status.value,
                "retryCount": t.retryCount,
                "failureReason": t.failureReason
            }
            for t in txns
        ]
