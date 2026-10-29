import sqlite3
import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from src.storage.base import BaseStorage
from src.models import TransactionRecord, AccountRecord, TransactionStatus, TransactionType


class SQLiteStorage(BaseStorage):
    """
    Open-source ACID-compliant SQLite implementation of Transaction & Idempotency Store.
    Supports in-memory mode (for ephemeral test runs) or file-based mode.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    current_balance REAL NOT NULL DEFAULT 0.0,
                    last_processed_sequence INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
            """)

            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS idempotency_keys (
                    request_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_payload TEXT,
                    created_at TEXT NOT NULL
                );
            """)

            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL,
                    transaction_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    failure_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
                );
            """)
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_req ON transactions(request_id);")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_acc_seq ON transactions(account_id, sequence_number);")

    def get_account(self, account_id: str) -> Optional[AccountRecord]:
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return AccountRecord(
            accountId=row["account_id"],
            currency=row["currency"],
            currentBalance=row["current_balance"],
            lastProcessedSequence=row["last_processed_sequence"],
            updatedAt=datetime.fromisoformat(row["updated_at"])
        )

    def save_account(self, account: AccountRecord) -> None:
        with self._conn:
            self._conn.execute("""
                INSERT INTO accounts (account_id, currency, current_balance, last_processed_sequence, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    currency = excluded.currency,
                    current_balance = excluded.current_balance,
                    last_processed_sequence = excluded.last_processed_sequence,
                    updated_at = excluded.updated_at;
            """, (
                account.accountId,
                account.currency,
                account.currentBalance,
                account.lastProcessedSequence,
                account.updatedAt.isoformat()
            ))

    def get_transaction(self, transaction_id: str) -> Optional[TransactionRecord]:
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE transaction_id = ?", (transaction_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_transaction(row)

    def get_idempotency_record(self, request_id: str) -> Optional[Dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM idempotency_keys WHERE request_id = ?", (request_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "requestId": row["request_id"],
            "transactionId": row["transaction_id"],
            "accountId": row["account_id"],
            "status": row["status"],
            "responsePayload": json.loads(row["response_payload"]) if row["response_payload"] else None,
            "createdAt": row["created_at"]
        }

    def save_idempotency_record(self, request_id: str, transaction_id: str, account_id: str, status: str, response_payload: Optional[str] = None) -> None:
        with self._conn:
            self._conn.execute("""
                INSERT INTO idempotency_keys (request_id, transaction_id, account_id, status, response_payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    status = excluded.status,
                    response_payload = excluded.response_payload;
            """, (
                request_id,
                transaction_id,
                account_id,
                status,
                response_payload,
                datetime.utcnow().isoformat()
            ))

    def save_transaction(self, record: TransactionRecord) -> None:
        with self._conn:
            self._conn.execute("""
                INSERT INTO transactions (
                    transaction_id, request_id, account_id, sequence_number,
                    transaction_type, amount, currency, status,
                    retry_count, max_retries, failure_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(transaction_id) DO UPDATE SET
                    status = excluded.status,
                    retry_count = excluded.retry_count,
                    failure_reason = excluded.failure_reason,
                    updated_at = excluded.updated_at;
            """, (
                record.transactionId,
                record.requestId,
                record.accountId,
                record.sequenceNumber,
                record.transactionType.value,
                record.amount,
                record.currency,
                record.status.value,
                record.retryCount,
                record.maxRetries,
                record.failureReason,
                record.createdAt.isoformat(),
                record.updatedAt.isoformat()
            ))

    def list_transactions(self) -> List[TransactionRecord]:
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM transactions ORDER BY created_at ASC")
        return [self._row_to_transaction(r) for r in cursor.fetchall()]

    def list_accounts(self) -> List[AccountRecord]:
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM accounts ORDER BY account_id ASC")
        return [
            AccountRecord(
                accountId=r["account_id"],
                currency=r["currency"],
                currentBalance=r["current_balance"],
                lastProcessedSequence=r["last_processed_sequence"],
                updatedAt=datetime.fromisoformat(r["updated_at"])
            )
            for r in cursor.fetchall()
        ]

    def _row_to_transaction(self, row: sqlite3.Row) -> TransactionRecord:
        return TransactionRecord(
            transactionId=row["transaction_id"],
            requestId=row["request_id"],
            accountId=row["account_id"],
            sequenceNumber=row["sequence_number"],
            transactionType=TransactionType(row["transaction_type"]),
            amount=row["amount"],
            currency=row["currency"],
            status=TransactionStatus(row["status"]),
            retryCount=row["retry_count"],
            maxRetries=row["max_retries"],
            failureReason=row["failure_reason"],
            createdAt=datetime.fromisoformat(row["created_at"]),
            updatedAt=datetime.fromisoformat(row["updated_at"])
        )

    def close(self) -> None:
        self._conn.close()

