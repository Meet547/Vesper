# Three-minute local demonstration script

Track 1 only. Use the separate local adapter and saved live evidence. No real Bitcoin records are shown. This is a script; no demo video was recorded or published in this run.

1. **0:00–0:20:** Explain the analyst's task: inspect a synthetic connection, show supporting edges, reject a disconnected branch, and choose a next action. Show the synthetic notice and manifest.
2. **0:20–1:20:** Enter the first manifest start ID with three hops. Show database mode and `vesper_synthetic_verify`, the four-node expected path, native relationship IDs `[0, 2, 3]` from this instance, and parameterized Cypher in `gate2_cypher.txt`. Open `gate2_edges.txt`: each path edge returns exactly one row.
3. **1:20–2:00:** Show `gate2_leads.txt`: the decoy's last connection returns zero rows. Compare the separate counterfactual using `final_counterfactual.json`. Its missing `SYN-000002 → SYN-000003` edge changes `inspect_endpoint` to `request_additional_evidence`. The primary remains 4,000 nodes/6,685 edges; other planted paths remain intact.
4. **2:00–2:40:** Show `gate3_selection.json`, the NetworkX comparison, and real MCP tool list/exchange in `gate4_results.json`. Explain deterministic selection, six-hop bound and two-second server deadline. Do not describe it as LLM-selected or tested in an external chat client.
5. **2:40–3:00:** Show the live HTTP negative response in `final_http_negative.json`, followed by recovery. If reenacting, use only the owned-container lifecycle script. Finish with the limitation: synthetic investigative leads, not legal conclusions.

The report lists the exact commit and evidence. Originality requires the team's written evidence or an organizer response before submission. Track 2 live status is NOT TESTED TODAY; its preserved regression tests are reported separately.
