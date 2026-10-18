# Gate 0 — originality evidence

Target: `8e041522bd48e34b9ea3b12a1a4764dbcd66e6af` (public Vesper `main`, no release/tag).
Audit began: 2026-10-18 13:08:12 IST. Clean checkout established: 13:09:40 IST. Detailed collection completed: 13:12:26 IST.
Event boundary: 2026-10-15 00:01:00 IST (2026-10-14 18:31:00 UTC).

**Verdict: no substantive pre-event implementation was substantiated in the inspected history. Actual development start remains unproven.** Neither a fresh import commit nor filesystem modification times establish authorship time. This is not an unconditional eligibility certification.

| Core component | Earliest substantiated development date | Evidence source | Pre-existing template/infrastructure or hackathon implementation | Eligibility concern |
|---|---|---|---|---|
| FalkorDB integration and Cypher | Existing portions recorded 2026-10-17 10:28:24 IST; released version imported 2026-10-18 12:33:08 IST | `graph_store.py`: 481 matching lines with immutable source commit; `git log --follow` attributes source file to `c4f0a58`; release attribution is `77593ae` | Application-specific implementation; not established as a general template | Both recorded author/commit dates are in-event. Import dates and mtimes cannot establish when earlier code was written. |
| Agent orchestration | Existing portions recorded 2026-10-17 10:28:24 IST; released version imported 2026-10-18 12:33:08 IST | `orchestrator.py`: 335 matching lines with immutable source; release `git log` and `git blame` | Application-specific investigation orchestration | Earliest recorded presence is in-event; actual start unknown. Fresh commit/mtime is not proof. |
| Graph decision logic | 2026-10-18 12:33:08 IST recorded import | `backend/app/agents/graph_decisions.py`, `77593ae`; `choose_next_action` at line 144 | Application-specific ranking/action logic; absent from the inspected source commit's tracked tree | No earlier committed provenance for this file was found. Import/mtime cannot prove original development date. |
| Memory and persistence | Existing `graph_store.py`/`historian.py` portions recorded 2026-10-17 10:28:24 IST; isolated demo store recorded 2026-10-18 12:33:08 IST | `save_case`/`find_related_memories` in graph store; historian has 14 matching source lines; `track2_demo_store.py` imported at `77593ae`; `memory_schema.cypher` is byte-identical to source | Product-specific case memory and isolated storage adapter | Recorded dates are in-event. Runtime persistence is not tested here. Import/mtime does not establish creation date. |
| Handoffs and shared state | Existing shared-context portions recorded 2026-10-17 10:28:24 IST; released version imported 2026-10-18 12:33:08 IST | `shared_context.py`: 174 matching source lines; release `add_handoff` at line 81 and orchestrator `handoff` at line 76 | Application-specific coordination | No pre-event record found; origin of every added line cannot be independently dated. Import/mtime is insufficient. |
| Cypher schema and seed loader | Schema recorded 2026-10-17 10:28:24 IST; release loader recorded 2026-10-18 12:33:08 IST | `databases/schema.cypher` byte-identical to source (8 lines); `scripts/seed_milestone_8_4_isolated_graph.py`, `77593ae` | Application-specific schema and authored synthetic fixture loader | Dates are in-event. Dataset license documentation is a separate stop. Import/mtime does not prove writing time. |
| Frontend investigation UI | Existing portions recorded 2026-10-17 10:28:24 IST; import 2026-10-18 12:33:08 IST; later UI commits at 12:42:49 and 12:57:43 IST | `frontend/index.html`: 518 matching source lines; source README describes an earlier supplied office prototype; release compliance notes earlier sprite assets | Mixed application UI and reused office/art assets; not demonstrated to be a general template | Earlier prototype/art creation dates are unsubstantiated. No dated pre-event implementation found. Fresh publication/mtime cannot settle origin. |
| MCP layer | No implementation date established | Filename inventory and textual search across tracked code, requirements and docs found no MCP/FastMCP/ModelContextProtocol matches | No MCP implementation found in the inspected release | Not an originality blocker; do not claim MCP support. No runtime MCP gate was attempted. |

## Commands and records

Executed from the clean release checkout, for all 25 identified core files:

```sh
git status --porcelain=v1
git rev-parse HEAD
git log --reverse --format='%h %ad %s' --date=iso
git log --follow --format='%h %an %ad %cd %s' --date=iso -- <file>
git blame -w --date=iso -- <file>
```

Exact commands, timestamps, exits and outputs: [commands.json](commands.json). Blame output retains commit/date/line attribution; source text is omitted to avoid recording sensitive values. File hashes, histories and named code symbols: [core-file-history.json](core-file-history.json).

Release history (author date equals committer date for each):

```text
61d2878 2026-10-18 01:26:01 +0530 Initial commit
77593ae 2026-10-18 12:33:08 +0530 Publish verified Vesper release candidate
d6e1591 2026-10-18 12:42:49 +0530 Restore Vesper character sprite animations
8e04152 2026-10-18 12:57:43 +0530 Fix Vesper office navigation and depth layering
```

## Imported source provenance

Release `docs/COMPLIANCE.md:5` explicitly describes an allowlisted publication excluding the original source history. Accordingly, immutable source Git objects were read as provenance evidence; no dirty source-file contents were used to verify release behavior. Commands ran from the release checkout with an explicit read-only `--git-dir` pointing to the existing source repository. BUREAU was not modified, fetched, reset, checked out, committed or pushed.

Source history:

```text
c4f0a5801a665a56d44ecb390850018668285861 2026-10-17 10:28:24 +0530 Initial commit: Upload all project files to BUREAU repo
77dc829c0fa56f0cff08e953a420c03d25b749f0 2026-10-17 10:37:23 +0530 fix: audit & structural hardening
```

Comparisons use exact immutable blobs at `77dc829c0fa56f0cff08e953a420c03d25b749f0`, not the dirty files. [source-provenance.json](source-provenance.json) records both SHA-256 hashes, matching-line counts and matching blocks. Matching blocks substantiate shared code, not a complete genealogy of later modifications. Source history dates those existing files to `c4f0a58`.

Source WORKLOG/PROJECT_STATE contain self-reported activity on October 15–17; these are historical claims, not independently rerun tests. The source README references a supplied office prototype without a substantiated creation date. No inspected README/CHANGELOG established a pre-event implementation date. No mtime was used.

Gate 0's pre-event blocker was not demonstrated. Work stopped separately on the user's undocumented dataset-license condition; no later functional gate was run.
