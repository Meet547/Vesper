from typing import Any

from backend.app.services.graph_store import GraphStore


class HistorianAgent:
    """Loads related graph-backed memories and persists case memory."""

    def __init__(self, store: GraphStore):
        self.store = store

    def recall(self, transaction_ids: list[str], shared_context=None,
               owner_id: str | None = None) -> list[dict[str, Any]]:
        if shared_context is not None:
            shared_context.record_read("Historian")
        return self.store.find_related_memories(transaction_ids, limit=5, owner_id=owner_id)

    def remember(self, case: dict[str, Any], owner_id: str | None = None) -> dict[str, Any]:
        return self.store.save_case(case, owner_id=owner_id)
