"""Safely initialize or verify Vesper's dedicated local synthetic graph."""
from __future__ import annotations

import json
import subprocess
from typing import Any

from redis import Redis

from backend.app.config import Settings

HOST = "127.0.0.1"
PORT = 6389
GRAPH_NAME = "vesper_track2_synthetic_test"
DATASET = "bureau_synthetic_v1"
TRANSACTIONS = [
    {"txId": tx_id, "label": "unknown", "timeStep": 8, "sourceDataset": DATASET}
    for tx_id in ("731000001", "731000002", "731000003", "731000004", "731000005", "731000006", "731000007", "731000008")
]
EDGES = [
    {"source": "731000001", "target": "731000002"}, {"source": "731000001", "target": "731000005"},
    {"source": "731000002", "target": "731000003"}, {"source": "731000003", "target": "731000004"},
    {"source": "731000005", "target": "731000006"}, {"source": "731000005", "target": "731000007"},
    {"source": "731000005", "target": "731000008"},
]


def _assert_synthetic_fixture_contract() -> None:
    ids = {tx["txId"] for tx in TRANSACTIONS}
    if len(ids) != len(TRANSACTIONS) or any(tx["sourceDataset"] != DATASET for tx in TRANSACTIONS):
        raise RuntimeError("Synthetic fixture IDs and namespace must be unique and consistent")
    adjacency = {tx_id: set() for tx_id in ids}
    for edge in EDGES:
        if edge["source"] not in ids or edge["target"] not in ids:
            raise RuntimeError("Synthetic fixture edge points to a missing node")
        adjacency[edge["source"]].add(edge["target"])
        adjacency[edge["target"]].add(edge["source"])
    reached, pending = set(), [min(ids)]
    while pending:
        node = pending.pop()
        if node in reached:
            continue
        reached.add(node)
        pending.extend(adjacency[node] - reached)
    if reached != ids:
        raise RuntimeError("Synthetic fixture must be connected")


