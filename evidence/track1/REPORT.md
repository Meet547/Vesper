# Vesper isolated release evidence

**Verdict: READY FOR FINAL STAGED CHECKS.** The isolated Track 1 implementation, clean-clone checks, and live gates passed. The user supplied the written team history statement in `../../docs/ELIGIBILITY.md` and selected Apache-2.0; no organizer reply has been supplied or claimed. At the time of this saved report, no public branch, release, PR, or submission had been changed. Track 1 is the proposed entry.

Start: **2026-10-18 16:57:06 IST**. The completed clean-clone checks and source commit are recorded in `delivery.json`. Base: `8e041522bd48e34b9ea3b12a1a4764dbcd66e6af`. Work is isolated in `/private/tmp/vesper-track1-20261018`, branch `codex/track1-isolated`. The pre-existing `vesper-submission` branch belongs to another checkout and was preserved. The original source checkout was not changed.

| Gate | Status | Saved evidence |
| --- | --- | --- |
| 0 — written originality closure | PASS — user-supplied team statement; no organizer answer claimed | `../../docs/ELIGIBILITY.md`, `../originality.md`, `../core-file-history.json`, `gate0_status.json` |
| 1 — live FalkorDB dependency | PASS | `gate1_status.json`, `gate1_positive.txt`, `gate1_negative.txt`, `gate1_restarted.txt`, `final_http_positive.json`, `final_http_negative.json`, `final_http_recovery.json` |
| 2 — edge provenance / counterfactual | PASS | `gate2_status.json`, `gate2_edges.txt`, `gate2_leads.txt`, `gate2_delete.txt`, `final_counterfactual.json` |
| 3 — bounded graph algorithm tool | PASS | `gate3_status.json`, `tool-interface-inspection.json`, `gate3_syntax.txt`, `gate3_selection.json`, `gate3_networkx.json`, `gate3_errors.json` |
| 4 — MCP | PASS | `gate4_status.json`, `gate4_tool_list.json`, `gate4_selection.json`, `gate4_results.json`, `gate4_invalid_bound.json` |

Originality evidence wording: **no contradicting evidence found**. No substantive pre-event implementation was found in the inspected history. Both imports fall within the event window. Git cannot establish when the original code was written. The user explicitly answered “No” regarding an organizer response. No history, tags or timestamps were altered to address this question.

## Dataset and adapter

The separate adapter accepts only SYN-prefixed six-digit IDs and neutral hub/relay/endpoint roles. The global numeric-only validation contract remains unchanged. The implementation commits did not edit existing runtime code, fixtures, validators, or tests. Byte comparison of the implementation base found only README changed among existing files; 65 files remained byte-identical (`legacy-preservation.json`). The old dataset references and contract are preserved in `../dataset_references.md` and `../contract_before.md`.

Version **1.0.0**, seed **20261018**, **4,000 nodes / 6,685 directed edges**. Roles: hub 2,071; relay 1,799; endpoint 130. Generator SHA-256: `1fe417c7f3116887f5eec03514f923617bfe223bc4df6ae78e3adbc56082f411`. Node SHA-256: `ca3f2687499b1f6ccfae571d7b0c83277d5d7b371f3fdd58d88d1e5379922b43`. Edge SHA-256: `a4781ff93307754ec5295c58ab673adf156bc98b66d421101e9348d2054fe795`. Manifest SHA-256: `a2d70d4496a5622e6dc38117c10017748751b8b25196708d5611acb77b9448f2`.

Manifest: `manifest/synthetic_manifest.json`. `generator.json` records byte-identical results from two generation runs. Schema, provenance and AI assistance are documented in `../../docs/TRACK1_ADAPTER.md`. All data is newly authored synthetic scenario data; none is a real Bitcoin record. No external assets were introduced. Added libraries MCP and NetworkX retain MIT and BSD-3-Clause licenses respectively (`dependency-provenance.json`).

The identity record pins loopback port 16479, graph allowlist, owned container and Redis run ID. Lifecycle checks also pin the ownership label and newly created volume. Docker server **29.8.2**; FalkorDB module raw version **42201**; image digest `falkordb/falkordb@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a`. Only `vesper_synthetic_verify` and `vesper_counterfactual` were loaded. Container `vesper-verify` and its new volume remain available for local review. No existing container/volume/graph was modified; no Cloud writes occurred.

## Exact graph proof

