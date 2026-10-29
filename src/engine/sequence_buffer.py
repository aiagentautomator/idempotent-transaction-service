from typing import Dict, List, Optional
from collections import defaultdict
from src.models import TransactionRequest


class SequenceBuffer:
    """
    Partitioned Out-of-Order Sequence Buffer (L2-FR-07).
    Maintains an in-memory priority staging area per account.
    If an event arrives with sequence > expected, it is parked here until
    the preceding sequence arrives, triggering an automatic cascading drain.
    """

    def __init__(self):
        # account_id -> { sequenceNumber: TransactionRequest }
        self._buffers: Dict[str, Dict[int, TransactionRequest]] = defaultdict(dict)

    def buffer_request(self, req: TransactionRequest) -> None:
        """Hold a premature transaction request in the account's pending buffer."""
        self._buffers[req.accountId][req.sequenceNumber] = req

    def get_buffered(self, account_id: str, sequence_number: int) -> Optional[TransactionRequest]:
        """Retrieve a specific buffered transaction for an account."""
        return self._buffers[account_id].get(sequence_number)

    def pop_buffered(self, account_id: str, sequence_number: int) -> Optional[TransactionRequest]:
        """Extract and remove a transaction from the pending buffer once ready to process."""
        return self._buffers[account_id].pop(sequence_number, None)

    def list_pending_sequences(self, account_id: str) -> List[int]:
        """Return sorted list of pending sequence numbers for the account."""
        return sorted(self._buffers[account_id].keys())

    def pending_count(self) -> int:
        """Total count of transactions currently waiting in buffers across all accounts."""
        return sum(len(seq_dict) for seq_dict in self._buffers.values())

    def clear(self) -> None:
        self._buffers.clear()

