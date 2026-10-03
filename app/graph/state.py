from __future__ import annotations

from typing import TypedDict


class GraphState(TypedDict):
    user_id: int
    session_id: str
    question: str
    response: str
    agent_used: str
    chart_data: dict | None
