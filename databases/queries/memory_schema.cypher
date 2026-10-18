// Created by backend on first saved case. Shown here for architecture/reference.
// (:InvestigationCase {caseId, seedTxId, status, summary, findingsJson, createdAt})
// (:InvestigationCase)-[:INVESTIGATES]->(:Transaction)
// (:InvestigationCase)-[:GENERATED_MEMORY]->(:InvestigationMemory)
// (:InvestigationMemory {memoryId, caseId, seedTxId, summary, evidenceJson,
//   evidenceLedgerJson, evidenceRefsJson, verifiedClaimsJson, rejectedClaimsJson,
//   modelMetadataJson, schemaVersion, createdAt, tags})
// (:InvestigationMemory)-[:REFERENCES]->(:Transaction)
