"""Avalia respostas completas com Jev e aplica uma política local explícita."""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import ConfigurationError, get_judge_config
from app.observability.diagnostics import component, current_trace
from app.services.prompts import (
    JUIZ_FACTS_SUPPORTED_CRITERIA,
    JUIZ_FACTS_SUPPORTED_INSTRUCTIONS,
    JUIZ_PROMPT_COMPLETO,
    JUIZ_RELEVANT_CRITERIA,
    JUIZ_RELEVANT_INSTRUCTIONS,
    JUIZ_SEVERITY_CRITERIA,
    JUIZ_SEVERITY_INSTRUCTIONS,
)

SAFE_RESPONSE = (
    "Não foi possível validar a resposta com segurança. Tente novamente mais tarde."
)
RUBRIC_VERSION = "delta-judge-fixed-v6"
SEVERITIES = {"no_error", "correctable_error", "critical_error"}

logger = logging.getLogger(__name__)


class JudgeInput(BaseModel):
    """Estado mínimo e evidências usadas para avaliar a candidata composta."""

    question: str
    candidate: str
    agent_results: list[dict[str, Any]]
    context: dict[str, Any] = Field(default_factory=dict)
    chart_data: dict[str, Any] | None = None


class JudgeResult(BaseModel):
    """Decisão do Juiz; justificativas e códigos são produzidos localmente."""

    decision: Literal["approve", "correct", "reject"]
    status: Literal["evaluated", "unavailable"]
    justification: str
    reason_codes: list[str]
    confidence: float | None
    severity: str | None
    assessment: dict[str, Any] = Field(default_factory=dict)


def _unavailable(reason_code: str, error: Exception | None = None) -> JudgeResult:
    if trace := current_trace():
        if error is not None:
            trace.error("judge", error, operation="evaluate",
                        metadata={"provider": "typesafe", "outcome": reason_code})
        trace.event("judge.unavailable", component="judge", operation="evaluate",
                    status="unavailable",
                    metadata={"provider": "typesafe", "outcome": reason_code})
    logger.warning("Juiz indisponível; reason_code=%s", reason_code)
    return JudgeResult(
        decision="reject",
        status="unavailable",
        justification=SAFE_RESPONSE,
        reason_codes=[reason_code],
        confidence=None,
        severity=None,
        assessment={"provider": "typesafe", "reason_code": reason_code},
    )


