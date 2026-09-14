"""Tools do Agente de Vazamento (app/agents/leak.py).

analysis.py -- resumo descritivo puro, sem inventar limiar novo.
tools.py    -- as tools de verdade, que o LLM chama (usam analysis.py e as
               funções de app/tools/db_mongo.py).
"""
