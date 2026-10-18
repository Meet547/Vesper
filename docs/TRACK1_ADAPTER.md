# Track 1 contract and provenance

This adapter is separately selectable through `VESPER_TRACK=track1_synthetic`, an allowlisted `VESPER_TRACK1_GRAPH`, and a local `VESPER_TRACK1_TARGET_FILE` JSON identity record. It has its own application factory and validation models. It never reads `.env`, legacy Settings, or a Cloud connection. Host is fixed at loopback; default Redis port is rejected; Redis run identity must match the record. Lifecycle operations additionally check container ID, ownership label, port binding, and volume. The only graph names accepted are `vesper_synthetic_verify` and `vesper_counterfactual`.

The pre-adapter contract is in `evidence/contract_before.md`, with the old query inventory in `evidence/contract_queries.json`. Explicit authorization permits the new ID and role vocabularies in this separate adapter. No existing query, schema, validator, fixture, Track 2 test, owner isolation behavior, or legacy runtime file was changed. Existing numeric ID validation still rejects `SYN-` IDs.

Generator version 1.0.0 uses Python's seeded random generator with seed 20261018, fixed 4,000-node size, sorted nodes/edges, compact sorted-key JSON, and one trailing newline. Three isolated six-node planted components contain three-hop paths and dead-end branches. The remaining nodes form 32 forward-only layers. Neutral role counts: hub 2,071; relay 1,799; endpoint 130. Graph counts: Transaction 4,000; FLOWS_TO 6,685. The counterfactual has the same nodes and 6,684 edges after one deletion.

Generator SHA-256: `1fe417c7f3116887f5eec03514f923617bfe223bc4df6ae78e3adbc56082f411`.
Node JSON SHA-256: `ca3f2687499b1f6ccfae571d7b0c83277d5d7b371f3fdd58d88d1e5379922b43`.
Edge JSON SHA-256: `a4781ff93307754ec5295c58ab673adf156bc98b66d421101e9348d2054fe795`.
Manifest SHA-256: `a2d70d4496a5622e6dc38117c10017748751b8b25196708d5611acb77b9448f2`.
The duplicate manifest paths are byte-identical. `evidence/track1/generator.json` records two independent generation runs and hashes.

Dataset provenance is independently authored synthetic scenario data, made with AI assistance under team authorization. No Bitcoin records, wallet addresses, personal data, external datasets, images, or fonts were input. Manifest endpoint references are not database relationship IDs. Live `id(r)` values and independent edge checks are saved in `gate2_edges.txt`; they apply only to that instance. The [FalkorDB function reference](https://docs.falkordb.com/cypher/functions) documents `shortestPath` and internal IDs; actual supported syntax was selected by live probes in `gate3_syntax.txt`.

The loader creates records only when an allowed graph does not yet exist. For an existing graph it compares the full node/edge export and counts; any mismatch raises an isolation error without clearing or rewriting records. It rejects any other graph name on the server. Initial load acknowledgement timed out, but a subsequent exact read-only export matched every expected node/edge. That attempt remains in `load-attempt-1.json`; no blind retry or deletion was performed. Subsequent writes use bounded batches, explicit timeouts and disabled automatic retries.

Investigation is deterministic: lookup, bounded expansion, individual edge rereads, then a depth-based action. Missing database evidence yields no paths, action, conclusion or echoed IDs. Timeout also closes the investigation. Expansion truncation prevents a conclusion. Shortest-path errors carry no path; `max_hops` is required and strictly bounded. Runtime tools use graph data, not manifest expected paths. The manifest is read by generation and verification scripts only.

MCP uses the official SDK's maintained v1 API, pinned to 1.30.0. The [versioned documentation](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x), [server guide](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/docs/server.md), and [client guide](https://github.com/modelcontextprotocol/python-sdk/blob/v1.x/docs/client.md) were read before implementation. A real client launches a stdio subprocess, lists tools, selects the destination-route tool through a deterministic policy, and calls all three tools. No claim is made about LLM-driven selection or an external chat host.

Gate 0 remains open: no substantive pre-event implementation was found in the inspected history; Git cannot establish when original code was written. Both imported histories fall within the event window. Evidence wording: **no contradicting evidence found**. The user reports no organizer answer. This adapter does not resolve that authorship question.
