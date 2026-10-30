"""Valida cache, concorrência e fechamento sem acessar provedores."""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from app import config
from app.agents import judge_specialist as judge
from app.services import rag


def google_client():
    return SimpleNamespace(close=MagicMock(), aio=SimpleNamespace(aclose=AsyncMock()))


class ClientReuseTests(unittest.TestCase):
    def setUp(self):
        self.settings = config.load_settings({
            "APP_ENV": "test", "LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "offline-google",
            "GROQ_API_KEY": "offline-groq", "QDRANT_URL": "https://offline.invalid",
        })
        self.embedding = SimpleNamespace(client=google_client())
        self.qdrant = SimpleNamespace(close=MagicMock())
        self.google = SimpleNamespace(client=google_client())
        self.groq = SimpleNamespace(
            client=SimpleNamespace(_client=SimpleNamespace(close=MagicMock())),
            async_client=SimpleNamespace(_client=SimpleNamespace(close=AsyncMock())),
        )
        patches = [
            patch.object(rag, "get_settings", return_value=self.settings),
            patch.object(rag, "GoogleGenerativeAIEmbeddings", return_value=self.embedding),
            patch.object(rag, "QdrantClient", return_value=self.qdrant),
            patch("langchain_google_genai.ChatGoogleGenerativeAI", return_value=self.google),
            patch("langchain_groq.ChatGroq", return_value=self.groq),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.addCleanup(self.close_all)

    def close_all(self):
        asyncio.run(rag.close_rag_clients())
        asyncio.run(judge.close_judge_clients())

    def test_reuses_clients_under_simultaneous_first_access(self):
        getters = [
            rag.create_embeddings, rag.create_qdrant,
            lambda: judge._get_model("google", self.settings),
            lambda: judge._get_model("groq", self.settings),
        ]
        for getter, constructor in zip(getters, self.mocks[1:]):
            expected = constructor.return_value

            def slow_constructor(*args, **kwargs):
                time.sleep(0.01)
                return expected

            constructor.side_effect = slow_constructor
            with ThreadPoolExecutor(max_workers=8) as pool:
                clients = list(pool.map(lambda _: getter(), range(16)))
            self.assertTrue(all(c is clients[0] for c in clients))
            constructor.assert_called_once()

    def test_close_is_lazy_idempotent_and_closes_both_transports(self):
        self.close_all()
        for constructor in self.mocks[1:]:
            constructor.assert_not_called()
        rag.create_embeddings(); rag.create_qdrant()
        judge._get_model("google", self.settings)
        judge._get_model("groq", self.settings)
        self.close_all(); self.close_all()
        self.embedding.client.close.assert_called_once()
        self.embedding.client.aio.aclose.assert_awaited_once()
        self.qdrant.close.assert_called_once()
        self.google.client.close.assert_called_once()
        self.google.client.aio.aclose.assert_awaited_once()
        self.groq.client._client.close.assert_called_once()
        self.groq.async_client._client.close.assert_awaited_once()

    def test_construction_failure_does_not_poison_cache(self):
        self.mocks[1].side_effect = [RuntimeError("offline"), self.embedding]
        with self.assertRaises(RuntimeError):
            rag.create_embeddings()
        self.assertIs(rag.create_embeddings(), self.embedding)
        self.assertEqual(self.mocks[1].call_count, 2)

    def test_close_attempts_remaining_resources_after_failure(self):
        rag.create_qdrant(); rag.create_embeddings()
        self.qdrant.close.side_effect = RuntimeError("offline")
        with self.assertRaises(RuntimeError):
            asyncio.run(rag.close_rag_clients())
        self.embedding.client.close.assert_called_once()
        self.embedding.client.aio.aclose.assert_awaited_once()
        self.assertEqual(rag._CLIENTS, {})
        asyncio.run(rag.close_rag_clients())

    def test_reload_after_close_uses_new_configuration(self):
        judge._get_model("google", self.settings)
        asyncio.run(judge.close_judge_clients())
        changed = replace(self.settings, judge_specialist_model="another-test-model")
        judge._get_model("google", changed)
        self.assertEqual(self.mocks[3].call_args.kwargs["model"], "another-test-model")
        self.assertEqual(self.mocks[3].call_count, 2)

    def test_fallback_preserves_parameters_and_each_messages_list(self):
        verdict = {"decision": "approve", "severity": "no_error", "justification": "offline"}
        primary = MagicMock()
        primary.invoke.side_effect = httpx.ConnectError("offline")
        secondary = MagicMock()
        secondary.invoke.return_value = verdict
        self.google.with_structured_output = MagicMock(return_value=primary)
        self.groq.with_structured_output = MagicMock(return_value=secondary)
        agent = judge.SpecialistJudgeAgent()
        for question in ("first", "second"):
            messages = [("human", question)]
            assessment = {"revision_count": 0}
            self.assertEqual(agent._evaluate(messages, self.settings, assessment), verdict)
            self.assertEqual(secondary.invoke.call_args.args[0], messages)
            self.assertEqual(assessment["provider"], "groq")
        self.mocks[3].assert_called_once(); self.mocks[4].assert_called_once()
        self.assertEqual(self.mocks[3].call_args.kwargs["max_retries"], self.settings.llm_max_retries + 1)
        self.assertEqual(self.mocks[4].call_args.kwargs["max_retries"], self.settings.llm_max_retries)
        self.assertEqual(self.mocks[3].call_args.kwargs["temperature"], config.JUDGE_SPECIALIST_TEMPERATURE)

    def test_rag_tool_keeps_clients_open_and_preserves_output(self):
        from app.tools import rag as tool_module
        document = SimpleNamespace()
        result = {"headings": ["Test"], "start_line": 1, "end_line": 2, "text": "evidence"}
        settings = replace(self.settings, rag_document_path="offline.md")
        with patch.object(tool_module, "get_settings", return_value=settings), \
             patch.object(tool_module, "load_document", return_value=document), \
             patch.object(tool_module, "ensure_document_indexed"), \
             patch.object(tool_module, "search_document", side_effect=[
                 [result], RuntimeError("offline"), [result],
             ]):
            for status in ("ok", "unavailable", "ok"):
                output = tool_module.search_knowledge_base.invoke({"question": "offline"})
                self.assertEqual(output["status"], status)
                if status == "ok":
                    self.assertEqual(output["chunks"][0]["text"], "evidence")
        self.qdrant.close.assert_not_called()
        self.mocks[1].assert_called_once(); self.mocks[2].assert_called_once()

    def test_lifespan_closes_judge_even_when_rag_close_fails(self):
        from app.main import app, lifespan
        async def run():
            async with lifespan(app):
                pass
        with patch.object(rag, "close_rag_clients", new=AsyncMock(side_effect=RuntimeError("offline"))) as close_rag, \
             patch.object(judge, "close_judge_clients", new=AsyncMock()) as close_judge:
            with self.assertRaises(RuntimeError):
                asyncio.run(run())
            close_rag.assert_awaited_once(); close_judge.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
