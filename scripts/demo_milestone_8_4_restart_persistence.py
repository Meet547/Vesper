"""Run the Case A to fresh-process Case B proof on an isolated FalkorDB graph.

The script fails closed unless a separately configured M8.4 graph, explicit
nonproduction confirmation, and fixture transaction IDs are supplied. It never
falls back to the application's normal graph settings.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from time import perf_counter
from urllib.parse import urlsplit

from backend.app.config import Settings, get_settings


MARKER = "M84_JSON="
TARGET_GRAPH = "vesper_track2_synthetic_test"
TARGET_URL = "redis://127.0.0.1:6389"
TARGET_OWNER_ID = "track2-isolated-demo"


class QueryAccountingGraphStore(__import__("backend.app.services.graph_store", fromlist=["GraphStore"]).GraphStore):
    """Count application GraphStore query calls and their wall-clock latency."""

    def __init__(self, settings):
        super().__init__(settings)
        self.reset_query_accounting()

    def reset_query_accounting(self):
        self.read_latencies_ms = []
        self.write_latencies_ms = []

    def _read_rows(self, query, params=None):
        started = perf_counter()
        try:
            return super()._read_rows(query, params)
        finally:
            self.read_latencies_ms.append((perf_counter() - started) * 1000)

    def _write_rows(self, query, params=None):
        started = perf_counter()
        try:
            return super()._write_rows(query, params)
        finally:
            self.write_latencies_ms.append((perf_counter() - started) * 1000)

    def query_accounting(self):
        def summarize(values):
            return {"count": len(values), "total_latency_ms": round(sum(values), 3),
                    "mean_latency_ms": round(sum(values) / len(values), 3) if values else 0,
                    "max_latency_ms": round(max(values), 3) if values else 0}
        return {"source_database_reads": summarize(self.read_latencies_ms),
                "database_writes": summarize(self.write_latencies_ms),
                "scope": "application GraphStore query calls; connection health handshake excluded"}


def isolated_settings() -> Settings:
    confirmation = os.getenv("BUREAU_M84_GRAPH_ISOLATED_CONFIRM", "")
    graph_name = os.getenv("BUREAU_M84_ISOLATED_GRAPH_NAME", "").strip()
    if confirmation != "I_CONFIRM_NONPRODUCTION" or not graph_name:
        raise RuntimeError("BLOCKED: configure the Vesper nonproduction graph and set BUREAU_M84_GRAPH_ISOLATED_CONFIRM=I_CONFIRM_NONPRODUCTION")
    if graph_name != TARGET_GRAPH:
        raise RuntimeError(f"BLOCKED: Track 2 persistence must use the dedicated Vesper graph {TARGET_GRAPH!r}")
    url = os.getenv("BUREAU_M84_ISOLATED_FALKORDB_URL", "").strip()
    host = os.getenv("BUREAU_M84_ISOLATED_FALKORDB_HOST", "").strip()
    password = os.getenv("BUREAU_M84_ISOLATED_FALKORDB_PASSWORD", "")
    if url != TARGET_URL or host or password:
        raise RuntimeError(f"BLOCKED: Track 2 persistence must use only {TARGET_URL} with no remote host or credentials")

    production = get_settings()
    isolated_host = _endpoint(url)[1] if url else host.lower()
    production_host = (_endpoint(production.falkordb_url)[1] if production.falkordb_url.strip()
                       else production.falkordb_host.strip().lower())
    if isolated_host and production_host and isolated_host == production_host:
        raise RuntimeError("BLOCKED: isolated endpoint shares the application's configured graph host")
    if production.falkordb_graph_name == TARGET_GRAPH:
        raise RuntimeError("BLOCKED: the configured application graph name collides with the Vesper test graph")
    return Settings(
        _env_file=None, app_mode="cloud", app_host="localhost", auth_mode="cognito",
        falkordb_url=url, falkordb_host=host,
        falkordb_port=int(os.getenv("BUREAU_M84_ISOLATED_FALKORDB_PORT", "6379")),
        falkordb_username=os.getenv("BUREAU_M84_ISOLATED_FALKORDB_USERNAME", ""),
        falkordb_password=password, falkordb_graph_name=graph_name,
        falkordb_ssl=os.getenv("BUREAU_M84_ISOLATED_FALKORDB_SSL", "true").lower() == "true",
        falkordb_query_timeout_ms=3000, falkordb_socket_timeout_seconds=5,
    )


def _endpoint(value: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(value)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


def _emit(payload: dict) -> None:
    print(MARKER + json.dumps(payload, separators=(",", ":")))


def _close(store) -> None:
    client = getattr(store, "_client", None)
    close = getattr(client, "close", None)
    if callable(close):
        close()


def run_stage(stage: str, case_a_json: str | None = None) -> dict:
    from backend.app.agents.orchestrator import InvestigationOrchestrator
    settings = isolated_settings()
    store = QueryAccountingGraphStore(settings)
    try:
        health = store.health()
        if not health.get("database_connected"):
            raise RuntimeError("BLOCKED: isolated FalkorDB is unavailable")
        # Match the isolated identity used by run_track2_demo.sh and the UI;
        # do not allow an environment override to hide saved memory from Case B.
        owner_id = TARGET_OWNER_ID
        max_hops = max(2, min(4, int(os.getenv("BUREAU_M84_MAX_HOPS", "3"))))
        orchestrator = InvestigationOrchestrator(store, settings)
        if stage == "write":
            seed_a = os.getenv("BUREAU_M84_SEED_A", "").strip()
            if not seed_a.isdigit():
                raise RuntimeError("BLOCKED: configure BUREAU_M84_SEED_A for a fixture transaction in the isolated graph")
            investigation_started = perf_counter()
            saved = orchestrator.investigate(seed_a, max_hops, owner_id=owner_id)
            investigation_latency_ms = round((perf_counter() - investigation_started) * 1000, 3)
            if not saved or not saved.get("persisted"):
                raise RuntimeError("FAIL: Case A did not save to the isolated graph")
            return {"stage": "write", "case_id": saved["case_id"], "memory_id": saved["memory_id"],
                    "seed_tx_id": seed_a, "graph_name": settings.falkordb_graph_name,
                    "verified_edge_ids": [edge["edge_id"] for edge in saved["evidence_ledger"].get("edges", [])],
                    "selected_policy_actions": len(saved.get("graph_decisions", [])),
                    "investigation_latency_ms": investigation_latency_ms,
                    "query_accounting": store.query_accounting()}
        if stage != "read" or not case_a_json:
            raise RuntimeError("Invalid internal restart demo stage")
        prior = json.loads(case_a_json)
        seed_b = os.getenv("BUREAU_M84_SEED_B", "").strip()
        if not seed_b.isdigit():
            raise RuntimeError("BLOCKED: configure BUREAU_M84_SEED_B for a related fixture transaction")
        baseline_started = perf_counter()
        baseline = orchestrator.preview(seed_b, max_hops, use_local_model=False,
                                        owner_id=owner_id, memory_enabled=False)
        baseline_latency_ms = round((perf_counter() - baseline_started) * 1000, 3)
        baseline_accounting = store.query_accounting()
        store.reset_query_accounting()
        memory_started = perf_counter()
        with_memory = orchestrator.preview(seed_b, max_hops, use_local_model=False,
                                           owner_id=owner_id, memory_enabled=True)
        memory_latency_ms = round((perf_counter() - memory_started) * 1000, 3)
        memory_accounting = store.query_accounting()
        candidates = [item for item in with_memory["related_memories"] if item.get("caseId") == prior["case_id"]]
        decision = next((item for item in with_memory["graph_decisions"]
                         if item["selected_action"] == "follow_verified_memory_route"), None)
        return {
            "stage": "read", "fresh_process": True,
            "prior_case_id": prior["case_id"], "prior_memory_id": prior["memory_id"],
            "historian_recalled_prior_case": bool(candidates),
            "skeptic_status": candidates[0].get("validationStatus") if candidates else None,
            "memory_disabled_actions": [item["selected_action"] for item in baseline["graph_decisions"]],
            "memory_enabled_actions": [item["selected_action"] for item in with_memory["graph_decisions"]],
            "memory_route_decision": decision.get("action_outcome") if decision else None,
            "verified_current_path_ids": [path["evidence_id"] for path, check in zip(
                with_memory["traces"], with_memory["skeptic"]["checks"]["pathValidation"]["paths"])
                if check.get("valid")],
            "same_owner_scope": True,
            "query_accounting": {"memory_disabled": baseline_accounting,
                                 "memory_enabled": memory_accounting},
            "investigation_latency_ms": {"memory_disabled": baseline_latency_ms,
                                         "memory_enabled": memory_latency_ms},
            "selected_policy_actions": {"memory_disabled": len(baseline.get("graph_decisions", [])),
                                        "memory_enabled": len(with_memory.get("graph_decisions", []))},
        }
    finally:
        _close(store)


def main() -> int:
    if len(sys.argv) > 1:
        stage = sys.argv[1]
        case_a = sys.argv[2] if len(sys.argv) > 2 else None
        _emit(run_stage(stage, case_a))
        return 0
    try:
        isolated_settings()
    except Exception as exc:
        _emit({"status": "BLOCKED", "reason": str(exc), "writes_performed": 0})
        return 2
    writer = subprocess.run([sys.executable, __file__, "write"], capture_output=True, text=True, check=False,
                            env=os.environ.copy(), timeout=45)
    write_data = _last_json(writer.stdout)
    if writer.returncode or not write_data or not write_data.get("case_id"):
        print(writer.stderr, file=sys.stderr)
        _emit({"status": "FAIL", "stage": "case_a_write", "result": write_data, "writes_performed": bool(write_data)})
        return 1
    # The writer process has exited and closed its FalkorDB client before this
    # second process is launched.
    reader = subprocess.run([sys.executable, __file__, "read", json.dumps(write_data)], capture_output=True,
                            text=True, check=False, env=os.environ.copy(), timeout=60)
    read_data = _last_json(reader.stdout)
    if reader.returncode or not read_data:
        print(reader.stderr, file=sys.stderr)
        _emit({"status": "FAIL", "stage": "fresh_process_read", "case_a": write_data, "result": read_data})
        return 1
    success = (read_data.get("historian_recalled_prior_case") is True
               and read_data.get("skeptic_status") == "VERIFIED_RELEVANT"
               and bool(read_data.get("memory_route_decision", {}).get("memory_route_verified")))
    _emit({"status": "PASS" if success else "FAIL", "case_a": write_data, "fresh_process_case_b": read_data,
           "writes_performed": True})
    return 0 if success else 1


def _last_json(output: str) -> dict | None:
    items = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
    return json.loads(items[-1]) if items else None


if __name__ == "__main__":
    raise SystemExit(main())