class JudgeAgent:
    """Consulta os critérios juntos e aplica os quatro limites em Python."""

    def __init__(self, classifier: Any | None = None) -> None:
        self.classifier = classifier

    def run(
        self,
        judge_input: JudgeInput,
        *,
        revision_count: int = 0,
    ) -> JudgeResult:
        if isinstance(revision_count, bool) or not isinstance(revision_count, int) or revision_count < 0:
            return _unavailable("JUDGE_INPUT_INVALID")

        try:
            config = get_judge_config()
        except ConfigurationError as error:
            return _unavailable("JUDGE_CONFIGURATION_INVALID", error)

        try:
            from langchain_typesafe import Choice, Noul

            rubric = f"{JUIZ_PROMPT_COMPLETO}\n\n"
            questions = {
                "severity": Choice(
                    instructions=rubric + JUIZ_SEVERITY_INSTRUCTIONS,
                    criteria=JUIZ_SEVERITY_CRITERIA,
                ),
                "facts_supported": Noul(
                    instructions=rubric + JUIZ_FACTS_SUPPORTED_INSTRUCTIONS,
                    criteria=JUIZ_FACTS_SUPPORTED_CRITERIA,
                ),
                "relevant": Noul(
                    instructions=rubric + JUIZ_RELEVANT_INSTRUCTIONS,
                    criteria=JUIZ_RELEVANT_CRITERIA,
                ),
            }
        except ImportError as error:
            return _unavailable("JUDGE_PROVIDER_UNAVAILABLE", error)
        except Exception as error:
            return _unavailable("JUDGE_SCHEMA_INVALID", error)

        classifier = self.classifier
        if classifier is None:
            try:
                from app.services.jev import create_jev_classifier

                classifier = create_jev_classifier()
            except ImportError as error:
                return _unavailable("JUDGE_PROVIDER_UNAVAILABLE", error)
            except Exception as error:
                return _unavailable("JUDGE_CONFIGURATION_INVALID", error)

        try:
            state = json.loads(json.dumps(judge_input.model_dump(mode="json"), allow_nan=False))
        except (TypeError, ValueError, OverflowError) as error:
            return _unavailable("JUDGE_INPUT_INVALID", error)

        try:
            with component("judge_criteria"):
                response = classifier.invoke({"state": state, "questions": questions})
        except Exception as error:
            return _unavailable("JUDGE_PROVIDER_ERROR", error)

        try:
            answer = response.choices["severity"]
            severity = answer.choice
            values = {
                "confidence": answer.confidence,
                "probability": answer.probabilities[severity],
                "facts_supported": response.nouls["facts_supported"].noul,
                "relevant": response.nouls["relevant"].noul,
            }
            if severity not in SEVERITIES or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1
                for value in values.values()
            ):
                raise ValueError("Critério inválido na resposta do Juiz.")
            usage = response.usage.model_dump(mode="json")
            request = {
                "stage": "criteria", "model": response.model,
                "request_id": response.request_id, "usage": usage,
            }
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as error:
            return _unavailable("JUDGE_SCHEMA_INVALID", error)

        thresholds = {
            "confidence": config.jev_confidence_threshold,
            "probability": config.jev_probability_threshold,
            "facts_supported": config.jev_facts_supported_threshold,
            "relevant": config.jev_relevance_threshold,
        }
        checks = {name: value >= thresholds[name] for name, value in values.items()}
        tool_calls = [
            call for result in state["agent_results"]
            if isinstance(result.get("tool_calls"), list)
            for call in result["tool_calls"] if isinstance(call, dict)
        ]
        assessment = {
            "provider": "typesafe", "model": response.model,
            "request_id": response.request_id, "usage": usage, "requests": [request],
            "rubric_version": RUBRIC_VERSION,
            "confidence_source": "choices.severity.confidence",
            "confidence_threshold": thresholds["confidence"],
            "probability_threshold": thresholds["probability"],
            "facts_supported_threshold": thresholds["facts_supported"],
            "relevance_threshold": thresholds["relevant"],
            "severity_probabilities": answer.probabilities,
            "selected_probability": values["probability"],
            "diagnostics": {**values, "checks": checks},
            "input_summary": {
                "tools": [
                    {"name": call.get("name"), "output_type": type(call.get("output")).__name__}
                    for call in tool_calls
                ],
            },
            "revision_count": revision_count,
        }

        failures = []
        if severity == "critical_error":
            failures.append(("CRITICAL_ISSUE", "a candidata foi classificada com problema crítico"))
        elif severity == "correctable_error":
            failures.append(("CORRECTABLE_ISSUE", "a candidata foi classificada com erro corrigível"))

        criteria = {
            "confidence": ("LOW_CONFIDENCE", "a confiança"),
            "probability": ("LOW_PROBABILITY", "a probabilidade da categoria"),
            "facts_supported": ("FACTS_UNSUPPORTED", "o suporte factual"),
            "relevant": ("LOW_RELEVANCE", "a relevância"),
        }
        for name, (code, label) in criteria.items():
            if not checks[name]:
                failures.append((code, f"{label} ficou abaixo de {thresholds[name]:.0%}"))

        if not failures:
            decision = "approve"
            reason_codes = ["ANSWER_APPROVED"]
            justification = "A candidata está sem erro material e atingiu os quatro limites do Juiz."
        else:
            decision = "reject" if severity == "critical_error" or revision_count > 0 else "correct"
            reason_codes = [code for code, _ in failures]
            if revision_count > 0 and severity != "critical_error":
                reason_codes.insert(0, "REVIEW_EXHAUSTED")
            justification = "; ".join(message for _, message in failures) + "."
            if decision == "correct":
                justification += (
                    " Revise usando somente as ferramentas e fontes já fornecidas. "
                    "Baixa confiança ou probabilidade indica incerteza, não erro factual comprovado."
                )

        return JudgeResult(
            decision=decision, status="evaluated", justification=justification,
            reason_codes=reason_codes, confidence=values["confidence"],
            severity=severity, assessment=assessment,
        )
