"""Modelos de IA generativa usados pelos agentes. Construção preguiçosa via
__getattr__ de módulo: nada é criado até o primeiro acesso, então o módulo
importa mesmo sem GEMINI_API_KEY/GROQ_API_KEY no ambiente."""

from functools import lru_cache

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config import GEMINI_API_KEY, GROQ_API_KEY

__all__ = [
    "llm_gemini",
    "llm_groq_especialista",
    "llm_especialista",
    "llm_rapido",
    "EMBEDDING_MODEL_NAME",
]

EMBEDDING_MODEL_NAME = "gemini-embedding-2-preview"


@lru_cache(maxsize=1)
def _get_llm_gemini() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0.3,
        top_p=0.95,
        api_key=GEMINI_API_KEY,
    )


@lru_cache(maxsize=1)
def _get_llm_groq_especialista() -> ChatGroq:
    return ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0.3,
        api_key=GROQ_API_KEY,
    )


@lru_cache(maxsize=1)
def _get_llm_especialista():
    return _get_llm_gemini().with_fallbacks([_get_llm_groq_especialista()])


@lru_cache(maxsize=1)
def _get_llm_rapido() -> ChatGroq:
    return ChatGroq(
        model="openai/gpt-oss-20b",
        temperature=0.0,
        api_key=GROQ_API_KEY,
    )


_LAZY = {
    "llm_gemini": _get_llm_gemini,
    "llm_groq_especialista": _get_llm_groq_especialista,
    "llm_especialista": _get_llm_especialista,
    "llm_rapido": _get_llm_rapido,
}


def __getattr__(name: str):
    try:
        return _LAZY[name]()
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None


def __dir__() -> list[str]:
    return sorted(__all__)
