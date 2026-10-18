"""Deterministic claim validator for investigation reports.

Every factual statement that is rendered to the user is converted into a structured
claim and validated here against the evidence ledger. The validator is pure Python;
it never trusts a claim merely because it cites an evidence ID — it checks that the
referenced evidence actually supports the specific claim.

Status vocabulary is machine-checkable:
- ``verified``        — recomputed from the ledger and matches exactly.
- ``rejected``        — contradicts the ledger or claims something the evidence
                        cannot support.
- ``unverified``      — no deterministic ground truth is available for the claim.
- ``not_applicable``  — the claim type carries no factual assertion this validator
                        checks (e.g. pure interpretation notas fact).

Nothing in this module reads gold answers, contacts FalkorDB, or mutates state.
"""
from __future__ import annotations

import re
from typing import Any

LABELS = ("illicit", "licit", "unknown")
STATUS_VERIFIED = "verified"
STATUS_REJECTED = "rejected"
STATUS_UNVERIFIED = "unverified"
STATUS_NOT_APPLICABLE = "not_applicable"

# Claim types whose factual content lives entirely in the ledger.
COUNT_CLAIM_TYPES = {
    "unique_transaction_count": "unique_transaction_count",
    "label_unique_count": "unique_transactions_by_label",
    "path_count": "path_count",
    "path_occurrence_count": "path_occurrence_count",
    "path_occurrence_count_by_label": "path_occurrence_count",
    "distinct_edge_count": "distinct_edge_count",
    "invalid_path_count": "invalid_path_count",
}
ATTRIBUTION_CLAIM_TYPES = {
    "wallet_ownership": "wallet ownership needs sources the dataset does not contain",
    "ransomware_family_attribution": "ransomware-family attribution needs sources the dataset does not contain",
    "transaction_amount": "transaction amounts need amount fields the dataset does not contain",
    "criminal_intent": "criminal intent cannot be inferred from dataset labels",
}
GLOBAL_ABSENCE_MARKERS = re.compile(
    r"no (wider|other|further|direct) (connection|relationship|link|path)|"
    r"not connected (to|with) anything|proves no (connection|relationship)|"
    r"isolated from (the|any) network|no relationship anywhere|"
    r"has no (wider|global|network) (connection|relationship)",
    re.IGNORECASE,
)
ABSOLUTE_NO_EVIDENCE_MARKERS = re.compile(
    r"no evidence of (any )?(illicit|criminal|risk)|"
    r"(is|are) not (illicit|licit)|definitely (licit|not illicit)",
    re.IGNORECASE,
)
BOUNDED_SEARCH_MARKERS = re.compile(
    r"within (the|a|up to \d+[- ]hop|three[- ]hop|\d+-hop) (hop )?(bound|limit|search)|"
    r"\d+[- ]hop (bound|limit|search|neighbo)", re.IGNORECASE,
)
UNSUPPORTED_CONFIDENCE_PATTERN = re.compile(
    r"\b(high confidence|very confident|certain|definitely|100% (sure|certain)|"
    r"proves conclusively|definitively (is|are))\b",
    re.IGNORECASE,
)


def _ledger_stat(ledger: dict[str, Any], key: str) -> Any:
    return (ledger.get("scope_stats") or {}).get(key) or {}


def _make_claim(claim: dict[str, Any]) -> dict[str, Any]:
    # Preserve every claim field (property, seed_tx_id, label, path_index, direction,
    # hop_count, node_ids, max_hops, ...): the validators below depend on them and a
    # lossy normalisation silently mis-scores claims (see seed_property regression).
    structured = dict(claim or {})
    structured.update({
        "claim_id": claim.get("claim_id") or "claim_unnumbered",
        "claim_type": str(claim.get("claim_type") or "unclassified"),
        "claim_text": str(claim.get("claim_text") or ""),
        "claim_value": claim.get("claim_value"),
        "evidence_ids": list(claim.get("evidence_ids") or []),
        "source": str(claim.get("source") or "model_observation"),
    })
    return structured


