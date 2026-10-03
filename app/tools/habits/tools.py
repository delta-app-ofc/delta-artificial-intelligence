"""As tools de verdade do Agente de Hábitos — o que o LLM efetivamente chama.

Somente usuários residenciais: sem branching organizacional.
O user_id nunca é exposto ao LLM como argumento.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from app.data import db_postgres

_VALID_HABITS: dict[str, str] = {
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

    @tool
    def create_habit(name: str, frequency: int, days: list[str]) -> dict:
        """Cadastra um novo hábito de consumo de água para o usuário.

        name: nome do hábito — deve ser um dos hábitos válidos do catálogo:
          BANHO LONGO, LAVAR QUINTAL, LAVAR ROUPA, REGAR PLANTAS, LAVAR CARRO,
          LAVAR LOUÇA. Também aceita formas abreviadas como "banho", "carro",
          "plantas", "louça", etc.
        frequency: número de vezes por semana (inteiro positivo).
        days: lista de dias da semana em português em que o hábito ocorre.
          Aceita as mesmas formas que get_habits_by_day (seg, segunda, etc.).
          Pode ser lista vazia se os dias ainda não forem conhecidos.

        Retorna confirmação com o nome canônico, frequência e dias vinculados.
        """
        canonical_name = _VALID_HABITS.get(name.strip().lower())
        if canonical_name is None:
            valid = ", ".join(sorted(set(_VALID_HABITS.values())))
            return {
                "status": "error",
                "message": (
                    f"Hábito '{name}' não reconhecido. "
                    f"Hábitos válidos: {valid}."
                ),
            }

        if frequency < 1:
            return {
                "status": "error",
                "message": "A frequência deve ser pelo menos 1 vez por semana.",
            }

        canonical_days: list[str] = []
        for d in days:
            cd = _normalize_day(d)
            if cd is None:
                return {
                    "status": "error",
                    "message": (
                        f"Dia '{d}' não reconhecido. "
                        "Use: segunda, terça, quarta, quinta, sexta, sábado ou domingo."
                    ),
                }
            canonical_days.append(cd)

        try:
            result = db_postgres.create_habit(
                user_id, canonical_name, frequency, canonical_days
            )
            return {"status": "ok", **result}
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}

    return [list_habits, get_habits_by_day, create_habit]
