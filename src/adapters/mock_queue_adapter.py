import collections
from typing import Iterator, Dict, Any, List
from src.adapters.base import BaseIngestionAdapter


class MockQueueAdapter(BaseIngestionAdapter):
    """
    Simulates an asynchronous distributed message queue (e.g. Kafka, RabbitMQ, SQS).
    Enables test harnesses to push messages dynamically and consume them sequentially.
    """

    def __init__(self, initial_messages: List[Dict[str, Any]] = None):
        self._queue = collections.deque(initial_messages or [])

    def enqueue(self, message: Dict[str, Any]) -> None:
        """Push a message to the simulated queue."""
        self._queue.append(message)

    def read_requests(self) -> Iterator[Dict[str, Any]]:
        """Drain the queue yield by yield."""
        while self._queue:
            yield self._queue.popleft()

