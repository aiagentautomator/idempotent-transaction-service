import pytest
from src.storage.sqlite_store import SQLiteStorage
from src.engine.processor import TransactionProcessor, OrderingScope
from src.models import TransactionStatus


@pytest.fixture
def processor():
    storage = SQLiteStorage(":memory:")
    return TransactionProcessor(storage=storage, ordering_scope=OrderingScope.GLOBAL)


def test_reject_negative_amount(processor):
    payload = {
        "transactionId": "TXN-INV-1",
        "requestId": "REQ-INV-1",
        "sequenceNumber": 1,
        "accountId": "ACC-INV",
        "transactionType": "DEBIT",
        "amount": -50.0,
        "currency": "USD"
    }
    rec = processor.process_single_raw(payload)
    assert rec.status == TransactionStatus.FAILED
    assert "Amount must be strictly positive" in rec.failureReason


def test_reject_zero_amount(processor):
    payload = {
        "transactionId": "TXN-INV-2",
        "requestId": "REQ-INV-2",
        "sequenceNumber": 1,
        "accountId": "ACC-INV",
        "transactionType": "CREDIT",
        "amount": 0.0,
        "currency": "USD"
    }
    rec = processor.process_single_raw(payload)
    assert rec.status == TransactionStatus.FAILED
    assert "Amount must be strictly positive" in rec.failureReason


def test_reject_invalid_sequence_number(processor):
    payload = {
        "transactionId": "TXN-INV-3",
        "requestId": "REQ-INV-3",
        "sequenceNumber": 0,
        "accountId": "ACC-INV",
        "transactionType": "CREDIT",
        "amount": 10.0,
        "currency": "USD"
    }
    rec = processor.process_single_raw(payload)
    assert rec.status == TransactionStatus.FAILED
    assert "sequenceNumber must be >= 1" in rec.failureReason


def test_validation_isolation_does_not_block_subsequent_valid_records(processor):
    """L2-FR-12: Isolation test - invalid record does not stop the batch."""
    invalid_req = {
        "transactionId": "TXN-BAD",
        "requestId": "REQ-BAD",
        "sequenceNumber": 1,
        "accountId": "ACC-ISO",
        "transactionType": "DEBIT",
        "amount": -20.0,
        "currency": "USD"
    }
    valid_req = {
        "transactionId": "TXN-GOOD",
        "requestId": "REQ-GOOD",
        "sequenceNumber": 2,
        "accountId": "ACC-ISO",
        "transactionType": "CREDIT",
        "amount": 50.0,
        "currency": "USD"
    }

    rec1 = processor.process_single_raw(invalid_req)
    assert rec1.status == TransactionStatus.FAILED

    rec2 = processor.process_single_raw(valid_req)
    assert rec2.status == TransactionStatus.PROCESSED

    acc = processor.storage.get_account("ACC-ISO")
    assert acc.currentBalance == 50.0

