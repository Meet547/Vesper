"""Canonical, deterministic evidence ledger for investigation previews.

The ledger is the single counting authority in the harness. It is built in Python
from already-verified graph output (the seed record, bounded traversals, and the
independent path-validation results). No model output ever writes into the ledger.

Counting scopes are explicit and never interchangeable:

- ``unique_transactions`` — one record per distinct transaction ID.
- ``path_occurrences``    — every node appearance across returned paths, including
                            repeats of the same transaction in multiple paths.
- ``distinct_edges``      — one record per ordered (source -> target) FLOWS_TO pair.
- ``paths``               — one record per returned directed path.

Every statistic is computed from these canonical structures and carries its scope
identifier so callers can never present two scopes as interchangeable.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

LABELS = ("illicit", "licit", "unknown")
ENUMERATION_CAP_PER_DIRECTION = 20


def build_evidence_ledger(
    seed: dict[str, Any] | None,
    traces: list[dict[str, Any]] | None,
    path_validation: dict[str, Any] | None = None,
    max_hops: int = 3,
    graph_name: str = "",
) -> dict[str, Any]:
    """Build the canonical ledger from verified graph evidence.

    ``traces`` are the bounded traversal records as returned by GraphStore.trace_paths.
    ``path_validation`` is the independent GraphStore.validate_paths result; when
    present, per-path valid flags are copied verbatim so the ledger never re-decides
    evidence validity by itself.
    """
    traces = traces if isinstance(traces, list) else []
    seed = seed if isinstance(seed, dict) else None
    validation_paths = list((path_validation or {}).get("paths") or [])
    seed_id = str((seed or {}).get("txId", ""))

    transactions: dict[str, dict[str, Any]] = {}
    if seed_id:
        transactions[seed_id] = {
            "tx_id": seed_id,
            "label": str((seed or {}).get("label") or "unknown"),
            "time_step": (seed or {}).get("timeStep"),
            "source_dataset": (seed or {}).get("sourceDataset"),
            "is_seed": True,
            "evidence_paths": [],
        }

    edges: dict[tuple[str, str], dict[str, Any]] = {}
    path_index_records: list[dict[str, Any]] = []
    malformed_paths = 0

    for index, path in enumerate(traces):
        nodes = path.get("nodes") if isinstance(path, dict) else None
        direction = path.get("direction")
        if not isinstance(nodes, list) or len(nodes) < 2 or direction not in {"upstream", "downstream"}:
            malformed_paths += 1
            continue
        node_ids = [str(node.get("txId", "")) for node in nodes]
        # Display order keeps forward FLOWS_TO direction in both directions:
        # node[i] FLOWS_TO node[i+1]. Upstream paths simply end at the seed.
        edge_ids = []
        for source, target in zip(node_ids, node_ids[1:]):
            edge_id = f"{source}->{target}"
            edge_ids.append(edge_id)
            record = edges.setdefault(
                (source, target),
                {"edge_id": edge_id, "source": source, "target": target, "evidence_paths": []},
            )
            record["evidence_paths"].append(index)
            if target not in {"", "None"}:
                record.setdefault("target_present", True)
            if source not in {"", "None"}:
                record.setdefault("source_present", True)
        path_index_records.append({
            "path_index": index,
            "evidence_id": path.get("evidence_id") or ("path:" + str(direction) + ":" + ">".join(node_ids)),
            "direction": direction,
            "hop_count": len(node_ids) - 1,
            "reported_hops": path.get("hops"),
            "node_ids": node_ids,
            "edge_ids": edge_ids,
            "valid": bool(validation_paths[index].get("valid")) if index < len(validation_paths) else None,
            "validation_reason": validation_paths[index].get("reason") if index < len(validation_paths) else None,
        })
        for position, node in enumerate(nodes):
            tx_id = node_ids[position]
            record = transactions.setdefault(tx_id, {
                "tx_id": tx_id,
                "label": str((node or {}).get("label") or "unknown"),
                "time_step": (node or {}).get("timeStep"),
                "source_dataset": (node or {}).get("sourceDataset") if len(node or {}) > 3 else None,
                "is_seed": tx_id == seed_id,
                "evidence_paths": [],
            })
            record["evidence_paths"].append(index)

    # Path-occurrence counts come from appearances, not unique IDs.
    occurrence_by_label: Counter[str] = Counter()
    for record in transactions.values():
        occurrences = len(record["evidence_paths"])
        record["path_occurrence_count"] = occurrences
        if record["is_seed"]:
            # Seed occurrences exist whenever a returned path includes it.
            pass
        occurrence_by_label[record["label"]] += occurrences
    occurrence_by_label_total = sum(len(record["evidence_paths"]) for record in transactions.values())

    unique_counts_by_label = Counter(record["label"] for record in transactions.values())
    distinct_edge_count = len({record["edge_id"] for record in edges.values()})
    invalid_path_count = sum(1 for record in path_index_records if record["valid"] is False)
    # GraphStore probes one row beyond the per-direction cap and marks returned
    # paths when additional results exist. Keep the historical cap guard for
    # frozen callers that do not yet supply that provenance bit.
    truncated = any(bool(path.get("search_truncated")) for path in traces) or len(path_index_records) >= 2 * ENUMERATION_CAP_PER_DIRECTION

    ledger = {
        "source_graph": graph_name or "unknown",
        "created_scope_note": (
            "unique_transactions counts distinct transaction IDs once; "
            "path_occurrences counts node appearances across paths and may exceed it."
        ),
        "transactions": {
            tx_id: {
                **record,
                "evidence_paths": sorted(set(record["evidence_paths"])),
            }
            for tx_id, record in sorted(transactions.items())
        },
        "edges": [
            {
                **record,
                "evidence_paths": sorted(set(record["evidence_paths"])),
                "target_present": record.pop("target_present", False),
                "source_present": record.pop("source_present", False),
            }
            for record in (edges[key] for key in sorted(edges))
        ],
        "paths": path_index_records,
        "scope_stats": {
            # Each statistic names its counting scope explicitly.
            "unique_transaction_count": {
                "scope": "unique_transactions",
                "value": len(transactions),
                "note": "distinct transaction IDs, deduplicated across paths",
            },
            "unique_transactions_by_label": {
                "scope": "unique_transactions",
                "values": {label: int(unique_counts_by_label.get(label, 0)) for label in LABELS},
                "note": "per dataset label, one count per distinct transaction ID",
            },
            "path_occurrence_count": {
                "scope": "path_occurrences",
                "values": {"total": occurrence_by_label_total,
                           "by_label": {label: int(occurrence_by_label.get(label, 0)) for label in LABELS}},
                "note": "node appearances across returned paths; may exceed unique counts",
            },
            "distinct_edge_count": {
                "scope": "distinct_edges",
                "value": distinct_edge_count,
                "note": "ordered FLOWS_TO pairs, deduplicated across paths",
            },
            "path_count": {
                "scope": "paths",
                "value": len(path_index_records),
                "note": "returned directed paths (excluding malformed records)",
            },
            "invalid_path_count": {
                "scope": "paths",
                "value": invalid_path_count,
                "note": "paths rejected by independent node/edge/endpoint/hop validation",
            },
            "malformed_path_count": {
                "scope": "paths",
                "value": malformed_paths,
                "note": "unusable path records in the traversal response",
            },
            "truncated_enumeration": {
                "scope": "paths",
                "value": truncated,
                "enumeration_cap_per_direction": ENUMERATION_CAP_PER_DIRECTION,
                "note": "True when the traversal observed additional results beyond its cap, or a legacy caller returned the cap; "
                        "the returned path set is then not exhaustive within the hop bound",
            },
        },
        "completeness": {
            "max_hops": int(max_hops),
            "hop_bound_note": "paths are bounded to the requested hop depth; a bounded "
                              "no-path result is not evidence of no wider connection",
        },
    }
    return ledger


def compact_ledger_for_model(ledger: dict[str, Any], limits: dict[str, int] | None = None) -> dict[str, Any]:
    """Deterministic compact representation for the LLM evidence payload.

    One record per unique transaction, one per distinct directed edge, and paths
    referencing node/edge IDs. Full traversal records remain available to the
    verifier through the preview payload; compaction is only for the model input.

    Nothing is dropped silently: the returned structure reports the configured
    limits, how many records were included, and how many were omitted, and states
    that deterministic counts are computed over the full verified result, not the
    truncated model context.
    """
    limits = {
        "transactions": 160,
        "edges": 200,
        "paths": 40,
        **(limits or {}),
    }
    transactions = sorted(ledger["transactions"].values(), key=lambda t: (not t.get("is_seed"), t["tx_id"]))
    tx_included = transactions[: limits["transactions"]]
    edges = ledger["edges"]
    edges_included = edges[: limits["edges"]]
    paths = ledger["paths"]
    paths_included = paths[: limits["paths"]]
    return {
        "ledger_summary": ledger["scope_stats"],
        "source_graph": ledger["source_graph"],
        "completeness": ledger["completeness"],
        "transactions": [
            {"txId": t["tx_id"], "label": t["label"], "timeStep": t.get("time_step"),
             "sourceDataset": t.get("source_dataset"), "isSeed": t.get("is_seed", False)}
            for t in tx_included
        ],
        "edges": [
            {"edgeId": e["edge_id"], "source": e["source"], "target": e["target"]}
            for e in edges_included
        ],
        "paths": [
            {"path_index": p["path_index"], "direction": p["direction"],
             "hop_count": p["hop_count"], "node_ids": p["node_ids"], "valid": p["valid"]}
            for p in paths_included
        ],
        "truncation": {
            "limits": limits,
            "transactions_included": len(tx_included),
            "transactions_omitted": max(0, len(transactions) - len(tx_included)),
            "edges_included": len(edges_included),
            "edges_omitted": max(0, len(edges) - len(edges_included)),
            "paths_included": len(paths_included),
            "paths_omitted": max(0, len(paths) - len(paths_included)),
            "deterministic_counts_scope": "full verified result, not the truncated model context",
            "note": "Counts below are computed over the complete verified evidence; "
                    "the model payload above may be a truncated view. Never recount from the payload.",
        },
    }


def complete_graph_facts(ledger: dict[str, Any]) -> dict[str, Any]:
    """Everything Python-derived that reports must show as verified fact."""
    stats = ledger["scope_stats"]
    return {
        "unique_transaction_count": stats["unique_transaction_count"]["value"],
        "unique_transactions_by_label": stats["unique_transactions_by_label"]["values"],
        "path_occurrence_total": stats["path_occurrence_count"]["values"]["total"],
        "path_occurrences_by_label": stats["path_occurrence_count"]["values"]["by_label"],
        "distinct_edge_count": stats["distinct_edge_count"]["value"],
        "path_count": stats["path_count"]["value"],
        "invalid_path_count": stats["invalid_path_count"]["value"],
        "truncated_enumeration": stats["truncated_enumeration"]["value"],
        "scope_notes": {
            "unique_transactions": "distinct transaction IDs",
            "path_occurrences": "appearances across returned paths",
        },
    }
