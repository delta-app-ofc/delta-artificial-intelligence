from __future__ import annotations

from typing import Literal

from langgraph.graph import MessagesState
from pydantic import BaseModel, Field


class AgentOutput(BaseModel):
    agent: str
    status: Literal["success", "error", "skipped"]
    answer: str
    data: dict = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    confidence: float | None = None
    warnings: list[str] = Field(default_factory=list)
    chart_data: dict | None = None
    tool_calls: list[dict] = Field(default_factory=list)


class GraphState(MessagesState, total=False):
    """`messages` (herdado) acumula a conversa entre as perguntas da mesma sessão."""

    user_id: int
    access_kind: str
    unavailable_agents: list[str]
    session_id: str
    question: str
    relevant_memory: list[str]
    recent_messages: list[dict]
    _history: list[dict] | None
    _persist_session: bool
    candidate: str
    previous_candidate: str | None
    previous_agent_results: list[dict]
    revision_feedback: str
    revision_count: int
    judge_history: list[dict]
    judge_action: Literal["approve", "correct", "block"] | str
    composition_status: Literal["ready", "no_agents", "no_success", "bypass"] | str
    intent: str
    complexity: str
    selected_agents: list[str]
    agent_results: list[dict]
    warnings: list[str]
    response: str
    agent_used: str
    chart_data: dict | None
    pii_map: dict
    _blocked: bool