def _decode(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _assert_container_boundary() -> dict:
    completed = subprocess.run(
        ["docker", "inspect", "--format", "{{.Name}}|{{.Config.Image}}|{{.State.Status}}|{{json .NetworkSettings.Ports}}", "bureau-m84-isolated"],
        check=True, capture_output=True, text=True, timeout=5,
    )
    fields = completed.stdout.strip().split("|", 3)
    if len(fields) != 4 or fields[0] != "/bureau-m84-isolated" or not fields[1].startswith("falkordb/falkordb:") or fields[2] != "running":
        raise RuntimeError("Refusing to seed: the named running FalkorDB container was not confirmed")
    ports = json.loads(fields[3])
    if ports.get("6379/tcp") != [{"HostIp": HOST, "HostPort": str(PORT)}]:
        raise RuntimeError("Refusing to seed: the container is not published only on 127.0.0.1:6389")
    return {"container": fields[0].lstrip("/"), "image": fields[1], "status": fields[2],
            "published_ports": ports}


def seed() -> dict:
    _assert_synthetic_fixture_contract()
    production_settings = Settings()
    if GRAPH_NAME == production_settings.falkordb_graph_name:
        raise RuntimeError("Refusing to seed: test graph name matches configured production graph name")
    container = _assert_container_boundary()
    redis = Redis(host=HOST, port=PORT, socket_connect_timeout=2, socket_timeout=3,
                  decode_responses=True)
    if redis.ping() is not True:
        raise RuntimeError("Isolated FalkorDB did not answer PING")
    modules = redis.execute_command("MODULE", "LIST")
    module_versions = {}
    for item in modules:
        if isinstance(item, dict):
            flattened = {_decode(key).lower(): _decode(value) for key, value in item.items()}
        else:
            flattened = {_decode(item[i]).lower(): _decode(item[i + 1])
                         for i in range(0, len(item), 2)}
        module_versions[flattened.get("name", "unknown")] = flattened.get("ver", "unknown")
    if "graph" not in module_versions:
        raise RuntimeError("Refusing to seed: the local service is not running FalkorDB's graph module")
    existing = sorted(_decode(value) for value in redis.execute_command("GRAPH.LIST"))

    from falkordb import FalkorDB

    client = FalkorDB(host=HOST, port=PORT, ssl=False,
                      socket_connect_timeout=2, socket_timeout=3)
    graph = client.select_graph(GRAPH_NAME)
    try:
        # Preflight an existing target graph before any write. Partial fixture
        # initialization is repairable; unrelated labels, IDs, or edges fail closed.
        labels = existing_txs = existing_edges_rows = relation_types = []
        if GRAPH_NAME in existing:
            labels = graph.ro_query(
                "MATCH (n) UNWIND labels(n) AS label RETURN DISTINCT label ORDER BY label",
                timeout=3000,
            ).result_set
            label_names = {_decode(row[0]) for row in labels}
            if not label_names.issubset({"Transaction", "InvestigationCase", "InvestigationMemory"}):
                raise RuntimeError(f"Refusing to seed: unexpected labels in target graph: {sorted(label_names)}")
            existing_txs = graph.ro_query(
                "MATCH (t:Transaction) RETURN t.txId, t.label, t.timeStep, t.sourceDataset ORDER BY t.txId",
                timeout=3000,
            ).result_set
            existing_edges_rows = graph.ro_query(
                "MATCH (s:Transaction)-[:FLOWS_TO]->(t:Transaction) RETURN s.txId, t.txId ORDER BY s.txId, t.txId",
                timeout=3000,
            ).result_set
            relation_types = graph.ro_query(
                "MATCH ()-[r]->() RETURN DISTINCT type(r) ORDER BY type(r)", timeout=3000,
            ).result_set
        expected_by_id = {tx["txId"]: tx for tx in TRANSACTIONS}
        for row in existing_txs:
            tx_id = _decode(row[0])
            expected = expected_by_id.get(tx_id)
            if expected is None or (_decode(row[1]), int(row[2]), _decode(row[3])) != (
                    expected["label"], expected["timeStep"], expected["sourceDataset"]):
                raise RuntimeError(f"Refusing to seed: conflicting or unexpected transaction {tx_id!r} in target graph")
        expected_edge_set = {(edge["source"], edge["target"]) for edge in EDGES}
        existing_edge_set = {(_decode(row[0]), _decode(row[1])) for row in existing_edges_rows}
        if not existing_edge_set.issubset(expected_edge_set):
            raise RuntimeError("Refusing to seed: target graph contains unexpected directed fixture edges")
        allowed_relations = {"FLOWS_TO", "GENERATED_MEMORY", "INVESTIGATES", "REFERENCES"}
        relation_names = {_decode(row[0]) for row in relation_types}
        if not relation_names.issubset(allowed_relations):
            raise RuntimeError(f"Refusing to seed: unexpected relationship types: {sorted(relation_names)}")

        graph.query(
            "UNWIND $transactions AS tx "
            "MERGE (t:Transaction {txId: tx.txId}) "
            "ON CREATE SET t.label = tx.label, t.timeStep = tx.timeStep, t.sourceDataset = tx.sourceDataset "
            "RETURN count(tx) AS created",
            {"transactions": TRANSACTIONS}, timeout=3000,
        )
        graph.query(
            "UNWIND $edges AS edge "
            "MATCH (s:Transaction {txId: edge.source}), (t:Transaction {txId: edge.target}) "
            "MERGE (s)-[:FLOWS_TO]->(t) "
            "RETURN count(edge) AS created",
            {"edges": EDGES}, timeout=3000,
        )
        tx_rows = graph.ro_query(
            "MATCH (t:Transaction) RETURN t.txId, t.label, t.timeStep, t.sourceDataset ORDER BY t.txId",
            timeout=3000,
        ).result_set
        edge_rows = graph.ro_query(
            "MATCH (s:Transaction)-[:FLOWS_TO]->(t:Transaction) RETURN s.txId, t.txId ORDER BY s.txId, t.txId",
            timeout=3000,
        ).result_set
        actual_txs = [tuple(_decode(value) if index != 2 else int(value)
                            for index, value in enumerate(row)) for row in tx_rows]
        expected_txs = [(tx["txId"], tx["label"], tx["timeStep"], tx["sourceDataset"]) for tx in TRANSACTIONS]
        actual_edges = [( _decode(row[0]), _decode(row[1])) for row in edge_rows]
        expected_edges = [(edge["source"], edge["target"]) for edge in EDGES]
        if actual_txs != sorted(expected_txs) or actual_edges != sorted(expected_edges):
            raise RuntimeError("Seed verification failed; node properties or directed edges differ from fixture")
        server = redis.info("server")
        return {
            "status": "PASS",
            "database": "FalkorDB graph module",
            "redis_compatible_server_version": server.get("redis_version"),
            "falkordb_module_version": module_versions["graph"],
            "connection": {"host": HOST, "port": PORT, "tls": False,
                           "nonproduction_container": container["container"],
                           "container_image": container["image"], "bound_to_loopback_only": True},
            "graph_name": GRAPH_NAME,
            "production_graph_name": production_settings.falkordb_graph_name,
            "preseed_graphs": existing,
            "target_graph_preexisted": GRAPH_NAME in existing,
            "preexisting_case_memory_nodes_preserved": True,
            "transaction_count": len(actual_txs), "flow_edge_count": len(actual_edges),
            "transaction_ids": [row[0] for row in actual_txs],
            "directed_edges": [list(edge) for edge in actual_edges],
            "transaction_schema": ["txId:string", "label:string", "timeStep:integer", "sourceDataset:string"],
            "synthetic_dataset": DATASET,
            "fixture_connected": True,
            "production_graph_writes": 0,
        }
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        redis.close()


if __name__ == "__main__":
    print(json.dumps(seed(), indent=2, sort_keys=True))
