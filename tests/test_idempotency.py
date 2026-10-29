import pytest
from src.storage.sqlite_store import SQLiteStorage
from src.engine.processor import TransactionProcessor, OrderingScope
from src.models import TransactionRequest, TransactionType, TransactionStatus


@pytest.fixture
def processor():
    storage = SQLiteStorage(":memory:")
    return TransactionProcessor(storage=storage, ordering_scope=OrderingScope.GLOBAL)


def test_idempotent_duplicate_request_id(processor):
    """Verify that submitting the identical requestId multiple times is ignored safely."""
    req1 = {
        "transactionId": "TXN-101",
        "requestId": "REQ-101",
        "sequenceNumber": 1,
        "accountId": "ACC-TEST",
        "transactionType": "CREDIT",
        "amount": 100.0,
        "currency": "USD"
    }

    # First attempt: should process
    rec1 = processor.process_single_raw(req1)
    assert rec1.status == TransactionStatus.PROCESSED

    # Check balance
    acc = processor.storage.get_account("ACC-TEST")
    assert acc.currentBalance == 100.0

    # Second attempt: exact duplicate
    rec2 = processor.process_single_raw(req1)
    assert rec2.status == TransactionStatus.DUPLICATE

    # Balance must remain exactly 100.0 (no double credit)
    acc = processor.storage.get_account("ACC-TEST")
    assert acc.currentBalance == 100.0


def test_idempotent_duplicate_transaction_id_different_request_id(processor):
    """Verify that reusing a transactionId with a different requestId is caught as duplicate."""
    req1 = {
        "transactionId": "TXN-202",
        "requestId": "REQ-A",
        "sequenceNumber": 1,
        "accountId": "ACC-TEST",
        "transactionType": "CREDIT",
        "amount": 50.0,
        "currency": "USD"
    }
    req2 = {
        "transactionId": "TXN-202",
        "requestId": "REQ-B",
        "sequenceNumber": 2,
        "accountId": "ACC-TEST",
        "transactionType": "CREDIT",
        "amount": 50.0,
        "currency": "USD"
    }

    rec1 = processor.process_single_raw(req1)
    assert rec1.status == TransactionStatus.PROCESSED

    rec2 = processor.process_single_raw(req2)
    assert rec2.status == TransactionStatus.DUPLICATE

    acc = processor.storage.get_account("ACC-TEST")
    assert acc.currentBalance == 50.0

