from typing import Tuple
from src.models import TransactionRecord, TransactionStatus


class RetryHandler:
    """
    Manages resilience, simulated transient network/downstream failures,
    and retry budgets (L2-FR-08, L2-FR-09).
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def should_retry(self, record: TransactionRecord, is_transient_failure: bool) -> Tuple[bool, TransactionStatus]:
        """
        Determines if a failed transaction should transition to RETRY_PENDING or FAILED.
        """
        if not is_transient_failure:
            return False, TransactionStatus.FAILED

        if record.retryCount < self.max_retries:
            return True, TransactionStatus.RETRY_PENDING
        else:
            return False, TransactionStatus.FAILED

