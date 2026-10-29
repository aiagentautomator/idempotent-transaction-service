from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from src.models import TransactionRecord, AccountRecord, TransactionStatus


class BaseStorage(ABC):
    """Abstract Storage Interface for Idempotency, Transaction, and Ledger state."""

    @abstractmethod
    def get_account(self, account_id: str) -> Optional[AccountRecord]:
        """Fetch account record by ID."""
        pass

    @abstractmethod
    def save_account(self, account: AccountRecord) -> None:
        """Create or update account record."""
        pass

    @abstractmethod
    def get_transaction(self, transaction_id: str) -> Optional[TransactionRecord]:
        """Fetch transaction by business transactionId."""
        pass

    @abstractmethod
    def get_idempotency_record(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Check if request_id has already been processed or is in-flight."""
        pass

    @abstractmethod
    def save_idempotency_record(self, request_id: str, transaction_id: str, account_id: str, status: str, response_payload: Optional[str] = None) -> None:
        """Record idempotency key execution."""
        pass

    @abstractmethod
    def save_transaction(self, record: TransactionRecord) -> None:
        """Persist or update transaction record state."""
        pass

    @abstractmethod
    def list_transactions(self) -> List[TransactionRecord]:
        """List all transactions for audit report."""
        pass

    @abstractmethod
    def list_accounts(self) -> List[AccountRecord]:
        """List all accounts with current balances and sequences."""
        pass

