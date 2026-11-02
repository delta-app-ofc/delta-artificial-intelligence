"""Normalização do nome de hábitos escrito em linguagem natural para o catálogo."""

from __future__ import annotations

import unicodedata

CATALOG_ALIASES: dict[str, str] = {
    "banho longo": "BANHO LONGO",
    "banho": "BANHO LONGO",
    "lavar quintal": "LAVAR QUINTAL",
    "quintal": "LAVAR QUINTAL",
    "lavar roupa": "LAVAR ROUPA",
    "roupa": "LAVAR ROUPA",
    "regar plantas": "REGAR PLANTAS",
    "plantas": "REGAR PLANTAS",
    "regar": "REGAR PLANTAS",
    "lavar carro": "LAVAR CARRO",
    "carro": "LAVAR CARRO",
    "lavar louça": "LAVAR LOUÇA",
    "louça": "LAVAR LOUÇA",
    "louca": "LAVAR LOUÇA",
    "lavar louca": "LAVAR LOUÇA",
}

CATALOG_NAMES = sorted(set(CATALOG_ALIASES.values()))

_STOPWORDS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "minha", "meu", "minhas",
              "meus", "um", "uma", "uns", "umas", "para", "pra", "no", "na", "nos", "nas", "em"}

_FILLER_VERBS = {"tomar", "fazer", "dar"}


def _tokens(text: str) -> tuple[str, ...]:
    """Minúsculas, sem acento, sem artigos e com plural simples removido ("roupas" -> "roupa")."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = [w.strip(".,;:!?\"'()") for w in plain.split()]
    words = [w for w in words if w and w not in _STOPWORDS]
    return tuple(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words)


_INDEXED_ALIASES = {_tokens(alias): name for alias, name in CATALOG_ALIASES.items()}


def resolve_habit_name(raw: str) -> tuple[str | None, list[str]]:
    """Converte o texto do usuário em um hábito do catálogo.

    Devolve (nome, []) quando há uma única opção; (None, opções) quando é ambíguo e
    (None, []) quando o nome não existe no catálogo.
    """
    tokens = _tokens(raw)
    if not tokens:
        return None, []
    if tokens in _INDEXED_ALIASES:
        return _INDEXED_ALIASES[tokens], []

    given = set(tokens)
    contained = {
        name
        for alias, name in _INDEXED_ALIASES.items()
        if set(alias) <= given and (len(alias) > 1 or given - set(alias) <= _FILLER_VERBS)
    }
    if not contained:
        contained = {name for alias, name in _INDEXED_ALIASES.items() if given <= set(alias)}
    if len(contained) == 1:
        return next(iter(contained)), []
    return None, sorted(contained)
