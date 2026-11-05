"""Guardrail de entrada: anonimiza PII, detecta injeção e classifica a mensagem.

Fluxo: anonimizar → checar injeção → checar dados internos → classificar (LLM)
O LLM só é chamado se os filtros determinísticos passarem.
"""

from __future__ import annotations

import re
import uuid
import unicodedata
from collections.abc import Callable

from app.observability.diagnostics import current_trace
from app.config import ConfigurationError
from app.agents._runtime import _message_text

_MAX_LEN = 2000

# Uma única passagem evita interpretar parte de um CNPJ como CPF e preserva a pontuação.
_PII_PATTERN = re.compile(
    r"(?P<EMAIL>[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+)"
    r"|(?P<CNPJ>(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d))"
    r"|(?P<CPF>(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d))"
    r"|(?P<TELEFONE>(?<!\d)\(?\d{2}\)?\s?\d{4,5}-?\d{4}(?!\d))"
)
_PHONE_CONTEXT = re.compile(
    r"\b(?:telefone|celular|whatsapp|fone|contato)(?:\s+(?:cadastrado|principal|é|e))?\s*[:=]?\s*$",
    re.I,
)


def replace_pii(text: str, replacement: Callable[[str, str], str]) -> str:
    """Substitui cada ocorrência inteira, compartilhando a detecção entre entrada e saída.

    CPF e telefone sem pontuação podem ter os mesmos 11 dígitos. Um rótulo explícito
    de telefone decide a categoria; sem contexto, preservamos o padrão anterior (CPF).
    Em ambos os casos, todos os dígitos são ocultados.
    """
    def replace(match: re.Match[str]) -> str:
        label = match.lastgroup
        value = match.group()
        if label == "CPF" and value.isdigit() and _PHONE_CONTEXT.search(text[max(0, match.start() - 60):match.start()]):
            label = "TELEFONE"
        return replacement(label, value)

    return _PII_PATTERN.sub(replace, text)


_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(as\s+)?instru[çc][oõ]es", re.I),
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions?", re.I),
    re.compile(r"forget\s+your\s+instructions", re.I),
    re.compile(r"(system|assistant)\s*:\s*", re.I),
    re.compile(r"<\s*/?system\s*>", re.I),
    re.compile(r"jailbreak", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"act\s+as\s+(if\s+)?", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)", re.I),
    re.compile(r"dan\s+mode", re.I),
    re.compile(r"modo\s+irrestrito", re.I),
    re.compile(r"\[INST\]", re.I),
    re.compile(r"###\s*instruction", re.I),
    re.compile(r"override\s+(your\s+)?instructions?", re.I),
    re.compile(r"desconsider[ea]\s+(suas\s+)?instru[çc][oõ]es", re.I),
    # Formulações adicionais; a normalização abaixo permite acentos e espaços variados.
    re.compile(r"\besqueca\s+(?:suas\s+instrucoes|tudo\s+que\s+te\s+disseram)\b", re.I),
    re.compile(r"\b(?:aja|responda|atue)\s+sem\s+(?:filtros|restricoes|limites)\b", re.I),
    re.compile(r"\ba\s+partir\s+de\s+agora\s+voce\s+e\b.{0,60}\b(?:sem\s+limites|irrestrit[oa]|sem\s+restricoes)\b", re.I),
    re.compile(r"\b(?:ative|entre\s+em|habilite)\s+(?:o\s+)?modo\s+(?:desenvolvedor|administrador)\b", re.I),
    re.compile(r"\b(?:repita|reproduza|mostre)\s+(?:exatamente\s+)?(?:o\s+)?texto\s+(?:que\s+)?(?:aparece|esta)\s+acima\s+(?:desta|da)\s+(?:mensagem|conversa)\b", re.I),
    re.compile(r"\bfinja\s+que\s+eu\s+sou\s+(?:o|um|a|uma)\s+(?:administrador|admin|outro\s+usuario)\b", re.I),
    re.compile(r"\b(?:conta(?:\s+de\s+agua)?|dados|consumo|historico)\s+(?:do|da|de)\s+(?:(?:meu|minha|seu|sua)\s+)?(?:vizinh[oa]s?|colega|outra\s+pessoa)\b", re.I),
    re.compile(r"\b(?:qual|mostre|revele|exiba|copie)\b.{0,70}\bprompt\s+inicial\b", re.I),
    re.compile(r"\b(?:liste|mostre|revele|exiba)\b.{0,60}\b(?:tabelas|schema|estrutura)\s+(?:do|de)\s+banco(?:\s+de\s+dados)?\b", re.I),
    re.compile(r"\b(?:execute|rode|executar|rodar)\s+(?:o\s+(?:comando|sql)\s+)?(?:drop\s+table|delete\s+from|truncate(?:\s+table)?|alter\s+table|insert\s+into|update\s+\w+\s+set)\b", re.I),
    # Tentativas de agir como outro usuário ou de consultar dados de outro usuário.
    re.compile(r"\baj[ao]\s+como\s+(o\s+|um\s+)?(usu[aá]rio|cliente|outr[oa]|admin)", re.I),
    re.compile(r"\bfinj[ae]\s+(que\s+)?(ser|sou|é)\b", re.I),
    re.compile(r"como\s+se\s+eu\s+fosse\s+(o\s+|um\s+)?(usu[aá]rio|cliente|outr[oa]|admin)", re.I),
    re.compile(r"\bmeu\s+(user[_\s-]?id|id)\s+(agora\s+)?(é|e|=)\s*\d+", re.I),
    re.compile(r"\buser[_\s-]?id\s*[:=]\s*\d+", re.I),
    re.compile(r"\b(usu[aá]rio|cliente)\s+(n[º°o]\.?\s*|id\s*|#)?\d+", re.I),
    re.compile(r"\b(conta|dados|consumo|hist[oó]rico)\s+(do|da|de)\s+(outr[oa]s?|usu[aá]rio|cliente)\b(?!\s+(?:m[eê]s|meses|semanas?|dias?|per[ií]odos?|anos?|datas?|vez|vezes)\b)", re.I),
]

