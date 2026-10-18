"""Narrow, bounded tool surface intended for investigator agents.

An LLM/agent may call these Python methods, but it cannot submit arbitrary Cypher.
"""

from typing import Any

from backend.app.services.graph_store import GraphStore


class InvestigationTools:
    def __init__(self, store: GraphStore):
        self.store = store

    def get_transaction(self, tx_id: str) -> dict[str, Any] | None:
        return self.store.get_transaction(tx_id)

    def get_neighbors(self, tx_id: str) -> dict[str, list[dict[str, Any]]]:
        return self.store.get_neighbors(tx_id)

    def trace_paths(self, tx_id: str, max_hops: int = 3, direction: str | None = None) -> list[dict[str, Any]]:
        # GraphStore clamps this to a hard maximum of four hops and fixed result caps.
        return self.store.trace_paths(tx_id, max_hops, direction=direction)

    def find_related_memories(self, transaction_ids: list[str]) -> list[dict[str, Any]]:
        return self.store.find_related_memories(transaction_ids, limit=5)
