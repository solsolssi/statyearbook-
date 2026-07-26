from __future__ import annotations

from pydantic import BaseModel, Field


class JobOperationMetrics(BaseModel):
    total: int = 0
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    failure_rate_percent: float = 0
    average_duration_seconds: float = 0


class StageOperationMetrics(BaseModel):
    stage: str
    attempts: int = 0
    completed: int = 0
    failed: int = 0
    failure_rate_percent: float = 0
    average_duration_seconds: float = 0


class LLMOperationMetrics(BaseModel):
    provider: str
    model: str
    request_kind: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0


class OperationsOverview(BaseModel):
    generated_at: str
    window_days: int
    report_id: int | None = None
    jobs: JobOperationMetrics
    stages: list[StageOperationMetrics] = Field(default_factory=list)
    llm_usage: list[LLMOperationMetrics] = Field(default_factory=list)
    llm_total_tokens: int = 0
    llm_estimated_cost_usd: float = 0
