from __future__ import annotations

from typing import Literal

from langgraph.graph import MessagesState
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


class GraphState(MessagesState, total=False):
    """`messages` (herdado) acumula a conversa entre as perguntas da mesma sessão."""

    user_id: int
    session_id: str
    question: str
    relevant_memory: list[str]
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
