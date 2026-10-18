"""Local stdio MCP adapter. No write, arbitrary-query, or memory tools."""
from __future__ import annotations

import json
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from .config import Target
from .store import EvidenceUnavailable, IsolationError, SyntheticStore
from .tools import Track1Tools

SyntheticId = Annotated[str, Field(pattern=r"^SYN-[0-9]{6}$")]
HopBound = Annotated[int, Field(strict=True, ge=1, le=6)]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
mcp = FastMCP("Vesper synthetic Track 1")


def execute(operation):
    trace = []
    store = SyntheticStore(Target.from_environment(), trace.append)
    try:
        result = operation(store)
        failed = result.get("status") == "FAIL"
        payload = result if failed else {"result": result, "execution": trace}
    except EvidenceUnavailable:
        failed, payload = True, {"status": "FAIL", "error": "evidence_unavailable", "message": "evidence unavailable", "path": []}
    except IsolationError:
        failed, payload = True, {"status": "FAIL", "error": "isolation_check_failed", "path": []}
    finally:
        store.close()
    return CallToolResult(isError=failed, content=[TextContent(type="text", text=json.dumps(payload))], structuredContent=payload)


@mcp.tool(annotations=READ_ONLY)
def get_transaction(tx_id: SyntheticId) -> CallToolResult:
    """Read one synthetic transaction by ID from the isolated graph; two-second query deadline."""
    def operation(store):
        value = store.get_transaction(tx_id)
        return {"status": "PASS", "transaction": value} if value else {"status": "FAIL", "error": "unknown_id", "path": []}
    return execute(operation)


@mcp.tool(annotations=READ_ONLY)
def expand_outgoing(start_txid: SyntheticId, max_hops: HopBound) -> CallToolResult:
    """Read up to 40 directed paths, bounded to 1–6 hops; two-second query deadline."""
    return execute(lambda store: {"status": "PASS", **store.expand_outgoing(start_txid, max_hops)})


@mcp.tool(annotations=READ_ONLY)
def shortest_path(start_txid: SyntheticId, end_txid: SyntheticId, max_hops: HopBound) -> CallToolResult:
    """Read a bounded minimum-hop route between two synthetic IDs; two-second query deadline."""
    return execute(lambda store: Track1Tools(store).shortest_path(start_txid=start_txid, end_txid=end_txid, max_hops=max_hops))


if __name__ == "__main__":
    Target.from_environment()  # Fail startup without explicit local configuration.
    mcp.run(transport="stdio")
