import csv
from typing import Iterator, Dict, Any, Union
from pathlib import Path
from src.adapters.base import BaseIngestionAdapter


class CsvIngestionAdapter(BaseIngestionAdapter):
    """Ingests transaction requests from CSV files."""

    def __init__(self, file_path: Union[str, Path]):
        self.file_path = Path(file_path)

    def read_requests(self) -> Iterator[Dict[str, Any]]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"CSV input file not found: {self.file_path}")

        with open(self.file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Type conversions for CSV string fields
                parsed = {
                    "transactionId": row.get("transactionId", "").strip(),
                    "requestId": row.get("requestId", "").strip(),
                    "sequenceNumber": int(row["sequenceNumber"]) if row.get("sequenceNumber") else None,
                    "accountId": row.get("accountId", "").strip(),
                    "transactionType": row.get("transactionType", "").strip().upper(),
                    "amount": float(row["amount"]) if row.get("amount") else None,
                    "currency": row.get("currency", "USD").strip().upper(),
                    "simulateTransientError": row.get("simulateTransientError", "false").strip().lower() in ("true", "1", "yes")
                }
                yield parsed

