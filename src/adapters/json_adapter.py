import json
from typing import Iterator, Dict, Any, Union
from pathlib import Path
from src.adapters.base import BaseIngestionAdapter


class JsonIngestionAdapter(BaseIngestionAdapter):
    """Ingests transaction requests from JSON files or in-memory JSON payloads."""

    def __init__(self, source: Union[str, Path, list]):
        self.source = source

    def read_requests(self) -> Iterator[Dict[str, Any]]:
        if isinstance(self.source, list):
            for item in self.source:
                yield item
        else:
            path = Path(self.source)
            if not path.exists():
                raise FileNotFoundError(f"JSON input source not found: {path}")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    raise ValueError("JSON root must be an array of transaction objects")
                for item in data:
                    yield item

