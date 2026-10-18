"""Bounded local/cloud Ollama tool-calling analyst; no write-capable tools are exposed."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from backend.app.tools.investigation_tools import InvestigationTools

logger = logging.getLogger(__name__)

# Transient HTTP statuses worth a single bounded retry (rate limiting / upstream hiccups).
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 1
_RETRY_BACKOFF_SECONDS = 1.0

TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "get_transaction", "description": "Read one transaction by digit-only ID.",
     "parameters": {"type": "object", "properties": {"tx_id": {"type": "string"}}, "required": ["tx_id"]}}},
    {"type": "function", "function": {"name": "get_neighbors", "description": "Read incoming and outgoing directed neighbors.",
     "parameters": {"type": "object", "properties": {"tx_id": {"type": "string"}}, "required": ["tx_id"]}}},
    {"type": "function", "function": {"name": "trace_paths", "description": "Read bounded directed transaction paths (1-4 hops).",
     "parameters": {"type": "object", "properties": {"tx_id": {"type": "string"}, "max_hops": {"type": "integer", "minimum": 1, "maximum": 4}}, "required": ["tx_id"]}}},
    {"type": "function", "function": {"name": "find_related_memories", "description": "Read prior memories by transaction ID overlap.",
     "parameters": {"type": "object", "properties": {"transaction_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 100}}, "required": ["transaction_ids"]}}},
]


class LocalModelAgent:
    """Uses an Ollama-compatible chat tool-calling endpoint (local daemon or Ollama Cloud).

    The same fixed read-only allowlist is enforced for both providers. Authentication
    is optional: when an ``api_key`` is supplied it is sent as a Bearer token and is
    never logged, returned, or echoed into observations.
    """

    def __init__(self, tools: InvestigationTools, base_url: str, model: str, timeout: float = 90.0,
                 client: httpx.Client | None = None, api_key: str | None = None):
        self.tools, self.base_url, self.model, self.timeout = tools, base_url.rstrip("/"), model, timeout
        self.api_key = api_key or ""
        self.client = client or httpx.Client(timeout=timeout)

    def analyze(self, seed_id: str, max_hops: int, evidence: dict[str, Any], shared_context=None) -> dict[str, Any]:
        if shared_context is not None:
            shared_context.record_read("Analyst")
            evidence = {**evidence, "shared_investigation_context": shared_context.public_snapshot()}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": (
                "You are the Analyst in an evidence-first Bitcoin transaction investigation. "
                "Use only provided graph evidence and the available read-only tools. Never infer ownership, intent, "
                "criminal conduct, or facts absent from the graph. Treat labels as dataset labels, not proof. "
                "A deterministic evidence ledger is provided in evidence_payload.compact_ledger: its counts are "
                "computed in Python over the full verified evidence. Use ledger counts verbatim together with their "
                "counting scope (unique_transactions vs path_occurrences); never recount transactions from paths "
                "and never adjust deterministic values. Bounded searches prove nothing beyond their hop depth. "
                "You may call tools only to inspect evidence; do not attempt writes. Return concise observations and caveats."
            )},
            {"role": "user", "content": json.dumps({"seed_tx_id": seed_id, "max_hops": max_hops,
                                                     "evidence_payload": evidence})},
        ]
        events: list[dict[str, Any]] = []
        calls = 0
        try:
            for _ in range(3):
                payload = {"model": self.model, "messages": messages, "stream": False,
                           "options": {"temperature": 0.1}}
                if calls == 0:
                    payload["tools"] = TOOL_DEFINITIONS
                response = self._post(payload)
                response.raise_for_status()
                message = response.json().get("message", {})
                messages.append(message)
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    content = self._extract_content(message)
                    # Some locally packaged models emit a JSON tool intent in content
                    # instead of Ollama's native tool_calls field. Treat it as untrusted
                    # input and pass it through the exact same read-only allowlist.
                    try:
                        intent = json.loads(content)
                    except (json.JSONDecodeError, TypeError):
                        intent = None
                    if isinstance(intent, dict):
                        name = intent.get("name") or intent.get("tool")
                        args = intent.get("arguments") or intent.get("parameters") or {}
                        if name in {item["function"]["name"] for item in TOOL_DEFINITIONS} and isinstance(args, dict):
                            if calls >= 8:
                                break
                            result = self._invoke(name, args)
                            calls += 1
                            events.append({"agent": "Analyst", "type": "tool_call", "tool": name,
                                           "status": "completed", "read_only": True})
                            messages.append({"role": "tool", "content": json.dumps(result, default=str), "name": name})
                            messages.append({"role": "user", "content": "You have completed the read-only check. Do not request or invent more tool calls. Provide a concise plain-text observation based only on the evidence and returned tool data, with an explicit caveat that transaction links do not prove shared ownership or intent."})
                            continue
                        # Never surface structured tool-like model output as a report.
                        if any(key in intent for key in ("name", "tool", "arguments", "parameters")):
                            return {"status": "no_observation", "observations": "", "events": events, "model": self.model}
                    return {"status": "complete" if content else "no_observation", "observations": content,
                            "events": events, "model": self.model}
                if calls >= 1:
                    return {"status": "no_observation", "observations": "", "events": events, "model": self.model}
                for tool_call in tool_calls:
                    if calls >= 1:
                        break
                    function = tool_call.get("function") or {}
                    name, args = function.get("name"), function.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args)
                    result = self._invoke(name, args)
                    calls += 1
                    events.append({"agent": "Analyst", "type": "tool_call", "tool": name,
                                   "status": "completed", "read_only": True})
                    messages.append({"role": "tool", "content": json.dumps(result, default=str), "name": name})
            return {"status": "no_observation", "observations": "", "events": events, "model": self.model}
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            logger.info("Model analysis unavailable (%s)", type(exc).__name__)
            return {"status": "unavailable", "observations": "", "events": events, "model": self.model,
                    "message": "Ollama analysis is unavailable; deterministic graph checks remain authoritative.",
                    "warnings": [f"Model call failed ({type(exc).__name__}); the report contains only deterministic evidence."]}

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        """POST to /api/chat with the optional Bearer token and a single bounded retry."""
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        for attempt in range(_MAX_RETRIES + 1):
            response = self.client.post(f"{self.base_url}/api/chat", json=payload, headers=headers)
            status = getattr(response, "status_code", None)
            if status in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_SECONDS)
                continue
            return response
        return response  # pragma: no cover - loop always returns

    @staticmethod
    def _extract_content(message: dict[str, Any]) -> str:
        """Return only the user-facing text, never provider 'thinking' metadata."""
        message = {k: v for k, v in message.items() if k != "thinking"}
        return str(message.get("content") or "").strip()

    def _invoke(self, name: str | None, args: dict[str, Any]) -> Any:
        if name == "get_transaction":
            return self.tools.get_transaction(self._tx_id(args.get("tx_id")))
        if name == "get_neighbors":
            return self.tools.get_neighbors(self._tx_id(args.get("tx_id")))
        if name == "trace_paths":
            hops = args.get("max_hops", 3)
            if isinstance(hops, bool) or not isinstance(hops, int):
                raise ValueError("max_hops must be an integer")
            return self.tools.trace_paths(self._tx_id(args.get("tx_id")), max(1, min(hops, 4)))
        if name == "find_related_memories":
            ids = args.get("transaction_ids")
            if not isinstance(ids, list) or len(ids) > 100:
                raise ValueError("transaction_ids must be a bounded list")
            return self.tools.find_related_memories([self._tx_id(item) for item in ids])
        raise ValueError("Tool is not in the read-only allowlist")

    @staticmethod
    def _tx_id(value: Any) -> str:
        tx_id = str(value or "")
        if not tx_id.isdigit() or len(tx_id) > 50:
            raise ValueError("Transaction IDs must contain digits only")
        return tx_id
