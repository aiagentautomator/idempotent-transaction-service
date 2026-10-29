import pytest
from src.storage.sqlite_store import SQLiteStorage
from src.engine.processor import TransactionProcessor, OrderingScope
from src.models import TransactionStatus


@pytest.fixture
def processor():
    storage = SQLiteStorage(":memory:")
    return TransactionProcessor(storage=storage, ordering_scope=OrderingScope.GLOBAL)


def test_out_of_order_buffering_and_cascading_drain(processor):
    """
    Simulate arrival of Seq 3, then Seq 2, then Seq 1.
    Seq 3 & Seq 2 must wait in PENDING state until Seq 1 arrives,
    then automatically cascade and process all in order: 1 -> 2 -> 3.
    """
    req3 = {
        "transactionId": "TXN-3",
        "requestId": "REQ-3",
        "sequenceNumber": 3,
        "accountId": "ACC-ORD",
        "transactionType": "CREDIT",
        "amount": 30.0,
        "currency": "USD"
    }
    req2 = {
        "transactionId": "TXN-2",
        "requestId": "REQ-2",
        "sequenceNumber": 2,
        "accountId": "ACC-ORD",
        "transactionType": "DEBIT",
        "amount": 20.0,
        "currency": "USD"
    }
    req1 = {
        "transactionId": "TXN-1",
        "requestId": "REQ-1",
        "sequenceNumber": 1,
        "accountId": "ACC-ORD",
        "transactionType": "CREDIT",
        "amount": 100.0,
        "currency": "USD"
    }

    # Step 1: Send Seq 3 -> should be PENDING
    rec3 = processor.process_single_raw(req3)
    assert rec3.status == TransactionStatus.PENDING
    assert processor.sequence_buffer.pending_count() == 1

    # Step 2: Send Seq 2 -> should be PENDING
    rec2 = processor.process_single_raw(req2)
    assert rec2.status == TransactionStatus.PENDING
    assert processor.sequence_buffer.pending_count() == 2

    # Account balance before Seq 1 should still be 0
    acc = processor.storage.get_account("ACC-ORD")
    assert acc is None or acc.currentBalance == 0.0

    # Step 3: Send Seq 1 -> should process immediately and trigger drain
    rec1 = processor.process_single_raw(req1)
    assert rec1.status == TransactionStatus.PROCESSED

    # Buffer should now be completely drained
    assert processor.sequence_buffer.pending_count() == 0

    # Verify that rec2 and rec3 were updated to PROCESSED in storage
    stored_rec2 = processor.storage.get_transaction("TXN-2")
    stored_rec3 = processor.storage.get_transaction("TXN-3")
    assert stored_rec2.status == TransactionStatus.PROCESSED
    assert stored_rec3.status == TransactionStatus.PROCESSED

    # Final balance: 100 - 20 + 30 = 110.0
    final_acc = processor.storage.get_account("ACC-ORD")
    assert final_acc.currentBalance == 110.0
    assert final_acc.lastProcessedSequence == 3

