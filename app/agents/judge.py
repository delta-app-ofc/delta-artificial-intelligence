"""Avalia respostas completas com Jev e aplica uma política local explícita."""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import ConfigurationError
from app.services.prompts import (
    JUIZ_PROMPT_COMPLETO,
    JUIZ_SEVERITY_CRITERIA,
    JUIZ_SEVERITY_INSTRUCTIONS,
)

SAFE_RESPONSE = (
    "Não foi possível validar a resposta com segurança. Tente novamente mais tarde."
)
CONFIDENCE_THRESHOLD = 0.80
RUBRIC_VERSION = "delta-judge-choice-v1"
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


def _unavailable(reason_code: str) -> JudgeResult:
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
    """Avalia com Jev; a aplicação decide conforme gravidade e confidence."""

    def __init__(self, classifier: Any | None = None) -> None:
        self.classifier = classifier

    def run(
        self,
        judge_input: JudgeInput,
        *,
        revision_count: int = 0,
    ) -> JudgeResult:
        if (
            isinstance(revision_count, bool)
            or not isinstance(revision_count, int)
            or revision_count < 0
        ):
            return _unavailable("JUDGE_INPUT_INVALID")

        try:
            from langchain_typesafe import Choice

            question = Choice(
                instructions=(
                    f"{JUIZ_PROMPT_COMPLETO}\n\n{JUIZ_SEVERITY_INSTRUCTIONS}"
                ),
                criteria=JUIZ_SEVERITY_CRITERIA,
            )
        except ImportError:
            return _unavailable("JUDGE_PROVIDER_UNAVAILABLE")
        except Exception:
            return _unavailable("JUDGE_SCHEMA_INVALID")

        classifier = self.classifier
        if classifier is None:
            try:
                from app.services.jev import create_jev_classifier

                classifier = create_jev_classifier()
            except ConfigurationError:
                return _unavailable("JUDGE_CONFIGURATION_INVALID")
            except ImportError:
                return _unavailable("JUDGE_PROVIDER_UNAVAILABLE")
            except Exception:
                return _unavailable("JUDGE_CONFIGURATION_INVALID")

        try:
            state = json.loads(
                json.dumps(
                    judge_input.model_dump(mode="json"),
                    ensure_ascii=False,
                    default=str,
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError, OverflowError):
            return _unavailable("JUDGE_INPUT_INVALID")

        try:
            response = classifier.invoke(
                {"state": state, "questions": {"severity": question}}
            )
        except Exception:
            return _unavailable("JUDGE_PROVIDER_ERROR")

        try:
            answer = response.choices["severity"]
            severity = answer.choice
            confidence = answer.confidence
            if (
                severity not in SEVERITIES
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            return _unavailable("JUDGE_SCHEMA_INVALID")

        if severity == "critical_error":
            decision = "reject"
            reason_code = "CRITICAL_ISSUE"
            justification = "A candidata foi classificada com um problema crítico."
        elif severity == "no_error" and confidence >= CONFIDENCE_THRESHOLD:
            decision = "approve"
            reason_code = "ANSWER_APPROVED"
            justification = (
                "A candidata não apresentou erro material e atingiu a confiança "
                "mínima definida."
            )
        elif revision_count == 0:
            decision = "correct"
            if severity == "correctable_error":
                reason_code = "CORRECTABLE_ISSUE"
                justification = (
                    "Confira a candidata usando apenas os resultados e fontes "
                    "fornecidos. Reformule somente o que puder ser sustentado e "
                    "indique limitações ou dados ausentes; não invente informações."
                )
            else:
                reason_code = "LOW_CONFIDENCE"
                justification = (
                    f"A avaliação teve confiança de {confidence * 100}%, abaixo do "
                    "mínimo de 80%. Revise a candidata usando apenas os resultados "
                    "e fontes fornecidos; baixa confiança não confirma, por si só, "
                    "um erro material."
                )
        else:
            decision = "reject"
            reason_code = "REVIEW_EXHAUSTED"
            justification = "A revisão única não atingiu os critérios de liberação."

        return JudgeResult(
            decision=decision,
            status="evaluated",
            justification=justification,
            reason_codes=[reason_code],
            confidence=confidence,
            severity=severity,
            assessment={
                "provider": "typesafe",
                "model": response.model,
                "request_id": response.request_id,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
                "rubric_version": RUBRIC_VERSION,
                "confidence_source": "choices.severity.confidence",
                "revision_count": revision_count,
            },
        )
