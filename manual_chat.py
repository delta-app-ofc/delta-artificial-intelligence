"""Testa ForecastAgent e LeakAgent standalone, sem API/FastAPI.

Requer docker-compose.dev.yml de pé (Postgres + Mongo) e .env configurado
(GEMINI_API_KEY ou GROQ_API_KEY, DATABASE_URL, MONGODB_URI).

    python manual_chat.py forecast "Quanto eu vou gastar de água esse mês?"
    python manual_chat.py leak "Tem algum indício de vazamento na minha casa?"
"""

from __future__ import annotations

import sys
from datetime import date

from app.agents.forecast import ForecastAgent
from app.agents.leak import LeakAgent

# user_id=1: usuário elegível no dataload do Postgres (tem propriedade,
# dispositivo ativo e tarifa cadastrada) — mas sem histórico no Mongo local,
# então o ForecastAgent cai no fallback "usa a última conta cadastrada".
FORECAST_USER_ID = 1

# user_id=217: gerado pelo delta-hardware-data-simulator com
# anomaly_detected=True em consumption_summary — dá pra ver o LeakAgent
# descrever uma janela anômala de verdade. Rode o simulador antes
# (python -m dataload.cli consumption_summary 20) se este id não existir
# no seu Mongo.
LEAK_USER_ID = 217


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in ("forecast", "leak"):
        print(__doc__)
        sys.exit(1)

    agent_name, question = sys.argv[1], sys.argv[2]

    if agent_name == "forecast":
        agent = ForecastAgent(user_id=FORECAST_USER_ID, today=date.today())
    else:
        agent = LeakAgent(user_id=LEAK_USER_ID)

    result = agent.run(question)

    print("\n=== Resposta ===")
    print(result.response)

    print("\n=== Tools chamadas ===")
    print(result.readable_log())


if __name__ == "__main__":
    main()
