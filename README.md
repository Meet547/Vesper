# Vesper

Vesper is an evidence-first transaction-graph investigation prototype built with FastAPI and FalkorDB. It demonstrates two workflows through one shared frontend: graph-driven investigations (Track 1) and persistent, Skeptic-verified case memory (Track 2).

The single interface is `frontend/index.html`. It contains the animated Vesper office, investigation controls, Case Board, findings report, JSON export, and the conditional Track 2 memory panel. Both tracks use this interface.

The six specialists move between authored Vesper office waypoints. The scene uses explicit furniture collision boundaries and foreground depth masks for the arcade, desk cluster, server racks, shelves, and lounge. Named destinations include workstations, archive shelves, memory pods, meeting aisle, arcade, water station, and paper station. This is scripted scene navigation; the frontend does not dynamically recognize or infer arbitrary objects in the artwork.

## Data and limits

The release uses authored synthetic fixtures only. The in-memory fixture uses IDs `730000001`–`730000008`; the isolated FalkorDB fixture uses IDs `731000001`–`731000008`, with eight transaction nodes and seven directed `FLOWS_TO` edges. IDs, labels, time steps, and relationships are invented for this demonstration. They are not Bitcoin transaction records and make no claims about real wallets, people, ownership, or conduct. The source tag is `bureau_synthetic_v1` for fixture provenance.

Graph evidence comes from bounded FalkorDB reads. The Skeptic independently rereads nodes and directed edges before accepting a path. A successful result proves only that the returned path matches the selected synthetic graph and configured hop bound; it does not establish completeness or real-world attribution. Case memory is owner-scoped and revalidated against the current graph before use.

## Local setup

Requirements: macOS or Linux, Python 3.11+, Node.js 20+, and Docker Desktop / Docker Engine. The isolated demo uses no Cloud credentials and no hosted model. From a fresh clone:

```sh
git clone https://github.com/Meet547/Vesper.git
cd Vesper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
node --test tests/*.test.mjs
python -m pytest -q
```

Check for the local FalkorDB container before creating one:

```sh
docker ps -a --filter 'name=^/bureau-m84-isolated$'
```

If it exists and is stopped, start it with `docker start bureau-m84-isolated`. If no such container exists, start the loopback-only service from the included Compose file:

```sh
docker compose --profile local-db up -d
```

Wait for readiness:

```sh
for i in {1..60}; do
  if docker exec bureau-m84-isolated redis-cli PING 2>/dev/null | grep -q PONG; then break; fi
  sleep 1
done
docker exec bureau-m84-isolated redis-cli PING
```

The expected response is `PONG`. The published ports are restricted to loopback. Do not remove the container or its volume to resolve a conflict; inspect and preserve existing graphs.

Seed or verify only the named Vesper graph. This script is idempotent: it checks the target graph and refuses unexpected transaction properties or relationships; it does not delete data.

```sh
./.venv/bin/python scripts/seed_milestone_8_4_isolated_graph.py
```

Expected graph: `vesper_track2_synthetic_test`, transactions `731000001`–`731000008`, and seven directed edges. The seeder reports existing graph names and preserves other graphs and saved cases/memories.

## Run the shared Vesper UI

```sh
./scripts/run_track2_demo.sh
```

Open <http://127.0.0.1:8012/>. The launcher pins the backend to `127.0.0.1:8012`, FalkorDB to `redis://127.0.0.1:6389`, graph `vesper_track2_synthetic_test`, and owner `track2-isolated-demo`. The HTML response is not cached so an older page cannot mask the current Vesper frontend.

## Track 1: graph-driven investigation

Use seed `731000004` and a three-hop search in the shared UI, or run the read-only API preview:

```sh
curl --fail-with-body --silent --show-error \
  -H 'Content-Type: application/json' \
  -d '{"seed_tx_id":"731000004","max_hops":3,"memory_enabled":false}' \
  http://127.0.0.1:8012/api/investigations/preview
```

Review `traces`, `skeptic.checks.pathValidation`, `graph_decisions`, and `persisted:false`. The report and Case Board show the returned paths, independent checks, action history, handoffs, and scope limits. Preview does not save a case.

## Track 2: persistent case memory

For the process-restart persistence check, run this in a separate terminal after FalkorDB is ready:

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

The script writes Case A to the Vesper graph, stops the writer process, starts a fresh reader process while FalkorDB remains available, and checks for the same case and memory IDs. It then runs Case B with memory disabled and enabled. Never point these variables at a production or Cloud graph.

For the browser demonstration, use the same page at `http://127.0.0.1:8012/`:

1. Click **Investigate Case A · seed 731000002**. Review the paths and Skeptic checks in Findings & evidence.
2. Click **Save case & memory**. Confirm the database acknowledgement and note the generated case and memory IDs.
3. Click **Case B · memory off**, then **Case B · memory on**. The panel shows the first selected frontier, saved-memory verification, Skeptic-verified paths, and graph-read counts.
4. Reload the page, then **Reload persisted cases**. Confirm that the same Case A and memory IDs are recovered.

Case IDs are generated at runtime. Capture the IDs shown in the actual run rather than using IDs from a previous session.

## Graph model and queries

```text
(:Transaction {txId, label, timeStep, sourceDataset})
  -[:FLOWS_TO]->
(:Transaction {txId, label, timeStep, sourceDataset})

(:InvestigationCase)-[:GENERATED_MEMORY]->(:InvestigationMemory)
(:InvestigationMemory)-[:REFERENCES]->(:Transaction)
```

`databases/schema.cypher` contains the documented graph model. Useful bounded queries are in `databases/queries/graph_health.cypher`, `flow_count.cypher`, `inspect_transaction.cypher`, `upstream_trace.cypher`, and `memory_schema.cypher`. The backend uses parameterized Cypher and applies explicit hop and result limits. The memory policy only follows a remembered route after a fresh graph check and Skeptic validation.

## Reproducibility and checks

The isolated seed and restart test report the graph name, node IDs, edge count, owner, and persistence IDs. Record the FalkorDB image digest alongside a demo recording because the Compose file uses the mutable upstream `latest` tag. A successful unit test or in-process fixture run is not evidence of a live database run; report those separately.

Run the suites with:

```sh
python -m pytest -q
node --test tests/*.test.mjs
```

The interface exports the structured investigation report as JSON using **Export JSON**. There is no Markdown export control in this release.

## Artwork and AI assistance

The office PNG was supplied by the project owner. The six specialists use their original animated pixel-art clips, restored from the earlier project sprite pack at the owner’s request. Provenance is recorded, but copyright ownership and redistribution rights for either artwork asset have not been independently verified. The interface requests Silkscreen from Google Fonts; no font files are bundled. The upstream [Google Fonts Silkscreen repository](https://github.com/googlefonts/silkscreen) identifies the font as SIL Open Font License 1.1. System monospace fallbacks are defined.

AI coding assistants were used during development. Disclose that assistance in the official submission form. The submitter should be prepared to explain the graph schema, queries, action policy, Skeptic verification, memory workflow, and limitations.

No root source-code license is declared in this repository. No license should be inferred from public visibility.
