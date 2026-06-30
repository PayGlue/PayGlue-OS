# Copyright (c) 2026 PayGlue by André Nünninghoff
# Licensed under the Business Source License 1.1, see LICENSE.md
class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._processing_keys: set[str] = set()
        self._processed_keys: set[str] = set()

    def start_processing(self, idempotency_key: str) -> bool:
        if idempotency_key in self._processed_keys:
            return False
        if idempotency_key in self._processing_keys:
            return False

        self._processing_keys.add(idempotency_key)
        return True

    def mark_processed(self, idempotency_key: str) -> None:
        self._processing_keys.discard(idempotency_key)
        self._processed_keys.add(idempotency_key)

    def release(self, idempotency_key: str) -> None:
        self._processing_keys.discard(idempotency_key)
