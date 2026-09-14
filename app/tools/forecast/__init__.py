"""Tools do Agente de Previsão (app/agents/forecast.py).

calculations.py  -- cálculo determinístico, sem LLM.
tools.py         -- as tools de verdade, que o LLM chama (usam calculations.py
                     e as funções de app/tools/db_postgres.py e db_mongo.py).
"""
