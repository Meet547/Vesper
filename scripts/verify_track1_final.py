"""Final HTTP outage/recovery and read-only counterfactual recheck."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from backend.track1.investigator import Track1Investigator
from scripts.track1_container import run as lifecycle
from scripts.verify_track1_gates import MANIFEST, OUT, configured, positive, save


def main():
    manifest = json.loads(MANIFEST.read_text())
    scenario = manifest["scenarios"][0]
    trace = []
    primary = configured(record=trace.append)
    before = positive(primary, scenario, "final_primary.json")
    counter = configured("vesper_counterfactual", trace.append)
    assert counter.edge(*manifest["counterfactual_edge"])["row_count"] == 0
    after = Track1Investigator(counter).investigate(scenario["start_txid"], 3)
    assert after["action"] == "request_additional_evidence" and after["accepted_lead"] is None
    assert counter.counts()["edges"] == [["FLOWS_TO", manifest["edge_count"]-1]]
    for i, other in enumerate(manifest["scenarios"][1:], 2):
        positive(counter, other, f"final_counterfactual_unaffected_{i}.json")
    assert primary.counts() == json.loads((OUT / "gate1_counts.txt").read_text())
    save("final_counterfactual.json", {"status": "PASS", "mode": "Read-only recheck of preserved deletion state",
         "original_deletion_evidence": "gate2_delete.txt", "before": before, "after": after, "primary_unchanged": True})
    save("final_counterfactual_cypher.json", trace)
    primary.close()
    counter.close()
    # Use a separate HTTP process and fresh store per request, not TestClient fixtures.
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "VESPER_TRACK": "track1_synthetic",
           "VESPER_TRACK1_GRAPH": "vesper_synthetic_verify", "VESPER_TRACK1_TARGET_FILE": str((OUT / "isolation-target.json").resolve())}
    with (OUT / "final_http_server.txt").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.track1.app:create_app", "--factory",
                                    "--host", "127.0.0.1", "--port", "18783"], env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url="http://127.0.0.1:18783", trust_env=False, timeout=20) as client:
                for _ in range(40):
                    if process.poll() is not None:
                        raise RuntimeError("HTTP server exited before readiness")
                    try:
                        if client.get("/api/health").status_code == 200:
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.25)
                body = {"start_txid": scenario["start_txid"], "max_hops": 3}
                positive_http = client.post("/api/investigate", json=body).json()
                assert positive_http["accepted_lead"]["txids"] == scenario["expected_path"]
                route = client.post("/api/route", json={**body, "end_txid": scenario["end_txid"]}).json()
                assert route["result"]["path"] == scenario["expected_path"]
                html = client.get("/")
                assert html.status_code == 200 and "Team-authored synthetic scenarios" in html.text
                assert client.post("/api/investigate", json={"start_txid": "730000004"}).status_code == 422
                save("final_http_positive.json", {"investigation": positive_http, "route": route, "page_status": html.status_code})
                lifecycle("stop")
                negative = client.post("/api/investigate", json=body).json()
                negative_route = client.post("/api/route", json={**body, "end_txid": scenario["end_txid"]}).json()
                save("final_http_negative.json", {"investigation": negative, "route": negative_route})
                for result in (negative, negative_route):
                    assert result["message"] == "evidence unavailable" and result["paths"] == []
                    assert result["action"] is None and result["conclusion"] is None
                    assert "SYN-" not in json.dumps(result)
                lifecycle("restart")
                recovery = client.post("/api/investigate", json=body).json()
                save("final_http_recovery.json", recovery)
                assert recovery["accepted_lead"]["txids"] == scenario["expected_path"]
        finally:
            process.terminate()
            process.wait(timeout=10)
    save("final_controls_status.json", {"status": "PASS", "time_IST": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                                        "evidence": ["final_counterfactual.json", "final_http_positive.json", "final_http_negative.json", "final_http_recovery.json"]})
    print(json.dumps({"final_controls": "PASS"}))


if __name__ == "__main__":
    main()
