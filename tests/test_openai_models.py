"""Contratos OpenAI/Responses e fallback, sem acesso à rede."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from openai import AuthenticationError, RateLimitError

from app import config
from app.agents._runtime import run_agent
from app.agents.judge_specialist import SpecialistVerdict
from app.services import llms


class OpenAIModelsTests(unittest.TestCase):
    def setUp(self):
        self.settings = config.load_settings({
            "APP_ENV": "test", "OPENAI_API_KEY": "offline-openai",
            "LLM_FALLBACK_ENABLED": "false",
        })
        self.addCleanup(lambda: asyncio.run(llms.close_openai_clients()))

    def test_openai_defaults_validate_without_other_provider_keys(self):
        for role in ("openai", "fast", "specialist", "judge"):
            config.validate_llm_config(role, settings=self.settings)
        self.assertEqual(self.settings.openai_model, "gpt-6-luna")
        self.assertEqual(self.settings.openai_reasoning_effort, "medium")
        self.assertNotIn("offline-openai", repr(self.settings))
        for invalid in ("", "automatic", "extreme"):
            with self.assertRaises(config.ConfigurationError):
                config.validate_llm_config("openai", settings=replace(
                    self.settings, openai_reasoning_effort=invalid,
                ))

    def test_missing_key_fails_lazily(self):
        settings = config.load_settings({"APP_ENV": "test"})
        self.assertIsNone(settings.openai_api_key)
        with self.assertRaises(config.ConfigurationError), patch.object(llms, "ChatOpenAI") as constructor:
            llms._get_llm_openai(settings)
        constructor.assert_not_called()

    def test_concurrent_cache_and_configuration_snapshots(self):
        first = MagicMock()
        second = MagicMock()
        first.root_async_client.close = AsyncMock()
        second.root_async_client.close = AsyncMock()
        with patch.object(llms, "ChatOpenAI", side_effect=[first, second]) as constructor:
            with ThreadPoolExecutor(max_workers=8) as pool:
                clients = list(pool.map(lambda _: llms._get_llm_openai(self.settings), range(16)))
            self.assertTrue(all(m is first for m in clients))
            constructor.assert_called_once()
            changed = replace(self.settings, openai_reasoning_effort="low")
            self.assertIs(llms._get_llm_openai(changed), second)
            self.assertEqual(constructor.call_count, 2)
            self.assertEqual(constructor.call_args.kwargs["reasoning"], {"effort": "low"})
            asyncio.run(llms.close_openai_clients())
        first.root_client.close.assert_called_once()
        first.root_async_client.close.assert_awaited_once()
        second.root_client.close.assert_called_once()
        second.root_async_client.close.assert_awaited_once()
        self.assertFalse(llms._OPENAI_MODELS)

    def test_roles_share_openai_client_and_judge_uses_it(self):
        from app.agents import judge_specialist
        model = MagicMock()
        model.root_async_client.close = AsyncMock()
        with patch.object(llms, "get_settings", return_value=self.settings), \
             patch.object(llms, "ChatOpenAI", return_value=model):
            self.assertIs(llms._get_llm_rapido(), model)
            self.assertIs(llms._get_llm_especialista()._primary, model)
            self.assertIs(judge_specialist._get_model("openai", self.settings), model)

    def test_text_blocks_are_read_by_router_guard_and_synthesis(self):
        from langchain_core.messages import AIMessage
        from app.graph.router import classify
        from app.graph.synthesis import synthesize
        from app.guardrails.input import validate_input
        fake = MagicMock()
        texts = [
            json.dumps({"intent": "consumption", "complexity": "simple", "agents": ["consumption"]}),
            "CATEGORIA: APROVADO",
            "Resumo de teste.",
        ]
        fake.invoke.side_effect = [
            AIMessage(content=[{"type": "reasoning", "summary": []}, {"type": "text", "text": text}])
            for text in texts
        ]
        with patch.dict(llms.__dict__, {"llm_rapido": fake}):
            self.assertEqual(classify("Qual meu consumo?", {}).agents, ["consumption"])
            self.assertTrue(validate_input(1, "Qual meu consumo?")["ok"])
            self.assertEqual(synthesize("Resumo", [{"agent": "demo", "answer": "Dado"}])["response"], "Resumo de teste.")

    def test_memory_summary_embeds_only_response_text(self):
        from langchain_core.messages import AIMessage
        from app.memory import long_term
        fake = MagicMock()
        fake.invoke.return_value = AIMessage(content=[
            {"type": "reasoning", "summary": []},
            {"type": "text", "text": "Resumo de teste."},
        ])
        embeddings, qdrant = MagicMock(), MagicMock()
        embeddings.embed_query.return_value = [0.1]
        with patch.dict(llms.__dict__, {"llm_rapido": fake}), \
             patch.object(long_term, "get_settings", return_value=self.settings), \
             patch.object(long_term, "_embed_model", return_value=embeddings), \
             patch.object(long_term, "_qdrant", return_value=qdrant), \
             patch.object(long_term, "_ensure_collection"):
            long_term.save_summary(1, "offline-session", [{"role": "user", "content": "Teste"}])
        embeddings.embed_query.assert_called_once_with("Resumo de teste.")
        self.assertEqual(qdrant.upsert.call_args.kwargs["points"][0].payload["summary"], "Resumo de teste.")

    def test_authentication_error_does_not_fallback_or_leak(self):
        response = httpx.Response(401, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
        primary, fallback = MagicMock(), MagicMock()
        primary.invoke.side_effect = AuthenticationError("secret-offline", response=response, body={})
        model = llms._FallbackLLM(primary, fallback, primary_provider="openai")
        with self.assertRaises(llms.LLMProviderError) as raised:
            model.invoke(["question"])
        self.assertNotIn("secret-offline", str(raised.exception))
        fallback.invoke.assert_not_called()

    def test_rate_limit_falls_back_with_same_messages(self):
        response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
        primary, fallback = MagicMock(), MagicMock()
        primary.invoke.side_effect = RateLimitError("offline", response=response, body={})
        fallback.invoke.return_value = "safe"
        messages = [{"role": "user", "content": "question"}]
        self.assertEqual(llms._FallbackLLM(primary, fallback, primary_provider="openai").invoke(messages), "safe")
        self.assertIs(fallback.invoke.call_args.args[0], messages)

    def test_responses_tools_encrypted_reasoning_text_and_json(self):
        requests = []

        def handler(request):
            self.assertEqual(request.url.path, "/v1/responses")
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(body["model"], "gpt-6-luna")
            self.assertEqual(body["reasoning"]["effort"], "medium")
            self.assertFalse(body["store"])
            self.assertNotIn("temperature", body)
            self.assertNotIn("top_p", body)
            self.assertEqual(body["max_output_tokens"], self.settings.llm_max_output_tokens)
            output = []
            if body.get("tools") and not any(i.get("type") == "function_call_output" for i in body["input"]):
                output = [
                    {"type": "reasoning", "id": "rs_test", "summary": [], "encrypted_content": "opaque-test"},
                    {"type": "function_call", "id": "fc_test", "call_id": "call_test", "name": "demo_consumption",
                     "arguments": "{}", "status": "completed"},
                ]
            else:
                text = "Foram registrados 100 litros."
                if body.get("text", {}).get("format", {}).get("type") == "json_schema":
                    text = json.dumps({"decision": "approve", "severity": "no_error", "justification": "Dados compatíveis."})
                output = [{"type": "message", "id": "msg_test", "status": "completed", "role": "assistant",
                           "content": [{"type": "output_text", "text": text, "annotations": []}]}]
            return httpx.Response(200, json={
                "id": f"resp_test_{len(requests)}", "object": "response", "created_at": 1, "status": "completed",
                "model": "gpt-6-luna", "output": output,
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 2}},
            })

        sync = httpx.Client(transport=httpx.MockTransport(handler))
        asynchronous = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        real_class = ChatOpenAI

        def construct(**kwargs):
            return real_class(**kwargs, http_client=sync, http_async_client=asynchronous)

        @tool
        def demo_consumption() -> dict:
            """Retorna uma medição fictícia usada somente neste teste."""
            return {"total_liters": 100}

        with patch.object(llms, "ChatOpenAI", side_effect=construct):
            model = llms._get_llm_openai(self.settings)
            result = run_agent(llm=model, system_prompt="Use a ferramenta e responda.", tools=[demo_consumption], question="Qual o consumo?")
            self.assertEqual(result.response, "Foram registrados 100 litros.")
            self.assertEqual(result.tool_calls[0].output, {"total_liters": 100})
            self.assertTrue(any(i.get("type") == "reasoning" and i.get("encrypted_content") == "opaque-test"
                                for i in requests[1]["input"]))
            self.assertTrue(any(i.get("type") == "function_call_output" and i.get("call_id") == "call_test"
                                for i in requests[1]["input"]))
            verdict = model.with_structured_output(SpecialistVerdict, method="json_schema").invoke("Avalie.")
            self.assertEqual(verdict.decision, "approve")
            self.assertEqual(len(requests), 3)
            self.assertIsInstance(model.invoke("Texto").text, str)
            from langchain.agents import create_agent
            agent = create_agent(model=model, tools=[demo_consumption])
            state = agent.invoke({"messages": [{"role": "user", "content": "Qual o consumo?"}]})
            self.assertEqual(state["messages"][-1].text, "Foram registrados 100 litros.")


if __name__ == "__main__":
    unittest.main()
