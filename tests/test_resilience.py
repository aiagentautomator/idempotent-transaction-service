import pytest
from src.storage.sqlite_store import SQLiteStorage
from src.engine.processor import TransactionProcessor, OrderingScope
from src.models import TransactionStatus


@pytest.fixture
def processor():
    storage = SQLiteStorage(":memory:")
    return TransactionProcessor(storage=storage, ordering_scope=OrderingScope.GLOBAL)


def test_simulated_transient_failure_and_successful_retry(processor):
    """L2-FR-08 & 09: Simulates transient failure, retries without duplicate effect."""
    payload = {
        "transactionId": "TXN-RETRY-1",
        "requestId": "REQ-RETRY-1",
        "sequenceNumber": 1,
        "accountId": "ACC-RES",
        "transactionType": "CREDIT",
        "amount": 250.0,
        "currency": "USD",
        "simulateTransientError": True
    }

    rec = processor.process_single_raw(payload)
    assert rec.status == TransactionStatus.PROCESSED
    assert rec.retryCount == 2  # Attempt 1 failed, Attempt 2 succeeded

    acc = processor.storage.get_account("ACC-RES")
    assert acc.currentBalance == 250.0
    assert acc.lastProcessedSequence == 1


def test_retry_exhaustion_leads_to_terminal_failed_state():
    """Verify that exceeding maxRetries marks transaction as FAILED."""
    from src.engine.retry_handler import RetryHandler
    handler = RetryHandler(max_retries=2)
    from src.models import TransactionRecord, TransactionType

    record = TransactionRecord(
        transactionId="TXN-FAIL-MAX",
        requestId="REQ-FAIL-MAX",
        accountId="ACC-EX",
        sequenceNumber=1,
        transactionType=TransactionType.CREDIT,
        amount=100.0,
        currency="USD",
        retryCount=2,  # already at max
        maxRetries=2
    )

    should_retry, status = handler.should_retry(record, is_transient_failure=True)
    assert not should_retry
    assert status == TransactionStatus.FAILED