_INTERNAL_DATA_KEYWORDS = [
    "prompt do sistema", "system prompt", "suas instruções", "your instructions",
    "variável de ambiente", "variáveis de ambiente", "chave de api", "api key", "senha do sistema",
    "token de acesso", "banco de dados interno", "dados de outros usuários",
    "lista de usuários", "credenciais",
    "url do banco", "uri do banco", "endereço do banco",
    "senha do banco", "usuário do banco", "host do banco",
    "url do mongo", "url do postgres", "url do qdrant", "url do redis",
]

_PROMPT_CLASSIFIER = """\
Você é um classificador de segurança de um sistema de monitoramento de consumo de água.
Classifique a mensagem em UMA categoria. Responda SOMENTE:

CATEGORIA: [categoria]
JUSTIFICATIVA: [uma linha]

Categorias:
APROVADO  - pergunta legítima sobre consumo, vazamentos, previsão, conta ou hábitos
OFENSIVO  - xingamentos, assédio ou discurso de ódio
PERIGOSO  - instruções que causam dano físico, psicológico ou coletivo
ILICITO   - pedido de auxílio para atividades ilegais ou fraudulentas

Mensagem: {message}
"""

_BLOCK_RESPONSES: dict[str, tuple[str, str]] = {
    "OFENSIVO": ("conteudo_ofensivo", "Por favor, mantenha um tom respeitoso para que eu possa te ajudar."),
    "PERIGOSO": ("pedido_perigoso",   "Não posso ajudar com esse tipo de solicitação."),
    "ILICITO":  ("pedido_ilicito",    "Não posso auxiliar com atividades ilegais."),
}


def anonymize(text: str) -> tuple[str, dict[str, str]]:
    """Substitui PII por tokens temporários. Retorna (texto_anonimizado, mapa token→valor)."""
    pii_map: dict[str, str] = {}
    tokens: dict[tuple[str, str], str] = {}

    def token_for(label: str, value: str) -> str:
        key = (label, value)
        if key not in tokens:
            token = f"[PII_{label}_{uuid.uuid4().hex[:6]}]"
            tokens[key] = token
            pii_map[token] = value
        return tokens[key]

    return replace_pii(text, token_for), pii_map


def _normalize_rules(text: str) -> str:
    """Normaliza apenas a cópia de comparação, sem mudar o texto enviado ao chatbot."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


def validate_input_rules(user_id: int, message: str) -> dict:
    """Validações instantâneas (tamanho, PII, injeção, dados internos), sem chamar LLM.

    Retorna {"ok": True, "message": <anonimizada>, "pii_map": {...}}
    ou {"ok": False, "reason": "..."}.
    """
    if not isinstance(user_id, int) or user_id <= 0:
        return {"ok": False, "reason": "user_id inválido."}

    if not message or not message.strip():
        return {"ok": False, "reason": "Mensagem vazia."}

    if len(message) > _MAX_LEN:
        return {"ok": False, "reason": f"Mensagem excede {_MAX_LEN} caracteres."}

    anonymized, pii_map = anonymize(message)

    normalized = _normalize_rules(anonymized)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            return {"ok": False, "reason": "Mensagem contém padrão não permitido."}

    for kw in _INTERNAL_DATA_KEYWORDS:
        if _normalize_rules(kw) in normalized:
            return {"ok": False, "reason": "Não consigo compartilhar dados internos do sistema."}

    return {"ok": True, "message": anonymized, "pii_map": pii_map}


def classify_input(anonymized: str) -> dict | None:
    """Classifica a mensagem já anonimizada com o LLM rápido.

    Retorna {"ok": False, "reason": "..."} se for bloqueada e None se puder seguir.
    Falha do classificador não bloqueia a mensagem (é registrada no diagnóstico).
    """
    try:
        from app.services.llms import llm_rapido
        from langchain_core.messages import HumanMessage

        if llm_rapido is None:
            raise ConfigurationError("Configure o provedor de linguagem selecionado para o guardrail de entrada.")
        raw = _message_text(llm_rapido.invoke(
            [HumanMessage(content=_PROMPT_CLASSIFIER.format(message=anonymized))]
        ))
        category = "APROVADO"
        for line in raw.splitlines():
            if line.strip().upper().startswith("CATEGORIA:"):
                category = line.split(":", 1)[1].strip().upper()
                break
        if category in _BLOCK_RESPONSES:
            _, msg = _BLOCK_RESPONSES[category]
            return {"ok": False, "reason": msg}
    except Exception as error:
        if trace := current_trace():
            trace.error("input_guard", error)
    return None


def validate_input(user_id: int, message: str) -> dict:
    """Valida e anonimiza a mensagem: regras instantâneas e depois o classificador LLM."""
    result = validate_input_rules(user_id, message)
    if not result["ok"]:
        return result
    return classify_input(result["message"]) or result
