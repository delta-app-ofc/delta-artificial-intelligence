"""Avalia respostas completas com Jev e aplica uma política local explícita."""

from __future__ import annotations

import json
import logging
import math
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import ConfigurationError
from app.services.prompts import (
    JUIZ_FACTS_SUPPORTED_CRITERIA,
    JUIZ_FACTS_SUPPORTED_INSTRUCTIONS,
    JUIZ_PROMPT_COMPLETO,
    JUIZ_QUALITY_CRITERIA,
    JUIZ_QUALITY_INSTRUCTIONS,
    JUIZ_RELEVANT_CRITERIA,
    JUIZ_RELEVANT_INSTRUCTIONS,
    JUIZ_SEVERITY_CRITERIA,
    JUIZ_SEVERITY_INSTRUCTIONS,
)

SAFE_RESPONSE = (
    "Não foi possível validar a resposta com segurança. Tente novamente mais tarde."
)
CONFIDENCE_THRESHOLD = 0.80
FACTS_SUPPORTED_THRESHOLD = 0.80
RELEVANCE_THRESHOLD = 0.60
RUBRIC_VERSION = "delta-judge-staged-v3"
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
    """Avalia primeiro a Choice; só então consulta Noul e Score se necessário."""

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

            primary_question = Choice(
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
            serialized_state = json.dumps(
                judge_input.model_dump(mode="json"),
                ensure_ascii=False,
                default=str,
                allow_nan=False,
            )
            state = json.loads(serialized_state)
        except (TypeError, ValueError, OverflowError):
            return _unavailable("JUDGE_INPUT_INVALID")

        try:
            primary_response = classifier.invoke(
                {"state": state, "questions": {"severity": primary_question}}
            )
        except Exception:
            return _unavailable("JUDGE_PROVIDER_ERROR")

        try:
            answer = primary_response.choices["severity"]
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

        requests = [
            {
                "stage": "severity",
                "model": primary_response.model,
                "request_id": primary_response.request_id,
                "usage": primary_response.usage.model_dump(mode="json"),
            }
        ]
        tool_calls = [
            call for result in state["agent_results"]
            if isinstance(result.get("tool_calls"), list)
            for call in result["tool_calls"] if isinstance(call, dict)
        ]
        assessment = {
            "provider": "typesafe",
            "model": primary_response.model,
            "request_id": primary_response.request_id,
            "usage": primary_response.usage.model_dump(mode="json"),
            "requests": requests,
            "rubric_version": RUBRIC_VERSION,
            "confidence_source": "choices.severity.confidence",
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "severity_probabilities": answer.probabilities,
            "selected_probability": answer.probabilities.get(severity),
            "input_summary": {
                "state_characters": len(serialized_state),
                "candidate_characters": len(state["candidate"]),
                "agent_count": len(state["agent_results"]),
                "tool_count": len(tool_calls),
                "tools": [
                    {"name": call.get("name"),
                     "output_type": type(call.get("output")).__name__}
                    for call in tool_calls
                ],
            },
            "revision_count": revision_count,
            "subcriteria_checked": False,
        }

        if severity == "critical_error":
            decision = "reject"
            reason_codes = ["CRITICAL_ISSUE"]
            justification = "A candidata foi classificada com um problema crítico."
        elif severity == "correctable_error":
            if revision_count == 0:
                decision = "correct"
                reason_codes = ["CORRECTABLE_ISSUE"]
                justification = (
                    "A Choice identificou um erro corrigível. Revise a candidata "
                    "usando somente as ferramentas e fontes já fornecidas."
                )
            else:
                decision = "reject"
                reason_codes = ["REVIEW_EXHAUSTED", "CORRECTABLE_ISSUE"]
                justification = (
                    "A revisão única ainda foi classificada com erro corrigível."
                )
        elif confidence < CONFIDENCE_THRESHOLD:
            if revision_count == 0:
                decision = "correct"
                reason_codes = ["LOW_CONFIDENCE"]
                justification = (
                    f"A Choice indicou no_error, mas sua confidence foi {confidence}, "
                    "abaixo de 0,80. Isso indica incerteza na classificação, não um erro "
                    "específico comprovado. Confira a correspondência com as evidências "
                    "e explicite unidades, período e caráter estimado quando aplicável. "
                    "Preserve os valores sustentados e não invente dados."
                )
            else:
                decision = "reject"
                reason_codes = ["REVIEW_EXHAUSTED", "LOW_CONFIDENCE"]
                justification = (
                    "A revisão única ainda não atingiu confidence de 0,80 na Choice."
                )
        else:
            try:
                from langchain_typesafe import Noul, Score

                rubric = f"{JUIZ_PROMPT_COMPLETO}\n\n"
                questions = {
                    "facts_supported": Noul(
                        instructions=rubric + JUIZ_FACTS_SUPPORTED_INSTRUCTIONS,
                        criteria=JUIZ_FACTS_SUPPORTED_CRITERIA,
                    ),
                    "relevant": Noul(
                        instructions=rubric + JUIZ_RELEVANT_INSTRUCTIONS,
                        criteria=JUIZ_RELEVANT_CRITERIA,
                    ),
                    "quality": Score(
                        instructions=rubric + JUIZ_QUALITY_INSTRUCTIONS,
                        criteria=JUIZ_QUALITY_CRITERIA,
                    ),
                }
            except ImportError:
                return _unavailable("JUDGE_PROVIDER_UNAVAILABLE")
            except Exception:
                return _unavailable("JUDGE_SCHEMA_INVALID")

            try:
                secondary_response = classifier.invoke(
                    {"state": state, "questions": questions}
                )
            except Exception:
                return _unavailable("JUDGE_PROVIDER_ERROR")

            try:
                facts_supported = secondary_response.nouls["facts_supported"].noul
                relevant = secondary_response.nouls["relevant"].noul
                quality = secondary_response.scores["quality"]
                if (
                    not math.isfinite(facts_supported)
                    or not 0 <= facts_supported <= 1
                    or not math.isfinite(relevant)
                    or not 0 <= relevant <= 1
                    or not math.isfinite(quality.score)
                    or not 0 <= quality.score <= 2
                ):
                    raise ValueError
            except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                return _unavailable("JUDGE_SCHEMA_INVALID")

            checks = {
                "facts_supported": facts_supported >= FACTS_SUPPORTED_THRESHOLD,
                "relevant": relevant >= RELEVANCE_THRESHOLD,
                "quality": quality.score >= 1.0,
            }
            diagnostics = {
                "facts_supported": facts_supported,
                "relevant": relevant,
                "quality": quality.model_dump(mode="json"),
                "checks": checks,
            }
            requests.append(
                {
                    "stage": "subcriteria",
                    "model": secondary_response.model,
                    "request_id": secondary_response.request_id,
                    "usage": secondary_response.usage.model_dump(mode="json"),
                }
            )
            assessment["subcriteria_checked"] = True
            assessment["diagnostics"] = diagnostics

            failures: list[tuple[str, str]] = []
            if not checks["facts_supported"]:
                failures.append(
                    ("FACTS_UNSUPPORTED", "o suporte factual ficou abaixo de 0,80")
                )
            if not checks["relevant"]:
                failures.append(
                    ("LOW_RELEVANCE", "a relevância ficou abaixo de 0,60")
                )
            if not checks["quality"]:
                failures.append(
                    (
                        "QUALITY_INADEQUATE",
                        "o Score retornou: " + JUIZ_QUALITY_CRITERIA[0],
                    )
                )

            if not failures:
                decision = "approve"
                reason_codes = ["ANSWER_APPROVED"]
                justification = (
                    "A candidata passou pela gravidade, confidence, suporte factual, "
                    "relevância e qualidade."
                )
            elif revision_count == 0:
                decision = "correct"
                reason_codes = [code for code, _ in failures]
                justification = (
                    "Revise a candidata: "
                    + "; ".join(message for _, message in failures)
                    + ". Use somente as ferramentas e fontes já fornecidas; "
                    "não invente dados."
                )
            else:
                decision = "reject"
                reason_codes = ["REVIEW_EXHAUSTED"] + [
                    code for code, _ in failures
                ]
                justification = (
                    "A revisão única ainda não atingiu os critérios: "
                    + "; ".join(message for _, message in failures)
                    + "."
                )

        return JudgeResult(
            decision=decision,
            status="evaluated",
            justification=justification,
            reason_codes=reason_codes,
            confidence=confidence,
            severity=severity,
            assessment=assessment,
        )
