from __future__ import annotations

from .store import EvidenceUnavailable, check_hops, check_id


def unavailable():
    return {"status": "evidence_unavailable", "message": "evidence unavailable",
            "database_connected": False, "paths": [], "action": None, "conclusion": None, "events": []}


class Track1Investigator:
    """Deterministic tool-using policy; no LLM or fixture evidence is involved."""

    def __init__(self, store):
        self.store = store

    def investigate(self, start_txid, max_hops=3):
        check_id(start_txid)
        check_hops(max_hops)
        events = []
        try:
            health = self.store.health()  # Must succeed before any input/event is echoed.
            events.append({"selected_tool": "get_transaction", "arguments": {"tx_id": start_txid}})
            seed = self.store.get_transaction(start_txid)
            if seed is None:
                return {"status": "not_found", **health, "paths": [], "action": None,
                        "conclusion": None, "events": events}
            events.append({"selected_tool": "expand_outgoing", "arguments": {
                "start_txid": start_txid, "max_hops": max_hops},
                "reason": "The seed exists; inspect bounded directed connections."})
            expanded = self.store.expand_outgoing(start_txid, max_hops)
            candidates = expanded["paths"]
            if expanded["truncated"]:
                return {"status": "bounded_search_truncated", **health, "paths": [], "action": None,
                        "conclusion": None, "events": events}
            accepted = []
            checks = []
            for path in candidates:
                edge_checks = [self.store.edge(a, b) for a, b in zip(path["txids"], path["txids"][1:])]
                checks.extend(edge_checks)
                if (all(c["row_count"] == 1 for c in edge_checks)
                        and [c["native_relationship_ids"][0] for c in edge_checks] == path["relationship_ids"]):
                    accepted.append(path)
            full_depth = [p for p in accepted if p["hops"] == max_hops]
            chosen = full_depth[0] if full_depth else None
            action = "inspect_endpoint" if chosen else "request_additional_evidence"
            events.append({"selected_action": action, "reason": "An independently checked path reaches the requested depth."
                           if chosen else "No independently checked path reaches the requested depth."})
            return {"status": "evidence_available", **health, "seed": seed, "paths": accepted,
                    "accepted_lead": chosen, "edge_checks": checks, "action": action,
                    "conclusion": None, "events": events,
                    "notice": "Synthetic scenario leads, not legal conclusions about any person."}
        except EvidenceUnavailable:
            return unavailable()
