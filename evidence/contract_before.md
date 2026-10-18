# Existing graph and application contract

Status: PASS — contract inventory saved; replacement compatibility is FAIL at Step 1.2.

Commit: `8e041522bd48e34b9ea3b12a1a4764dbcd66e6af`.
Inspection started 2026-10-18 13:21:57 IST. Probe and inventories saved at 13:24:54 IST.

## Graph storage shape

`databases/schema.cypher:2` describes the transaction shape below; line 8 creates an index on `Transaction.txId`. The file does not declare property-type constraints or a label-value enum. Application and loader behavior impose additional requirements.

| Element | Property / representation | Current type and behavior | Source |
|---|---|---|---|
| Node label | `Transaction` | All transaction records use this graph label | `databases/schema.cypher:2`; loader lines 136–138 |
| Transaction identity | `txId` | String. API and evidence validation require digits only; request length 1–50. Seed loader currently supplies nine-digit strings. | `backend/app/models.py:18–27`; `backend/app/services/graph_store.py:343,363`; loader lines 16–18 |
| Dataset classification | `label` | String. Current search API accepts only `illicit`, `licit`, `unknown`, or an empty filter. Counts/ledger/UI assume the same three categories. | `backend/app/main.py:228`; graph store lines 161–165,193; ledger line 23 |
| Time ordering | `timeStep` | Integer in loader; returned as stored by graph reads. Existing isolated fixture uses 8 for every node. | loader lines 17,157–159; graph store lines 140–145 |
| Source marker | `sourceDataset` | String in loader, currently `bureau_synthetic_v1`; graph reads can return null for missing data. | loader lines 15,17; graph store lines 140–145 |
| Directed relationship | `FLOWS_TO` | Transaction-to-transaction. Existing loader stores no relationship properties. | loader lines 143–147 |
| Loader edge record | `source`, `target` | Strings matching node `txId`; these are input dictionary fields, not stored relationship properties. | loader lines 20–24,143–147 |
| Path edge reference | `source->target` | Application-derived string, not native `id(r)` and not a stored edge ID | graph store lines 304,389 |

The generator could preserve the graph labels/property types while using `SYN-` strings. That alone would not preserve the current application contract: the API and path-validation code reject those IDs. The underlying parameterized ID lookup query does **not** impose the digits-only restriction.

## Existing query inventory

All 56 query/source-construction records are saved in `contract_queries.json`, with file and line. They are static source records, not executed Cypher results. Records include standalone reference queries, application calls, dynamic construction expressions and loader commands; a record count is not a count of unique executed queries.

| Query group | Location | Contract dependency |
|---|---|---|
| Readiness | `graph_store.py:93` | `RETURN 1 AS ready`; no dataset dependency |
| Node/classification totals | `graph_store.py:160`; `databases/queries/graph_health.cypher` | Exact equality against the three old classification strings |
| Relationship total | `graph_store.py:168`; `flow_count.cypher` | `FLOWS_TO` relationship type |
| Single transaction | `graph_store.py:183`; `inspect_transaction.cypher` | Parameterized string identity in runtime; reference file has an old sample literal |
| Transaction search | `graph_store.py:201` | String substring search and optional `label` equality; upstream Python/API restrict filter vocabulary |
| Incoming/outgoing neighbors | `graph_store.py:219,224` | Directed `FLOWS_TO`, four transaction properties, result caps |
| Bounded path traversal | `graph_store.py:276,285`; `upstream_trace.cypher` | One to four hops in runtime; query text interpolates the clamped hop bound; returns ordered node IDs/properties, not native edge IDs |
| Independent edge existence | `graph_store.py:322` | Directed endpoint identity match, `count(r)` |
| Memory retrieval/save/list/get | `graph_store.py:420,546,588,606`; `memory_schema.cypher` | Case/memory labels and relationships, optional owner identity, serialized evidence |
| Track 2 persistence acknowledgement | `track2_demo_store.py:61` | Owner-scoped case/memory relationships; preserved without execution |
| Seed preflight, insert and postflight | `seed_milestone_8_4_isolated_graph.py:101–155` | Fixed node/edge dictionaries; merges Transaction nodes and property-free FLOWS_TO edges |

Exact current totals query:

```cypher
MATCH (t:Transaction)
RETURN count(t) AS totalTransactions,
       sum(CASE WHEN t.label = 'illicit' THEN 1 ELSE 0 END) AS illicitTransactions,
       sum(CASE WHEN t.label = 'licit' THEN 1 ELSE 0 END) AS licitTransactions,
       sum(CASE WHEN t.label = 'unknown' THEN 1 ELSE 0 END) AS unknownTransactions
```

For a neutral-label sample `hub, relay, relay, endpoint`, all three equality counts are zero. This is a local evaluation of the query's literal equality predicates, **not a database execution**. It does not mean the Cypher is invalid: it means the existing query has no counters for the requested role vocabulary. Preserving a category breakdown under that replacement requires a query change.

## Track 2 boundary

Case nodes carry `caseId`, `seedTxId`, `status`, `summary`, `findingsJson`, `createdAt`, and optionally `ownerId`. Memory nodes carry `memoryId`, `caseId`, `seedTxId`, `summary`, serialized evidence/ledger/reference/claim/model fields, `schemaVersion`, `createdAt`, `tags`, and optionally `ownerId`. Identifiers/text/serialized JSON are strings; schema version is numeric; tags are a string list. Relationships are `INVESTIGATES`, `GENERATED_MEMORY`, and `REFERENCES`. These are runtime write/query expectations, not database-enforced constraints.

The only existing loader is the Track 2 fixture loader. It is hardcoded to container `bureau-m84-isolated`, port 6389 and graph `vesper_track2_synthetic_test`. It does not accept a generated data file. Running it as written would violate this run's allowed graph/container boundary. It was not run or edited. A separate Track 1 loader or adapter would be needed to preserve the Track 2 implementation.

## Reproduced mismatch and stop

Saved output: `contract_probe.json`. The probe extracts and executes the existing `normalize_seed_id` function body, with decorators removed, without importing application configuration. No environment file, application startup or database connection is involved.

```text
SYN-000001 -> ValueError: Transaction ID must contain digits only
SYN-004000 -> ValueError: Transaction ID must contain digits only
730000004 -> accepted
```

Additional unchanged digit-only checks appear in the graph store, local model tool input, Skeptic, orchestrator context collection, and frontend form/submit validation. Neutral category filters also need application changes; these are inventoried in `dataset_references.md`.

Step 1.2 replacement compatibility: **FAIL**. A generator cannot satisfy the requested IDs and neutral role vocabulary while preserving the existing application ID/category contract. Supporting neutral category counts requires a query change, which invokes the user's stop condition. No generator, manifest, database control or product change was attempted after this finding.

Proposed scope for user authorization: a separate Track 1 path/adapter accepting `SYN-` IDs and neutral labels, with matching category-count Cypher and a new loader restricted to `vesper-verify` plus `vesper_synthetic_verify` / `vesper_counterfactual`. Keep all existing Track 2 code and tests unchanged. This is a proposed change, not an implemented one.
