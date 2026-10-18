from __future__ import annotations

import re
from typing import Callable

from falkordb import FalkorDB
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from .config import Target

ID = re.compile(r"SYN-[0-9]{6}\Z")
READY = "RETURN 1 AS ready"
GET = "MATCH (t:Transaction {txId: $tx_id}) RETURN t.txId, t.label, t.timeStep, t.sourceDataset LIMIT 2"
COUNTS = "MATCH (n) RETURN labels(n) AS label, count(*) AS nodes ORDER BY label"
EDGE_COUNTS = "MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS edges ORDER BY rel"
ROLES = "MATCH (t:Transaction) RETURN t.label AS role, count(*) AS nodes ORDER BY role"
EXPAND = ("MATCH p=(s:Transaction {txId: $start_txid})-[:FLOWS_TO*1..6]->(t:Transaction) "
          "WHERE length(p) <= $max_hops "
          "RETURN [n IN nodes(p) | n.txId] AS txids, [r IN relationships(p) | id(r)] AS relationship_ids, "
          "length(p) AS hops ORDER BY hops DESC, txids ASC LIMIT 41")
EDGE = ("MATCH (s:Transaction {txId: $source})-[r:FLOWS_TO]->(t:Transaction {txId: $target}) "
        "RETURN id(r) AS relationship_id LIMIT 2")
EXPORT_NODES = "MATCH (t:Transaction) RETURN t.txId, t.label, t.timeStep, t.sourceDataset ORDER BY t.txId"
EXPORT_EDGES = ("MATCH (s:Transaction)-[r:FLOWS_TO]->(t:Transaction) "
                "RETURN s.txId, t.txId, id(r) ORDER BY s.txId, t.txId")


class EvidenceUnavailable(RuntimeError):
    pass


class IsolationError(RuntimeError):
    pass


def check_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("A SYN- ID with exactly six digits is required")
    return value


def check_hops(value):
    if type(value) is not int or not 1 <= value <= 6:
        raise ValueError("max_hops must be an integer from 1 to 6")
    return value


class SyntheticStore:
    """Read-only surface; no inherited demo or memory methods."""

    def __init__(self, target: Target, record: Callable | None = None):
        self.target = target
        self.record = record or (lambda event: None)
        self.redis = Redis(host="127.0.0.1", port=target.port, socket_connect_timeout=1,
                           socket_timeout=3, retry=Retry(NoBackoff(), 0))
        self.client = None
        self._graph = None

    @property
    def graph(self):
        self.identity()
        if self._graph is None:
            try:
                self.client = FalkorDB(host="127.0.0.1", port=self.target.port, socket_connect_timeout=1,
                                      socket_timeout=15, retry=Retry(NoBackoff(), 0))
                self._graph = self.client.select_graph(self.target.graph)
            except Exception:
                raise EvidenceUnavailable("evidence unavailable") from None
        return self._graph

    def identity(self):
        try:
            actual = self.redis.info("server")["run_id"]
        except Exception:
            raise EvidenceUnavailable("evidence unavailable") from None
        if actual != self.target.run_id:
            raise IsolationError("Database identity differs from the authorized disposable server")

    def read(self, query, params=None, timeout=2000):
        self.identity()
        try:
            result = self.graph.ro_query(query, params or {}, timeout=timeout)
            rows = list(result.result_set or [])
        except Exception as error:
            # Exceptions are never returned verbatim: transport data can be sensitive.
            self.record({"event": "query_error", "graph": self.target.graph,
                         "error_type": type(error).__name__})
            raise EvidenceUnavailable("evidence unavailable") from None
        self.record({"event": "cypher", "graph": self.target.graph, "query": query,
                     "parameters": params or {}, "server_timeout_ms": timeout, "rows": rows})
        return rows

    def health(self):
        self.read(READY)
        return {"database_connected": True, "mode": "database", "graph_name": self.target.graph,
                "dataset_kind": "team-authored synthetic scenarios"}

    def counts(self):
        return {"nodes": self.read(COUNTS), "edges": self.read(EDGE_COUNTS), "roles": self.read(ROLES)}

    def get_transaction(self, tx_id):
        rows = self.read(GET, {"tx_id": check_id(tx_id)})
        if len(rows) > 1:
            raise IsolationError("Duplicate transaction identities")
        return dict(zip(("txId", "label", "timeStep", "sourceDataset"), rows[0])) if rows else None

    def expand_outgoing(self, start_txid, max_hops):
        rows = self.read(EXPAND, {"start_txid": check_id(start_txid), "max_hops": check_hops(max_hops)})
        return {"paths": [{"txids": r[0], "relationship_ids": r[1], "hops": r[2]} for r in rows[:40]],
                "truncated": len(rows) > 40}

    def edge(self, source, target):
        rows = self.read(EDGE, {"source": check_id(source), "target": check_id(target)})
        return {"source": source, "target": target, "row_count": len(rows),
                "native_relationship_ids": [r[0] for r in rows]}

    def close(self):
        self.redis.close()
        close = getattr(self.client, "close", None)
        if close:
            close()
