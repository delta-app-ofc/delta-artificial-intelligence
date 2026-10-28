"""Segundo parecer com Gemini para avaliações de baixa confiança do Jev."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.judge import JudgeInput, JudgeResult, SAFE_RESPONSE
from app.config import (
    JUDGE_SPECIALIST_PROMPT,
    JUDGE_SPECIALIST_TEMPERATURE,
    get_judge_config,
    validate_llm_config,
)
from app.observability.diagnostics import ModelDiagnostics, component, current_trace, fallback_call
from app.services.prompts import (
    JUIZ_FACTS_SUPPORTED_CRITERIA,
    JUIZ_RELEVANT_CRITERIA,
    JUIZ_SEVERITY_CRITERIA,
)

logger = logging.getLogger(__name__)


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
            "provider": "google", "reviewer": "specialist",
            "jev_result": jev_result.model_dump(mode="json"),
            "revision_count": revision_count,
        }
        try:
            config = get_judge_config()
            assessment["model"] = config.judge_specialist_model
            llm = self.llm
            if llm is None:
                validate_llm_config(provider="judge", settings=config)

                from langchain_google_genai import ChatGoogleGenerativeAI

                llm = ChatGoogleGenerativeAI(
                    model=config.judge_specialist_model,
                    api_key=config.gemini_api_key,
                    temperature=JUDGE_SPECIALIST_TEMPERATURE,
                    timeout=config.llm_timeout_seconds,
                    max_retries=config.llm_max_retries + 1,
                    max_output_tokens=config.llm_max_output_tokens,
                    callbacks=[ModelDiagnostics("google", config.judge_specialist_model)],
                )

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
                structured_llm = llm.with_structured_output(SpecialistVerdict, method="json_schema")
                response = structured_llm.invoke(messages)
                verdict = SpecialistVerdict.model_validate(response)
                if not verdict.justification.strip():
                    raise ValueError("Justificativa vazia do juiz especialista.")
        except Exception as error:
            if trace := current_trace():
                trace.error("judge_specialist", error, operation="evaluate",
                            metadata={"provider": "google", "outcome": "specialist_unavailable"})
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
                    "provider": "google", "model": config.judge_specialist_model,
                    "outcome": decision, "revision_count": revision_count,
                },
            )
        return JudgeResult(
            decision=decision, status="evaluated", justification=verdict.justification.strip(),
            reason_codes=reason_codes, confidence=None,
            severity=verdict.severity, assessment=assessment,
        )
