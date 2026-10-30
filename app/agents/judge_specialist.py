"""Segundo parecer com Gemini e fallback Groq para avaliações incertas do Jev."""

from __future__ import annotations

import json
import logging
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.judge import JudgeInput, JudgeResult, SAFE_RESPONSE
from app.config import (
    JUDGE_SPECIALIST_PROMPT,
    JUDGE_SPECIALIST_TEMPERATURE,
    JUIZ_FACTS_SUPPORTED_CRITERIA,
    JUIZ_RELEVANT_CRITERIA,
    JUIZ_SEVERITY_CRITERIA,
    Settings,
    get_judge_config,
    validate_llm_config,
)
from app.observability.diagnostics import ModelDiagnostics, component, current_trace, fallback_call

logger = logging.getLogger(__name__)


_MODELS: dict[str, Any] = {}
_MODELS_LOCK = Lock()


def _get_model(provider: Literal["google", "groq", "openai"], config: Settings) -> Any:
    """Reutiliza o cliente de cada provedor; a configuração muda após fechamento."""
    if provider == "openai":
        from app.services.llms import _get_llm_openai

        return _get_llm_openai(config)
    with _MODELS_LOCK:
        if provider not in _MODELS:
            if provider == "google":
                from langchain_google_genai import ChatGoogleGenerativeAI

                model = ChatGoogleGenerativeAI(
                    model=config.judge_specialist_model,
                    api_key=config.gemini_api_key,
                    temperature=JUDGE_SPECIALIST_TEMPERATURE,
                    timeout=config.llm_timeout_seconds,
                    max_retries=config.llm_max_retries + 1,
                    max_output_tokens=config.llm_max_output_tokens,
                    callbacks=[ModelDiagnostics("google", config.judge_specialist_model)],
                )
            else:
                from langchain_groq import ChatGroq

                model = ChatGroq(
                    model=config.groq_specialist_model,
                    api_key=config.groq_api_key,
                    temperature=JUDGE_SPECIALIST_TEMPERATURE,
                    timeout=config.llm_timeout_seconds,
                    max_retries=config.llm_max_retries,
                    max_tokens=config.llm_max_output_tokens,
                    callbacks=[ModelDiagnostics("groq", config.groq_specialist_model)],
                )
            _MODELS[provider] = model
        return _MODELS[provider]


async def close_judge_clients() -> None:
    """Fecha os transportes sync/async inicializados e permite nova configuração."""
    with _MODELS_LOCK:
        models = dict(_MODELS)
        _MODELS.clear()

    close_error = None
    for provider, model in models.items():
        try:
            if provider == "google":
                try:
                    model.client.close()
                finally:
                    await model.client.aio.aclose()
            else:
                try:
                    model.client._client.close()
                finally:
                    await model.async_client._client.close()
        except Exception as error:
            if close_error is None:
                close_error = error
    if close_error is not None:
        raise RuntimeError("Falha ao fechar clientes do juiz especialista.") from close_error


class SpecialistVerdict(BaseModel):
    """Parecer tipado; o modelo avalia sem produzir uma nova candidata."""

    decision: Literal["approve", "correct", "reject"]
    severity: Literal["no_error", "correctable_error", "critical_error"]
    justification: str = Field(min_length=1)


