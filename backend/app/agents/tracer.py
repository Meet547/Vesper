from typing import Any

from backend.app.tools.investigation_tools import InvestigationTools


class TracerAgent:
    """Returns bounded upstream and downstream paths from the graph."""

    def __init__(self, tools: InvestigationTools):
        self.tools = tools

    def trace(self, tx_id: str, max_hops: int, shared_context=None,
              direction: str | None = None) -> list[dict[str, Any]]:
        if shared_context is not None:
            shared_context.record_read("Tracer")
            max_hops = min(max_hops, shared_context.public_snapshot()["graph_scope"]["hop_depth"])
        return self.tools.trace_paths(tx_id, max_hops=max_hops, direction=direction)
