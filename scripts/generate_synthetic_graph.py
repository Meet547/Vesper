"""Team-authored deterministic scenarios; no external records or assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

VERSION = "1.0.0"
SEED = 20261018
SIZE = 4000
SOURCE = "vesper_team_synthetic_v1"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def generate(output: Path, seed: int = SEED):
    rng = random.Random(seed)
    txid = lambda i: f"SYN-{i:06d}"
    edges = set()
    steps = {}
    scenarios = []
    for group in range(3):
        a, b, c, d, e, f = [txid(group * 6 + i) for i in range(1, 7)]
        path = [a, b, c, d]
        edges.update([(a, b), (b, c), (c, d), (a, e), (e, f)])
        steps.update({a: 0, b: 1, c: 2, d: 3, e: 1, f: 2})
        scenarios.append({"name": f"Scenario {group + 1}", "start_txid": a, "end_txid": d,
                          "expected_path": path,
                          "edge_ids": [f"{x}->{y}" for x, y in zip(path, path[1:])],
                          "edge_id_kind": "derived endpoint reference, not native database ID",
                          "decoy_path": [a, e, f], "missing_decoy_edge": [f, d]})
    layers = [[] for _ in range(32)]
    for number in range(19, SIZE + 1):
        layer = (number - 19) % len(layers)
        node = txid(number)
        steps[node] = layer
        layers[layer].append(node)
    for layer, nodes in enumerate(layers[:-1]):
        for index, node in enumerate(nodes):
            degree = 5 if index % 17 == 0 else rng.randint(1, 2)
            for destination in rng.sample(layers[layer + 1], degree):
                edges.add((node, destination))
    outgoing = {txid(i): 0 for i in range(1, SIZE + 1)}
    for source, target in edges:
        assert steps[source] < steps[target]
        outgoing[source] += 1
    nodes = [{"txId": node, "label": "endpoint" if degree == 0 else "hub" if degree > 1 else "relay",
              "timeStep": steps[node], "sourceDataset": SOURCE} for node, degree in sorted(outgoing.items())]
    edge_rows = [{"source": a, "target": b} for a, b in sorted(edges)]
    node_bytes, edge_bytes = encoded(nodes), encoded(edge_rows)
    manifest = {
        "generator": "scripts/generate_synthetic_graph.py", "generator_version": VERSION,
        "generator_sha256": sha256(Path(__file__).read_bytes()), "seed": seed,
        "authorship": "Independently authored for the Vesper team with AI assistance; no third-party dataset input.",
        "usage": "Team-authorized synthetic scenario data for this project; no real transactions, addresses or personal data.",
        "sourceDataset": SOURCE, "schema": {"node_label": "Transaction", "relationship_type": "FLOWS_TO",
            "properties": {"txId": "string: SYN-[0-9]{6}", "label": "hub|relay|endpoint",
                           "timeStep": "integer", "sourceDataset": "string"}, "relationship_properties": []},
        "node_count": len(nodes), "edge_count": len(edges),
        "counts_by_node_label": {"Transaction": len(nodes)}, "counts_by_relationship_type": {"FLOWS_TO": len(edges)},
        "counts_by_role": {role: sum(n["label"] == role for n in nodes) for role in ("hub", "relay", "endpoint")},
        "files": {"nodes.json": {"sha256": sha256(node_bytes), "bytes": len(node_bytes)},
                  "edges.json": {"sha256": sha256(edge_bytes), "bytes": len(edge_bytes)}},
        "scenarios": scenarios, "counterfactual_edge": scenarios[0]["expected_path"][1:3],
        "counterfactual_scenario": 0,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "nodes.json").write_bytes(node_bytes)
    (output / "edges.json").write_bytes(edge_bytes)
    (output / "synthetic_manifest.json").write_bytes(encoded(manifest))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    result = generate(args.output, args.seed)
    print(json.dumps({k: result[k] for k in ("generator_version", "generator_sha256", "seed", "node_count", "edge_count", "files")}))
