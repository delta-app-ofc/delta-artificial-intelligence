from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool

DEFAULT_MAX_ITERATIONS = 6


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    output: Any


@dataclass
class AgentResult:
    response: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    def readable_log(self) -> str:
        if not self.tool_calls:
            return "(nenhuma ferramenta foi chamada)"
        return "\n".join(
            f"{i}. {tc.name}({tc.input}) -> {tc.output}"
            for i, tc in enumerate(self.tool_calls, 1)
        )


def _message_text(msg: BaseMessage) -> str:
    text = getattr(msg, "text", None)
    if isinstance(text, str) and text:
        return text
    if callable(text) and not isinstance(text, str):
        try:
            value = text()
            if isinstance(value, str) and value:
                return value
        except Exception:
            pass
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts)
    return str(content)


def _run_tool(tool: BaseTool | None, name: str, args: dict) -> Any:
    if tool is None:
        return {"status": "error", "message": f"ferramenta desconhecida: {name}"}
    try:
        return tool.invoke(args)
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def run_agent(
    *,
    llm,
    system_prompt: str,
    tools: list[BaseTool],
    question: str,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> AgentResult:
    tools_by_name = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=question),
    ]
    log: list[ToolCall] = []

    for _ in range(max_iterations):
        ai: AIMessage = llm_with_tools.invoke(messages)
        messages.append(ai)

        calls = getattr(ai, "tool_calls", None) or []
        if not calls:
            return AgentResult(response=_message_text(ai), tool_calls=log)

        for call in calls:
            name = call["name"]
            args = call.get("args", {}) or {}
            output = _run_tool(tools_by_name.get(name), name, args)

            log.append(ToolCall(name=name, input=args, output=output))
            messages.append(
                ToolMessage(
                    content=json.dumps(output, default=str, ensure_ascii=False),
                    tool_call_id=call.get("id") or name,
                )
            )

    # Passou do limite de iterações: pede resposta final sem mais tools.
    final = llm.invoke(
        messages
        + [HumanMessage(content="Responda agora com o que as ferramentas já retornaram.")]
    )
    return AgentResult(response=_message_text(final), tool_calls=log)
