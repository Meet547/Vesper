"""Live evidence runner; failures stop the gate sequence."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.track1.config import Target
from backend.track1.investigator import Track1Investigator
from backend.track1.store import SyntheticStore
from scripts.load_track1_graph import load
from scripts.track1_container import run as lifecycle

OUT = Path("evidence/track1")
MANIFEST = Path("manifest/synthetic_manifest.json")
DELETE_EDGE = ("MATCH (s:Transaction {txId: $source})-[r:FLOWS_TO]->(t:Transaction {txId: $target}) "
               "DELETE r RETURN count(r) AS removed")


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n")


def configured(graph="vesper_synthetic_verify", record=None):
    os.environ["VESPER_TRACK"] = "track1_synthetic"
    os.environ["VESPER_TRACK1_TARGET_FILE"] = str(OUT / "isolation-target.json")
    os.environ["VESPER_TRACK1_GRAPH"] = graph
    return SyntheticStore(Target.from_environment(), record)


def positive(store, scenario, name):
    result = Track1Investigator(store).investigate(scenario["start_txid"], 3)
    save(name, result)
    assert result["database_connected"] and result["mode"] == "database"
    assert result["accepted_lead"]["txids"] == scenario["expected_path"]
    assert result["action"] == "inspect_endpoint"
    assert len(result["accepted_lead"]["relationship_ids"]) == 3
    return result


def gate1():
    manifest = json.loads(MANIFEST.read_text())
    trace = []
    store = configured(record=trace.append)
    counts = store.counts()
    save("gate1_counts.txt", counts)
    assert counts["nodes"] == [[["Transaction"], manifest["node_count"]]]
    assert counts["edges"] == [["FLOWS_TO", manifest["edge_count"]]]
    for i, scenario in enumerate(manifest["scenarios"]):
        positive(store, scenario, "gate1_positive.txt" if i == 0 else f"gate1_positive_scenario_{i+1}.json")
    save("gate1_cypher.txt", trace)
    lifecycle("stop")
    # Reuse the already-warm store and investigator path to test stale-cache behavior.
    negative = Track1Investigator(store).investigate(manifest["scenarios"][0]["start_txid"], 3)
    save("gate1_negative.txt", negative)
    raw = json.dumps(negative)
    assert negative["status"] == "evidence_unavailable"
    assert negative["paths"] == [] and negative["action"] is None and negative["conclusion"] is None
    assert not any(tx in raw for tx in manifest["scenarios"][0]["expected_path"])
    store.close()
    lifecycle("restart")
    recovery_trace = []
    store = configured(record=recovery_trace.append)
    positive(store, manifest["scenarios"][0], "gate1_restarted.txt")
    save("gate1_restarted_cypher.txt", recovery_trace)
    store.close()
    save("gate1_status.json", {"status": "PASS", "time_IST": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                               "positive": "gate1_positive.txt", "negative": "gate1_negative.txt",
                               "recovery": "gate1_restarted.txt", "query_log": "gate1_cypher.txt",
                               "fail_closed_source": "backend/track1/investigator.py:investigate and unavailable"})


def gate2():
    assert json.loads((OUT / "gate1_status.json").read_text())["status"] == "PASS"
    manifest = json.loads(MANIFEST.read_text())
    scenario = manifest["scenarios"][0]
    trace = []
    store = configured(record=trace.append)
    before_counts = store.counts()
    old = positive(store, scenario, "gate2_primary_positive.txt")
    checks = [store.edge(a, b) for a, b in zip(scenario["expected_path"], scenario["expected_path"][1:])]
    save("gate2_edges.txt", checks)
    assert all(c["row_count"] == 1 for c in checks)
    assert all(type(c["native_relationship_ids"][0]) is int for c in checks)
    decoy_edges = [store.edge(a, b) for a, b in zip(scenario["decoy_path"], scenario["decoy_path"][1:])]
    missing = store.edge(*scenario["missing_decoy_edge"])
    assert all(c["row_count"] == 1 for c in decoy_edges) and missing["row_count"] == 0
    save("gate2_leads.txt", {"accepted": {"path": old["accepted_lead"], "reason": "Every directed edge returned exactly one row.", "checks": checks},
                              "rejected": {"candidate_path": scenario["decoy_path"] + [scenario["end_txid"]],
                                           "reason": "The decoy branch exists, but the required connection to the destination returns zero rows.",
                                           "existing_decoy_edges": decoy_edges, "missing_edge_result": missing}})
    cf_trace = []
    counter = configured("vesper_counterfactual", cf_trace.append)
    load_result = load(counter, Path("data/track1"))
    save("gate2_counterfactual_load.txt", load_result)
    before = positive(counter, scenario, "gate2_counterfactual_before.txt")
    assert counter.target.graph == "vesper_counterfactual"
    edge = manifest["counterfactual_edge"]
    assert counter.edge(*edge)["row_count"] == 1
    counter.identity()
    deleted = counter.graph.query(DELETE_EDGE, {"source": edge[0], "target": edge[1]}, timeout=2000).result_set
    save("gate2_delete.txt", {"graph": counter.target.graph, "query": DELETE_EDGE,
                              "parameters": {"source": edge[0], "target": edge[1]}, "rows": deleted})
    assert deleted == [[1]]
    after = Track1Investigator(counter).investigate(scenario["start_txid"], 3)
    save("gate2_counterfactual_after.txt", after)
    assert after["action"] == "request_additional_evidence" and after["accepted_lead"] is None
    for i, other in enumerate(manifest["scenarios"][1:], 2):
        positive(counter, other, f"gate2_unaffected_scenario_{i}.txt")
    after_counts = store.counts()
    save("gate2_primary_unchanged.txt", {"before": before_counts, "after": after_counts})
    assert before_counts == after_counts == json.loads((OUT / "gate1_counts.txt").read_text())
    save("gate2_counterfactual.txt", {"old_action": before["action"], "new_action": after["action"],
                                     "difference": "Removing one required edge removes the three-hop lead; the policy requests more evidence.",
                                     "removed_edge": edge, "other_planted_paths_unchanged": True,
                                     "primary_graph_unchanged": True})
    save("gate2_cypher.txt", {"primary": trace, "counterfactual": cf_trace})
    save("gate2_status.json", {"status": "PASS", "time_IST": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                               "native_relationship_ids": [c["native_relationship_ids"][0] for c in checks],
                               "evidence": ["gate2_edges.txt", "gate2_leads.txt", "gate2_delete.txt", "gate2_counterfactual.txt", "gate2_primary_unchanged.txt", "gate2_cypher.txt"]})
    store.close()
    counter.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("gate", choices=["1", "2"])
    selected = parser.parse_args().gate
    try:
        {"1": gate1, "2": gate2}[selected]()
    except Exception as error:
        save(f"gate{selected}_status.json", {"status": "FAIL", "error_type": type(error).__name__,
                                            "message": "Stopped; inspect saved stage outputs before continuing."})
        raise
    print(json.dumps({"gate": selected, "status": "PASS", "evidence": f"evidence/track1/gate{selected}_status.json"}))
