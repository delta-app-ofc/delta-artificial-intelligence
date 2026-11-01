from __future__ import annotations

import re

from langchain_core.tools import BaseTool, tool

from app.data import db_mongo, db_postgres
from app.tools.exceptions import DatabaseAccessError, HabitConflictError
from app.tools.habits.names import CATALOG_NAMES, resolve_habit_name
from app.tools.validation import validate_user_id

_HABIT_LITERS_PER_SESSION: dict[str, float] = {
    "BANHO LONGO": 80.0,
    "LAVAR QUINTAL": 150.0,
    "LAVAR ROUPA": 100.0,
    "REGAR PLANTAS": 15.0,
    "LAVAR CARRO": 200.0,
    "LAVAR LOUÇA": 20.0,
}

_WEEKS_PER_MONTH = 4.33

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


_TIME_FORMAT = re.compile(r"^([01]?\d|2[0-3])(?::|h)?([0-5]\d)?$")


def _parse_time(value: str) -> str | None:
    """Converte "18:30", "18h30" ou "18h" em "18:30"; None se não for um horário válido."""
    match = _TIME_FORMAT.match(value.strip().lower().replace(" ", ""))
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2) or '00'}"


def _habit_name_problem(raw: str, options: list[str]) -> dict:
    """Resposta para nome ambíguo (peça esclarecimento) ou fora do catálogo."""
    if options:
        return {
            "status": "needs_clarification",
            "message": f"'{raw}' pode ser mais de um hábito. Qual deles? {', '.join(options)}.",
            "options": options,
        }
    return {
        "status": "error",
        "message": f"Hábito '{raw}' não reconhecido. Válidos: {', '.join(CATALOG_NAMES)}.",
    }


_NOT_RESIDENTIAL = {
    "status": "not_applicable",
    "message": (
        "Hábitos de consumo estão disponíveis apenas para usuários residenciais. "
        "Sua conta está vinculada a uma organização."
    ),
}


