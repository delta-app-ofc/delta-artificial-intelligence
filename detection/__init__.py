"""Motor de detecção de vazamento — regras explicáveis + Isolation Forest.

Componente separado do chat de IA (app/): não usa LLM, roda à parte,
calculando consumption_summary.anomaly_detected e criando alerts_history. O
LeakAgent só lê o que este motor já sinalizou.

Ver detection/README.md para o detalhe de cada escolha e como rodar.
"""
