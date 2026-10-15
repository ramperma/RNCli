"""LRU Cache con O(1) get/put, sin functools: dict + doubly linked list."""
from typing import Any, Hashable


class LRUCache:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._values: dict[Hashable, Any] = {}
        self.order: dict[Hashable, None] = {}  # key -> None, dict preserves insertion order

    def get(self, key: Hashable) -> Any:
        if key not in self.order:
            return None
        value = self._values[key]
        del self.order[key]
        self.order[key] = None  # move to end (most recent)
        return value

    def put(self, key: Hashable, value: Any) -> None:
        self._values[key] = value
        self.order.pop(key, None)
        self.order[key] = None
        if len(self.order) > self.capacity:
            oldest = next(iter(self.order))
            del self.order[oldest]
            del self._values[oldest]

    def __len__(self) -> int:
        return len(self.order)
