"""LLM falso e roteirizado para testar o laço dos agentes sem chamar Gemini/Groq."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr


class ScriptedChatModel(BaseChatModel):
    """Devolve, em ordem, uma lista pré-definida de AIMessage.

    Cada invoke consome a próxima mensagem do roteiro. bind_tools é no-op (o
    roteiro já traz as tool_calls explícitas). Serve para exercitar
    app.agents._runtime.run_agent de forma determinística.
    """

    responses: list[BaseMessage]
    _index: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":  # noqa: D401
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self._index >= len(self.responses):
            # Segurança: se o laço pedir mais do que o roteiro previu, encerra.
            msg: BaseMessage = AIMessage(content="(roteiro esgotado)")
        else:
            msg = self.responses[self._index]
            self._index += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


def ai_tool_call(name: str, args: dict | None = None, call_id: str = "call_1") -> AIMessage:
    """AIMessage que pede a execução de uma ferramenta."""
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}
        ],
    )


def ai_final(text: str) -> AIMessage:
    """AIMessage de resposta final (sem tool call)."""
    return AIMessage(content=text)
