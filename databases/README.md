# Database notes

## Current graph schema

The cloud graph should already contain the imported data:

- `(:Transaction {txId, label, timeStep, sourceDataset})`
- `(:Transaction)-[:FLOWS_TO]->(:Transaction)`

`txId` is stored as a string. The local synthetic examples use values such as `730000004`; keep IDs as strings at API boundaries.

## Case and memory schema

The backend creates these node types on the first saved investigation:

- `(:InvestigationCase {caseId, seedTxId, status, summary, findingsJson, createdAt})`
- `(:InvestigationMemory {memoryId, seedTxId, summary, evidenceJson, createdAt, tags})`
- `(case)-[:INVESTIGATES]->(seed transaction)`
- `(case)-[:GENERATED_MEMORY]->(memory)`
- `(memory)-[:REFERENCES]->(evidence transaction)`

This keeps case metadata and memory in the same graph, adjacent to its evidence. The backend uses fixed parameterized Cypher and does not accept arbitrary queries from a frontend or agent.

## Optional index

If transaction searches become slow, copy `CREATE INDEX ON :Transaction(txId)` into the **main FalkorDB query editor** and run it once. Do not paste it into the `Upload Data → Load CSV` dialog. If FalkorDB reports the index already exists, continue.
