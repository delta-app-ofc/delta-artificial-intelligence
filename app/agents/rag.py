"""Agente de consulta da documentação oficial, com tool de busca vetorial."""

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage

from app.agents._runtime import AgentResult, ToolCall, build_revision_messages
from app.config import ConfigurationError
from app.observability.diagnostics import current_trace
from app.services.prompts import RAG_PROMPT_COMPLETO
from app.tools.rag import search_knowledge_base


class RagAgent:
    def __init__(self, user_id: int, llm: Any = None) -> None:
        self.user_id = user_id

        if llm is None:
            from app.services.llms import llm_rapido

            llm = llm_rapido

        if llm is None:
            raise ConfigurationError("Configure o modelo rápido Groq para executar o agente RAG.")

        self.agent = create_agent(
            model=llm,
            tools=[search_knowledge_base],
            system_prompt=RAG_PROMPT_COMPLETO,
        )

    def run(
        self,
        question: str,
        *,
        revision_feedback: str | None = None,
        revision_context: dict | None = None,
    ) -> AgentResult:
        previous_result = (revision_context or {}).get("agent_result") or {}
        messages = build_revision_messages(revision_feedback, revision_context)
        messages.append({"role": "user", "content": question})

        state = self.agent.invoke(
            {"messages": messages},
            config={"recursion_limit": 12},
        )
        calls = {}
        result = AgentResult(response=state["messages"][-1].text)

        for message in state["messages"]:
            if isinstance(message, AIMessage):
                for call in message.tool_calls:
                    calls[call["id"]] = call

            elif isinstance(message, ToolMessage) and message.name == "search_knowledge_base":
                try:
                    output = json.loads(message.content)
                except json.JSONDecodeError:
                    output = {"status": "unavailable", "chunks": []}

                call = calls.get(message.tool_call_id)
                if call is None:
                    continue
                result.tool_calls.append(ToolCall(call["name"], call["args"], output))
                if trace := current_trace():
                    trace.tool("rag", call["name"], call["args"], output)

                if output.get("status") == "ok":
                    result.sources.extend(chunk["citation"] for chunk in output["chunks"])


        result.sources = list(dict.fromkeys(previous_result.get("sources", []) + result.sources))
        if not result.response.strip() and previous_result.get("answer"):
            result.response = previous_result["answer"]

        if not result.sources or not result.response.strip():
            unavailable = any(
                isinstance(call.output, dict) and call.output.get("status") == "unavailable"
                for call in result.tool_calls
            )
            result.response = (
                "Não consegui consultar a base documental do Delta neste momento."
                if unavailable
                else (
                    "Não encontrei informação suficiente na base documental "
                    "do Delta para responder."
                )
            )
            return result

        if "Fontes consultadas:" not in result.response:
            result.response += "\n\nFontes consultadas:\n" + "\n".join(
                f"- {source}" for source in result.sources
            )

        return result