def build_tools(user_id: int, access_kind: str | None = None) -> list[BaseTool]:
    """Monta as ferramentas de hábitos presas a `user_id` (o modelo nunca o informa); só funcionam
    para conta residencial.
    """
    validate_user_id(user_id)

    def _is_residential() -> bool:
        # Sem perfil informado, consulta a cada chamada; com ele, vale o da pergunta atual.
        """Indica se a conta é residencial, usando o perfil informado ou consultando o banco."""
        return (access_kind or db_postgres.get_user_access_kind(user_id)) == "residential"

    @tool
    def list_habits() -> dict:
        """Lista todos os hábitos de consumo de água do usuário com frequência
        semanal e dias da semana em que ocorrem.

        Retorna lista com name (nome do hábito), frequency (vezes por semana) e
        days (lista de dias). Lista vazia significa sem hábitos cadastrados.

        Disponível apenas para usuários residenciais.
        """
        if not _is_residential():
            return _NOT_RESIDENTIAL
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

        Disponível apenas para usuários residenciais.
        """
        if not _is_residential():
            return _NOT_RESIDENTIAL
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
    def create_habit(
        name: str,
        frequency: int | None = None,
        days: list[str] | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict:
        """Cadastra um novo hábito de consumo de água para o usuário.

        Use somente quando o usuário pedir para cadastrar, adicionar ou registrar
        um hábito. Para consultar, use list_habits; para simular, use as
        ferramentas de estimativa. Listar não substitui o cadastro pedido.

        name: hábito do catálogo (BANHO LONGO, LAVAR QUINTAL, LAVAR ROUPA, REGAR
          PLANTAS, LAVAR CARRO, LAVAR LOUÇA). Aceita variações como "lavar roupas",
          "banho", "plantas". Nome ambíguo devolve needs_clarification.
        frequency: vezes por semana. Se omitida e houver dias informados, usa a
          quantidade de dias; sem nenhum dos dois, devolve needs_frequency.
        days: dias da semana em português (seg, segunda, terça...). Opcional.
        start_time, end_time: horário opcional (ex.: "18:30"), os dois ou nenhum.
          Cadastrar o mesmo hábito no mesmo dia e horário é recusado (conflict);
          sem horário, dois cadastros no mesmo dia colidem.

        Só confirme o cadastro quando o status for ok (gravado no banco).

        Disponível apenas para usuários residenciais.
        """
        if not _is_residential():
            return _NOT_RESIDENTIAL
        canonical_name, options = resolve_habit_name(name)
        if canonical_name is None:
            return _habit_name_problem(name, options)

        canonical_days: list[str] = []
        for d in days or []:
            cd = _normalize_day(d)
            if cd is None:
                return {
                    "status": "error",
                    "message": (
                        f"Dia '{d}' não reconhecido. "
                        "Use: segunda, terça, quarta, quinta, sexta, sábado ou domingo."
                    ),
                }
            if cd not in canonical_days:
                canonical_days.append(cd)

        if frequency is None:
            if not canonical_days:
                return {
                    "status": "needs_frequency",
                    "message": "Informe quantas vezes por semana (ou em quais dias) o hábito acontece.",
                }
            frequency = len(canonical_days)
        if frequency < 1:
            return {
                "status": "error",
                "message": "A frequência deve ser pelo menos 1 vez por semana.",
            }
        if len(canonical_days) > frequency:
            return {
                "status": "needs_clarification",
                "message": (
                    f"Foram informados {len(canonical_days)} dias para {frequency} vez(es) por "
                    "semana. Qual é a frequência correta?"
                ),
            }

        start = end = None
        if bool(start_time) != bool(end_time):
            return {"status": "error", "message": "Informe o horário de início e o de fim, ou nenhum dos dois."}
        if start_time and end_time:
            start, end = _parse_time(start_time), _parse_time(end_time)
            if start is None or end is None:
                return {"status": "error", "message": "Horário inválido. Use o formato HH:MM, por exemplo 18:30."}
            if end <= start:
                return {"status": "error", "message": "O horário de fim deve ser depois do início."}

        try:
            result = db_postgres.create_habit(
                user_id, canonical_name, frequency, canonical_days, start, end
            )
        except HabitConflictError as exc:
            return {"status": "conflict", "message": str(exc)}
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        except DatabaseAccessError:
            return {
                "status": "error",
                "message": "Não foi possível gravar agora. Nada foi cadastrado; tente novamente.",
            }
        return {"status": "ok", **result}

    @tool
    def estimate_habit_water_impact(habit_name: str, frequency: int) -> dict:
        """Estima o impacto hídrico de um hábito com base em médias de referência.

        habit_name: nome do hábito — aceita as mesmas formas que create_habit
          (BANHO LONGO, LAVAR CARRO, REGAR PLANTAS, etc., ou abreviações como
          "carro", "plantas", "banho").
        frequency: vezes por semana (inteiro positivo).

        Retorna liters_per_session, liters_per_week e liters_per_month
        (mês = 4,33 semanas). Os valores são estimativas médias de referência —
        não são medições do hidrômetro do usuário.

        Use quando o usuário perguntar quanto de água um hábito consome, ou para
        contextualizar o peso de um hábito no consumo mensal.

        Disponível apenas para usuários residenciais.
        """
        if not _is_residential():
            return _NOT_RESIDENTIAL
        canonical, options = resolve_habit_name(habit_name)
        if canonical is None:
            return _habit_name_problem(habit_name, options)
        if frequency < 1:
            return {"status": "error", "message": "A frequência deve ser pelo menos 1 vez por semana."}

        liters_per_session = _HABIT_LITERS_PER_SESSION[canonical]
        liters_per_week = liters_per_session * frequency
        liters_per_month = round(liters_per_week * _WEEKS_PER_MONTH, 1)

        return {
            "status": "ok",
            "habit": canonical,
            "frequency_per_week": frequency,
            "liters_per_session": liters_per_session,
            "liters_per_week": liters_per_week,
            "liters_per_month": liters_per_month,
            "note": "Estimativas baseadas em médias de referência. Não representam medições do hidrômetro.",
        }

    @tool
    def get_weather_history(days: int = 7) -> dict:
        """Retorna o histórico meteorológico recente da localização do usuário,
        lendo da coleção weather_daily no MongoDB.

        days: número de dias para trás (padrão 7, máximo 30).

        Use para identificar padrões climáticos recentes que influenciam hábitos
        ao ar livre: chuva acumulada, temperaturas médias, vento.

        Retorna lista de dias com temperatura média, chuva total e condição
        predominante. Lista vazia significa sem registros no período.
        """
        days = max(1, min(days, 30))
        try:
            location = db_postgres.get_user_location(user_id)
            if location is None:
                return {
                    "status": "insufficient_data",
                    "message": "Localização do usuário não encontrada.",
                }
            docs = db_mongo.get_weather_daily(
                location["city"], location["state"], location["country"], days
            )
        except Exception:
            return {
                "status": "error",
                "message": "Não foi possível acessar o histórico meteorológico.",
            }

        if not docs:
            return {
                "status": "no_data",
                "location": location,
                "days_requested": days,
                "message": "Sem registros meteorológicos para o período solicitado.",
            }

        summaries = []
        for doc in docs:
            hours = doc.get("hours", [])
            if not hours:
                continue
            temps = [h["temperature_c"] for h in hours if "temperature_c" in h]
            rains = [h.get("rain_mm", 0) for h in hours]
            conditions = [h.get("condition", "") for h in hours if h.get("condition")]
            avg_temp = round(sum(temps) / len(temps), 1) if temps else None
            total_rain = round(sum(rains), 1)
            condition = max(set(conditions), key=conditions.count) if conditions else None
            summaries.append({
                "date": doc.get("weather_date").isoformat() if doc.get("weather_date") else None,
                "avg_temperature_c": avg_temp,
                "total_rain_mm": total_rain,
                "predominant_condition": condition,
                "samples": doc.get("samples", len(hours)),
            })

        return {
            "status": "ok",
            "location": location,
            "days": summaries,
            "note": "Dados históricos do MongoDB. Não representam previsão futura.",
        }

    return [
        list_habits,
        get_habits_by_day,
        create_habit,
        estimate_habit_water_impact,
        get_weather_history,
    ]
