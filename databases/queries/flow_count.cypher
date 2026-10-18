MATCH ()-[r:FLOWS_TO]->()
RETURN count(r) AS totalFlows
