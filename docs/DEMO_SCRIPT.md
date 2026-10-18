# Vesper Track 1 demonstration

Use the canonical three-minute storyboard in [`judge-walkthrough.md`](judge-walkthrough.md). It references only saved Track 1 evidence and does not claim that a video has been recorded.

For the live positive control, start the application with the command in `README.md`, then call `POST /api/route` with `SYN-000001`, `SYN-000004`, and `max_hops` 3. The fresh-clone response, manifest comparison, and clean shutdown are saved in `evidence/track1/clean-server.txt` and `evidence/track1/clean-server-response.json`.

The expected route is `SYN-000001 → SYN-000002 → SYN-000003 → SYN-000004`. The generator manifest and the saved HTTP response contain the same path hop for hop.
