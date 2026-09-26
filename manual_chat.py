"""Testa ForecastAgent e LeakAgent:
    python manual_chat.py forecast "Quanto eu vou gastar de água esse mês?"
    python manual_chat.py leak "Tem algum indício de vazamento na minha casa?"
"""

from __future__ import annotations

import sys
from datetime import date

from app.agents.forecast import ForecastAgent
from app.agents.leak import LeakAgent


FORECAST_USER_ID = 1
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
