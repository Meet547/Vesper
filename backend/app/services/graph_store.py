"""Safe graph access layer for FalkorDB and an explicitly labelled demo dataset.

Only fixed, application-owned Cypher statements live here. User input is passed
through query parameters; arbitrary Cypher is never accepted from an API caller.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from backend.app.config import Settings

logger = logging.getLogger(__name__)


# Independently authored synthetic graph for UI/demo mode only. IDs, labels,
# timesteps, and directed edges are invented for BUREAU examples; they are not
# copied from a real transaction dataset. Cloud mode remains separate.
_DEMO_TRANSACTIONS: dict[str, dict[str, Any]] = {
    "730000001": {"txId": "730000001", "label": "licit", "timeStep": 1, "sourceDataset": "bureau_synthetic_v1"},
    "730000002": {"txId": "730000002", "label": "unknown", "timeStep": 2, "sourceDataset": "bureau_synthetic_v1"},
    "730000003": {"txId": "730000003", "label": "illicit", "timeStep": 3, "sourceDataset": "bureau_synthetic_v1"},
    "730000004": {"txId": "730000004", "label": "unknown", "timeStep": 4, "sourceDataset": "bureau_synthetic_v1"},
    "730000005": {"txId": "730000005", "label": "licit", "timeStep": 5, "sourceDataset": "bureau_synthetic_v1"},
    "730000006": {"txId": "730000006", "label": "unknown", "timeStep": 6, "sourceDataset": "bureau_synthetic_v1"},
    "730000007": {"txId": "730000007", "label": "illicit", "timeStep": 7, "sourceDataset": "bureau_synthetic_v1"},
    "730000008": {"txId": "730000008", "label": "licit", "timeStep": 8, "sourceDataset": "bureau_synthetic_v1"},
}
_DEMO_EDGES: list[tuple[str, str]] = [
    ("730000001", "730000004"),
    ("730000002", "730000004"),
    ("730000004", "730000003"),
    ("730000003", "730000005"),
    ("730000005", "730000006"),
    ("730000006", "730000007"),
    ("730000007", "730000008"),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GraphStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.mode = settings.app_mode
        self._connection_lock = threading.RLock()
        self._client = None
        self._graph = None
        self._connect_error: str | None = None
        self._demo_cases: list[dict[str, Any]] = []
        self._demo_memories: list[dict[str, Any]] = []

    @property
    def graph_name(self) -> str:
        return self.settings.falkordb_graph_name

    def _require_owner_scope(self, owner_id: str | None) -> None:
        if self.mode == "cloud" and self.settings.auth_required and not owner_id:
            raise RuntimeError("Authenticated case and memory reads require a verified owner identity.")

    def close(self):
        with self._connection_lock:
            if self._client is not None:
                self._client.close()
            self._client = None
            self._graph = None

    def _connect(self):
        with self._connection_lock:
            return self._connect_locked()

    def _connect_locked(self):
        if self.mode != "cloud":
            raise RuntimeError("Cloud graph access is unavailable in demo mode")
        if self._graph is not None:
            return self._graph
        if not self.settings.cloud_configured:
            raise RuntimeError("FalkorDB Cloud credentials are incomplete. Set FALKORDB_URL or both FALKORDB_HOST and FALKORDB_PASSWORD in .env.")
        try:
            from falkordb import FalkorDB

            if self.settings.falkordb_url.strip():
                # Use rediss://... for TLS URLs. Keep the URL in .env only.
                self._client = FalkorDB.from_url(self.settings.falkordb_url.strip(),
                    socket_connect_timeout=5, socket_timeout=self.settings.falkordb_socket_timeout_seconds,
                    **({"ssl_cert_reqs": "required", "ssl_check_hostname": True}
                       if self.settings.falkordb_url.startswith("rediss://") else {}))
            else:
                kwargs: dict[str, Any] = {
                    "host": self.settings.falkordb_host.strip(),
                    "port": self.settings.falkordb_port,
                    "password": self.settings.falkordb_password,
                    "ssl": self.settings.falkordb_ssl,
                    "socket_connect_timeout": 5,
                    "socket_timeout": self.settings.falkordb_socket_timeout_seconds,
                }
                if self.settings.falkordb_ssl:
                    kwargs.update(ssl_cert_reqs="required", ssl_check_hostname=True)
                if self.settings.falkordb_username.strip():
                    kwargs["username"] = self.settings.falkordb_username.strip()
                self._client = FalkorDB(**kwargs)
            self._graph = self._client.select_graph(self.settings.falkordb_graph_name)
            # Fail early, but never expose connection credentials to API clients.
            self._graph.ro_query("RETURN 1 AS ready", timeout=self.settings.falkordb_query_timeout_ms)
            self._connect_error = None
            return self._graph
        except Exception as exc:  # network/library errors vary by deployment
            self.close()
            self._connect_error = type(exc).__name__
            logger.warning("FalkorDB connection failed (%s)", type(exc).__name__)
            raise RuntimeError("Could not connect to FalkorDB. Check host, port, username, password, and TLS settings.") from exc

    def health(self) -> dict[str, Any]:
        if self.mode == "demo":
            return {
                "ok": True,
                "mode": "demo",
                "database_connected": False,
                "graph_name": "demo_sample_graph",
                "message": "Demo mode is active. Results are illustrative and are not read from your cloud graph.",
            }
        try:
            self._connect().ro_query("RETURN 1 AS ready", timeout=self.settings.falkordb_query_timeout_ms)
            return {
                "ok": True,
                "mode": "cloud",
                "database_connected": True,
                "graph_name": self.graph_name,
                "message": "Connected to the configured FalkorDB graph.",
            }
        except Exception:
            return {
                "ok": False,
                "mode": "cloud",
                "database_connected": False,
                "graph_name": self.graph_name,
                "message": "FalkorDB readiness probe failed. Check server connection configuration.",
            }

    def _read_rows(self, query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        graph = self._connect()
        result = graph.ro_query(query, params or {}, timeout=self.settings.falkordb_query_timeout_ms)
        return list(result.result_set or [])

    def _write_rows(self, query: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        graph = self._connect()
        result = graph.query(query, params or {}, timeout=self.settings.falkordb_query_timeout_ms)
        return list(result.result_set or [])

    @staticmethod
    def _transaction_from_row(row: list[Any]) -> dict[str, Any]:
        return {
            "txId": str(row[0]),
            "label": row[1] if row[1] is not None else "unknown",
            "timeStep": row[2],
            "sourceDataset": row[3] if len(row) > 3 else None,
        }

    def get_stats(self) -> dict[str, Any]:
        if self.mode == "demo":
            labels = [item["label"] for item in _DEMO_TRANSACTIONS.values()]
            return {
                "totalTransactions": len(_DEMO_TRANSACTIONS),
                "totalFlows": len(_DEMO_EDGES),
                "illicitTransactions": labels.count("illicit"),
                "licitTransactions": labels.count("licit"),
                "unknownTransactions": labels.count("unknown"),
                "mode": "demo",
                "is_sample": True,
            }
        rows = self._read_rows(
            "MATCH (t:Transaction) "
            "RETURN count(t) AS totalTransactions, "
            "sum(CASE WHEN t.label = 'illicit' THEN 1 ELSE 0 END) AS illicitTransactions, "
            "sum(CASE WHEN t.label = 'licit' THEN 1 ELSE 0 END) AS licitTransactions, "
            "sum(CASE WHEN t.label = 'unknown' THEN 1 ELSE 0 END) AS unknownTransactions"
        )
        totals = rows[0] if rows else [0, 0, 0, 0]
        edge_rows = self._read_rows("MATCH ()-[r:FLOWS_TO]->() RETURN count(r) AS totalFlows")
        return {
            "totalTransactions": int(totals[0] or 0),
            "illicitTransactions": int(totals[1] or 0),
            "licitTransactions": int(totals[2] or 0),
            "unknownTransactions": int(totals[3] or 0),
            "totalFlows": int(edge_rows[0][0] or 0) if edge_rows else 0,
            "mode": "cloud",
            "is_sample": False,
        }

    def get_transaction(self, tx_id: str) -> dict[str, Any] | None:
        if self.mode == "demo":
            item = _DEMO_TRANSACTIONS.get(tx_id)
            return dict(item) if item else None
        rows = self._read_rows(
            "MATCH (t:Transaction {txId: $tx_id}) "
            "RETURN t.txId AS txId, t.label AS label, t.timeStep AS timeStep, t.sourceDataset AS sourceDataset LIMIT 1",
            {"tx_id": tx_id},
        )
        return self._transaction_from_row(rows[0]) if rows else None

    def search_transactions(self, query: str = "", label: str = "", limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        query = query.strip()[:50]
        label = label if label in {"", "illicit", "licit", "unknown"} else ""
        if self.mode == "demo":
            items = list(_DEMO_TRANSACTIONS.values())
            if query:
                items = [item for item in items if query.lower() in item["txId"].lower()]
            if label:
                items = [item for item in items if item["label"] == label]
            return [dict(item) for item in items[:limit]]
        rows = self._read_rows(
            "MATCH (t:Transaction) "
            "WHERE ($query = '' OR toLower(t.txId) CONTAINS toLower($query)) "
            "AND ($label = '' OR t.label = $label) "
            "RETURN t.txId AS txId, t.label AS label, t.timeStep AS timeStep, t.sourceDataset AS sourceDataset "
            "ORDER BY t.txId LIMIT $limit",
            {"query": query, "label": label, "limit": limit},
        )
        return [self._transaction_from_row(row) for row in rows]

    def get_neighbors(self, tx_id: str) -> dict[str, list[dict[str, Any]]]:
        if self.mode == "demo":
            incoming_ids = [source for source, target in _DEMO_EDGES if target == tx_id]
            outgoing_ids = [target for source, target in _DEMO_EDGES if source == tx_id]
            return {
                "incoming": [dict(_DEMO_TRANSACTIONS[node_id]) for node_id in sorted(incoming_ids)],
                "outgoing": [dict(_DEMO_TRANSACTIONS[node_id]) for node_id in sorted(outgoing_ids)],
            }
        incoming = self._read_rows(
            "MATCH (p:Transaction)-[:FLOWS_TO]->(t:Transaction {txId: $tx_id}) "
            "RETURN p.txId AS txId, p.label AS label, p.timeStep AS timeStep, p.sourceDataset AS sourceDataset ORDER BY p.txId ASC LIMIT 25",
            {"tx_id": tx_id},
        )
        outgoing = self._read_rows(
            "MATCH (t:Transaction {txId: $tx_id})-[:FLOWS_TO]->(n:Transaction) "
            "RETURN n.txId AS txId, n.label AS label, n.timeStep AS timeStep, n.sourceDataset AS sourceDataset ORDER BY n.txId ASC LIMIT 25",
            {"tx_id": tx_id},
        )
        return {
            "incoming": [self._transaction_from_row(row) for row in incoming],
            "outgoing": [self._transaction_from_row(row) for row in outgoing],
        }

    def trace_paths(self, tx_id: str, max_hops: int, direction: str | None = None) -> list[dict[str, Any]]:
        max_hops = max(1, min(int(max_hops), 4))
        if direction not in {None, "upstream", "downstream"}:
            raise ValueError("direction must be upstream or downstream")
        if self.mode == "demo":
            adjacency: dict[str, list[str]] = {key: [] for key in _DEMO_TRANSACTIONS}
            reverse: dict[str, list[str]] = {key: [] for key in _DEMO_TRANSACTIONS}
            for source, target in _DEMO_EDGES:
                adjacency[source].append(target)
                reverse[target].append(source)
            paths: list[dict[str, Any]] = []
            directions = ((direction, adjacency if direction == "downstream" else reverse),) if direction else (("downstream", adjacency), ("upstream", reverse))
            for path_direction, mapping in directions:
                frontier: list[list[str]] = [[tx_id]]
                for _ in range(max_hops):
                    next_frontier: list[list[str]] = []
                    for path in frontier:
                        for neighbor in sorted(mapping.get(path[-1], [])):
                            if neighbor in path:
                                continue
                            internal_path = path + [neighbor]
                            display_path = internal_path if path_direction == "downstream" else internal_path[::-1]
                            nodes = [dict(_DEMO_TRANSACTIONS[node_id]) for node_id in display_path]
                            ids = [node["txId"] for node in nodes]
                            paths.append({"direction": path_direction, "hops": len(display_path) - 1, "nodes": nodes,
                                          "edge_ids": [f"{source}->{target}" for source, target in zip(ids, ids[1:])]})
                            next_frontier.append(internal_path)
                    frontier = next_frontier
            unique = {(path["direction"], *(node["txId"] for node in path["nodes"])): path for path in paths}
            ordered = sorted(unique.values(), key=lambda item: (item["hops"], item["direction"], tuple(node["txId"] for node in item["nodes"])))
            truncated = len(ordered) > self.settings.max_trace_paths
            result = ordered[:self.settings.max_trace_paths]
            if truncated:
                for path in result:
                    path["search_truncated"] = True
            return result

        paths: list[dict[str, Any]] = []
        directions = (direction,) if direction else ("downstream", "upstream")
        for path_direction in directions:
            if path_direction == "downstream":
                query = (
                    f"MATCH p = (s:Transaction {{txId: $tx_id}})-[:FLOWS_TO*1..{max_hops}]->(t:Transaction) "
                    "WITH p, length(p) AS hops, [n IN nodes(p) | n.txId] AS txIds, "
                    "[n IN nodes(p) | n.label] AS labels, [n IN nodes(p) | n.timeStep] AS timeSteps, "
                    "[n IN nodes(p) | n.sourceDataset] AS sourceDatasets "
                    "RETURN txIds, labels, timeSteps, sourceDatasets, hops "
                    "ORDER BY hops ASC, txIds ASC LIMIT 21"
                )
            else:
                query = (
                    f"MATCH p = (s:Transaction)-[:FLOWS_TO*1..{max_hops}]->(t:Transaction {{txId: $tx_id}}) "
                    "WITH p, length(p) AS hops, [n IN nodes(p) | n.txId] AS txIds, "
                    "[n IN nodes(p) | n.label] AS labels, [n IN nodes(p) | n.timeStep] AS timeSteps, "
                    "[n IN nodes(p) | n.sourceDataset] AS sourceDatasets "
                    "RETURN txIds, labels, timeSteps, sourceDatasets, hops "
                    "ORDER BY hops ASC, txIds ASC LIMIT 21"
                )
            rows = self._read_rows(query, {"tx_id": tx_id})
            direction_truncated = len(rows) > 20
            for row in rows[:20]:
                tx_ids = row[0] or []
                labels = row[1] or []
                time_steps = row[2] or []
                source_datasets = row[3] or []
                nodes = [
                    {"txId": str(node_id), "label": labels[index] if index < len(labels) and labels[index] is not None else "unknown",
                     "timeStep": time_steps[index] if index < len(time_steps) else None,
                     "sourceDataset": source_datasets[index] if index < len(source_datasets) else None}
                    for index, node_id in enumerate(tx_ids)
                ]
                ids = [node["txId"] for node in nodes]
                paths.append({"direction": path_direction, "hops": int(row[4]), "nodes": nodes,
                              "edge_ids": [f"{source}->{target}" for source, target in zip(ids, ids[1:])],
                              "search_truncated": direction_truncated})
        unique = {(path["direction"], *(node["txId"] for node in path["nodes"])): path for path in paths}
        ordered = sorted(unique.values(), key=lambda item: (item["hops"], item["direction"], tuple(node["txId"] for node in item["nodes"])))
        truncated = len(ordered) > self.settings.max_trace_paths
        result = ordered[:self.settings.max_trace_paths]
        if truncated:
            for path in result:
                path["search_truncated"] = True
        return result

    def has_flow_edge(self, source_tx_id: str, target_tx_id: str) -> bool:
        """Independently verify one directed FLOWS_TO relationship."""
        if self.mode == "demo":
            return (source_tx_id, target_tx_id) in _DEMO_EDGES
        rows = self._read_rows(
            "MATCH (s:Transaction {txId: $source_tx_id})-[r:FLOWS_TO]->(t:Transaction {txId: $target_tx_id}) "
            "RETURN count(r) AS edgeCount LIMIT 1",
            {"source_tx_id": source_tx_id, "target_tx_id": target_tx_id},
        )
        return bool(rows and int(rows[0][0] or 0) > 0)

    def validate_paths(self, paths: list[dict[str, Any]], max_hops: int,
                       seed_tx_id: str | None = None) -> dict[str, Any]:
        """Independently verify returned path nodes and directed edges against the graph.

        This intentionally does not trust the traversal response's labels, hop count,
        or direction. Reads are bounded by the configured path and hop limits.
        """
        bounded = paths[: self.settings.max_trace_paths]
        node_ids: list[str] = []
        for path in bounded:
            nodes = path.get("nodes") if isinstance(path, dict) else None
            if not isinstance(nodes, list) or len(nodes) < 2:
                continue
            for node in nodes:
                if not isinstance(node, dict) or not str(node.get("txId", "")).isdigit():
                    continue
                node_ids.append(str(node["txId"]))
        graph_nodes = {tx_id: self.get_transaction(tx_id) for tx_id in dict.fromkeys(node_ids)}
        existing = {tx_id for tx_id, record in graph_nodes.items() if record is not None}
        checks: list[dict[str, Any]] = []
        invalid = 0
        for path in bounded:
            nodes = path.get("nodes") if isinstance(path, dict) else None
            direction = path.get("direction") if isinstance(path, dict) else None
            if not isinstance(nodes, list) or len(nodes) < 2 or direction not in {"upstream", "downstream"}:
                checks.append({"valid": False, "reason": "malformed_path"})
                invalid += 1
                continue
            ids = [str(node.get("txId", "")) if isinstance(node, dict) else "" for node in nodes]
            hops = len(ids) - 1
            valid = (all(tx_id in existing for tx_id in ids)
                     and 1 <= hops <= min(max_hops, 4)
                     and path.get("hops") == hops
                     and len(set(ids)) == len(ids)
                     and all(tx_id.isdigit() for tx_id in ids))
            if seed_tx_id is not None:
                valid = valid and ((direction == "downstream" and ids[0] == seed_tx_id)
                                   or (direction == "upstream" and ids[-1] == seed_tx_id))
            edge_pairs = list(zip(ids, ids[1:]))
            property_mismatches: list[str] = []
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                tx_id = str(node.get("txId", ""))
                graph_node = graph_nodes.get(tx_id)
                if graph_node is None:
                    continue
                for key in ("label", "timeStep", "sourceDataset"):
                    if key in node and node.get(key) != graph_node.get(key):
                        property_mismatches.append(f"{key}:{tx_id}")
            properties_match = not property_mismatches
            if valid:
                for source, target in edge_pairs:
                    if not self.has_flow_edge(source, target):
                        valid = False
                        break
            valid = valid and properties_match
            checks.append({"valid": valid,
                           "reason": None if valid else "transaction_properties_mismatch" if not properties_match else "node_edge_direction_or_bound_mismatch",
                           "node_ids": ids,
                           "edge_ids": [f"{source}->{target}" for source, target in edge_pairs],
                           "verified_transaction_properties": {tx_id: graph_nodes[tx_id] for tx_id in ids if tx_id in existing}})
            invalid += int(not valid)
        return {"checkedPathCount": len(checks), "validPathCount": sum(bool(item["valid"]) for item in checks),
                "invalidPathCount": invalid, "allPathsValid": bool(bounded) and invalid == 0 and len(checks) == len(bounded),
                "paths": checks}

    def find_related_memories(self, context_tx_ids: list[str], limit: int = 5,
                              owner_id: str | None = None) -> list[dict[str, Any]]:
        self._require_owner_scope(owner_id)
        context_tx_ids = list(dict.fromkeys(str(value) for value in context_tx_ids))[:100]
        if not context_tx_ids:
            return []
        limit = max(1, min(limit, 10))
        if self.mode == "demo":
            results = []
            wanted = set(context_tx_ids)
            for memory in self._demo_memories:
                if owner_id is not None and memory.get("ownerId") != owner_id:
                    continue
                overlap = sorted(wanted.intersection(memory.get("evidence_tx_ids", [])))
                if overlap:
                    item = dict(memory)
                    item["sharedTransactions"] = overlap
                    item["overlapCount"] = len(overlap)
                    item["relevanceReason"] = (
                        f"Case {item.get('caseId', 'unknown')} shares transaction IDs "
                        f"{', '.join(overlap)} with the current evidence."
                    )
                    results.append(item)
            return sorted(results, key=lambda item: item["overlapCount"], reverse=True)[:limit]
        owner_filter = " AND c.ownerId = $owner_id AND m.ownerId = $owner_id" if owner_id is not None else ""
        rows = self._read_rows(
            "MATCH (c:InvestigationCase)-[:GENERATED_MEMORY]->(m:InvestigationMemory)-[:REFERENCES]->(t:Transaction) "
            "WHERE t.txId IN $context_tx_ids" + owner_filter + " "
            "WITH c, m, collect(DISTINCT t.txId) AS overlap "
            "RETURN c.caseId AS caseId, m.memoryId AS memoryId, m.seedTxId AS seedTxId, m.summary AS summary, "
            "m.evidenceJson AS evidenceJson, m.evidenceLedgerJson AS evidenceLedgerJson, "
            "m.evidenceRefsJson AS evidenceRefsJson, m.verifiedClaimsJson AS verifiedClaimsJson, "
            "m.rejectedClaimsJson AS rejectedClaimsJson, m.modelMetadataJson AS modelMetadataJson, "
            "m.schemaVersion AS schemaVersion, c.findingsJson AS findingsJson, "
            "m.createdAt AS createdAt, overlap AS sharedTransactions "
            "ORDER BY size(overlap) DESC, m.createdAt DESC LIMIT $limit",
            {"context_tx_ids": context_tx_ids, "limit": limit,
             **({"owner_id": owner_id} if owner_id is not None else {})},
        )
        results = []
        for row in rows:
            def decode(index: int, fallback: Any) -> Any:
                try:
                    return json.loads(row[index] or json.dumps(fallback))
                except (TypeError, json.JSONDecodeError):
                    return fallback

            evidence = decode(4, [])
            evidence_ledger = decode(5, {})
            evidence_refs = decode(6, {})
            verified_claims = decode(7, [])
            rejected_claims = decode(8, [])
            model_metadata = decode(9, {})
            findings = decode(11, {}) if len(row) > 13 else {}
            shared_context = findings.get("sharedContext", {}) if isinstance(findings, dict) else {}
            overlap = row[13] if len(row) > 13 else row[12]
            overlap = overlap or []
            case_id = row[0]
            results.append({
                "caseId": case_id, "memoryId": row[1], "seedTxId": row[2], "summary": row[3],
                "evidence": evidence, "evidenceLedger": evidence_ledger,
                "evidenceRefs": evidence_refs, "verifiedClaims": verified_claims,
                "rejectedClaims": rejected_claims, "modelMetadata": model_metadata,
                "sharedContext": shared_context,
                "schemaVersion": row[10] or "legacy",
                "createdAt": row[12] if len(row) > 13 else row[11], "sharedTransactions": list(overlap),
                "overlapCount": len(overlap),
                "relevanceReason": (
                    f"Case {case_id} shares transaction IDs "
                    f"{', '.join(str(tx_id) for tx_id in overlap)} with the current evidence."
                ),
            })
        return results

    def save_case(self, case: dict[str, Any], owner_id: str | None = None) -> dict[str, Any]:
        if self.mode == "cloud" and self.settings.auth_required and owner_id is None:
            raise RuntimeError("Authenticated case saves require a verified owner identity.")
        evidence_tx_ids = list(dict.fromkeys(str(value) for value in case.get("evidence_tx_ids", [])))[:100]
        if case["seed"]["txId"] not in evidence_tx_ids:
            evidence_tx_ids.insert(0, case["seed"]["txId"])
        evidence_ledger = case.get("evidence_ledger") or {}
        evidence_refs = case.get("evidence_refs") or {
            "transaction_ids": evidence_tx_ids,
            "edge_ids": [edge.get("edge_id") for edge in evidence_ledger.get("edges", []) if edge.get("edge_id")],
            "path_ids": [f"path:{path.get('path_index')}" for path in evidence_ledger.get("paths", [])],
        }
        verified_claims = case.get("verified_claims") or []
        rejected_claims = case.get("rejected_claims") or []
        schema_version = str(case.get("memory_schema_version") or "1.0")
        if self.mode == "demo":
            memory = {
                "memoryId": case["memory_id"],
                "caseId": case["case_id"],
                "seedTxId": case["seed"]["txId"],
                "summary": case["summary"],
                "evidence": case["traces"],
                "evidenceLedger": evidence_ledger,
                "evidenceRefs": evidence_refs,
                "verifiedClaims": verified_claims,
                "rejectedClaims": rejected_claims,
                "sharedContext": case.get("shared_context", {}),
                "schemaVersion": schema_version,
                "evidence_tx_ids": evidence_tx_ids,
                "createdAt": case["created_at"],
                "tags": ["bitcoin-investigation", case["seed"].get("label", "unknown")],
                "ownerId": owner_id,
            }
            self._demo_memories = [item for item in self._demo_memories
                                   if item.get("memoryId") != case["memory_id"]]
            self._demo_memories.insert(0, memory)
            demo_case = {
                "caseId": case["case_id"], "memoryId": case["memory_id"],
                "ownerId": owner_id,
                "seedTxId": case["seed"]["txId"], "seedLabel": case["seed"].get("label"),
                "status": case["status"], "summary": case["summary"], "createdAt": case["created_at"],
                "findings": case["skeptic"], "traces": case["traces"],
                "relatedMemories": case["related_memories"],
                "evidenceLedger": evidence_ledger,
                "evidenceRefs": evidence_refs,
                "verifiedClaims": verified_claims,
                "rejectedClaims": rejected_claims,
                "structuredReport": case.get("structured_report", {}),
                "sharedContext": case.get("shared_context", {}),
                "claimValidation": case.get("claim_validation", {}),
                "modelMetadata": case.get("model_metadata", {}),
                "memorySchemaVersion": schema_version,
            }
            self._demo_cases = [item for item in self._demo_cases
                                if item.get("caseId") != case["case_id"]]
            self._demo_cases.insert(0, demo_case)
            return {"caseId": case["case_id"], "memoryId": case["memory_id"], "linkedEvidence": len(evidence_tx_ids)}

        findings_json = json.dumps({"skeptic": case["skeptic"], "traces": case["traces"],
                                    "relatedMemories": case.get("related_memories", []),
                                    "evidenceLedger": evidence_ledger,
                                    "structuredReport": case.get("structured_report", {}),
                                    "sharedContext": case.get("shared_context", {}),
                                    "claimValidation": case.get("claim_validation", {}),
                                    "modelMetadata": case.get("model_metadata", {})}, separators=(",", ":"))
        evidence_json = json.dumps(case["traces"], separators=(",", ":"))
        evidence_ledger_json = json.dumps(evidence_ledger, separators=(",", ":"))
        evidence_refs_json = json.dumps(evidence_refs, separators=(",", ":"))
        verified_claims_json = json.dumps(verified_claims, separators=(",", ":"))
        rejected_claims_json = json.dumps(rejected_claims, separators=(",", ":"))
        model_metadata_json = json.dumps(case.get("model_metadata") or {}, separators=(",", ":"))
        tags = ["bitcoin-investigation", str(case["seed"].get("label") or "unknown")]
        case_identity = ("(c:InvestigationCase {caseId: $case_id, ownerId: $owner_id})"
                         if owner_id is not None else "(c:InvestigationCase {caseId: $case_id})")
        memory_identity = ("(m:InvestigationMemory {memoryId: $memory_id, ownerId: $owner_id})"
                           if owner_id is not None else "(m:InvestigationMemory {memoryId: $memory_id})")
        rows = self._write_rows(
            "MATCH (seed:Transaction {txId: $seed_tx_id}) "
            "MERGE " + case_identity + " "
            "SET c.seedTxId = $seed_tx_id, c.status = $status, c.summary = $summary, "
            "c.findingsJson = $findings_json, c.createdAt = $created_at "
            "MERGE " + memory_identity + " "
            "SET m.caseId = $case_id, m.seedTxId = $seed_tx_id, m.summary = $summary, "
            "m.evidenceJson = $evidence_json, m.evidenceLedgerJson = $evidence_ledger_json, "
            "m.evidenceRefsJson = $evidence_refs_json, m.verifiedClaimsJson = $verified_claims_json, "
            "m.rejectedClaimsJson = $rejected_claims_json, m.modelMetadataJson = $model_metadata_json, "
            "m.schemaVersion = $schema_version, m.createdAt = $created_at, m.tags = $tags "
            "MERGE (c)-[:INVESTIGATES]->(seed) "
            "MERGE (c)-[:GENERATED_MEMORY]->(m) "
            "WITH c, m "
            "UNWIND $evidence_tx_ids AS evidence_tx_id "
            "MATCH (e:Transaction {txId: evidence_tx_id}) "
            "MERGE (m)-[:REFERENCES]->(e) "
            "RETURN c.caseId AS caseId, m.memoryId AS memoryId, count(e) AS linkedEvidence",
            {
                "seed_tx_id": case["seed"]["txId"], "case_id": case["case_id"],
                "memory_id": case["memory_id"], "status": case["status"],
                "summary": case["summary"], "findings_json": findings_json,
                "evidence_json": evidence_json, "evidence_ledger_json": evidence_ledger_json,
                "evidence_refs_json": evidence_refs_json, "verified_claims_json": verified_claims_json,
                "rejected_claims_json": rejected_claims_json, "model_metadata_json": model_metadata_json,
                "schema_version": schema_version, "created_at": case["created_at"],
                "tags": tags, "evidence_tx_ids": evidence_tx_ids,
                **({"owner_id": owner_id} if owner_id is not None else {}),
            },
        )
        if not rows:
            raise RuntimeError("Case could not be saved. Confirm the seed transaction exists in the selected graph.")
        return {"caseId": rows[0][0], "memoryId": rows[0][1], "linkedEvidence": int(rows[0][2] or 0)}

    def list_cases(self, limit: int = 20, owner_id: str | None = None) -> list[dict[str, Any]]:
        self._require_owner_scope(owner_id)
        limit = max(1, min(int(limit), self.settings.max_case_list))
        if self.mode == "demo":
            cases = [case for case in self._demo_cases if owner_id is None or case.get("ownerId") == owner_id]
            return [dict(case) for case in cases[:limit]]
        owner_filter = " WHERE c.ownerId = $owner_id" if owner_id is not None else ""
        memory_owner_filter = "WHERE m.ownerId = $owner_id" if owner_id is not None else ""
        rows = self._read_rows(
            "MATCH (c:InvestigationCase)" + owner_filter + " "
            "OPTIONAL MATCH (c)-[:GENERATED_MEMORY]->(m:InvestigationMemory) "
            + memory_owner_filter + " "
            "RETURN c.caseId AS caseId, c.seedTxId AS seedTxId, c.status AS status, "
            "c.summary AS summary, c.createdAt AS createdAt, m.memoryId AS memoryId "
            "ORDER BY c.createdAt DESC LIMIT $limit",
            {"limit": limit, **({"owner_id": owner_id} if owner_id is not None else {})},
        )
        return [{"caseId": row[0], "seedTxId": row[1], "status": row[2], "summary": row[3], "createdAt": row[4], "memoryId": row[5]} for row in rows]

    def get_case(self, case_id: str, owner_id: str | None = None) -> dict[str, Any] | None:
        self._require_owner_scope(owner_id)
        if self.mode == "demo":
            return next((dict(case) for case in self._demo_cases if case.get("caseId") == case_id
                         and (owner_id is None or case.get("ownerId") == owner_id)), None)
        owner_filter = " WHERE c.ownerId = $owner_id" if owner_id is not None else ""
        memory_owner_filter = "WHERE m.ownerId = $owner_id" if owner_id is not None else ""
        rows = self._read_rows(
            "MATCH (c:InvestigationCase {caseId: $case_id})" + owner_filter + " "
            "OPTIONAL MATCH (c)-[:GENERATED_MEMORY]->(m:InvestigationMemory) "
            + memory_owner_filter + " "
            "RETURN c.caseId AS caseId, c.seedTxId AS seedTxId, c.status AS status, "
            "c.summary AS summary, c.createdAt AS createdAt, c.findingsJson AS findingsJson, "
            "m.memoryId AS memoryId, m.evidenceJson AS evidenceJson, m.evidenceLedgerJson AS evidenceLedgerJson, "
            "m.evidenceRefsJson AS evidenceRefsJson, m.verifiedClaimsJson AS verifiedClaimsJson, "
            "m.rejectedClaimsJson AS rejectedClaimsJson, m.schemaVersion AS schemaVersion, "
            "m.modelMetadataJson AS modelMetadataJson LIMIT 1",
            {"case_id": case_id, **({"owner_id": owner_id} if owner_id is not None else {})},
        )
        if not rows:
            return None
        row = rows[0]
        try:
            findings = json.loads(row[5] or "{}")
        except (TypeError, json.JSONDecodeError):
            findings = {}
        try:
            evidence = json.loads(row[7] or "[]")
        except (TypeError, json.JSONDecodeError):
            evidence = []
        def decode(index: int, fallback: Any) -> Any:
            try:
                return json.loads(row[index] or json.dumps(fallback))
            except (TypeError, json.JSONDecodeError):
                return fallback
        return {"caseId": row[0], "seedTxId": row[1], "status": row[2], "summary": row[3], "createdAt": row[4],
                "findings": findings.get("skeptic", {}), "traces": evidence, "memoryId": row[6],
                "relatedMemories": findings.get("relatedMemories", []),
                "evidenceLedger": decode(8, findings.get("evidenceLedger", {})),
                "evidenceRefs": decode(9, {}), "verifiedClaims": decode(10, []),
                "rejectedClaims": decode(11, []), "memorySchemaVersion": row[12] or "legacy",
                "modelMetadata": decode(13, findings.get("modelMetadata", {})),
                "structuredReport": findings.get("structuredReport", {}),
                "sharedContext": findings.get("sharedContext", {}),
                "claimValidation": findings.get("claimValidation", {})}