Accepted path: **SYN-000001 → SYN-000002 → SYN-000003 → SYN-000004**. Native relationship IDs on this instance: **[0, 2, 3]**. Each independent directed-edge query returned exactly one row; the decoy's `SYN-000006 → SYN-000004` check returned zero. Saved full queries, parameters and rows are in `gate2_cypher.txt` and `gate2_edges.txt`.

```cypher
MATCH (s:Transaction {txId: $source})-[r:FLOWS_TO]->(t:Transaction {txId: $target}) RETURN id(r) AS relationship_id LIMIT 2
```

The deletion below ran **only in vesper_counterfactual**, with `source=SYN-000002` and `target=SYN-000003`. Result: `[[1]]`.

```cypher
MATCH (s:Transaction {txId: $source})-[r:FLOWS_TO]->(t:Transaction {txId: $target}) DELETE r RETURN count(r) AS removed
```

Action changed from **inspect_endpoint** to **request_additional_evidence**, with no accepted three-hop lead. The counterfactual has 6,684 edges; both other planted paths survive. The primary remains 4,000 nodes/6,685 edges. Final code was rerun against the preserved deletion state without another deletion, reload or reset (`final_counterfactual.json`).

Warm-store and fresh HTTP-request outage tests returned `evidence unavailable`, no paths, null action/conclusion, and no SYN IDs. Recovery restored the exact expected path. The fail-closed implementation is `backend/track1/investigator.py:unavailable` and `investigate`; tests cover failure at health, lookup, expansion and edge recheck. The full query catalog is `../../docs/TRACK1_QUERIES.md`.

## Tools, tests and reproducibility

Shortest-path selection uses a deterministic destination-directed policy. FalkorDB's returned path and length exactly match NetworkX computed from a full database export (`gate3_database_export.json`). Unknown ID, seven-hop request, actual server timeout, and stopped database all return no path. MCP 1.30.0 was checked against its official versioned docs before implementation. A real stdio client lists and calls all three bounded, read-only tools. This is not an LLM-selection or external-chat-host claim. MCP finished well within the 90-minute cap.

- Python: **91 passed**, including all 79 existing tests and 12 new adapter tests. One upstream Starlette/TestClient deprecation warning. `regression-python-final.json` and `.txt`.
- Frontend: **37 passed**, zero failed/skipped. `regression-frontend-final.json` and `.txt`.
- Existing source preservation: **PASS**, `legacy-preservation.json`.
- Exact existing primary readback, including property checks: **PASS**, `final_loader_readback.json`, with zero writes.
- Clean clone: **PASS** from committed source `a51f7c8b7d81b7cb2441c2f42db4786e4e7e600c`; Node 24.1.0 ran 37 frontend tests, readback reported zero writes, the HTTP path matched the manifest hop for hop, the server exited cleanly, and the clone remote was removed. `delivery.json`, `clean-frontend-tests.txt`, `clean-readback.txt`, `clean-server.txt`, and `clean-origin-removal.txt`.

Commands used: `python -m scripts.generate_synthetic_graph --output ...` twice; `python -m scripts.track1_container create`; `python -m scripts.load_track1_graph`; `python -m scripts.verify_track1_gates 1`; `python -m scripts.verify_track1_gates 2`; `python -m scripts.verify_track1_tool`; `python -m scripts.verify_track1_mcp`; `python -m scripts.verify_track1_final`; `python -m pytest -q`; `node --test tests/*.test.mjs`. Run-specific command arrays and IST timestamps are preserved alongside test logs and `container-lifecycle.jsonl`.

Earlier attempts are retained, not presented as passes: one new adapter unit test exposed eager SDK construction and was fixed before live gates; the initial bulk-load acknowledgement timed out and an exact read-only export established its committed contents; one unsupported shortest-path syntax was rejected before selecting the working WITH form. A one-millisecond request may finish successfully, so timeout attempts retain every result and require an actual server timeout. No failed fail-closed control occurred.

The README and submission documents now describe this Track 1 adapter only. The README includes a project-local six-agent hero image, concise installation steps, role descriptions, architecture, sample questions, test results, disclosure, limits, and the complete Cypher catalog. The judge walkthrough is a script, not a recorded video. At the time of this report, nothing had been pushed or submitted.

**Next action in this authorized run:** stage only submission files, run the staged diff and secret checks, commit, and push only to the new `track1-submission` branch. Any failed check or secret finding stops the run before push.