def validate_claim(raw_claim: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    """Validate one claim against the ledger; returns the claim with a status + reason."""
    claim = _make_claim(raw_claim)
    ctype = claim["claim_type"]
    value = claim.get("claim_value")

    if ctype in COUNT_CLAIM_TYPES and ctype != "label_unique_count" and ctype != "path_occurrence_count_by_label":
        stat = _ledger_stat(ledger, COUNT_CLAIM_TYPES[ctype])
        expected = stat.get("value")
        if isinstance(value, (int, float)) and expected == int(value):
            claim.update(verification_status=STATUS_VERIFIED,
                         reason=f"recomputed {ctype} from the {stat.get('scope')} scope matches",
                         expected_value=expected)
        else:
            claim.update(verification_status=STATUS_REJECTED,
                         reason=f"claim value {value} does not match the {stat.get('scope')} census",
                         expected_value=expected)
        return claim

    if ctype == "label_unique_count":
        label = str((claim.get("label") or _label_from_text(claim["claim_text"]) or "")).lower()
        stat = _ledger_stat(ledger, "unique_transactions_by_label")
        expected = (stat.get("values") or {}).get(label)
        if expected is None:
            claim.update(verification_status=STATUS_UNVERIFIED,
                         reason=f"label {label!r} is not scored by the ledger")
            return claim
        if isinstance(value, (int, float)) and expected == int(value):
            claim.update(verification_status=STATUS_VERIFIED,
                         reason=f"unique '{label}' census matches ({expected})",
                         expected_value=expected, label=label)
        else:
            # Distinguish the two failure shapes explicitly.
            occurrence_stats = _ledger_stat(ledger, "path_occurrence_count")
            occurrence_value = (occurrence_stats.get("values") or {}).get("by_label", {}).get(label)
            detail = f"unique '{label}' census is {expected}"
            if occurrence_value == value:
                detail += (f"; the reported number matches the path-occurrence scope "
                           f"({occurrence_value}), which counts appearances across paths "
                           f"and is never interchangeable with the unique census")
            claim.update(verification_status=STATUS_REJECTED,
                         reason=f"claimed {label} count {value} differs from deterministic census; {detail}",
                         expected_value=expected, label=label)
        return claim

    if ctype == "path_occurrence_count_by_label":
        label = str(claim.get("label") or "").lower()
        stat = _ledger_stat(ledger, "path_occurrence_count")
        expected = (stat.get("values") or {}).get("by_label", {}).get(label)
        scope = stat.get("scope", "path_occurrences")
        if expected is None:
            claim.update(verification_status=STATUS_UNVERIFIED, reason=f"label {label!r} not scored")
            return claim
        if isinstance(value, (int, float)) and expected == int(value):
            claim.update(verification_status=STATUS_VERIFIED,
                         reason=f"path-occurrence '{label}' census matches ({expected})",
                         expected_value=expected, label=label)
        else:
            claim.update(verification_status=STATUS_REJECTED,
                         reason=f"claimed {label} path-occurrence count {value} differs from deterministic census {expected} ({scope} scope)",
                         expected_value=expected, label=label)
        return claim

    if ctype == "seed_property":
        transactions = ledger.get("transactions") or {}
        requested = str(claim.get("seed_tx_id") or "")
        seed_record = transactions.get(requested) if requested else None
        if seed_record is None:
            # Identify the seed by the ledger's own is_seed marker, never by dict order:
            # transactions are sorted by ID, so the first key is generally not the seed.
            seed_record = next((rec for rec in transactions.values() if rec.get("is_seed")), None)
        property_name = str(claim.get("property") or "label")
        ledger_field = {"txId": "tx_id", "label": "label", "timeStep": "time_step",
                        "sourceDataset": "source_dataset"}.get(property_name, property_name)
        expected = (seed_record or {}).get(ledger_field) if seed_record else None
        claimed_value = claim.get("claim_value")
        if isinstance(claimed_value, dict) and property_name in claimed_value:
            claimed_value = claimed_value[property_name]
        if seed_record is None:
            claim.update(verification_status=STATUS_UNVERIFIED, reason="seed record not found in ledger")
        elif expected == claimed_value:
            claim.update(verification_status=STATUS_VERIFIED,
                         reason=f"seed {property_name} matches the graph record",
                         expected_value=expected)
        else:
            claim.update(verification_status=STATUS_REJECTED,
                         reason=f"seed {property_name} should be {expected!r}",
                         expected_value=expected)
        return claim

    if ctype == "path":
        path_index = claim.get("path_index")
        known = {p["path_index"]: p for p in ledger.get("paths", [])}
        record = (known or {}).get(path_index)
        if record is None:
            claim.update(verification_status=STATUS_UNVERIFIED, reason="path index not present in verified ledger")
            return claim
        if claim.get("direction") == record.get("direction") and claim.get("hop_count") == record.get("hop_count") \
                and list(claim.get("node_ids") or []) == record.get("node_ids"):
            status = STATUS_VERIFIED if record.get("valid") else STATUS_REJECTED
            reason = "matches the verified path record" if status == STATUS_VERIFIED else \
                "path failed independent node/edge/endpoint/hop validation"
            claim.update(verification_status=status, reason=reason)
        else:
            claim.update(verification_status=STATUS_REJECTED,
                         reason="described path differs from the verified record",
                         expected_direction=record.get("direction"), expected_hop_count=record.get("hop_count"))
        return claim

    if ctype == "bounded_absence":
        text = claim["claim_text"]
        if GLOBAL_ABSENCE_MARKERS.search(text) or ABSOLUTE_NO_EVIDENCE_MARKERS.search(text):
            claim.update(verification_status=STATUS_REJECTED,
                         reason="bounded searches cannot establish network-wide absence; the claim asserts more than the search depth covers")
            return claim
        if not BOUNDED_SEARCH_MARKERS.search(text):
            claim.update(verification_status=STATUS_UNVERIFIED,
                         reason="absence statement is not explicitly bounded to the searched hop depth and returned evidence")
            return claim
        hops = claim.get("max_hops")
        bound_hops = (ledger.get("completeness") or {}).get("max_hops")
        if hops is not None and bound_hops is not None and int(hops) > int(bound_hops):
            claim.update(verification_status=STATUS_REJECTED,
                         reason=f"claim searches {hops} hops; the verified evidence covers only {bound_hops}")
            return claim
        claim.update(verification_status=STATUS_VERIFIED,
                     reason=f"absence statement is bounded to the verified {bound_hops}-hop search")
        return claim

    if ctype in ATTRIBUTION_CLAIM_TYPES:
        claim.update(
            verification_status=STATUS_REJECTED,
            reason=f"unsupported {ctype.replace('_', ' ')}: {ATTRIBUTION_CLAIM_TYPES[ctype]}; "
                   f"dataset transaction labels do not establish identity, ownership, software family, or amounts",
            required_evidence="supporting sources that exist in the evidence data (none present)",
        )
        return claim

    claim.update(verification_status=STATUS_NOT_APPLICABLE,
                 reason="claim type carries no deterministic factual check")
    return claim


def validate_claims(claims: list[dict[str, Any]], ledger: dict[str, Any]) -> list[dict[str, Any]]:
    return [validate_claim(claim, ledger) for claim in (claims or [])]


def _label_from_text(text: str) -> str | None:
    match = re.search(r"\b(illicit|licit|unknown)\b", text or "", re.IGNORECASE)
    return match.group(1).lower() if match else None
