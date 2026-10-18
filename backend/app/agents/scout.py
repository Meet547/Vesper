from typing import Any

from backend.app.tools.investigation_tools import InvestigationTools


class ScoutAgent:
    """Validates the investigation seed against the graph."""

    def __init__(self, tools: InvestigationTools):
        self.tools = tools

    def find_seed(self, tx_id: str, shared_context=None) -> dict[str, Any] | None:
        if shared_context is not None:
            shared_context.record_read("Scout")
        return self.tools.get_transaction(tx_id)
