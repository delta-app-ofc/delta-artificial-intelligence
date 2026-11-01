"""Agente de consulta da documentação oficial, com tool de busca vetorial."""

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage

from app.agents._runtime import AgentResult, ToolCall, build_revision_messages
from app.config import ConfigurationError
from app.observability.diagnostics import current_trace
from app.services.prompts import RAG_PROMPT_COMPLETO, profile_block
from app.tools.rag import search_knowledge_base
from app.tools.external_knowledge import search_external_knowledge


class RagAgent:
    def __init__(self, user_id: int, llm: Any = None, access_kind: str | None = None) -> None:
        """Cria o agente RAG com o modelo rápido; levanta ConfigurationError se não houver modelo
        configurado.
        """
        self.user_id = user_id
        self.access_kind = access_kind

        if llm is None:
            from app.services.llms import llm_rapido

            llm = llm_rapido

        if llm is None:
            raise ConfigurationError("Configure o modelo de linguagem selecionado para executar o agente RAG.")

        self.agent = create_agent(
            model=llm,
            tools=[search_knowledge_base, search_external_knowledge],
            system_prompt=RAG_PROMPT_COMPLETO + profile_block(access_kind),
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

            elif isinstance(message, ToolMessage) and message.name in {
                "search_knowledge_base", "search_external_knowledge",
            }:
                try:
                    output = json.loads(message.content)
                    if not isinstance(output, dict):
                        raise ValueError("Resultado RAG inválido.")
                except (json.JSONDecodeError, ValueError, TypeError):
                    output = {"status": "unavailable", "chunks": []}

                call = calls.get(message.tool_call_id)
                if call is None or call["name"] != message.name:
                    continue
                result.tool_calls.append(ToolCall(call["name"], call["args"], output))
                if trace := current_trace():
                    trace.tool("rag", call["name"], call["args"], output)

                if output.get("status") == "ok":
                    result.sources.extend(
                        chunk["citation"] for chunk in output.get("chunks", [])
                        if isinstance(chunk, dict) and isinstance(chunk.get("citation"), str)
                        and chunk["citation"].strip()
                    )


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

        # A lista final é construída das evidências; o modelo não pode substituí-la.
        result.response = result.response.partition("Fontes consultadas:")[0].rstrip()
        result.response += "\n\nFontes consultadas:\n" + "\n".join(
            f"- {source}" for source in result.sources
        )

        return result
