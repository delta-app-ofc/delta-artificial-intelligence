"""Avalia respostas completas com Jev e aplica uma política local explícita."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.config import ConfigurationError
from app.services.prompts import (
    JUIZ_FACTS_SUPPORTED_CRITERIA,
    JUIZ_FACTS_SUPPORTED_INSTRUCTIONS,
    JUIZ_PROMPT,
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
RUBRIC_VERSION = "delta-judge-choice-v1"
SEVERITIES = {"no_error", "correctable_error", "critical_error"}
QUESTION_IDS = {"severity", "facts_supported", "relevant", "quality"}

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


class _ProviderContractError(ValueError):
    """Resposta do provider ausente, inesperada ou fora dos limites."""


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        if name not in value:
            raise _ProviderContractError
        return value[name]
    try:
        return getattr(value, name)
    except (AttributeError, TypeError) as error:
        raise _ProviderContractError from error


def _number(value: Any, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _ProviderContractError
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise _ProviderContractError from error
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise _ProviderContractError
    return result


def _probabilities(value: Any, expected_keys: set[Any]) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise _ProviderContractError
    probabilities = {
        str(key): _number(probability, minimum=0.0, maximum=1.0)
        for key, probability in value.items()
    }
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=0.02):
        raise _ProviderContractError
    return probabilities


def _answer_type(answer: Any, expected_type: str) -> None:
    if _field(answer, "type") != expected_type:
        raise _ProviderContractError


def _token_count(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _ProviderContractError
    return value


def _parse_response(response: Any) -> dict[str, Any]:
    provider_model = _field(response, "model")
    if not isinstance(provider_model, str) or not provider_model.strip():
        raise _ProviderContractError

    answers = _field(response, "answers")
    if not isinstance(answers, Mapping) or set(answers) != QUESTION_IDS:
        raise _ProviderContractError

    severity_answer = answers["severity"]
    _answer_type(severity_answer, "choice")
    severity = _field(severity_answer, "choice")
    if not isinstance(severity, str) or severity not in SEVERITIES:
        raise _ProviderContractError
    confidence = _number(
        _field(severity_answer, "confidence"), minimum=0.0, maximum=1.0
    )
    severity_probabilities = _probabilities(
        _field(severity_answer, "probabilities"), SEVERITIES
    )
    if severity_probabilities[severity] + 0.02 < max(severity_probabilities.values()):
        raise _ProviderContractError

    facts_answer = answers["facts_supported"]
    _answer_type(facts_answer, "noul")
    facts_supported = _number(
        _field(facts_answer, "noul"), minimum=0.0, maximum=1.0
    )

    relevant_answer = answers["relevant"]
    _answer_type(relevant_answer, "noul")
    relevant = _number(_field(relevant_answer, "noul"), minimum=0.0, maximum=1.0)

    quality_answer = answers["quality"]
    _answer_type(quality_answer, "score")
    quality_score = _number(_field(quality_answer, "score"), minimum=0.0, maximum=2.0)
    _number(_field(quality_answer, "confidence"), minimum=0.0, maximum=1.0)
    quality_probabilities = _probabilities(
        _field(quality_answer, "probabilities"), {0, 1, 2}
    )
    legend = _field(quality_answer, "legend")
    if not isinstance(legend, Mapping) or set(legend) != {0, 1, 2}:
        raise _ProviderContractError

    usage = _field(response, "usage")
    usage_data = {
        "input_tokens": _token_count(_field(usage, "input_tokens")),
        "output_tokens": _token_count(_field(usage, "output_tokens")),
    }
    request_id = _field(response, "request_id")
    if request_id is not None and (
        not isinstance(request_id, str) or not request_id.strip()
    ):
        raise _ProviderContractError

    return {
        "model": provider_model.strip(),
        "request_id": request_id,
        "usage": usage_data,
        "severity": severity,
        "confidence": confidence,
        "severity_probabilities": severity_probabilities,
        "diagnostics": {
            "nouls": {
                "facts_supported": facts_supported,
                "relevant": relevant,
            },
            "scores": {
                "quality": {
                    "score": quality_score,
                    "probabilities": quality_probabilities,
                }
            },
        },
    }


def _json_safe(value: Any) -> Any:
    """Converte valores do estado em JSON sem descartar conteúdo silenciosamente."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            string_key = str(key)
            if string_key in result:
                raise ValueError
            result[string_key] = _json_safe(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump(mode="python"))
    to_list = getattr(value, "tolist", None)
    if callable(to_list):
        return _json_safe(to_list())
    to_scalar = getattr(value, "item", None)
    if callable(to_scalar):
        return _json_safe(to_scalar())
    raise TypeError

