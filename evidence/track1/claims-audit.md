# Submission claims audit

Scope: `README.md` and every Markdown file under `docs/` after the submission-document rewrite. Each factual claim retained in those files is tied to a saved evidence file. Directions, commands, limitations, and value judgments are grouped only when they express the same factual claim. Removed legacy claims are listed at the end.

| Claim | Evidence file | Status |
| --- | --- | --- |
| README: Vesper turns a synthetic transaction ID into a bounded, edge-checked graph investigation with a next action. | `gate1_positive.txt`; `gate2_edges.txt`; `final_counterfactual.json` | SUPPORTED |
| README: the submitted path is Track 1 only through a separate adapter. | `gate1_status.json`; `tool-interface-inspection.json` | SUPPORTED |
| README: findings are investigative leads, not legal conclusions about any person. | `final_http_positive.json` | SUPPORTED |
| README: the generated dataset uses seed 20261018 and contains no real transaction, wallet address, or personal data. | `generator.json`; `dataset-origin-check.txt` | SUPPORTED |
| README: the generated graph has 4,000 Transaction nodes and 6,685 directed FLOWS_TO edges. | `clean-readback.txt`; `generator.json` | SUPPORTED |
| README: node and relationship properties match the documented graph model. | `final_loader_readback.json`; `generator.json` | SUPPORTED |
| README: the architecture uses deterministic selection, bounded parameterized reads, independent edge checks, and local FalkorDB. | `gate2_cypher.txt`; `gate3_selection.json`; `clean-readback.txt` | SUPPORTED |
| README: runtime reads use a two-second deadline, a six-hop bound, and no fixture fallback. | `gate3_errors.json`; `gate3_tool_schema.json`; `regression-python-final.txt` | SUPPORTED |
| README: the complete supported Cypher catalog is in `docs/TRACK1_QUERIES.md`. | `gate1_cypher.txt`; `gate2_cypher.txt`; `gate3_cypher.json`; `final_counterfactual_cypher.json` | SUPPORTED |
| README: clean-clone setup uses Python 3.12, Node 24.1.0, the pinned lock file, Docker Desktop, and the local FalkorDB image without an environment file. | `clean-venv.txt`; `clean-frontend-tests.txt`; `clean-dependencies.txt`; `isolation-target.json` | SUPPORTED |
| README: the existing graph readback is read-only and reports zero writes. | `clean-readback.txt` | SUPPORTED |
| README: the Track 1 server command runs the separate application on loopback port 18783. | `clean-server.txt` | SUPPORTED |
| README: scenario 1 and scenario 2 have the documented three-hop paths. | `gate1_positive.txt`; `gate1_positive_scenario_2.json` | SUPPORTED |
| README: the decoy edge is absent, and deleting the counterfactual edge changes the first action. | `gate2_leads.txt`; `final_counterfactual.json` | SUPPORTED |
| README: the quick API request returns the expected four-node path. | `clean-server.txt`; `clean-server-response.json` | SUPPORTED |
| README: MCP exposes only `get_transaction`, `expand_outgoing`, and `shortest_path`, with deterministic selection. | `gate4_tool_list.json`; `gate4_selection.json` | SUPPORTED |
| README: Python regression count is 91 and frontend regression count is 37. | `clean-python-tests.txt`; `clean-frontend-tests.txt` | SUPPORTED |
| README: Scout, Tracer, Analyst, Skeptic, Historian, and Reporter have the documented evidence-workflow roles. | `clean-frontend-tests.txt`; `regression-python-final.txt` | SUPPORTED |
| README: generator, adapter, tests, interface, documentation, and hero artwork disclose OpenAI Codex assistance. | `generator.json`; `REPORT.md`; `readme-hero.json` | SUPPORTED |
| README: records and role labels are invented; unit fixtures are mocked test inputs rather than database evidence. | `generator.json`; `regression-python-final.txt` | SUPPORTED |
| README: the office prototype and sprite pack have repository-recorded dates in the eligibility statement. | `../originality.md`; `../core-file-history.json` | SUPPORTED |
| README: the repository uses Apache License 2.0. | `../../LICENSE` | SUPPORTED |
| docs/ARCHITECTURE.md: the saved live gates cover the separate synthetic adapter. | `gate1_status.json`; `gate2_status.json`; `gate3_status.json`; `gate4_status.json` | SUPPORTED |
| docs/ARCHITECTURE.md: the graph schema and zero-write 4,000-node/6,685-edge readback are as documented. | `clean-readback.txt`; `final_loader_readback.json` | SUPPORTED |
| docs/ARCHITECTURE.md: deterministic lookup, expansion, edge rereads, and destination-directed shortest-path selection are used. | `gate2_cypher.txt`; `gate3_selection.json` | SUPPORTED |
| docs/ARCHITECTURE.md: the NetworkX path matches the database path. | `gate3_networkx.json` | SUPPORTED |
| docs/ARCHITECTURE.md: the MCP server has three bounded read-only stdio tools and a real client called them. | `gate4_tool_list.json`; `gate4_results.json` | SUPPORTED |
| docs/ARCHITECTURE.md: database failure returns no evidentiary path or conclusion, and recovery restores the path. | `final_http_negative.json`; `final_http_recovery.json` | SUPPORTED |
| docs/COMPLIANCE.md: submitted graph data is generated synthetic data without imported blockchain records, addresses, or personal data. | `generator.json`; `../../manifest/synthetic_manifest.json` | SUPPORTED |
| docs/COMPLIANCE.md: only the owned container and two allowlisted graph names are accepted by the adapter. | `isolation-target.json`; `docker-state.txt`; `final_counterfactual.json` | SUPPORTED |
| docs/COMPLIANCE.md: Codex assistance is disclosed. | `REPORT.md`; `generator.json` | SUPPORTED |
| docs/COMPLIANCE.md: office prototype and character sprite pack have the stated repository-recorded import dates. | `../originality.md`; `../core-file-history.json` | SUPPORTED |
| docs/DEMO_SCRIPT.md: the canonical storyboard uses saved evidence and does not claim a recorded video. | `REPORT.md`; `judge-walkthrough.md` | SUPPORTED |
| docs/DEMO_SCRIPT.md: the positive-control HTTP response matched the manifest hop for hop and the server exited cleanly. | `clean-server.txt`; `clean-server-response.json` | SUPPORTED |
| docs/DEMO_SCRIPT.md: the expected four-node path is the saved scenario 1 path. | `gate1_positive.txt`; `clean-server-response.json` | SUPPORTED |
| docs/ELIGIBILITY.md: repository history shows no contradicting evidence of pre-event implementation, cannot establish original writing time, and records the base import on October 17, 2026. | `../originality.md`; `../core-file-history.json` | SUPPORTED |
| docs/ELIGIBILITY.md: office prototype first appears in this repository at commit `77593ae` on October 18, 2026 at 12:33:08 IST. | `../originality.md`; `../core-file-history.json` | SUPPORTED |
| docs/ELIGIBILITY.md: character sprite pack first appears in this repository at commit `d6e1591` on October 18, 2026 at 12:42:49 IST. | `../originality.md`; `../core-file-history.json` | SUPPORTED |
| docs/ELIGIBILITY.md: implementation commits are `27cbe50` and `d930ac0`. | `state-verification.txt`; `delivery.json` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: configuration uses an explicit track selector, allowlisted graph, identity record, loopback host, non-default port, Redis run identity, and owned lifecycle metadata. | `isolation-target.json`; `docker-state.txt`; `final_controls_status.json` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: only `vesper_synthetic_verify` and `vesper_counterfactual` are accepted graph names. | `isolation-target.json`; `final_counterfactual.json`; `regression-python-final.txt` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: implementation commits did not change existing query, schema, validator, fixture, or legacy runtime files. | `legacy-preservation.json` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: generator mechanics, planted components, layers, role counts, and graph counts match the generated artifact. | `generator.json`; `gate1_counts.txt` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: generator, node, edge, and manifest hashes match the documented hashes and duplicate manifests are byte-identical. | `generator.json`; `clean-generator.txt` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: generator inputs contain no real Bitcoin records or external datasets/assets, and manifest references are not native relationship IDs. | `generator.json`; `gate2_edges.txt` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: shortest-path syntax was selected through live probes. | `gate3_syntax.txt` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: existing-graph loading performs exact readback without writes, and the initial timed-out acknowledgement was retained without blind deletion. | `clean-readback.txt`; `load-attempt-1.json`; `load-primary-readback.json` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: investigation is deterministic and fail-closed, with bounded expansion, shortest-path errors returning no path, and runtime tools not reading expected manifest paths. | `gate3_errors.json`; `final_http_negative.json`; `regression-python-final.txt` | SUPPORTED |
| docs/TRACK1_ADAPTER.md: MCP SDK 1.30.0 client lists and calls all three tools through stdio using deterministic selection. | `gate4_status.json`; `gate4_tool_list.json`; `gate4_selection.json`; `gate4_results.json` | SUPPORTED |
| docs/TRACK1_QUERIES.md: runtime tools use read-only graph queries; values are parameterized; hop, result, and timeout bounds match the catalog. | `gate1_cypher.txt`; `gate2_cypher.txt`; `gate3_cypher.json`; `gate3_errors.json` | SUPPORTED |
| docs/TRACK1_QUERIES.md: the health, ID lookup, count, role-count, expansion, and independent edge-check statements match saved executed query text. | `gate1_cypher.txt`; `gate2_cypher.txt` | SUPPORTED |
| docs/TRACK1_QUERIES.md: node export, edge export, and shortest-path statements match saved executed query text. | `gate3_database_export.json`; `gate3_cypher.json`; `gate3_syntax.txt` | SUPPORTED |
| docs/TRACK1_QUERIES.md: existing property checks and new-graph load statements match the loader evidence. | `final_loader_readback_cypher.json`; `load-primary.json` | SUPPORTED |
| docs/TRACK1_QUERIES.md: the counterfactual DELETE is guarded and was executed only in `vesper_counterfactual`. | `gate2_delete.txt`; `final_counterfactual_cypher.json` | SUPPORTED |
| docs/TRACK1_QUERIES.md: graph module version, native-ID locality, parameter/result logging, GRAPH.LIST isolation, and Redis INFO identity checks are saved. | `gate3_syntax.txt`; `gate2_edges.txt`; `container-lifecycle.jsonl`; `isolation-target.json` | SUPPORTED |
| docs/judge-walkthrough.md: the storyboard is Track 1 only, synthetic, and is not described as a recorded video. | `REPORT.md`; `generator.json` | SUPPORTED |
| docs/judge-walkthrough.md: first path and native relationship IDs are `[0, 2, 3]`, with one row for every directed edge. | `gate2_edges.txt`; `gate2_status.json` | SUPPORTED |
| docs/judge-walkthrough.md: decoy rejection and counterfactual action change are saved, while primary counts and unaffected scenarios remain intact. | `gate2_leads.txt`; `final_counterfactual.json`; `final_counterfactual_unaffected_2.json`; `final_counterfactual_unaffected_3.json` | SUPPORTED |
| docs/judge-walkthrough.md: shortest-path, NetworkX, and real MCP exchanges are saved; selection is deterministic and bounded. | `gate3_selection.json`; `gate3_networkx.json`; `gate4_results.json` | SUPPORTED |
| docs/judge-walkthrough.md: stopped-database failure and recovery are saved. | `final_http_negative.json`; `final_http_recovery.json` | SUPPORTED |
| docs/demo-storyboard.md: the planted start, expected three-hop path, and native relationship IDs match saved evidence. | `gate1_positive.txt`; `gate2_edges.txt`; `gate2_status.json` | SUPPORTED |
| docs/demo-storyboard.md: the decoy is rejected and the counterfactual edge removal changes the selected action. | `gate2_leads.txt`; `gate2_delete.txt`; `final_counterfactual.json` | SUPPORTED |
| docs/demo-storyboard.md: shortest-path and real MCP client verification commands produced the named results. | `gate3_selection.json`; `gate3_networkx.json`; `gate4_tool_list.json`; `gate4_results.json` | SUPPORTED |
| docs/demo-storyboard.md: stopped-database failure and restarted-database recovery are saved against the owned lifecycle target. | `final_http_negative.json`; `final_http_recovery.json`; `container-lifecycle.jsonl` | SUPPORTED |
| docs/demo-storyboard.md: no recorded-video claim is made. | `REPORT.md` | SUPPORTED |
| Prior README wording about the other event track's live status and preserved behavior. | Removed from `README.md` because it is outside this submission's claims. | REMOVED |
| Prior README wording naming preserved fixtures from the other event track. | Removed from `README.md` because it is outside this submission's claims. | REMOVED |
| Prior architecture claims about memory, ownership, identity shortcuts, and a different graph. | Removed by rewriting `docs/ARCHITECTURE.md` to the separate Track 1 adapter. | REMOVED |
| Prior compliance claims about owner-scoped memory, a different graph, and Cloud behavior. | Removed by rewriting `docs/COMPLIANCE.md` to saved Track 1 boundaries. | REMOVED |
| Prior demo instructions, persisted-case claims, IDs, and commands for the other event track. | Removed by rewriting `docs/DEMO_SCRIPT.md` to the Track 1 positive control. | REMOVED |
| Prior adapter wording about preserving tests and owner-isolation behavior from the other event track. | Removed from `docs/TRACK1_ADAPTER.md` because it is outside this submission's claims. | REMOVED |
| Prior walkthrough wording reporting the other event track as not tested. | Removed from `docs/judge-walkthrough.md` because it is outside this submission's claims. | REMOVED |
| Claims that the audit-machine Python installation was broken. | Removed because no saved evidence file establishes the cause; only the working executable is retained. | REMOVED |
| Claims that versioned external documentation was read before MCP implementation. | Removed because the saved evidence proves the interface and runtime exchange, not the act of reading. | REMOVED |
| Claims of blanket team authorization for all project data and assets. | Removed because the saved files establish synthetic provenance and repository history, not a blanket rights grant. | REMOVED |

## Counts

- SUPPORTED: 65
- REMOVED: 10
- UNSUPPORTED retained: 0
