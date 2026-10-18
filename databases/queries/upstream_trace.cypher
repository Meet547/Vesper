// Example upstream traversal. The backend bounds max_hops to 1..4.
MATCH p = (source:Transaction)-[:FLOWS_TO*1..3]->(target:Transaction {txId: '730000004'})
RETURN [n IN nodes(p) | n.txId] AS txIds,
       [n IN nodes(p) | n.label] AS labels,
       [n IN nodes(p) | n.timeStep] AS timeSteps,
       length(p) AS hops
ORDER BY hops ASC
LIMIT 20
