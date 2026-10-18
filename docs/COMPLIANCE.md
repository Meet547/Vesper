# Data and release notes

This repository packages a local demonstration of graph investigation and owner-scoped case memory. The release fixture contains invented transaction IDs, labels, time steps, and directed `FLOWS_TO` relationships. It contains no imported blockchain dataset or transaction attribution. `sourceDataset=bureau_synthetic_v1` is a fixture provenance tag retained for compatibility; it does not refer to BUREAU transaction records.

The public candidate is assembled from an explicit allowlist on top of Vesper's existing initial README commit. It excludes the original BUREAU checkout, its history, local logs, environment files, evaluation corpora, local QA output, and backups. The manifest lists the final included files and their SHA-256 hashes.

The office artwork was supplied directly by the project owner. The character animations were restored from the earlier project sprite pack at the owner’s request. These provenance notes are not an independent copyright review or license grant. The interface requests Silkscreen from Google Fonts; no font binary is included in this repository. The upstream [Google Fonts Silkscreen repository](https://github.com/googlefonts/silkscreen) identifies it as SIL Open Font License 1.1. No root source-code license is declared; public availability does not itself grant reuse rights.

The app defaults to local demo mode. The isolated integration runner binds HTTP and FalkorDB to loopback and pins the graph to `vesper_track2_synthetic_test`; it does not read Cloud credentials. Do not provide production or Cloud endpoints to the isolated scripts.

AI coding assistants were used during development. The submitter is responsible for reviewing the code and completing the official AI-assistance disclosure.
