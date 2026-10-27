from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str | None = Field(
        default=None,
        description="Id de uma sessão já devolvida pela API; omita para iniciar uma conversa nova.",
    )
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
    icon: str = "general"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_open: bool = False


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
