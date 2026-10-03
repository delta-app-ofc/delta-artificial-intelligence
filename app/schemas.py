from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: int
    session_id: str | None = None
    message: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    response: str
    agent_used: str
    session_id: str
    chart_data: dict | None = None
