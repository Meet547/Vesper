// Replace the example ID with a transaction ID present in the graph.
MATCH (t:Transaction {txId: '730000004'})
OPTIONAL MATCH (incoming:Transaction)-[:FLOWS_TO]->(t)
WITH t, collect(DISTINCT incoming.txId) AS incomingIds
OPTIONAL MATCH (t)-[:FLOWS_TO]->(outgoing:Transaction)
RETURN t.txId AS txId, t.label AS label, t.timeStep AS timeStep,
       incomingIds, collect(DISTINCT outgoing.txId) AS outgoingIds
