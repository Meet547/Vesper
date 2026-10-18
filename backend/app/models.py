from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    ok: bool
    mode: Literal["demo", "cloud"]
    database_connected: bool
    graph_name: str
    message: str
    environment: Literal["cloud", "demo", "isolated_demo"] = "demo"
    demo_identity: str | None = None
    process_instance_id: str | None = None


class InvestigationRequest(BaseModel):
    seed_tx_id: str = Field(min_length=1, max_length=50, description="Transaction ID from the graph")
    max_hops: int = Field(default=3, ge=1, le=4)
    memory_enabled: bool = True

    @field_validator("seed_tx_id")
    @classmethod
    def normalize_seed_id(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("Transaction ID must contain digits only")
        return value


class InvestigationResponse(BaseModel):
    case_id: str
    memory_id: str
    seed: dict[str, Any]
    traces: list[dict[str, Any]]
    skeptic: dict[str, Any]
    related_memories: list[dict[str, Any]]
    summary: str
    created_at: str
    mode: Literal["demo", "cloud"]


class TransactionSearchResponse(BaseModel):
    items: list[dict[str, Any]]
    count: int
    mode: Literal["demo", "cloud"]


class ErrorResponse(BaseModel):
    detail: str
