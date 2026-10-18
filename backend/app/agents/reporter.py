"""Evidence-first reporter.

Facts shown to the user are computed from the deterministic evidence ledger in
Python; model-generated interpretation is kept separate and clearly labeled.
Factual claims extracted from model prose are validated against the ledger by
the Skeptic (independent deterministic validators) before rendering; rejected
claims are recorded with their expected values, never silently replaced.
"""
from __future__ import annotations

import re
from typing import Any

from backend.app.agents import claim_validator
from backend.app.agents.evidence_ledger import complete_graph_facts

STATUS_VERIFIED = claim_validator.STATUS_VERIFIED
STATUS_REJECTED = claim_validator.STATUS_REJECTED
STATUS_UNVERIFIED = claim_validator.STATUS_UNVERIFIED
STATUS_NOT_APPLICABLE = claim_validator.STATUS_NOT_APPLICABLE

# Claim extraction over model prose (text-pattern detection only; actual semantic
# verification is performed separately by claim_validator on the ledger).
NUM_LABEL_RE = re.compile(
    r"\b(\d+)\s*(?:labeled\s+as|marked\s+as|tagged\s+as|are|is)?\s*[\"]?(licit|unknown|illicit)[\")]?\b",
    re.IGNORECASE,
)
NUM_TRANSACTIONS_RE = re.compile(r"\b(\d+)\s+transactions?\b", re.IGNORECASE)
# "N path occurrence(s)" describes node appearances across paths, not a path count;
# it must not be extracted as a path_count claim (guard against false rejections).
NUM_PATHS_RE = re.compile(r"\b(\d+)\s+(?:directed\s+)?paths?\b(?!\s*occurrence)", re.IGNORECASE)
SEED_LABEL_RE = re.compile(
    r"transaction (?:with ID )\`?[0-9]+\`? is labeled as [\"]?(illicit|licit|unknown)[\"]?",
    re.IGNORECASE,
)
ATTRIBUTION_RE = {
    "wallet_ownership": re.compile(r"own[sd]? (a|the|this|its)? ?wallet|belongs to (a|an|the) |owner of", re.IGNORECASE),
    "ransomware_family_attribution": re.compile(r"ransomware (family|strain)|(associated|attributed|linked) with [A-Za-z0-9 ]*ransomware", re.IGNORECASE),
    "transaction_amount": re.compile(r"\b(transferred|amount|volume)\b[^.]{0,40}\b\d+(?:\.\d+)?\s*(BTC|bitcoin|mBTC|USD)?", re.IGNORECASE),
    "criminal_intent": re.compile(r"criminal intent|money laundering|committed (fraud|crime)|is a criminal", re.IGNORECASE),
}
ABSENCE_RE = re.compile(r"\bno (?:evidence|path|connection|relationship|direct)\b", re.IGNORECASE)


def extract_model_claims(observations: str, max_claims: int = 20) -> list[dict[str, Any]]:
    """Text-pattern claim extraction. Produces candidate claims only; validation
    is a separate deterministic step (see SkepticAgent.evaluate_claims)."""
    claims: list[dict[str, Any]] = []
    text = observations or ""
    for number, label in NUM_LABEL_RE.findall(text):
        if number == 0 and not text:
            continue
        claims.append({
            "claim_type": "label_unique_count",
            "claim_text": f"reported {number} '{label}' transactions",
            "claim_value": int(number),
            "label": label.lower(),
            "evidence_ids": [],
            "source": "model_observation",
        })
    for number in NUM_TRANSACTIONS_RE.findall(text):
        claims.append({
            "claim_type": "unique_transaction_count",
            "claim_text": f"reported {number} transactions in the evidence network",
            "claim_value": int(number),
            "evidence_ids": [],
            "source": "model_observation",
        })
    for number in NUM_PATHS_RE.findall(text):
        claims.append({
            "claim_type": "path_count",
            "claim_text": f"reported {number} directed paths",
            "claim_value": int(number),
            "evidence_ids": [],
            "source": "model_observation",
        })
    seed_match = SEED_LABEL_RE.search(text)
    if seed_match:
        claims.append({
            "claim_type": "seed_property",
            "claim_text": seed_match.group(0),
            "claim_value": {"label": seed_match.group(1).lower()},
            "property": "label",
            "evidence_ids": [],
            "source": "model_observation",
        })
    if ABSENCE_RE.search(text):
        claims.append({
            "claim_type": "bounded_absence",
            "claim_text": ABSENCE_RE.search(text).group(0),
            "claim_value": None,
            "evidence_ids": [],
            "source": "model_observation",
        })
    for ctype, pattern in ATTRIBUTION_RE.items():
        match = pattern.search(text)
        if match:
            claims.append({
                "claim_type": ctype,
                "claim_text": match.group(0)[:160],
                "claim_value": None,
                "evidence_ids": [],
                "source": "model_observation",
            })
    numbered = []
    seen_apps = set()
    for claim in claims[:max_claims]:
        key = (claim["claim_type"], claim["claim_text"])
        if key in seen_apps:
            continue
        seen_apps.add(key)
        claim["claim_id"] = f"m{len(numbered) + 1}"
        numbered.append(claim)
    return numbered


