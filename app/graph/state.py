from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field


class AgentOutput(BaseModel):
    agent: str
    status: Literal["success", "error"]
    answer: str
    data: dict = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    chart_data: dict | None = None
    tool_calls: list[dict] = Field(default_factory=list)


class _GraphStateRequired(TypedDict):
    user_id: int
    session_id: str
    question: str


class GraphState(_GraphStateRequired, total=False):
    recent_messages: list[dict]
    relevant_memory: list[str]
    intent: str
    complexity: str
    selected_agents: list[str]
    agent_results: list[dict]
    warnings: list[str]
    response: str
    agent_used: str
    chart_data: dict | None
    candidate: str
    previous_candidate: str | None
    previous_agent_results: list[dict]
    revision_feedback: str
    revision_count: int
    judge_history: list[dict]
    judge_action: Literal["approve", "correct", "block"] | str
    composition_status: Literal["ready", "no_agents", "no_success"] | str
