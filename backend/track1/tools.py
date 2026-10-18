from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from .store import EvidenceUnavailable, QueryTimeout

SHORTEST = ("MATCH (s:Transaction {txId: $start_txid}), (t:Transaction {txId: $end_txid}) "
            "WITH shortestPath((s)-[:FLOWS_TO*1..6]->(t)) AS p "
            "WHERE p IS NOT NULL AND length(p) <= $max_hops "
            "RETURN [n IN nodes(p) | n.txId], [r IN relationships(p) | id(r)], length(p)")


class RouteArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_txid: str = Field(pattern=r"^SYN-[0-9]{6}$", description="Synthetic starting transaction ID")
    end_txid: str = Field(pattern=r"^SYN-[0-9]{6}$", description="Synthetic destination transaction ID")
    max_hops: StrictInt = Field(ge=1, le=6, description="Required directed-hop bound, 1 through 6")


SHORTEST_TOOL = {
    "name": "shortest_path",
    "description": "Read one shortest directed route between two synthetic transactions, bounded to at most six hops.",
    "input_schema": RouteArguments.model_json_schema(),
    "server_timeout_ms": 2000,
    "read_only": True,
}


class Track1Tools:
    def __init__(self, store, timeout_ms=2000):
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 2000:
            raise ValueError("Server timeout must be from 1 to 2000 milliseconds")
        self.store, self.timeout_ms = store, timeout_ms

    def shortest_path(self, **arguments):
        try:
            args = RouteArguments.model_validate(arguments)
        except ValidationError:
            return {"status": "FAIL", "error": "invalid_arguments", "message": "Provide SYN IDs and an integer max_hops from 1 through 6.", "path": []}
        try:
            self.store.health()
            if self.store.get_transaction(args.start_txid) is None or self.store.get_transaction(args.end_txid) is None:
                return {"status": "FAIL", "error": "unknown_id", "message": "A transaction ID is absent from the graph.", "path": []}
            rows = self.store.read(SHORTEST, args.model_dump(), timeout=self.timeout_ms)
            if not rows:
                return {"status": "FAIL", "error": "no_path", "message": "No directed path exists within the requested hop bound.", "path": []}
            ids, relationships, hops = rows[0]
            return {"status": "PASS", "path": ids, "relationship_ids": relationships, "hops": hops,
                    "graph": self.store.target.graph, "server_timeout_ms": self.timeout_ms}
        except QueryTimeout:
            return {"status": "FAIL", "error": "timeout", "message": "Graph query timed out.", "path": []}
        except EvidenceUnavailable:
            return {"status": "FAIL", "error": "evidence_unavailable", "message": "evidence unavailable", "path": []}

    def call(self, name, arguments):
        if name != SHORTEST_TOOL["name"]:
            return {"status": "FAIL", "error": "unknown_tool", "path": []}
        return self.shortest_path(**arguments)
