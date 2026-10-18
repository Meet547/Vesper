"""Query accounting and persistence verification for the loopback Track 2 demo."""
from __future__ import annotations

from threading import Lock
from time import perf_counter
from typing import Any

from backend.app.services.graph_store import GraphStore


class Track2DemoGraphStore(GraphStore):
    """Count GraphStore calls only for an explicitly isolated demo process."""

    def __init__(self, settings):
        super().__init__(settings)
        self._accounting_lock = Lock()
        self.reset_query_accounting()

    def reset_query_accounting(self) -> None:
        with self._accounting_lock:
            self._read_latencies_ms: list[float] = []
            self._write_latencies_ms: list[float] = []

    def _read_rows(self, query: str, params: dict[str, Any] | None = None):
        started = perf_counter()
        try:
            return super()._read_rows(query, params)
        finally:
            with self._accounting_lock:
                self._read_latencies_ms.append((perf_counter() - started) * 1000)

    def _write_rows(self, query: str, params: dict[str, Any] | None = None):
        started = perf_counter()
        try:
            return super()._write_rows(query, params)
        finally:
            with self._accounting_lock:
                self._write_latencies_ms.append((perf_counter() - started) * 1000)

    def query_accounting(self) -> dict[str, Any]:
        with self._accounting_lock:
            reads = list(self._read_latencies_ms)
            writes = list(self._write_latencies_ms)

        def summarize(values: list[float]) -> dict[str, float | int]:
            return {
                "count": len(values),
                "total_latency_ms": round(sum(values), 3),
                "mean_latency_ms": round(sum(values) / len(values), 3) if values else 0,
                "max_latency_ms": round(max(values), 3) if values else 0,
            }

        return {
            "source_database_reads": summarize(reads),
            "database_writes": summarize(writes),
            "scope": "application GraphStore calls; direct connection health handshake excluded",
        }

    def confirm_case_memory_provenance(self, case_id: str, memory_id: str,
                                       owner_id: str) -> dict[str, Any]:
        rows = self._read_rows(
            "MATCH (c:InvestigationCase {caseId: $case_id, ownerId: $owner_id}) "
            "-[gm:GENERATED_MEMORY]->(m:InvestigationMemory {memoryId: $memory_id, ownerId: $owner_id}) "
            "OPTIONAL MATCH (m)-[ref:REFERENCES]->(t:Transaction) "
            "RETURN count(DISTINCT gm), count(DISTINCT ref), collect(DISTINCT t.txId) LIMIT 1",
            {"case_id": case_id, "memory_id": memory_id, "owner_id": owner_id},
        )
        if not rows or int(rows[0][0] or 0) != 1:
            return {"confirmed": False, "case_id": case_id, "memory_id": memory_id,
                    "generated_memory_edges": 0, "referenced_transactions": 0,
                    "referenced_transaction_ids": []}
        return {"confirmed": int(rows[0][1] or 0) > 0,
                "case_id": case_id, "memory_id": memory_id,
                "generated_memory_edges": int(rows[0][0] or 0),
                "referenced_transactions": int(rows[0][1] or 0),
                "referenced_transaction_ids": sorted(str(value) for value in (rows[0][2] or []) if value is not None)}
