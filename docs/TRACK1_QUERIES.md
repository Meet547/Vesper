# Track 1 Cypher catalog

These are the complete statements used by the adapter, loader and gate runners. Runtime tools execute only GRAPH.RO_QUERY. Values are passed as parameters. Traversal depth is a constant six in the query and filtered by a validated max_hops parameter. Read deadlines are 2,000 ms; loader batches use 10,000 ms. Only the gate counterfactual script contains DELETE, guarded by the exact counterfactual graph name. The timeout control uses 1 ms.

## Health

```cypher
RETURN 1 AS ready
```

## ID lookup

```cypher
MATCH (t:Transaction {txId: $tx_id}) RETURN t.txId, t.label, t.timeStep, t.sourceDataset LIMIT 2
```

## Node counts

```cypher
MATCH (n) RETURN labels(n) AS label, count(*) AS nodes ORDER BY label
```

## Relationship counts

```cypher
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS edges ORDER BY rel
```

## Neutral role counts

```cypher
MATCH (t:Transaction) RETURN t.label AS role, count(*) AS nodes ORDER BY role
```

## Bounded outgoing paths

```cypher
MATCH p=(s:Transaction {txId: $start_txid})-[:FLOWS_TO*1..6]->(t:Transaction) WHERE length(p) <= $max_hops RETURN [n IN nodes(p) | n.txId] AS txids, [r IN relationships(p) | id(r)] AS relationship_ids, length(p) AS hops ORDER BY hops DESC, txids ASC LIMIT 41
```

## Independent directed edge check

```cypher
MATCH (s:Transaction {txId: $source})-[r:FLOWS_TO]->(t:Transaction {txId: $target}) RETURN id(r) AS relationship_id LIMIT 2
```

## Node export

```cypher
MATCH (t:Transaction) RETURN t.txId, t.label, t.timeStep, t.sourceDataset ORDER BY t.txId
```

## Edge export with native IDs

```cypher
MATCH (s:Transaction)-[r:FLOWS_TO]->(t:Transaction) RETURN s.txId, t.txId, id(r) ORDER BY s.txId, t.txId
```

## Shortest directed path

```cypher
MATCH (s:Transaction {txId: $start_txid}), (t:Transaction {txId: $end_txid}) WITH shortestPath((s)-[:FLOWS_TO*1..6]->(t)) AS p WHERE p IS NOT NULL AND length(p) <= $max_hops RETURN [n IN nodes(p) | n.txId], [r IN relationships(p) | id(r)], length(p)
```

## Existing node property check

```cypher
MATCH (n) RETURN n.txId, labels(n), keys(n) ORDER BY n.txId
```

## Existing edge property check

```cypher
MATCH ()-[r]->() RETURN DISTINCT keys(r)
```

## New-graph node load only

```cypher
UNWIND $nodes AS tx CREATE (t:Transaction {txId: tx.txId, label: tx.label, timeStep: tx.timeStep, sourceDataset: tx.sourceDataset}) RETURN count(t)
```

## New-graph edge load only

```cypher
UNWIND $edges AS edge MATCH (s:Transaction {txId: edge.source}), (t:Transaction {txId: edge.target}) CREATE (s)-[r:FLOWS_TO]->(t) RETURN count(r)
```

## One-time counterfactual deletion only

```cypher
MATCH (s:Transaction {txId: $source})-[r:FLOWS_TO]->(t:Transaction {txId: $target}) DELETE r RETURN count(r) AS removed
```

The shortest-path syntax was tested against the installed graph module (raw version 42201). Native IDs are local to this graph. Parameter values, result rows and native relationship IDs are saved in gate1_cypher.txt, gate2_cypher.txt, gate3_cypher.json, and gate4_results.json. Setup uses GRAPH.LIST to reject unexpected graph names; identity uses Redis INFO. Neither command mutates graph data.
