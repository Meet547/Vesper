MATCH (t:Transaction)
RETURN count(t) AS totalTransactions,
       sum(CASE WHEN t.label = 'illicit' THEN 1 ELSE 0 END) AS illicitTransactions,
       sum(CASE WHEN t.label = 'licit' THEN 1 ELSE 0 END) AS licitTransactions,
       sum(CASE WHEN t.label = 'unknown' THEN 1 ELSE 0 END) AS unknownTransactions
