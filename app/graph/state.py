from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel


class AgentOutput(BaseModel):
    agent: str
    status: Literal["success", "error"]
    answer: str
    data: dict = {}
    sources: list[str] = []
    confidence: float | None = None
    warnings: list[str] = []
    chart_data: dict | None = None


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
