import argparse
import sys
import os
import json
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.storage.sqlite_store import SQLiteStorage
from src.adapters.json_adapter import JsonIngestionAdapter
from src.adapters.csv_adapter import CsvIngestionAdapter
from src.engine.processor import TransactionProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("MainCLI")


def print_banner():
    print("""
================================================================================
   PRACTICAL FDE L2: IDEMPOTENT BACKGROUND TRANSACTION PROCESSING SERVICE
================================================================================
    """)


def print_summary_table(summary):
    print("\n" + "=" * 80)
    print("                      OPERATIONAL PROCESSING REPORT")
    print("=" * 80)
    print(f" Total Ingested : {summary.totalReceived}")
    print(f" PROCESSED      : {summary.processedCount}")
    print(f" DUPLICATE      : {summary.duplicateCount}")
    print(f" FAILED         : {summary.failedCount}")
    print(f" PENDING        : {summary.pendingCount}")
    print(f" RETRY_PENDING  : {summary.retryPendingCount}")
    print("-" * 80)

    print("\n--- FINAL ACCOUNT LEDGER BALANCES ---")
    print(f"{'Account ID':<15} | {'Currency':<8} | {'Balance':<15} | {'Last Processed Seq':<20}")
    print("-" * 65)
    for acc_id, details in summary.accounts.items():
        print(f"{acc_id:<15} | {details['currency']:<8} | {details['currentBalance']:<15.2f} | {details['lastProcessedSequence']:<20}")

    print("\n--- TRANSACTION AUDIT LOG ---")
    print(f"{'Txn ID':<12} | {'Req ID':<12} | {'Account':<10} | {'Seq':<4} | {'Type':<7} | {'Amount':<8} | {'Status':<12} | {'Retries':<7} | {'Reason'}")
    print("-" * 95)
    for t in summary.transactionAudit:
        reason = (t['failureReason'] or '')[:35]
        print(f"{t['transactionId']:<12} | {t['requestId']:<12} | {t['accountId']:<10} | {t['sequence']:<4} | {t['type']:<7} | {t['amount']:<8.2f} | {t['status']:<12} | {t['retryCount']:<7} | {reason}")
    print("=" * 95 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Idempotent Background Transaction Processing Service")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Input file format (json or csv)")
    parser.add_argument("--file", type=str, help="Custom input file path (defaults to sample data)")
    parser.add_argument("--db", type=str, default=":memory:", help="Database path (defaults to :memory:, or pass 'transactions.db')")
    args = parser.parse_args()

    print_banner()

    # Determine file path
    project_root = Path(__file__).resolve().parent.parent
    if args.file:
        input_path = Path(args.file)
    else:
        if args.format == "json":
            input_path = project_root / "data" / "sample_transactions.json"
        else:
            input_path = project_root / "data" / "sample_transactions.csv"

    logger.info(f"Using input source: {input_path}")
    logger.info(f"Using persistence store: {args.db}")

    # Choose Ingestion Adapter
    if args.format == "csv" or str(input_path).endswith(".csv"):
        adapter = CsvIngestionAdapter(input_path)
    else:
        adapter = JsonIngestionAdapter(input_path)

    # Initialize Engine
    storage = SQLiteStorage(args.db)
    processor = TransactionProcessor(storage=storage)

    # Execute Batch
    logger.info("Starting background batch execution...\n")
    summary = processor.process_batch(adapter)

    # Output Report
    print_summary_table(summary)

    # Also save JSON report to disk
    report_file = project_root / "processing_summary_report.json"
    with open(report_file, "w") as f:
        json.dump(summary.model_dump(), f, indent=2)
    logger.info(f"Operational report persisted to: {report_file}")


if __name__ == "__main__":
    main()

