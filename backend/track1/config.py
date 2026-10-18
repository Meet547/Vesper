from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

GRAPHS = frozenset({"vesper_synthetic_verify", "vesper_counterfactual"})


@dataclass(frozen=True)
class Target:
    port: int
    run_id: str
    container_id: str
    graph: str

    @classmethod
    def from_environment(cls):
        if os.environ.get("VESPER_TRACK") != "track1_synthetic":
            raise ValueError("Select VESPER_TRACK=track1_synthetic explicitly")
        graph = os.environ.get("VESPER_TRACK1_GRAPH", "")
        path = Path(os.environ.get("VESPER_TRACK1_TARGET_FILE", ""))
        if graph not in GRAPHS or path.suffix != ".json" or path.name.startswith(".env"):
            raise ValueError("An allowed graph and isolated target JSON are required")
        data = json.loads(path.read_text())
        if (data.get("container_name") != "vesper-verify" or data.get("host") != "127.0.0.1"
                or type(data.get("port")) is not int or not 1024 < data["port"] < 65536
                or data["port"] == 6379 or not data.get("created_by_this_run")
                or not data.get("container_id") or not data.get("run_id")):
            raise ValueError("Target must identify the new loopback-only disposable container")
        return cls(data["port"], data["run_id"], data["container_id"], graph)

    def __post_init__(self):
        if (self.graph not in GRAPHS or type(self.port) is not int or not 1024 < self.port < 65536
                or self.port == 6379 or not self.run_id or not self.container_id):
            raise ValueError("Invalid isolated target")
