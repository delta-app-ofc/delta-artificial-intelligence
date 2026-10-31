"""Testa a leitura das fontes RAG sem conectar ao provedor vetorial."""

import json
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from app.agents.rag import RagAgent


class FakeRagGraph:
    def __init__(self, messages):
        self.messages = messages
        self.invocation = None

    def invoke(self, payload, *, config):
        self.invocation = (payload, config)
        return {"messages": self.messages}


class RagAgentSmokeTest(unittest.TestCase):
    def test_run_collects_citations_from_search_tool(self):
        citation = "DADOS/SQL/modelagem.md#tarifas"
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge_base",
                        "args": {"query": "tarifas"},
                        "id": "search-1",
                        "type": "tool_call",
                    }
                ],
            ),
            ToolMessage(
                content=json.dumps(
                    {"status": "ok", "chunks": [{"citation": citation}]}
                ),
                tool_call_id="search-1",
                name="search_knowledge_base",
            ),
            AIMessage(content="A tarifa depende da região."),
        ]
        graph = FakeRagGraph(messages)

        with patch("app.agents.rag.create_agent", return_value=graph) as create_agent:
            agent = RagAgent(42, llm=object())
            result = agent.run("Como funciona a tarifa?")

        self.assertEqual(result.response, "A tarifa depende da região.\n\nFontes consultadas:\n- " + citation)
        self.assertEqual(result.sources, [citation])
        self.assertEqual(result.tool_calls[0].name, "search_knowledge_base")
        self.assertEqual(result.tool_calls[0].output["status"], "ok")
        self.assertEqual(graph.invocation[0]["messages"][-1], {
            "role": "user", "content": "Como funciona a tarifa?"
        })
        self.assertEqual(graph.invocation[1], {"recursion_limit": 12})
        create_agent.assert_called_once()


if __name__ == "__main__":
    unittest.main()
