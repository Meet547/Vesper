"""Gate 3: live algorithm, independent export, and bounded error controls."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import networkx as nx

from backend.track1.investigator import Track1Investigator
from backend.track1.store import EXPORT_EDGES, EXPORT_NODES
from backend.track1.tools import SHORTEST_TOOL, Track1Tools
from scripts.track1_container import run as lifecycle
from scripts.verify_track1_gates import MANIFEST, OUT, configured, save


def main():
    for gate in (1, 2):
        assert json.loads((OUT / f"gate{gate}_status.json").read_text())["status"] == "PASS"
    trace = []
    store = configured(record=trace.append)
    scenario = json.loads(MANIFEST.read_text())["scenarios"][0]
    args = dict(start_txid=scenario["start_txid"], end_txid=scenario["end_txid"], max_hops=3)
    selection = Track1Investigator(store).find_route(**args)
    save("gate3_selection.json", selection)
    assert selection["result"]["status"] == "PASS"
    assert selection["result"]["path"] == scenario["expected_path"]
    nodes, edges = store.read(EXPORT_NODES), store.read(EXPORT_EDGES)
    save("gate3_database_export.json", {"nodes": nodes, "edges": edges})
    graph = nx.DiGraph()
    graph.add_nodes_from(row[0] for row in nodes)
    graph.add_edges_from((row[0], row[1]) for row in edges)
    independent = nx.shortest_path(graph, args["start_txid"], args["end_txid"])
    assert independent == selection["result"]["path"]
    assert len(independent) - 1 == selection["result"]["hops"]
    save("gate3_networkx.json", {"status": "PASS", "version": nx.__version__, "path": independent,
                                "hops": len(independent)-1, "source": "gate3_database_export.json"})
    tools = Track1Tools(store)
    errors = {"unknown_id": tools.shortest_path(**{**args, "end_txid": "SYN-999999"}),
              "excessive_hops": tools.shortest_path(**{**args, "max_hops": 7})}
    # An actual one-millisecond server deadline, not a simulated exception.
    timeout_attempts = []
    for _ in range(20):
        result = Track1Tools(store, timeout_ms=1).shortest_path(**args)
        timeout_attempts.append(result)
        if result.get("error") == "timeout":
            break
    save("gate3_timeout_attempts.json", timeout_attempts)
    errors["timeout"] = timeout_attempts[-1]
    save("gate3_errors_partial.json", errors)
    assert errors["unknown_id"]["error"] == "unknown_id"
    assert errors["excessive_hops"]["error"] == "invalid_arguments"
    assert errors["timeout"].get("error") == "timeout"
    lifecycle("stop")
    errors["stopped_database"] = tools.shortest_path(**args)
    save("gate3_errors.json", errors)
    assert errors["stopped_database"]["error"] == "evidence_unavailable"
    assert all(row["path"] == [] for row in errors.values())
    assert "SYN-" not in json.dumps(errors["stopped_database"])
    store.close()
    lifecycle("restart")
    recovered = configured()
    assert Track1Tools(recovered).shortest_path(**args)["path"] == independent
    recovered.close()
    save("gate3_tool_schema.json", SHORTEST_TOOL)
    save("gate3_cypher.json", trace)
    save("gate3_status.json", {"status": "PASS", "time_IST": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                              "policy": "Deterministic destination-directed tool selection; no LLM involved.",
                              "evidence": ["gate3_syntax.txt", "gate3_selection.json", "gate3_networkx.json", "gate3_errors.json", "gate3_cypher.json"]})
    print(json.dumps({"gate": 3, "status": "PASS"}))


if __name__ == "__main__":
    main()
