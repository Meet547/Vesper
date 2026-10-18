"""Actual stdio subprocess/client exchange, gated on the preceding live controls."""
import asyncio
import importlib.metadata
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from scripts.verify_track1_gates import MANIFEST, OUT, save


async def main():
    for gate in (1, 2, 3):
        assert json.loads((OUT / f"gate{gate}_status.json").read_text())["status"] == "PASS"
    scenario = json.loads(MANIFEST.read_text())["scenarios"][0]
    server = StdioServerParameters(command=sys.executable, args=["-m", "backend.track1.mcp_server"],
        cwd=str(Path.cwd()), env={"VESPER_TRACK": "track1_synthetic", "VESPER_TRACK1_GRAPH": "vesper_synthetic_verify",
        "VESPER_TRACK1_TARGET_FILE": str((OUT / "isolation-target.json").resolve()), "PYTHONDONTWRITEBYTECODE": "1"})
    with (OUT / "gate4_server_stderr.txt").open("w") as stderr:
        async with stdio_client(server, errlog=stderr) as (read, write):
            async with ClientSession(read, write) as session:
                initialization = await session.initialize()
                listed = await session.list_tools()
                save("gate4_tool_list.json", listed.model_dump(mode="json"))
                names = {tool.name for tool in listed.tools}
                assert names == {"get_transaction", "expand_outgoing", "shortest_path"}
                assert all(tool.annotations.readOnlyHint for tool in listed.tools)
                args = dict(start_txid=scenario["start_txid"], end_txid=scenario["end_txid"], max_hops=3)
                selected = next(tool for tool in listed.tools if tool.name == "shortest_path")
                save("gate4_selection.json", {"policy": "Deterministic destination-directed policy", "selected_tool": selected.name,
                                             "arguments": args, "reason": "The task supplies both endpoints and requires a minimum-hop route."})
                route = await session.call_tool(selected.name, args)
                get = await session.call_tool("get_transaction", {"tx_id": scenario["start_txid"]})
                expand = await session.call_tool("expand_outgoing", {"start_txid": scenario["start_txid"], "max_hops": 3})
                save("gate4_results.json", {"initialize": initialization.model_dump(mode="json"),
                     "shortest_path": route.model_dump(mode="json"), "get_transaction": get.model_dump(mode="json"),
                     "expand_outgoing": expand.model_dump(mode="json")})
                assert not any(r.isError for r in (route, get, expand))
                assert route.structuredContent["result"]["path"] == scenario["expected_path"]
                assert get.structuredContent["result"]["transaction"]["txId"] == scenario["start_txid"]
                assert any(p["txids"] == scenario["expected_path"] for p in expand.structuredContent["result"]["paths"])
                bad = await session.call_tool("shortest_path", {**args, "max_hops": 7})
                save("gate4_invalid_bound.json", bad.model_dump(mode="json"))
                assert bad.isError
    save("gate4_status.json", {"status": "PASS", "time_IST": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                              "sdk": importlib.metadata.version("mcp"), "transport": "stdio subprocess",
                              "documentation": "https://github.com/modelcontextprotocol/python-sdk/tree/v1.x",
                              "evidence": ["gate4_tool_list.json", "gate4_selection.json", "gate4_results.json", "gate4_invalid_bound.json"]})
    print(json.dumps({"gate": 4, "status": "PASS"}))


if __name__ == "__main__":
    asyncio.run(main())
