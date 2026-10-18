"""Authoritative, serializable shared state for one evidence-first case.

The context stores compact observations and references, never model chain-of-thought.
Graph facts are derived from the deterministic ledger and cannot be replaced by an
interpretation update.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


AUTHORITY = {
    "graph": "DETERMINISTIC_GRAPH_EVIDENCE",
    "memory": "REVALIDATED_MEMORY",
    "model": "MODEL_INTERPRETATION",
    "hypothesis": "UNVERIFIED_HYPOTHESIS",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SharedInvestigationContext:
    """One mutable coordinator object; agents contribute typed updates to it."""

    def __init__(self, case_id: str, seed_transaction: str, max_hops: int,
                 investigation_id: str | None = None):
        self._ledger: dict[str, Any] = {}
        self._data: dict[str, Any] = {
            "schema_version": "1.0",
            "case_id": case_id,
            "investigation_id": investigation_id,
            "seed_transaction": str(seed_transaction),
            "investigation_goal": f"Trace transaction {seed_transaction} within {max_hops} hop(s), verify graph claims, and check relevant saved cases.",
            "status": "running", "active_agents": [], "report_status": "pending",
            "memory_lookup_status": "pending", "skeptic_conclusions": {},
            "graph_scope": {"hop_depth": max_hops, "current_nodes": [], "current_edges": [], "paths": [],
                            "path_details": []},
            "evidence_ledger": {},
            "verified_facts": [], "verified_claims": [], "rejected_claims": [], "unverified_claims": [],
            "hypotheses": [], "memory_candidates": [], "validated_memories": [],
            "graph_decisions": [], "current_graph_decision": None,
            "graph_action_budget": {"limit": 16, "used": 0, "remaining": 16, "exhausted": False},
            "agent_updates": [], "shared_readers": [], "handoffs": [], "open_questions": [], "next_actions": [],
            "constraints": ["Deterministic graph evidence is authoritative.", "Dataset labels do not establish ownership, intent, or criminal conduct."],
            "current_objective": "Validate the seed and trace bounded directed paths.",
            "current_focus": "validating seed transaction",
            "next_expected_agent": "Tracer",
            "timestamps": {"created_at": _now(), "updated_at": _now()},
            "authority": dict(AUTHORITY),
        }

    def add_update(self, agent: str, kind: str, summary: str, evidence_ids: list[str] | None = None,
                   source_type: str = "graph", verification: str = "verified") -> None:
        self._data["agent_updates"].append({
            "agent": agent, "kind": kind, "summary": str(summary)[:240],
            "evidence_ids": list(dict.fromkeys(evidence_ids or []))[:30],
            "source_type": source_type, "authority": AUTHORITY.get(source_type, AUTHORITY["hypothesis"]),
            "verification": verification, "timestamp": _now(),
        })
        self._touch()

    def record_read(self, agent: str) -> None:
        if agent not in self._data["shared_readers"]:
            self._data["shared_readers"].append(agent)
            self._touch()

    def record_graph_decision(self, decision: dict[str, Any]) -> None:
        """Record a bounded, user-visible decision and its evidence/outcome."""
        safe = deepcopy(decision)
        self._data["graph_decisions"].append(safe)
        if safe.get("graph_action_budget"):
            self._data["graph_action_budget"] = deepcopy(safe["graph_action_budget"])
        self._data["graph_decisions"] = self._data["graph_decisions"][-30:]
        self._data["current_graph_decision"] = deepcopy(safe)
        self._touch()

    def add_handoff(self, source: str, target: str, handoff_type: str, summary: str,
                    evidence_ids: list[str] | None = None, **details: Any) -> dict[str, Any]:
        item = {"from": source, "to": target, "type": handoff_type,
                "summary": str(summary)[:240], "evidence_ids": list(dict.fromkeys(evidence_ids or []))[:30],
                "timestamp": _now(), **deepcopy(details)}
        self._data["handoffs"].append(item)
        self._touch()
        return deepcopy(item)

    def set_graph_evidence(self, ledger: dict[str, Any], traces: list[dict[str, Any]]) -> None:
        # Keep the deterministic source private to this object; callers receive snapshots.
        self._ledger = deepcopy(ledger)
        transactions = self._ledger.get("transactions", {})
        edges = self._ledger.get("edges", [])
        paths = self._ledger.get("paths", [])
        self._data["evidence_ledger"] = {
            "ref": "preview.evidence_ledger", "source_graph": self._ledger.get("source_graph", "unknown"),
            "authority": AUTHORITY["graph"], "path_count": len(paths),
            "transaction_count": len(transactions), "edge_count": len(edges),
        }
        self._data["graph_scope"].update({
            "search_truncated": bool((self._ledger.get("scope_stats", {}).get("truncated_enumeration", {}) or {}).get("value")),
            "hop_depth": int(self._ledger.get("completeness", {}).get("max_hops", self._data["graph_scope"].get("hop_depth", 1))),
            "current_direction": next((path.get("direction") for path in reversed(self._ledger.get("paths", []))), None),
            "current_nodes": sorted(transactions),
            "current_edges": [edge.get("edge_id") for edge in edges if edge.get("edge_id")],
            "paths": [f"path:{path.get('path_index')}" for path in paths],
            "path_details": [{"evidence_id": path.get("evidence_id") or f"path:{path.get('path_index')}",
                              "direction": path.get("direction"), "hops": path.get("hop_count"),
                              "node_ids": list(path.get("node_ids") or []),
                              "edge_ids": list(path.get("edge_ids") or []),
                              "verification": "verified" if path.get("valid") is True else "unverified",
                              "reason": path.get("validation_reason")}
                             for path in paths],
        })
        valid_indices = {path.get("path_index") for path in paths if path.get("valid") is True}
        verified_nodes = {str(node) for path in paths if path.get("valid") is True
                          for node in path.get("node_ids", [])}
        verified_nodes.add(self._data["seed_transaction"])
        self._data["verified_facts"] = [
            {"fact_id": f"tx:{tx_id}", "claim_type": "transaction_label", "tx_id": tx_id,
             "label": record.get("label", "unknown"), "source_type": "graph",
             "authority": AUTHORITY["graph"], "verification": "verified"}
            for tx_id, record in sorted(transactions.items()) if tx_id in verified_nodes
        ] + [
            {"fact_id": edge.get("edge_id"), "claim_type": "directed_edge",
             "source": edge.get("source"), "target": edge.get("target"),
             "source_type": "graph", "authority": AUTHORITY["graph"], "verification": "verified"}
            for edge in edges if edge.get("edge_id") and valid_indices.intersection(edge.get("evidence_paths", []))
        ]
        for path in paths:
            if path.get("valid") is not True:
                self._data["unverified_claims"].append({
                    "claim_id": f"path:{path.get('path_index')}", "claim_type": "graph_path",
                    "reason": path.get("validation_reason") or "Independent path validation did not pass.",
                    "source_type": "graph", "verification": "unverified",
                    "evidence_ids": [f"path:{path.get('path_index')}"],
                })
        self._data["constraints"].append("Only returned paths are in scope; bounded enumeration does not establish completeness.")
        self._data["open_questions"] = ["Do any saved cases contain relevant paths that remain valid in the current graph?"]
        self._data["next_actions"] = ["Skeptic: validate returned paths and deterministic counts.",
                                       "Historian: find overlapping saved cases; Skeptic: revalidate any candidates."]
        self._touch()

    def add_memory_candidate(self, candidate: dict[str, Any]) -> None:
        self._data["memory_candidates"].append({
            "case_id": candidate.get("caseId"),
            "shared_transactions": list(candidate.get("sharedTransactions") or [])[:30],
            "source_type": "memory", "verification": "unverified",
            "authority": "UNVERIFIED_MEMORY",
        })
        self._touch()

    def add_validated_memory(self, memory: dict[str, Any]) -> None:
        status = memory.get("validationStatus", "UNVERIFIED")
        verification = ("verified" if status in {"VERIFIED_RELEVANT", "PARTIALLY_RELEVANT"}
                        else "unverified" if status == "UNVERIFIED" else "rejected")
        self._data["validated_memories"].append({
            "case_id": memory.get("caseId"), "status": status,
            "shared_transactions": list(memory.get("sharedTransactions") or [])[:30],
            "supporting_evidence_ids": list(memory.get("supportingEvidenceIds") or [])[:30],
            "summary": str(memory.get("validationReason") or "")[:240],
            "source_type": "memory",
            "verification": verification,
            "authority": AUTHORITY["memory"] if verification == "verified" else "MEMORY_REVIEW",
        })
        self._touch()

    def classify_claims(self, claims: list[dict[str, Any]]) -> None:
        buckets = {"verified": "verified_facts", "rejected": "rejected_claims",
                   "unverified": "unverified_claims"}
        for claim in claims:
            status = str(claim.get("verification_status") or "unverified").lower()
            bucket = buckets.get(status, "unverified_claims")
            safe_claim = {key: deepcopy(claim.get(key)) for key in
                          ("claim_id", "claim_type", "claim_text", "claim_value", "expected_value", "reason", "evidence_ids")
                          if key in claim}
            safe_claim.update({"source_type": "model", "authority": AUTHORITY["model"],
                               "verification": status if status in buckets else "unverified"})
            # A model claim is explicitly qualified and never replaces the graph facts above.
            if bucket == "verified_facts":
                self._data["verified_claims"].append(safe_claim)
                self._data["agent_updates"].append({"agent": "Skeptic", "kind": "validated_model_claim", **safe_claim})
            else:
                self._data[bucket].append(safe_claim)
            for hypothesis in self._data["hypotheses"]:
                if hypothesis.get("claim_id") == claim.get("claim_id"):
                    hypothesis["verification"] = safe_claim["verification"]
        self._data["skeptic_conclusions"]["claim_counts"] = {
            status: sum(claim.get("verification_status") == status for claim in claims)
            for status in buckets
        }
        self._touch()

    def set_activity(self, agent: str, stage: str, status: str) -> None:
        active = self._data["active_agents"]
        if status == "started" and agent not in active:
            active.append(agent)
        elif status != "started" and agent in active:
            active.remove(agent)
        if stage == "memory_lookup" and agent == "Historian":
            self._data["memory_lookup_status"] = "running" if status == "started" else "complete"
        if stage == "reporting":
            self._data["report_status"] = "assembling"
        self._touch()

    def set_skeptic_review(self, review: dict[str, Any]) -> None:
        validation = review.get("checks", {}).get("pathValidation", {})
        self._data["skeptic_conclusions"].update({
            "review_status": review.get("reviewStatus"),
            "valid_paths": validation.get("validPathCount", 0),
            "invalid_paths": validation.get("invalidPathCount", 0),
            "limitations": list(review.get("flags", [])),
        })
        self._touch()

    def add_hypothesis(self, claim_id: str | None, summary: str) -> None:
        self._data["hypotheses"].append({
            "claim_id": claim_id, "summary": str(summary)[:180],
            "source_type": "model", "authority": AUTHORITY["hypothesis"],
            "verification": "unverified",
        })
        self._touch()

    def set_case_id(self, case_id: str) -> None:
        self._data["case_id"] = case_id
        self._touch()

    def set_focus(self, objective: str, focus: str, next_agent: str | None) -> None:
        self._data["current_objective"] = str(objective)[:240]
        self._data["current_focus"] = str(focus)[:160]
        self._data["next_expected_agent"] = next_agent
        self._touch()

    def finish(self, status: str = "complete") -> None:
        self._data["status"] = status
        self._data["active_agents"] = []
        self._data["report_status"] = "ready" if status == "complete" else "unavailable"
        if status != "complete" and self._data["memory_lookup_status"] != "complete":
            self._data["memory_lookup_status"] = "not_completed"
        self._data["open_questions"] = [
            f"Unverified claim {claim.get('claim_id')}: {claim.get('reason') or 'needs independent evidence'}"
            for claim in self._data["unverified_claims"]
        ]
        self._data["next_actions"] = (["Human: review evidence, Skeptic conclusions, and limitations. Save only by explicit action."]
                                      if status == "complete" else ["Check the seed and service status before retrying."])
        self._data["timestamps"]["completed_at"] = _now()
        self._touch()

    def public_snapshot(self) -> dict[str, Any]:
        """A concise UI-safe view. The full structured context is persisted separately."""
        return {
            key: deepcopy(self._data[key]) for key in (
                "schema_version", "case_id", "investigation_id", "seed_transaction", "investigation_goal",
                "status", "active_agents", "report_status", "memory_lookup_status", "skeptic_conclusions",
                "graph_scope", "evidence_ledger", "verified_facts", "verified_claims", "rejected_claims", "unverified_claims",
                "hypotheses", "memory_candidates", "validated_memories", "handoffs", "open_questions",
                "graph_decisions", "current_graph_decision",
                "graph_action_budget",
                "next_actions", "constraints", "current_objective", "current_focus", "next_expected_agent",
                "shared_readers", "timestamps", "authority")
        }

    def final_context(self) -> dict[str, Any]:
        return deepcopy(self._data)

    def _touch(self) -> None:
        self._data["timestamps"]["updated_at"] = _now()