def deterministic_claims(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Canonical claims computed straight from the ledger (scope-labeled)."""
    stats = ledger.get("scope_stats") or {}
    facts = complete_graph_facts(ledger)
    claims = [
        {"claim_id": "d1", "claim_type": "unique_transaction_count", "claim_text": f"{facts['unique_transaction_count']} unique transactions (scope: unique_transactions)", "claim_value": facts["unique_transaction_count"], "evidence_ids": ["evidence_ledger"], "source": "deterministic_ledger"},
    ]
    for label, count in (facts["unique_transactions_by_label"] or {}).items():
        if count:
            claims.append({"claim_id": f"d{len(claims) + 1}", "claim_type": "label_unique_count",
                           "claim_text": f"{count} unique '{label}' transactions (scope: unique_transactions)",
                           "claim_value": count, "label": label,
                           "evidence_ids": ["evidence_ledger"], "source": "deterministic_ledger"})
    if facts["path_count"]:
        claims.append({"claim_id": f"d{len(claims) + 1}", "claim_type": "path_count",
                       "claim_text": f"{facts['path_count']} directed paths returned (scope: paths)",
                       "claim_value": facts["path_count"], "evidence_ids": ["evidence_ledger"],
                       "source": "deterministic_ledger"})
    claims.append({"claim_id": f"d{len(claims) + 1}", "claim_type": "path_occurrence_count_by_label",
                   "claim_text": f"{facts['path_occurrence_total']} path occurrences (scope: path_occurrences; "
                                 f"by label: {facts['path_occurrences_by_label']})",
                   "claim_value": facts["path_occurrence_total"],
                   "label": "total",
                   "evidence_ids": ["evidence_ledger"], "source": "deterministic_ledger"})
    claims.append({"claim_id": f"d{len(claims) + 1}", "claim_type": "distinct_edge_count",
                   "claim_text": f"{facts['distinct_edge_count']} distinct directed FLOWS_TO edges (scope: distinct_edges)",
                   "claim_value": facts["distinct_edge_count"], "evidence_ids": ["evidence_ledger"],
                   "source": "deterministic_ledger"})
    claims.append({"claim_id": f"d{len(claims) + 1}", "claim_type": "invalid_path_count",
                   "claim_text": f"{facts['invalid_path_count']} invalid path(s) after independent validation (scope: paths)",
                   "claim_value": facts["invalid_path_count"], "evidence_ids": ["evidence_ledger"],
                   "source": "deterministic_ledger"})
    if stats.get("truncated_enumeration", {}).get("value"):
        claims.append({"claim_id": f"d{len(claims) + 1}", "claim_type": "truncated_enumeration",
                       "claim_text": "path enumeration reached the traversal cap; the returned set is not exhaustive within the hop bound",
                       "claim_value": True, "evidence_ids": ["evidence_ledger"], "source": "deterministic_ledger"})
    return claims


class ReporterAgent:
    """Renders the final investigation report: deterministic facts first,
    model interpretation separated, rejected claims recorded."""

    def extract_claims(self, model_observations: str, ledger: dict[str, Any]) -> list[dict[str, Any]]:
        """Candidate model claims (extraction only; not yet validated)."""
        claims = extract_model_claims(model_observations or "")
        # Markdown path tables often place a transaction ID next to its dataset
        # label (for example, ``218062276 unknown``). It is an identifier, not a
        # numerical label-count claim; leave it in the interpretation, not the
        # claim validator's count queue.
        transaction_ids = set((ledger or {}).get("transactions", {}))
        return [claim for claim in claims
                if not (claim.get("claim_type") == "label_unique_count"
                        and str(claim.get("claim_value")) in transaction_ids)]

    @staticmethod
    def _memory_policy_explanation(memories: list[dict[str, Any]],
                                   graph_decisions: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Summarize only a verified memory route that the policy actually selected."""
        route_decision = next((decision for decision in (graph_decisions or [])
                               if decision.get("selected_action") == "follow_verified_memory_route"
                               and (decision.get("action_outcome") or {}).get("memory_route_verified") is True), None)
        if not route_decision:
            return None
        outcome = route_decision.get("action_outcome") or {}
        provenance = outcome.get("memory_provenance") or {}
        case_id, memory_id = provenance.get("case_id"), provenance.get("memory_id")
        memory = next((item for item in (memories or [])
                       if item.get("validationStatus") == "VERIFIED_RELEVANT"
                       and item.get("caseId") == case_id and item.get("memoryId") == memory_id), None)
        frontier = outcome.get("selected_frontier_tx_id")
        route_id = outcome.get("route_evidence_id")
        source_path_id = provenance.get("source_path_id")
        if not memory or not all((case_id, memory_id, frontier, route_id, source_path_id)):
            return None
        supporting_edges = sorted(str(edge) for edge in memory.get("currentSupportingEdges", []) if edge)
        support_text = ", ".join(supporting_edges) if supporting_edges else "the current Skeptic-verified overlap"
        explanation = (
            f"The graph policy followed verified case {case_id} memory {memory_id} at frontier {frontier}. "
            f"Skeptic revalidated its source path {source_path_id} against {support_text}, then independently "
            f"verified the joined current route {route_id}."
        )
        return {"status": "verified", "case_id": case_id, "memory_id": memory_id,
                "source_path_id": source_path_id, "frontier_tx_id": str(frontier),
                "current_route_evidence_id": route_id, "current_supporting_edges": supporting_edges,
                "explanation": explanation}

    def create_report(self, seed: dict[str, Any], ledger: dict[str, Any],
                      skeptic: dict[str, Any], memories: list[dict[str, Any]] | None,
                      model_observations: str = "",
                      evaluated_claims: list[dict[str, Any]] | None = None,
                      shared_context=None,
                      graph_decisions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Build the merged summary string plus the structured report readers need."""
        if shared_context is not None:
            shared_context.record_read("Reporter")
        facts = complete_graph_facts(ledger)
        by_label = facts["unique_transactions_by_label"]
        label_counts_text = ", ".join(f"{count} {label}" for label, count in by_label.items() if count)
        seed_id = (seed or {}).get("txId", "")
        seed_label = (seed or {}).get("label") or "unknown"

        summary = [
            f"Seed transaction {seed_id} has dataset label '{seed_label}' (verified graph record).",
            f"Evidence ledger (deterministic, computed in Python): "
            f"{facts['unique_transaction_count']} unique transaction(s) (scope: unique_transactions; "
            f"by label: {label_counts_text}); "
            f"{facts['path_occurrence_total']} path occurrence(s) across {facts['path_count']} returned "
            f"directed path(s) (scope: path_occurrences — appearances across paths, not unique nodes); "
            f"{facts['distinct_edge_count']} distinct directed FLOWS_TO edge(s).",
        ]
        if facts["invalid_path_count"]:
            summary.append(f"{facts['invalid_path_count']} path(s) failed independent validation (rejected evidence).")
        if facts["truncated_enumeration"]:
            summary.append("Path enumeration was truncated at the traversal cap; the returned set is not exhaustive within the hop bound.")
        validated_memories = [memory for memory in (memories or [])
                              if memory.get("validationStatus") in {"VERIFIED_RELEVANT", "PARTIALLY_RELEVANT"}]
        excluded_memories = [memory for memory in (memories or []) if memory not in validated_memories]
        memory_policy_explanation = self._memory_policy_explanation(validated_memories, graph_decisions or [])
        if validated_memories:
            summary.append(f"Historian recalled {len(memories)} prior case candidate(s); Skeptic validated {len(validated_memories)} as relevant. Remembered context remains separate from current deterministic facts.")
            for memory in validated_memories:
                edges = memory.get("currentSupportingEdges") or []
                shared = memory.get("sharedTransactions") or []
                reason = memory.get("validationReason") or memory.get("relevanceReason") or "shared graph evidence"
                summary.append(f"Validated memory from case {memory.get('caseId', 'unknown')} [{memory.get('validationStatus')}]: {reason} Shared transactions: {', '.join(shared)}. Current supporting edges: {', '.join(edges) if edges else 'none'}.")
        elif memories:
            summary.append(f"Historian recalled {len(memories)} prior case candidate(s), but Skeptic did not validate any for current use; remembered findings were excluded from report facts.")
        else:
            summary.append("Historian found no saved case sharing transaction IDs with the current deterministic evidence.")
        for memory in excluded_memories:
            summary.append(f"Memory candidate from case {memory.get('caseId', 'unknown')} was excluded [{memory.get('validationStatus', 'UNVERIFIED')}]: {memory.get('validationReason', 'not independently supported by current evidence')}.")
        summary.append(f"Skeptic review status: {(skeptic or {}).get('reviewStatus', 'unknown')}.")
        if memory_policy_explanation:
            summary.append("Reporter decision explanation: " + memory_policy_explanation["explanation"])

        verified = rejected = unverified = not_applicable = 0
        rejected_claims = []
        for claim in evaluated_claims or []:
            status = claim.get("verification_status", STATUS_UNVERIFIED)
            if status == STATUS_VERIFIED:
                verified += 1
            elif status == STATUS_REJECTED:
                rejected += 1
                rejected_claims.append(claim)
            elif status == STATUS_UNVERIFIED:
                unverified += 1
            else:
                not_applicable += 1
        if rejected_claims:
            summary.append("Rejected factual claims (claims below were made but do not match the deterministic census; they are not presented as facts):")
            for claim in rejected_claims:
                summary.append(f"- REJECTED {claim.get('claim_id', '')} [{claim.get('claim_type')}]: "
                               f"claimed {claim.get('claim_value')!r} — {claim.get('reason')}. "
                               f"Deterministic result: {claim.get('expected_value', 'see claim')!r}.")
        if unverified:
            summary.append(f"{unverified} claim(s) could not be verified deterministically and are marked unverified.")

        if model_observations:
            summary.append("Model interpretation (generated by the local model; factual counts "
                           "above are deterministic and take precedence): " + model_observations)
        else:
            summary.append("No model commentary was produced; the report reflects deterministic evidence only.")

        structured = {
            "verified_facts": facts,
            "counting_scope_note": complete_graph_facts(ledger)["scope_notes"],
            "deterministic_claims": deterministic_claims(ledger) if ledger else [],
            "_evaluated_model_claims": evaluated_claims or [],
            "memory_review": {
                "candidates": memories or [],
                "validated_count": len(validated_memories),
                "excluded_count": len(excluded_memories),
                "current_facts_unchanged": True,
            },
            **({"memory_policy_explanation": memory_policy_explanation}
               if memory_policy_explanation else {}),
            "rejected_claims": rejected_claims,
            "claim_status_counts": {"verified": verified, "rejected": rejected,
                                     "unverified": unverified, "not_applicable": not_applicable},
            "truncation": {
                "enumeration_truncated": facts["truncated_enumeration"],
                "note": "bounded-hop and capped enumeration status is reported explicitly",
            },
            "unknown_data": [
                "Transaction labels are dataset classifications, not proof of conduct, ownership, intent, or attribution.",
                "Real-world wallet ownership, identity, transfer amounts, and chronology beyond dataset fields are unknown.",
            ],
        }
        return {"summary": " ".join(summary), "structured_report": structured}

    # ------------------------------------------------------------------
    # Backward-compatible API (used by demos and earlier integration points).
    # ------------------------------------------------------------------

    def create_summary(self, seed: dict[str, Any], traces: list[dict[str, Any]],
                       skeptic: dict[str, Any], memories: list[dict[str, Any]]) -> str:
        label = (seed or {}).get("label") or "unknown"
        path_count = len(traces or [])
        transaction_count = (skeptic or {}).get("uniqueTransactionsReviewed", 1)
        parts = [f"Seed transaction {seed['txId']} has dataset label '{label}'."]
        parts.append(f"The graph returned {path_count} directed path(s) within the requested hop limit, covering {transaction_count} unique transaction(s).")
        if memories:
            parts.append(f"Historian retrieved {len(memories)} prior case memory item(s) sharing transaction context.")
        else:
            parts.append("No prior memory sharing these transaction IDs was found.")
        parts.append("Skeptic review is required; graph proximity and dataset labels do not independently establish ownership, intent, or ransomware attribution.")
        return " ".join(parts)
