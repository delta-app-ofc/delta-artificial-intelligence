from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: int = Field(..., gt=0, description="ID do usuário autenticado (positivo).")
    session_id: str | None = None
    message: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    response: str
    agents_used: list[str] = Field(default_factory=list)
    session_id: str
    chart_data: dict | None = None


class SessionInfo(BaseModel):
    session_id: str
    title: str = ""
    preview: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionsResponse(BaseModel):
    sessions: list[SessionInfo]
    total: int = 0


class MessageItem(BaseModel):
    role: str
    content: str
    timestamp: datetime | None = None


class HistoryResponse(BaseModel):
    messages: list[MessageItem]


class SessionActionResponse(BaseModel):
    status: str
    session_id: str
