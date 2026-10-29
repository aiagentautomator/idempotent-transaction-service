from typing import Tuple, Optional, Dict, Any
from src.storage.base import BaseStorage
from src.models import TransactionRequest, TransactionStatus


class IdempotencyManager:
    """
    Guarantees strict exactly-once transaction semantics (L2-FR-05, L2-FR-06).
    Enforces deduplication at two distinct levels:
      1. requestId (Idempotency Key level)
      2. transactionId (Business Entity level)
    """

    def __init__(self, storage: BaseStorage):
        self.storage = storage

    def check_duplicate(self, req: TransactionRequest) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_duplicate: bool, reason: Optional[str])
        """
        # 1. Check idempotency store for existing requestId
        idem = self.storage.get_idempotency_record(req.requestId)
        if idem:
            return True, f"Duplicate requestId '{req.requestId}' detected (status={idem['status']})"

        # 2. Check transaction store for existing business transactionId
        existing_txn = self.storage.get_transaction(req.transactionId)
        if existing_txn:
            if existing_txn.status in (TransactionStatus.PROCESSED, TransactionStatus.PENDING, TransactionStatus.PROCESSING):
                return True, f"Duplicate transactionId '{req.transactionId}' already registered with status={existing_txn.status.value}"

        return False, None

    def register_in_flight(self, req: TransactionRequest) -> None:
        """Mark request as in-flight to protect against concurrent duplicate bursts."""
        self.storage.save_idempotency_record(
            request_id=req.requestId,
            transaction_id=req.transactionId,
            account_id=req.accountId,
            status="IN_FLIGHT"
        )

    def mark_completed(self, req: TransactionRequest, response_data: Dict[str, Any]) -> None:
        import json
        self.storage.save_idempotency_record(
            request_id=req.requestId,
            transaction_id=req.transactionId,
            account_id=req.accountId,
            status="COMPLETED",
            response_payload=json.dumps(response_data)
        )

