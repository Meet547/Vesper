"""Create a new allowed graph; exact existing data is read-only, anything else rejected."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.track1.config import GRAPHS, Target
from backend.track1.store import EXPORT_EDGES, EXPORT_NODES, IsolationError, SyntheticStore

CREATE_NODES = ("UNWIND $nodes AS tx CREATE (t:Transaction {txId: tx.txId, label: tx.label, "
                "timeStep: tx.timeStep, sourceDataset: tx.sourceDataset}) RETURN count(t)")
CREATE_EDGES = ("UNWIND $edges AS edge MATCH (s:Transaction {txId: edge.source}), "
                "(t:Transaction {txId: edge.target}) CREATE (s)-[r:FLOWS_TO]->(t) RETURN count(r)")


def dataset(directory):
    manifest = json.loads((directory / "synthetic_manifest.json").read_text())
    if (manifest.get("sourceDataset") != "vesper_team_synthetic_v1" or not manifest.get("authorship")
            or not manifest.get("usage") or manifest.get("generator_version") != "1.0.0"):
        raise ValueError("Missing synthetic-data provenance")
    result = []
    for name in ("nodes.json", "edges.json"):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][name]["sha256"]:
            raise ValueError("Dataset hash differs from its provenance manifest")
        result.append(json.loads(raw))
    nodes, edges = result
    if len(nodes) != manifest["node_count"] or len(edges) != manifest["edge_count"]:
        raise ValueError("Dataset counts differ from manifest")
    return manifest, nodes, edges


def load(store, directory):
    manifest, nodes, edges = dataset(directory)
    store.identity()
    names = {name.decode() if isinstance(name, bytes) else name for name in store.redis.execute_command("GRAPH.LIST")}
    if names - GRAPHS:
        raise IsolationError("Unexpected graph in the disposable server")
    writes = []
    if store.target.graph not in names:
        for query, params in [(CREATE_NODES, {"nodes": nodes}), (CREATE_EDGES, {"edges": edges})]:
            key, values = next(iter(params.items()))
            for offset in range(0, len(values), 200):
                batch = values[offset:offset + 200]
                store.identity()
                response = store.graph.query(query, {key: batch}, timeout=10000)
                writes.append({"graph": store.target.graph, "query": query,
                               "batch_offset": offset, "parameter_count": len(batch), "rows": response.result_set})
    actual_nodes = store.read(EXPORT_NODES)
    actual_edges = store.read(EXPORT_EDGES)
    expected_nodes = [[n[k] for k in ("txId", "label", "timeStep", "sourceDataset")] for n in nodes]
    expected_edges = [[e["source"], e["target"]] for e in edges]
    if actual_nodes != expected_nodes or [r[:2] for r in actual_edges] != expected_edges:
        raise IsolationError("Unexpected existing graph contents; no records were cleared or overwritten")
    counts = store.counts()
    if counts["nodes"] != [[["Transaction"], manifest["node_count"]]] or counts["edges"] != [["FLOWS_TO", manifest["edge_count"]]]:
        raise IsolationError("Unexpected labels or relationships")
    return {"status": "PASS", "graph": store.target.graph, "writes": writes, "counts": counts,
            "existing_graph_read_only": not writes}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/track1"))
    args = parser.parse_args()
    store = SyntheticStore(Target.from_environment())
    try:
        print(json.dumps(load(store, args.data), indent=2))
    finally:
        store.close()
