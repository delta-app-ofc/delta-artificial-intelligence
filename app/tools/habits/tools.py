from __future__ import annotations

import httpx
from langchain_core.tools import BaseTool, tool

from app.data import db_mongo, db_postgres

_HABIT_LITERS_PER_SESSION: dict[str, float] = {
    "BANHO LONGO": 80.0,
    "LAVAR QUINTAL": 150.0,
    "LAVAR ROUPA": 100.0,
    "REGAR PLANTAS": 15.0,
    "LAVAR CARRO": 200.0,
    "LAVAR LOUÇA": 20.0,
}

_WEEKS_PER_MONTH = 4.33

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


_NOT_RESIDENTIAL = {
    "status": "not_applicable",
    "message": (
        "Hábitos de consumo estão disponíveis apenas para usuários residenciais. "
        "Sua conta está vinculada a uma organização."
    ),
}


def build_tools(user_id: int) -> list[BaseTool]:

    _access_kind = db_postgres.get_user_access_kind(user_id)
    _is_residential = _access_kind == "residential"

    @tool
    def list_habits() -> dict:
        """Lista todos os hábitos de consumo de água do usuário com frequência
        semanal e dias da semana em que ocorrem.

        Retorna lista com name (nome do hábito), frequency (vezes por semana) e
        days (lista de dias). Lista vazia significa sem hábitos cadastrados.

        Disponível apenas para usuários residenciais.
        """
        if not _is_residential:
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
        if not _is_residential:
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

        Disponível apenas para usuários residenciais.
        """
        if not _is_residential:
            return _NOT_RESIDENTIAL
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
        if not _is_residential:
            return _NOT_RESIDENTIAL
        canonical = _VALID_HABITS.get(habit_name.strip().lower())
        if canonical is None:
            valid = ", ".join(sorted(set(_VALID_HABITS.values())))
            return {
                "status": "error",
                "message": f"Hábito '{habit_name}' não reconhecido. Válidos: {valid}.",
            }
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
        location = db_postgres.get_user_location(user_id)
        if location is None:
            return {
                "status": "insufficient_data",
                "message": "Localização do usuário não encontrada.",
            }

        try:
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

    @tool
    def get_weather_forecast(days_ahead: int = 3) -> dict:
        """Consulta a previsão do tempo para os próximos dias via Open-Meteo (gratuita).

        days_ahead: quantos dias de previsão (padrão 3, máximo 7).

        Use para hábitos ao ar livre: recomendar o melhor dia para lavar o carro,
        regar plantas ou lavar o quintal com base na previsão de chuva, temperatura
        e vento.

        Retorna lista diária com temperatura máxima/mínima, chuva prevista,
        velocidade máxima do vento e código WMO da condição.
        """
        days_ahead = max(1, min(days_ahead, 7))
        location = db_postgres.get_user_location(user_id)
        if location is None:
            return {
                "status": "insufficient_data",
                "message": "Localização do usuário não encontrada.",
            }

        city = location["city"]

        try:
            geo = httpx.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "pt", "format": "json"},
                timeout=8.0,
            )
            geo.raise_for_status()
            results = geo.json().get("results", [])
            if not results:
                return {
                    "status": "no_data",
                    "message": f"Localidade '{city}' não encontrada na API de clima.",
                }
            lat = results[0]["latitude"]
            lon = results[0]["longitude"]
        except Exception:
            return {
                "status": "error",
                "message": "Não foi possível obter coordenadas para a previsão do tempo.",
            }

        try:
            forecast = httpx.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": ",".join([
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_sum",
                        "windspeed_10m_max",
                        "weathercode",
                    ]),
                    "timezone": "America/Sao_Paulo",
                    "forecast_days": days_ahead,
                },
                timeout=8.0,
            )
            forecast.raise_for_status()
            data = forecast.json()
        except Exception:
            return {
                "status": "error",
                "message": "Não foi possível obter a previsão do tempo.",
            }

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        t_max = daily.get("temperature_2m_max", [])
        t_min = daily.get("temperature_2m_min", [])
        rain = daily.get("precipitation_sum", [])
        wind = daily.get("windspeed_10m_max", [])
        codes = daily.get("weathercode", [])

        days_forecast = []
        for i, d in enumerate(dates):
            days_forecast.append({
                "date": d,
                "temperature_max_c": t_max[i] if i < len(t_max) else None,
                "temperature_min_c": t_min[i] if i < len(t_min) else None,
                "precipitation_mm": rain[i] if i < len(rain) else None,
                "wind_max_kmh": wind[i] if i < len(wind) else None,
                "weather_code": codes[i] if i < len(codes) else None,
            })

        return {
            "status": "ok",
            "location": {"city": city, "latitude": lat, "longitude": lon},
            "forecast": days_forecast,
            "source": "Open-Meteo (open-meteo.com)",
            "note": "Previsão dos próximos dias. Use para recomendar dias adequados para hábitos ao ar livre.",
        }

    return [
        list_habits,
        get_habits_by_day,
        create_habit,
        estimate_habit_water_impact,
        get_weather_history,
        get_weather_forecast,
    ]