class SpecialistJudgeAgent:
    """Julga a candidata e, quando solicitado, sua única revisão."""

    def __init__(self, llm: Any | None = None) -> None:
        self.llm = llm

    def run(
        self,
        judge_input: JudgeInput,
        *,
        jev_result: JudgeResult,
        revision_count: int = 0,
        previous_result: JudgeResult | None = None,
    ) -> JudgeResult:
        assessment = {
            "provider": "unknown", "reviewer": "specialist",
            "jev_result": jev_result.model_dump(mode="json"),
            "revision_count": revision_count,
        }
        try:
            config = get_judge_config()
            provider = "openai" if config.llm_provider == "openai" else "google"
            assessment["provider"] = provider
            assessment["model"] = (config.openai_model if provider == "openai"
                                   else config.judge_specialist_model)
            payload = {
                **judge_input.model_dump(mode="json"),
                "jev_result": jev_result.model_dump(mode="json"),
                "revision_count": revision_count,
                "previous_specialist_result": (
                    previous_result.model_dump(mode="json") if previous_result else None
                ),
            }
            rubric = {
                "severity": JUIZ_SEVERITY_CRITERIA,
                "facts_supported": JUIZ_FACTS_SUPPORTED_CRITERIA,
                "relevant": JUIZ_RELEVANT_CRITERIA,
            }
            messages = [
                ("system", JUDGE_SPECIALIST_PROMPT + "\n\nRubrica:\n"
                 + json.dumps(rubric, ensure_ascii=False)),
                ("human", json.dumps(payload, ensure_ascii=False, allow_nan=False)),
            ]
            with component("judge_specialist"), fallback_call():
                response = self._evaluate(messages, config, assessment)
                verdict = SpecialistVerdict.model_validate(response)
                if not verdict.justification.strip():
                    raise ValueError("Justificativa vazia do juiz especialista.")
        except Exception as error:
            if trace := current_trace():
                trace.error("judge_specialist", error, operation="evaluate",
                            metadata={"provider": assessment["provider"], "outcome": "specialist_unavailable"})
            logger.warning("Agente Juiz Especialista indisponível; resposta segura; revisão=%d", revision_count)
            return JudgeResult(
                decision="reject", status="unavailable", justification=SAFE_RESPONSE,
                reason_codes=["JUDGE_SPECIALIST_UNAVAILABLE"], confidence=None,
                severity=None, assessment=assessment,
            )

        decision = verdict.decision
        reason_codes = [f"SPECIALIST_{decision.upper()}"]
        if verdict.severity == "critical_error" or (
            decision == "approve" and verdict.severity != "no_error"
        ):
            decision = "reject"
            reason_codes = ["SPECIALIST_CRITICAL_ISSUE" if verdict.severity == "critical_error"
                            else "SPECIALIST_VERDICT_INCONSISTENT"]
        elif decision == "correct" and revision_count > 0:
            decision = "reject"
            reason_codes = ["REVIEW_EXHAUSTED"]

        logger.info("Agente Juiz Especialista: decisão=%s; revisão=%d", decision, revision_count)
        if trace := current_trace():
            trace.event(
                "judge.specialist.decision", component="judge_specialist", operation="evaluate",
                status="success", metadata={
                    "provider": assessment["provider"], "model": assessment["model"],
                    "outcome": decision, "revision_count": revision_count,
                },
            )
        return JudgeResult(
            decision=decision, status="evaluated", justification=verdict.justification.strip(),
            reason_codes=reason_codes, confidence=None,
            severity=verdict.severity, assessment=assessment,
        )

    def _evaluate(
        self,
        messages: list[tuple[str, str]],
        config: Settings,
        assessment: dict[str, Any],
    ) -> Any:
        """Consulta Gemini e usa Groq somente para falhas transitórias do provedor."""
        if self.llm is not None:
            return self.llm.with_structured_output(
                SpecialistVerdict, method="json_schema",
            ).invoke(messages)

        from app.services.llms import (
            _PROVIDER_REQUEST_ERRORS,
            _is_transient_provider_error,
            _request_error_cause,
        )

        validate_llm_config(provider="judge", settings=config)
        provider = "openai" if config.llm_provider == "openai" else "google"
        primary_model = config.openai_model if provider == "openai" else config.judge_specialist_model
        assessment.update(provider=provider, model=primary_model)
        primary = _get_model(provider, config)
        try:
            return primary.with_structured_output(
                SpecialistVerdict, method="json_schema",
            ).invoke(messages)
        except _PROVIDER_REQUEST_ERRORS as error:
            cause = _request_error_cause(error)
            if (
                not config.llm_fallback_enabled
                or cause is None
                or not _is_transient_provider_error(cause)
            ):
                raise
            if trace := current_trace():
                trace.error(
                    "judge_specialist", error, operation="evaluate",
                    metadata={"provider": provider, "model": assessment["model"]},
                )

        validate_llm_config(provider="groq_specialist", settings=config)
        fallback = _get_model("groq", config)
        assessment.update(
            provider="groq", model=config.groq_specialist_model, fallback=True,
            primary_model=primary_model,
        )
        logger.warning(
            "Agente Juiz Especialista: %s -> Groq (%s) por falha transitória; revisão=%d",
            provider, config.groq_specialist_model, assessment["revision_count"],
        )
        if trace := current_trace():
            trace.event(
                "judge.specialist.fallback", component="judge_specialist", operation="evaluate",
                status="started", metadata={
                    "provider": "groq", "model": config.groq_specialist_model,
                    "fallback": True, "outcome": "primary_transient_failure",
                    "revision_count": assessment["revision_count"],
                },
            )
        return fallback.with_structured_output(
            SpecialistVerdict, method="json_schema",
        ).invoke(messages)
