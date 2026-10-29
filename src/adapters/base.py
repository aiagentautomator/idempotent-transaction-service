from abc import ABC, abstractmethod
from typing import Iterator, Dict, Any


class BaseIngestionAdapter(ABC):
    """Abstract interface for input sources (CSV, JSON, Queue, Webhook, API)."""

    @abstractmethod
    def read_requests(self) -> Iterator[Dict[str, Any]]:
        """Yields raw transaction request dictionaries from the underlying source."""
        pass

