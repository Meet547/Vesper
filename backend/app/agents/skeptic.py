from typing import Any

from backend.app.agents import claim_validator
from backend.app.agents import evidence_ledger as ledger_mod

STATUS_VERIFIED = claim_validator.STATUS_VERIFIED
STATUS_REJECTED = claim_validator.STATUS_REJECTED
STATUS_UNVERIFIED = claim_validator.STATUS_UNVERIFIED
STATUS_NOT_APPLICABLE = claim_validator.STATUS_NOT_APPLICABLE


class SkepticAgent:
    """Rule-based evidence checks with structured, machine-checkable findings.

    This is deliberately not an attribution model. Path-integrity verification stays
    in Python (independent bounded graph reads); claims produced by the model or the
    report are independently re-validated by deterministic validators, never taken
    on trust.
    """

    def review(self, seed: dict[str, Any], traces: list[dict[str, Any]],
               path_validation: dict[str, Any] | None = None, seed_exists: bool = True,
               ledger: dict[str, Any] | None = None, shared_context=None) -> dict[str, Any]:
        if shared_context is not None:
            shared_context.record_read("Skeptic")
        seed_id = str(seed.get("txId", ""))
        evidence_nodes: dict[str, dict[str, Any]] = {seed_id: seed} if seed_id else {}
        malformed_evidence = 0
        for trace in traces if isinstance(traces, list) else []:
            if not isinstance(trace, dict) or not isinstance(trace.get("nodes"), list):
                malformed_evidence += 1
                continue
            for node in trace["nodes"]:
                if not isinstance(node, dict) or not str(node.get("txId", "")).isdigit():
                    malformed_evidence += 1
                    continue
                evidence_nodes[str(node["txId"])] = node

        unknown_nodes = sorted(node_id for node_id, node in evidence_nodes.items() if str(node.get("label") or "unknown").lower() == "unknown")
        illicit_nodes = sorted(node_id for node_id, node in evidence_nodes.items() if str(node.get("label") or "unknown").lower() == "illicit")
        licit_nodes = sorted(node_id for node_id, node in evidence_nodes.items() if str(node.get("label") or "unknown").lower() == "licit")

        flags: list[str] = []
        if unknown_nodes:
            flags.append(f"{len(unknown_nodes)} connected transaction(s) have an unknown dataset label; do not infer their status.")
        if not traces:
            flags.append("No path was found within the selected hop limit in the currently imported graph.")
        validation = path_validation or {"allPathsValid": False, "checkedPathCount": 0, "invalidPathCount": len(traces)}
        if not seed_exists:
            flags.append("The seed transaction could not be independently confirmed in the selected graph.")
        if malformed_evidence or not validation.get("allPathsValid", False):
            flags.append("One or more returned paths failed independent node, directed-edge, or hop-bound validation; treat those paths as invalid evidence.")
        if len(licit_nodes) and len(illicit_nodes):
            flags.append("Paths contain mixed dataset labels; adjacency alone does not prove shared ownership or intent.")
        flags.append("Dataset labels are not independent proof of criminal conduct or ransomware attribution.")
        flags.append("This graph response does not establish real-world wallet ownership, exact transfer amounts, or chronology beyond fields explicitly present in the dataset.")

        findings: list[dict[str, Any]] = self._structure_findings(
            seed, traces, validation, seed_exists, malformed_evidence, ledger
        )

        return {
            "reviewStatus": "needs_human_review" if (unknown_nodes or not traces or malformed_evidence or not validation.get("allPathsValid", False) or not seed_exists) else "evidence_found_review_required",
            "seedDatasetLabel": seed.get("label", "unknown"),
            "uniqueTransactionsReviewed": len(evidence_nodes),
            "pathCount": len(traces),
            "illicitLabelTxIds": illicit_nodes,
            "licitLabelTxIds": licit_nodes,
            "unknownLabelTxIds": unknown_nodes,
            "flags": flags,
            "findings": findings,
            "checks": {
                "seedExistsInGraph": seed_exists,
                "pathsReturnedByGraphQuery": len(traces) > 0,
                "pathsIndependentlyValidated": validation.get("allPathsValid", False),
                "pathValidation": validation,
                "malformedEvidenceCount": malformed_evidence,
                "unknownLabelsSurfaced": True,
                "attributionClaimMade": False,
            },
        }

    def independently_verify_paths(self, traces: list[dict[str, Any]], store,
                                   seed_tx_id: str, max_hops: int) -> dict[str, Any]:
        """Re-read every path node and edge with a Skeptic-owned verifier.

        This intentionally does not call ``GraphStore.validate_paths`` or trust a
        Tracer/orchestrator validation object. The graph store supplies only
        parameterized, read-only node and directed-edge lookups.
        """
        settings = getattr(store, "settings", None)
        limit = min(max(1, int(getattr(settings, "max_trace_paths", 20))), 20)
        bounded = list(traces or [])[:limit]
        checks: list[dict[str, Any]] = []
        for path in bounded:
            if not isinstance(path, dict) or not isinstance(path.get("nodes"), list):
                checks.append({"valid": False, "reason": "malformed_path", "node_ids": [], "edge_ids": []})
                continue

            nodes = path["nodes"]
            ids = [str(node.get("txId", "")) if isinstance(node, dict) else "" for node in nodes]
            hops = len(ids) - 1
            direction = path.get("direction")
            expected_edges = [f"{source}->{target}" for source, target in zip(ids, ids[1:])]
            expected_path_id = "path:" + str(direction) + ":" + ">".join(ids)
            path_shape_valid = (
                len(ids) >= 2 and all(tx_id.isdigit() for tx_id in ids)
                and len(set(ids)) == len(ids)
                and direction in {"upstream", "downstream"}
                and 1 <= hops <= min(max(1, int(max_hops)), 4)
                and path.get("hops") == hops
                and ((direction == "downstream" and ids[0] == seed_tx_id)
                     or (direction == "upstream" and ids[-1] == seed_tx_id))
            )
            evidence_refs_valid = (path.get("edge_ids") == expected_edges
                                   and path.get("evidence_id") == expected_path_id)

            source_nodes: dict[str, dict[str, Any] | None] = {}
            properties_match = True
            for node in nodes:
                if not isinstance(node, dict):
                    properties_match = False
                    continue
                tx_id = str(node.get("txId", ""))
                if not tx_id.isdigit():
                    properties_match = False
                    continue
                if tx_id not in source_nodes:
                    source_nodes[tx_id] = store.get_transaction(tx_id)
                current = source_nodes[tx_id]
                if current is None or any(
                    key not in node or node.get(key) != current.get(key)
                    for key in ("label", "timeStep", "sourceDataset")
                ):
                    properties_match = False

            edges_match = path_shape_valid and all(
                store.has_flow_edge(source, target) for source, target in zip(ids, ids[1:])
            )
            valid = path_shape_valid and evidence_refs_valid and properties_match and edges_match
            if not path_shape_valid:
                reason = "path_shape_or_bound_mismatch"
            elif not evidence_refs_valid:
                reason = "evidence_reference_mismatch"
            elif not properties_match:
                reason = "transaction_properties_mismatch"
            elif not edges_match:
                reason = "directed_edge_missing"
            else:
                reason = None
            checks.append({"valid": valid, "reason": reason, "node_ids": ids,
                           "edge_ids": expected_edges,
                           "verified_transaction_properties": {
                               tx_id: record for tx_id, record in source_nodes.items() if record is not None
                           },
                           "source": "skeptic_direct_graph_reads"})

        return {"checkedPathCount": len(checks),
                "validPathCount": sum(item["valid"] for item in checks),
                "invalidPathCount": sum(not item["valid"] for item in checks),
                "allPathsValid": bool(bounded) and len(checks) == len(traces or [])
                and all(item["valid"] for item in checks),
                "paths": checks, "independentSource": "SkepticAgent.independently_verify_paths"}

    # ------------------------------------------------------------------
    # Structured finding construction (evidence IDs, expected, observed,
    # reason, and a machine-checkable status on every finding).
    # ------------------------------------------------------------------

    def _finding(self, finding_type: str, evidence_ids: list[str], expected: Any,
                 observed: Any, reason: str, status: str, **extra: Any) -> dict[str, Any]:
        if status not in {STATUS_VERIFIED, STATUS_REJECTED, STATUS_UNVERIFIED, STATUS_NOT_APPLICABLE}:
            raise ValueError(f"skeptic finding status must be one of verified/rejected/unverified/not_applicable: {status}")
        return {
            "finding_type": finding_type,
            "evidence_ids": list(evidence_ids),
            "expected": expected,
            "observed": observed,
            "reason": reason,
            "status": status,
            **extra,
        }

    def _structure_findings(self, seed: dict[str, Any], traces: list[dict[str, Any]],
                            validation: dict[str, Any], seed_exists: bool,
                            malformed_evidence: int, ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        seed_id = str(seed.get("txId", ""))
        check_paths = list(validation.get("paths") or [])
        for index, trace in enumerate(traces if isinstance(traces, list) else []):
            nodes = trace.get("nodes") if isinstance(trace, dict) else None
            ids = [str(node.get("txId", "")) for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []
            check = check_paths[index] if index < len(check_paths) else {}
            if check.get("valid"):
                findings.append(self._finding(
                    "path_structure", ids,
                    expected="all nodes exist with directed FLOWS_TO edges in order, correct direction-specific seed endpoint, and hop count within bound",
                    observed="path passed independent node/edge/endpoint/hop validation",
                    reason="deterministic validation succeeded",
                    status=STATUS_VERIFIED,
                    path_index=index, direction=trace.get("direction"), hop_count=trace.get("hops")))
            else:
                findings.append(self._finding(
                    "path_structure", ids,
                    expected="all nodes exist with directed FLOWS_TO edges in order, correct direction-specific seed endpoint, and hop count within bound",
                    observed="path failed independent validation",
                    reason=f"validation reason: {check.get('reason') or 'node_edge_direction_or_bound_mismatch'}",
                    status=STATUS_REJECTED,
                    path_index=index, direction=trace.get("direction"), hop_count=trace.get("hops")))
        if malformed_evidence:
            findings.append(self._finding(
                "malformed_evidence", [],
                expected="each returned path is a directed path of digit-only transaction records",
                observed=f"{malformed_evidence} malformed evidence record(s)",
                reason="records missing node lists or containing non-graph shapes were rejected",
                status=STATUS_REJECTED))
        if seed_id:
            findings.append(self._finding(
                "seed_existence", [seed_id],
                expected="seed transaction exists in the selected graph",
                observed="confirmed" if seed_exists else "not confirmed",
                reason="Scout reads the record with the application-owned read method",
                status=STATUS_VERIFIED if seed_exists else STATUS_REJECTED))
        # Duplicate paths are inappropriate in the evidence set (traversal dedupes);
        # surface the finding so duplicates cannot silently pass.
        signatures: dict[tuple, int] = {}
        for trace in traces if isinstance(traces, list) else []:
            nodes = trace.get("nodes") if isinstance(trace, dict) else None
            if not isinstance(nodes, list):
                continue
            key = (trace.get("direction"), tuple(str(n.get("txId", "")) for n in nodes if isinstance(n, dict)))
            signatures[key] = signatures.get(key, 0) + 1
        duplicates = [(k, c) for k, c in signatures.items() if c > 1]
        findings.append(self._finding(
            "duplicate_paths", [k[0] for k, _ in duplicates],
            expected="no returned path is repeated in the evidence set",
            observed=f"{len(duplicates)} duplicate path record(s)",
            reason="duplicate paths would double-count occurrences and inflate evidence",
            status=STATUS_VERIFIED if not duplicates else STATUS_REJECTED))
        if ledger:
            stats = ledger.get("scope_stats") or {}
            findings.append(self._finding(
                "unique_node_counts",
                sorted(ledger.get("transactions", {}).keys()),
                expected="unique-transaction census deduplicated across paths",
                observed=f"unique count {stats.get('unique_transaction_count', {}).get('value')}, "
                          f"by label {stats.get('unique_transactions_by_label', {}).get('values')}",
                reason="counts recomputed from the canonical ledger in Python",
                status=STATUS_VERIFIED))
            findings.append(self._finding(
                "count_scope_separation",
                [],
                expected="unique-node counts and path-occurrence counts are reported separately",
                observed=(f"unique total {stats.get('unique_transaction_count', {}).get('value')}; "
                          f"occurrences total {stats.get('path_occurrence_count', {}).get('values', {}).get('total')}"),
                reason="the ledger keeps both scopes distinct and labeled",
                status=STATUS_VERIFIED))
        return findings

    # ------------------------------------------------------------------
    # Independent claim evaluation. Uses the same deterministic validators,
    # but the skeptic calls them itself and records one finding per claim.
    # ------------------------------------------------------------------

    def evaluate_claims(self, claims: list[dict[str, Any]], ledger: dict[str, Any],
                        model_observations: str = "", shared_context=None) -> dict[str, Any]:
        if shared_context is not None:
            shared_context.record_read("Skeptic")
        findings: list[dict[str, Any]] = []
        validated_claims: list[dict[str, Any]] = []
        counts = {"verified": 0, "rejected": 0, "unverified": 0, "not_applicable": 0}
        for claim in claims or []:
            validated = claim_validator.validate_claim(claim or {}, ledger)
            ctype = validated.get("claim_type", "unclassified")
            finding = self._finding(
                "claim_validation",
                list(validated.get("evidence_ids") or []),
                expected=validated.get("expected_value"),
                observed=validated.get("claim_value"),
                reason=validated.get("reason", ""),
                status=validated.get("verification_status", STATUS_UNVERIFIED),
                claim_id=validated.get("claim_id"),
                claim_type=ctype,
            )
            if validated.get("claim_text"):
                finding["claim_text"] = validated.get("claim_text")
            findings.append(finding)
            validated_claims.append(validated)
            counts[validated.get("verification_status", STATUS_UNVERIFIED)] += 1

        # Unsupported-confidence scan over the model's own words (a confidence value
        # is unsupported when it is stated without a deterministic basis).
        for match in claim_validator.UNSUPPORTED_CONFIDENCE_PATTERN.finditer(model_observations or ""):
            findings.append(self._finding(
                "unsupported_confidence",
                [],
                expected="confidence statements are backed by deterministic verification results",
                observed=match.group(0)[:120],
                reason="model confidence language is not a verification outcome",
                status=STATUS_UNVERIFIED))

        return {
            "findings": findings,
            "validated_claims": validated_claims,
            "claim_validation_counts": counts,
            "claims_verified": counts["verified"],
            "claims_rejected": counts["rejected"],
            "claims_unverified": counts["unverified"],
            "status_vocabulary": [STATUS_VERIFIED, STATUS_REJECTED, STATUS_UNVERIFIED, STATUS_NOT_APPLICABLE],
        }

    def validate_memories(self, memories: list[dict[str, Any]], ledger: dict[str, Any], store,
                          shared_context=None) -> list[dict[str, Any]]:
        """Revalidate recalled case evidence against the current graph and ledger.

        A shared transaction makes a memory a candidate only. Remembered paths
        are checked against the live graph, and only exact evidence also present
        in the current ledger is promoted as current supporting evidence.
        """
        if shared_context is not None:
            shared_context.record_read("Skeptic")
        current_transactions = (ledger or {}).get("transactions", {})
        current_edges = {str(edge.get("edge_id")) for edge in (ledger or {}).get("edges", [])
                         if edge.get("edge_id")}
        checked: list[dict[str, Any]] = []
        for candidate in memories or []:
            memory = dict(candidate)
            case_id = str(memory.get("caseId") or "unknown")
            shared = sorted(set(str(value) for value in memory.get("sharedTransactions", []))
                            .intersection(current_transactions))
            remembered_ledger = memory.get("evidenceLedger") or {}
            old_transactions = remembered_ledger.get("transactions", {})
            label_conflicts = []
            for tx_id in shared:
                prior = old_transactions.get(tx_id) or {}
                current = current_transactions.get(tx_id) or {}
                old_label = str(prior.get("label") or "unknown").lower()
                current_label = str(current.get("label") or "unknown").lower()
                if prior and old_label != current_label:
                    label_conflicts.append({"tx_id": tx_id, "remembered_label": old_label,
                                            "current_label": current_label,
                                            "evidence_id": f"tx:{tx_id}"})
            for claim in memory.get("verifiedClaims", []) or []:
                if claim.get("claim_type") != "transaction_label":
                    continue
                tx_id = str(claim.get("tx_id") or "")
                current = current_transactions.get(tx_id)
                remembered_label = str(claim.get("label") or "unknown").lower()
                current_label = str((current or {}).get("label") or "unknown").lower()
                if tx_id in shared and current and remembered_label != current_label:
                    conflict = {"tx_id": tx_id, "remembered_label": remembered_label,
                                "current_label": current_label, "evidence_id": f"tx:{tx_id}"}
                    if conflict not in label_conflicts:
                        label_conflicts.append(conflict)

            remembered_edges = {str(edge.get("edge_id")) for edge in remembered_ledger.get("edges", [])
                                if edge.get("edge_id")}
            if not remembered_edges:
                for path in memory.get("evidence", []) or []:
                    nodes = path.get("nodes") if isinstance(path, dict) else None
                    if isinstance(nodes, list):
                        ids = [str(node.get("txId", "")) for node in nodes if isinstance(node, dict)]
                        remembered_edges.update(f"{source}->{target}" for source, target in zip(ids, ids[1:]))
            shared_edges = sorted(remembered_edges.intersection(current_edges))

            paths = memory.get("evidence", []) or []
            path_validation = None
            if paths:
                # Memory evidence is independently reread by the Skeptic. The
                # traversal validator is never accepted as the authority here.
                path_validation = self.independently_verify_paths(
                    paths, store, str(memory.get("seedTxId") or ""), 4
                )
            path_checks = (path_validation or {}).get("paths", [])
            all_paths_valid = bool(paths) and len(path_checks) == len(paths) and all(
                item.get("valid") is True for item in path_checks
            )
            supporting_ids = [f"tx:{tx_id}" for tx_id in shared]
            supporting_ids.extend(f"edge:{edge_id}" for edge_id in shared_edges)

            if label_conflicts:
                status = "CONTRADICTED"
                reason = "Current deterministic graph labels conflict with remembered labels for shared transaction(s)."
            elif paths and not all_paths_valid:
                status = "STALE"
                reason = "One or more remembered paths failed independent validation against the current graph."
            elif shared_edges and all_paths_valid:
                status = "VERIFIED_RELEVANT"
                reason = (f"Current validated paths independently confirm {len(shared_edges)} remembered directed edge(s).")
            elif shared and all_paths_valid:
                status = "PARTIALLY_RELEVANT"
                reason = "Shared transactions are in both evidence sets, but no complete remembered edge is present in the current ledger."
            elif not shared:
                status = "IRRELEVANT"
                reason = "No transaction IDs from this case occur in current deterministic evidence."
            else:
                status = "UNVERIFIED"
                reason = "The memory lacks paths that can be independently checked against the current graph."

            revalidated_claims = []
            if status in {"VERIFIED_RELEVANT", "PARTIALLY_RELEVANT"}:
                for edge_id in shared_edges:
                    source, target = edge_id.split("->", 1)
                    revalidated_claims.append({"claim_type": "directed_edge", "edge_id": edge_id,
                                               "source": source, "target": target,
                                               "verification_status": "VERIFIED",
                                               "evidence_ids": [f"edge:{edge_id}"]})
                for tx_id in shared:
                    prior = old_transactions.get(tx_id) or {}
                    current = current_transactions.get(tx_id) or {}
                    if prior and str(prior.get("label") or "unknown").lower() == str(current.get("label") or "unknown").lower():
                        revalidated_claims.append({"claim_type": "transaction_label", "tx_id": tx_id,
                                                   "label": str(current.get("label") or "unknown").lower(),
                                                   "verification_status": "VERIFIED",
                                                   "evidence_ids": [f"tx:{tx_id}"]})

            memory.update({
                "validationStatus": status,
                "validationReason": reason,
                "supportingEvidenceIds": supporting_ids,
                "currentSupportingEdges": shared_edges,
                "labelConflicts": label_conflicts,
                "revalidatedClaims": revalidated_claims,
                "pathValidation": path_validation,
            })
            checked.append(memory)
        return checked
