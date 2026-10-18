# Vesper recording script: Track 1 and Track 2

This sequence uses the single Vesper interface at `http://127.0.0.1:8012/` and the local FalkorDB graph `vesper_track2_synthetic_test`. All transaction records and edges are authored synthetic fixtures, not observed Bitcoin transactions.

## Start and readiness

In Terminal 1, from the repository root, check whether the local database container already exists:

```sh
docker ps -a --filter 'name=^/bureau-m84-isolated$'
```

If its status is `Exited`, start the existing container (do not remove it or its volume):

```sh
docker start bureau-m84-isolated
```

If there is no matching container, create the local loopback-only database:

```sh
docker compose --profile local-db up -d
```

Wait for FalkorDB:

```sh
for i in {1..60}; do
  if docker exec bureau-m84-isolated redis-cli PING 2>/dev/null | grep -q PONG; then break; fi
  sleep 1
done
docker exec bureau-m84-isolated redis-cli PING
```

Expected: `PONG`. Seed or verify only the Vesper graph:

```sh
./.venv/bin/python scripts/seed_milestone_8_4_isolated_graph.py
```

Expected: `status: PASS`, graph `vesper_track2_synthetic_test`, IDs `731000001` through `731000008`, eight transactions, seven directed edges, and `production_graph_writes: 0`. This is repeat-safe and preserves unrelated graphs and saved records.

Start FastAPI in Terminal 1:

```sh
./scripts/run_track2_demo.sh
```

In Terminal 2, verify the graph and owner:

```sh
curl --fail-with-body --silent --show-error http://127.0.0.1:8012/api/health
curl --fail-with-body --silent --show-error http://127.0.0.1:8012/api/demo/track2/status
```

Expected fields include `database_connected:true`, graph `vesper_track2_synthetic_test`, environment `isolated_demo`, and owner `track2-isolated-demo`.

## Track 1: graph paths and Skeptic

1. Open `http://127.0.0.1:8012/` and confirm the Vesper brand, office scene, and connected graph name.
2. Enter `731000004`, set the depth to three hops, and click **Start investigation**.
3. Point out Tracer's graph-directed path selection and the Case Board action history.
4. Show Skeptic's independent node/property and directed-edge checks, then the evidence report. The verified paths in the recorded run were:
   - `731000003 → 731000004` (1 hop)
   - `731000002 → 731000003 → 731000004` (2 hops)
   - `731000001 → 731000002 → 731000003 → 731000004` (3 hops)
5. Show structured handoffs and report limits. Do not describe the synthetic fixture as live blockchain evidence.

Read-only API reproduction:

```sh
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' \
  -d '{"seed_tx_id":"731000004","max_hops":3,"memory_enabled":false}' \
  http://127.0.0.1:8012/api/investigations/preview
```

Verified browser run on 2026-10-18: invocation `inv_3349a2fa2d00`, three Skeptic-valid paths, three directed edges, `persisted:false`.

## Track 2: persisted Case A and paired Case B

1. In the Track 2 panel, click **Investigate Case A · seed 731000002**.
2. Review its graph paths and Skeptic checks. Click **Save case & memory** and show the database acknowledgement.
3. Click **Case B · memory off** and **Case B · memory on**. Keep the graph, seed `731000001`, three-hop limit, and action budget the same.
4. Show the comparison card, the revalidated memory path, the changed frontier, and the Skeptic-verified joined path.
5. Reload the page and use **Reload persisted cases** to demonstrate recovery of the same Case A and memory IDs.

The database-backed recorded Case A is `case_b9f4a7e565d2`, memory `memory_e826e337ca49`, owner `track2-isolated-demo`. Its writer and fresh reader process completed while FalkorDB remained running. The recorded memory-off invocation `inv_207ea0f5e550` selected frontier `731000005` with five Skeptic-valid paths. Memory-on invocation `inv_d223b32bb17a` recalled the Case A memory, passed Skeptic revalidation, selected `731000002` first, and returned six valid paths including `731000001 → 731000002 → 731000003 → 731000004`. Both UI A/B previews reported zero database writes.

For a fresh process restart run (this creates a new Case A and reports its newly generated IDs):

```sh
export BUREAU_M84_GRAPH_ISOLATED_CONFIRM=I_CONFIRM_NONPRODUCTION
export BUREAU_M84_ISOLATED_GRAPH_NAME=vesper_track2_synthetic_test
export BUREAU_M84_ISOLATED_FALKORDB_URL=redis://127.0.0.1:6389
export BUREAU_M84_ISOLATED_FALKORDB_SSL=false
export BUREAU_M84_SEED_A=731000002
export BUREAU_M84_SEED_B=731000001
export BUREAU_M84_MAX_HOPS=3
PYTHONPATH=. ./.venv/bin/python scripts/demo_milestone_8_4_restart_persistence.py
```

The script verifies the exact same case and memory IDs across its fresh reader process, then compares memory off/on. Do not use production or Cloud endpoints.

## Report files

The browser's **Export JSON** button saves the structured report currently displayed. In a fresh browser run, click it once and inspect the downloaded JSON for the invocation/case ID, seed, traces, Skeptic path validation, graph decisions, handoffs, memory verification, persistence status, and limitations. Do not present the file as a full graph export.

The browser JSON export was directly downloaded and parsed during verification: invocation `inv_d223b32bb17a`, seed `731000001`, six traces, Skeptic path validation, seven graph decisions, 12 agent events, and one `VERIFIED_RELEVANT` memory (`memory_e826e337ca49`). This was a read-only preview (`persisted:false`). The downloaded file was 290,954 bytes. In a fresh recording, export again and inspect the current invocation and evidence before submission.

This release has no Markdown report export control. Mark Markdown export as unavailable in the recording and submission notes; do not describe a manually written summary as an exported application report.

## Recording setup and limitations

Record the desktop browser at 1280×800 or larger with the Vesper page at 100% zoom. Keep the graph status and Case Board legible. For a narrow-screen check, use a viewport at or below 520 CSS pixels and capture the stacked office, investigation form, and Track 2 cards. The CSS has explicit breakpoints and reduced-motion behavior; report any direct layout check separately from automated tests.

Keep the browser on localhost. Show the synthetic-only warning and state the node/edge counts. Do not show credentials, `.env`, unrelated graphs, logs, personal machine paths, or the Docker console with data outside the Vesper graph. Record the Docker image ID with the video because the Compose file uses mutable `falkordb/falkordb:latest`.
