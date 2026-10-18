// Existing imported graph expected by this application:
// (:Transaction {txId, label, timeStep, sourceDataset})-[:FLOWS_TO]->(:Transaction)
// The Browser CSV import created the Transaction nodes and FLOWS_TO relationships.
// Case/memory schema is created lazily when an investigation is saved by the backend.

// Optional index: run this in FalkorDB Browser's MAIN query editor, NOT in Upload Data.
// Syntax for FalkorDB's Cypher implementation:
CREATE INDEX ON :Transaction(txId)
