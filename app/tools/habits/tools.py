"""As tools de verdade do Agente de Hábitos — o que o LLM efetivamente chama.

Somente usuários residenciais: sem branching organizacional.
O user_id nunca é exposto ao LLM como argumento.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from app.data import db_postgres

_DAY_ALIASES: dict[str, str] = {
    "seg": "SEGUNDA",
    "segunda": "SEGUNDA",
    "segunda-feira": "SEGUNDA",
    "ter": "TERÇA",
    "terca": "TERÇA",
    "terça": "TERÇA",
    "terça-feira": "TERÇA",
    "qua": "QUARTA",
    "quarta": "QUARTA",
    "quarta-feira": "QUARTA",
    "qui": "QUINTA",
    "quinta": "QUINTA",
    "quinta-feira": "QUINTA",
    "sex": "SEXTA",
    "sexta": "SEXTA",
    "sexta-feira": "SEXTA",
    "sab": "SÁBADO",
    "sáb": "SÁBADO",
    "sabado": "SÁBADO",
    "sábado": "SÁBADO",
    "dom": "DOMINGO",
    "domingo": "DOMINGO",
}


def _normalize_day(day: str) -> str | None:
    normalized = day.strip().lower()
    canonical = _DAY_ALIASES.get(normalized)
    if canonical:
        return canonical
    upper = normalized.upper()
    valid = {"SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA", "SÁBADO", "DOMINGO"}
    return upper if upper in valid else None


def build_tools(user_id: int) -> list[BaseTool]:
    """Cria as tools já amarradas a user_id.

    O user_id nunca é um argumento exposto ao LLM.
    """

    @tool
    def list_habits() -> dict:
        """Lista todos os hábitos de consumo de água do usuário com frequência
        semanal e dias da semana em que ocorrem.

        Retorna lista com name (nome do hábito), frequency (vezes por semana) e
        days (lista de dias). Lista vazia significa sem hábitos cadastrados.
        """
        habits = db_postgres.get_user_habits(user_id)
        if not habits:
            return {"status": "insufficient_data", "message": "Nenhum hábito cadastrado."}
        return {"status": "ok", "habits": habits}

    @tool
    def get_habits_by_day(day: str) -> dict:
        """Lista os hábitos que ocorrem em um dia específico da semana.

        Aceita o nome do dia em português, com ou sem acento, abreviado ou
        completo: seg, segunda, segunda-feira, ter, terça, sab, sábado, etc.

        Retorna lista com name e frequency dos hábitos daquele dia.
        """
        canonical = _normalize_day(day)
        if canonical is None:
            return {
                "status": "error",
                "message": (
                    f"Dia '{day}' não reconhecido. "
                    "Use: segunda, terça, quarta, quinta, sexta, sábado ou domingo."
                ),
            }
        habits = db_postgres.get_habits_by_weekday(user_id, canonical)
        if not habits:
            return {
                "status": "ok",
                "day": canonical,
                "habits": [],
                "message": f"Nenhum hábito cadastrado para {canonical}.",
            }
        return {"status": "ok", "day": canonical, "habits": habits}

    return [list_habits, get_habits_by_day]