def _with_judge_rubric(instructions: str) -> str:
    return "\n\n".join((JUIZ_PROMPT, instructions))


def _build_questions() -> dict[str, Any]:
    from langchain_typesafe import Choice, Noul, Score

    return {
        "severity": Choice(
            instructions=_with_judge_rubric(JUIZ_SEVERITY_INSTRUCTIONS),
            criteria=dict(JUIZ_SEVERITY_CRITERIA),
        ),
        "facts_supported": Noul(
            instructions=_with_judge_rubric(JUIZ_FACTS_SUPPORTED_INSTRUCTIONS),
            criteria=dict(JUIZ_FACTS_SUPPORTED_CRITERIA),
        ),
        "relevant": Noul(
            instructions=_with_judge_rubric(JUIZ_RELEVANT_INSTRUCTIONS),
            criteria=dict(JUIZ_RELEVANT_CRITERIA),
        ),
        "quality": Score(
            instructions=_with_judge_rubric(JUIZ_QUALITY_INSTRUCTIONS),
            criteria=list(JUIZ_QUALITY_CRITERIA),
        ),
    }


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
            questions = _build_questions()
        except ImportError:
            return _unavailable("JUDGE_PROVIDER_UNAVAILABLE")
        except ValidationError:
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
            except (ValidationError, ValueError):
                return _unavailable("JUDGE_CONFIGURATION_INVALID")

        try:
            state = _json_safe(judge_input.model_dump(mode="json"))
        except Exception:
            try:
                state = _json_safe(judge_input.model_dump(mode="python"))
            except Exception:
                return _unavailable("JUDGE_INPUT_INVALID")
        if not isinstance(state, Mapping):
            return _unavailable("JUDGE_INPUT_INVALID")
        try:
            from langchain_typesafe.client import TypeSafeError
        except ImportError:
            return _unavailable("JUDGE_PROVIDER_UNAVAILABLE")
        try:
            response = classifier.invoke({"state": state, "questions": questions})
        except (TypeSafeError, TimeoutError, ConnectionError):
            return _unavailable("JUDGE_PROVIDER_ERROR")

        try:
            parsed = _parse_response(response)
        except _ProviderContractError:
            return _unavailable("JUDGE_SCHEMA_INVALID")

        severity = parsed["severity"]
        confidence = parsed["confidence"]
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
                confidence_percent = repr(confidence * 100)
                reason_code = "LOW_CONFIDENCE"
                justification = (
                    f"A avaliação teve confiança de {confidence_percent}%, abaixo do "
                    "mínimo de 80%. Revise a candidata usando apenas os resultados "
                    "e fontes fornecidos; baixa confiança não confirma, por si só, "
                    "um erro material."
                )
        else:
            decision = "reject"
            reason_code = "REVIEW_EXHAUSTED"
            justification = "A revisão única não atingiu os critérios de liberação."

        assessment = {
            "provider": "typesafe",
            "model": parsed["model"],
            "request_id": parsed["request_id"],
            "usage": parsed["usage"],
            "rubric_version": RUBRIC_VERSION,
            "confidence_source": "choices.severity.confidence",
            "revision_count": revision_count,
            "severity_probabilities": parsed["severity_probabilities"],
            "diagnostics": parsed["diagnostics"],
        }
        return JudgeResult(
            decision=decision,
            status="evaluated",
            justification=justification,
            reason_codes=[reason_code],
            confidence=confidence,
            severity=severity,
            assessment=assessment,
        )
