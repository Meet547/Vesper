# Three-minute Track 1 recording storyboard

This is a script for the user to record. It does not claim that a video already exists. Run only against the recorded `vesper-verify` target and `vesper_synthetic_verify` or `vesper_counterfactual`.

## 0:00–0:20 — problem and planted start

Say: “Vesper helps an analyst inspect a synthetic directed connection, reject a disconnected lead, and choose the next investigative action. Its output is an investigative lead, not a legal conclusion about any person.” Enter `SYN-000001` as the planted start transaction.

Exact evidence command:

```sh
sed -n '1,220p' manifest/synthetic_manifest.json
```

Saved result: `manifest/synthetic_manifest.json` and `evidence/track1/gate1_positive.txt`.

## 0:20–1:20 — path, native IDs, Cypher, and edges

Show `SYN-000001 → SYN-000002 → SYN-000003 → SYN-000004`, native relationship IDs `[0, 2, 3]`, the parameterized Cypher, and the one-row independent check for each edge.

Exact verification command used:

```sh
.venv/bin/python -m scripts.verify_track1_gates 2
```

Saved results: `evidence/track1/gate2_cypher.txt`, `evidence/track1/gate2_edges.txt`, and `evidence/track1/gate2_status.json`.

## 1:20–2:00 — accepted, rejected, and counterfactual leads

Show the accepted four-node lead, then the rejected decoy connection `SYN-000006 → SYN-000004` with zero rows. Show that deleting only `SYN-000002 → SYN-000003` in `vesper_counterfactual` changes the action from `inspect_endpoint` to `request_additional_evidence`.

Exact read-only final-check command used after the one-time deletion:

```sh
.venv/bin/python -m scripts.verify_track1_final
```

Saved results: `evidence/track1/gate2_leads.txt`, `evidence/track1/gate2_delete.txt`, and `evidence/track1/final_counterfactual.json`.

## 2:00–2:40 — shortest path and MCP client

Show the bounded `shortest_path` selection and the real stdio MCP client's tool listing and call. Describe selection as deterministic, not LLM-driven.

Exact verification commands used:

```sh
.venv/bin/python -m scripts.verify_track1_tool
.venv/bin/python -m scripts.verify_track1_mcp
```

Saved results: `evidence/track1/gate3_selection.json`, `evidence/track1/gate3_networkx.json`, `evidence/track1/gate4_tool_list.json`, and `evidence/track1/gate4_results.json`.

## 2:40–3:00 — fail closed and recover

Show the saved stopped-database response: `evidence unavailable`, no path, and no conclusion. Then show the restarted-database recovery with the original accepted path. Do not stop the database manually during recording unless using the owned-container lifecycle script.

Exact lifecycle and final-check commands used:

```sh
.venv/bin/python -m scripts.track1_container stop
.venv/bin/python -m scripts.track1_container restart
.venv/bin/python -m scripts.verify_track1_final
```

Saved results: `evidence/track1/final_http_negative.json`, `evidence/track1/final_http_recovery.json`, and `evidence/track1/container-lifecycle.jsonl`.
