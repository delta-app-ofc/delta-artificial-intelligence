from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# O app converte cada nome em uma imagem; um nome desconhecido deve ser exibido como "general".
ICON_NAMES = (
    "routine",
    "habits",
    "summary",
    "report",
    "savings",
    "leak",
    "forecast",
    "consumption",
    "tips",
    "general",
)


class ErrorResponse(BaseModel):
    detail: str = Field(..., description="Mensagem do erro, em português.")


# Respostas de erro documentadas no Swagger, iguais em todas as rotas autenticadas.
AUTH_ERRORS = {
    401: {
        "model": ErrorResponse,
        "description": "Token Bearer ausente, inválido ou expirado.",
    },
    503: {
        "model": ErrorResponse,
        "description": "Autenticação não configurada no servidor (JWT_SECRET ausente ou curto).",
    },
}
SESSION_NOT_FOUND = {
    404: {
        "model": ErrorResponse,
        "description": "Sessão inexistente, excluída ou de outro usuário (a resposta é a mesma nos três casos).",
    },
}


class ChatRequest(BaseModel):
    session_id: str | None = Field(
        default=None,
        description=(
            "Id de uma sessão já devolvida pela API, para continuar a conversa. "
            "Omita para iniciar uma conversa nova; ids que o servidor não criou retornam 404."
        ),
    )
    message: str = Field(
        ..., min_length=1, max_length=2000, description="Pergunta do usuário (1 a 2000 caracteres)."
    )


class ChatResponse(BaseModel):
    response: str = Field(..., description="Resposta do assistente.")
    session_id: str = Field(
        ..., description="Id da sessão, criado pelo servidor; reenvie-o para continuar a conversa."
    )
    chart_data: dict | None = Field(
        default=None, description="Dados de gráfico (Plotly) quando a resposta traz um; senão nulo."
    )


class SessionInfo(BaseModel):
    session_id: str = Field(..., description="Id da sessão; use-o para abrir a conversa.")
    title: str = Field(
        default="",
        description=(
            "Título curto (até 40 caracteres) gerado pela IA na primeira troca de mensagens. "
            "Sem ele, vem o início da primeira pergunta."
        ),
    )
    preview: str = Field(
        default="",
        description=(
            "Frase-resumo (até 80 caracteres) gerada pela IA, exibida abaixo do título. "
            "Sem ela, vem o fim da última mensagem."
        ),
    )
    icon: str = Field(
        default="general",
        description=(
            "Nome do ícone do assunto, escolhido pela IA entre: "
            + ", ".join(ICON_NAMES)
            + ". Nome desconhecido deve ser exibido como general."
        ),
    )
    created_at: datetime | None = Field(default=None, description="Início da sessão (UTC).")
    updated_at: datetime | None = Field(
        default=None, description="Última atividade (UTC); define a ordem da lista."
    )
    is_open: bool = Field(
        default=False, description="Verdadeiro se a sessão aceita novas mensagens."
    )


class SessionsResponse(BaseModel):
    sessions: list[SessionInfo] = Field(
        ..., description="Sessões do usuário, da mais recente para a mais antiga."
    )
    total: int = Field(
        default=0,
        description="Total de sessões do usuário com mensagens; use com offset no ver todos.",
    )


class MessageItem(BaseModel):
    role: str = Field(..., description="Remetente: user (usuário) ou bot (assistente).")
    content: str = Field(..., description="Texto da mensagem.")
    timestamp: datetime | None = Field(default=None, description="Horário de envio (UTC).")


class HistoryResponse(BaseModel):
    messages: list[MessageItem] = Field(
        ..., description="Mensagens da sessão, em ordem cronológica."
    )


class SessionActionResponse(BaseModel):
    status: str = Field(..., description="Resultado da ação; ok quando concluída.")
    session_id: str = Field(..., description="Id da sessão afetada.")
