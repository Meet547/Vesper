"""Lifecycle commands only for the container created and recorded by this run."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

NAME = "vesper-verify"
PORT = 16479
OWNER_KEY = "vesper.track1.audit"
TARGET = Path("evidence/track1/isolation-target.json")
LOG = Path("evidence/track1/container-lifecycle.jsonl")


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"Docker command failed: {args[0]} (exit {result.returncode})")
    return result.stdout.strip()


def inspect(data):
    # Deliberately exclude Config.Env and other credential-bearing configuration.
    raw = docker("inspect", "--format", '{{json .Id}}|{{json .Name}}|{{json .Config.Labels}}|{{json .HostConfig.PortBindings}}|{{json .Mounts}}', data["container_id"])
    identity, name, labels, ports, mounts = [json.loads(part) for part in raw.split("|", 4)]
    if (identity != data["container_id"] or name != "/" + NAME
            or labels.get(OWNER_KEY) != data["audit_id"]
            or ports != {"6379/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(PORT)}]}
            or not any(m["Type"] == "volume" and m["Name"] == data["volume"] and m["Destination"] == "/data" for m in mounts)):
        raise RuntimeError("Failed graph isolation: container identity, ownership, port or volume differs")


def refresh(data):
    inspect(data)
    for _ in range(30):
        try:
            if docker("exec", data["container_id"], "redis-cli", "PING") == "PONG":
                break
        except RuntimeError:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError("Disposable FalkorDB did not become ready")
    info = docker("exec", data["container_id"], "redis-cli", "INFO", "server")
    fields = dict(line.split(":", 1) for line in info.splitlines() if ":" in line)
    data["run_id"] = fields["run_id"]
    data["redis_server_version"] = fields["redis_version"]
    modules = json.loads(docker("exec", data["container_id"], "redis-cli", "--json", "MODULE", "LIST"))
    module_maps = [m if isinstance(m, dict) else dict(zip(m[::2], m[1::2])) for m in modules]
    data["modules"] = [{"name": m.get("name"), "version": m.get("ver")} for m in module_maps]
    if not any(m["name"] == "graph" for m in data["modules"]):
        raise RuntimeError("Disposable server has no FalkorDB module")
    TARGET.write_text(json.dumps(data, indent=2) + "\n")
    return data


def run(action):
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    if action == "create":
        if TARGET.exists() or docker("ps", "-a", "--filter", "name=^/vesper-verify$", "--format", "{{.ID}}"):
            raise RuntimeError("Refusing to modify an existing container or target record")
        audit_id = uuid4().hex
        volume = "vesper-verify-20261018-" + audit_id[:10]
        digest = json.loads(docker("image", "inspect", "falkordb/falkordb:latest", "--format", "{{json .RepoDigests}}"))[0]
        server_version = docker("info", "--format", "{{.ServerVersion}}")
        docker("volume", "create", "--label", OWNER_KEY + "=" + audit_id, volume)
        identity = docker("run", "--detach", "--name", NAME, "--label", OWNER_KEY + "=" + audit_id,
                          "--publish", f"127.0.0.1:{PORT}:6379", "--mount", f"type=volume,source={volume},target=/data",
                          digest, "redis-server", "--loadmodule", "/var/lib/falkordb/bin/falkordb.so",
                          "--dir", "/data", "--save", "60 1")
        data = {"container_name": NAME, "container_id": identity, "volume": volume, "audit_id": audit_id,
                "created_by_this_run": True, "host": "127.0.0.1", "port": PORT,
                "image_digest": digest, "docker_server_version": server_version}
        TARGET.write_text(json.dumps(data, indent=2) + "\n")
        data = refresh(data)
    else:
        data = json.loads(TARGET.read_text())
        inspect(data)
        if action == "stop":
            docker("stop", "--time", "20", data["container_id"])
        elif action == "restart":
            docker("start", data["container_id"])
            data = refresh(data)
        elif action == "snapshot":
            data = refresh(data)
        else:
            raise ValueError("Unknown lifecycle action")
    record = {"time_IST": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(), "action": action, **data}
    with LOG.open("a") as handle:
        handle.write(json.dumps(record) + "\n")
    print(json.dumps({"status": "PASS", "action": action, "container_id": data["container_id"],
                      "container_name": NAME, "image_digest": data["image_digest"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "stop", "restart", "snapshot"])
    run(parser.parse_args().action)
