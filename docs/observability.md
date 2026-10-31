# Observabilidade do Delta AI

## Objetivo

Medir custo, latência, erros, resolução e ROI do chatbot, com relatório em PDF e projeção para 100 e 1000 usuários por semana.

## O que está implementado

| Peça | Arquivo |
| --- | --- |
| Tokens por chamada de modelo | `app/observability/diagnostics.py` (`ModelDiagnostics`) |
| Custo, latência, resolução, ROI, projeção | `app/observability/metrics.py` |
| Gravação ao fim de cada requisição | `app/observability/http.py` |
| Resumo e PDF (funções) | `app/routes/monitor.py` (`build_summary`, `pdf_response`) |
| Aba **Monitor** e PDF no console (sem autenticação, só com o playground ativo) | `frontend/tabs/monitor.js`, `GET /playground/observability` e `/playground/observability/report.pdf` |
| Projeção por linha de comando | `python -m scripts.cost_projection --pdf relatorio.pdf` |
| LangSmith opcional | `app/observability/langsmith.py`, `scripts/langsmith_reconcile.py` |

Só requisições de chat completo (`/chat` e as abas Chat e Juiz) são registradas. Cada registro fica na coleção `observability_requests` do MongoDB do app, sem pergunta, resposta ou `user_id`. Sem MongoDB, o painel usa os registros do processo atual.

## Definições

- **Tempo total**: da chegada da requisição ao fim da resposta. Latência por etapa vem dos eventos do grafo (guardrail, contexto, roteador, execução, síntese, Juiz, saída) e por agente das etapas de cada especialista. **Orquestração** = tempo total − soma das etapas.
- **Índice de erros** = requisições com falha (5xx ou etapa que quebrou) ÷ total. Bloqueios de guardrail e execuções parciais (ferramenta falhou, mas houve resposta) são contados à parte.
- **Resolução** = resposta publicada com sucesso, sem erro de agente e sem bloqueio do Juiz.
- **Custo por resolução** = custo de IA ÷ resoluções.
- **ROI** = (resoluções × custo de um atendimento − custo de IA) ÷ custo de IA. Acima de 0 há retorno.
- **SLO**: p95 do tempo total ≤ 8 s e índice de erros ≤ 5%.

## Premissas (ajuste pelo `.env`)

Todas são lidas e validadas em `app/config.py` (`get_observability_config`), como as demais configurações; valor inválido ou negativo gera erro claro.

| Variável | Padrão | Significado |
| --- | --- | --- |
| `OBS_SUPPORT_COST_USD` | 2.0 | custo de um atendimento humano (premissa, sem fonte) |
| `OBS_QUESTIONS_PER_USER_WEEK` | 5 | perguntas por usuário por semana (premissa) |
| `OBS_USD_TO_BRL` | 5.5 | câmbio da projeção |
| `OBS_JEV_COST_USD` | 0 | custo do Jev por avaliação; ele não passa pelo LangChain, então é informado à mão |
| `OBS_LATENCY_P95_LIMIT_MS` | 8000 | limite do p95 do tempo total no SLO |
| `OBS_ERROR_RATE_LIMIT` | 0.05 | limite do índice de erros no SLO (entre 0 e 1) |
| `OBS_PRICES_JSON` | tabela interna | sobrescreve preços, ex. `{"gpt-6-luna": [1.0, 8.0]}` |

Preços por 1 milhão de tokens (entrada/saída, USD): Gemini 2.5 Flash 0,30/2,50; gpt-oss-120b 0,15/0,60; gpt-oss-20b 0,075/0,30. O preço do `gpt-6-luna` (1,00/8,00) é **premissa**: confirme na conta e sobrescreva. O cenário pessimista multiplica o custo por 1,5.

Limites: embeddings não entram no custo; tokens vêm do que o provedor devolve; o custo real da fatura pode diferir. Com dados mockados, os números mostram o funcionamento, não o uso real.

## LangSmith (opcional)

1. Crie a chave em smith.langchain.com (Settings → API Keys).
2. No `.env` local (já ignorado pelo Git; lido por `app/config.py`) defina `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=...` e `LANGSMITH_PROJECT=delta-ai`. Nunca coloque a chave em arquivos versionados.
3. Suba a API normalmente: os traces aparecem no projeto, agrupados por `session_id`.
4. `python -m scripts.langsmith_reconcile` compara tokens, custo e latência do LangSmith com o cálculo local.

Use só com dados de teste: prompts e respostas vão para um serviço externo. Em `APP_ENV=test` o `.env` é ignorado e nada é enviado.

## Validado e pendente

- Validado com testes (`tests/test_observability.py`): cálculo de custo e tokens, percentis, erros, resolução, ROI, projeção, ausência de texto no registro e geração do PDF.
- Não validado: chamadas reais com credenciais (custos reais, envio ao LangSmith, gravação no MongoDB real) e o visual da aba Monitor em navegador.

Endpoints com Bearer (`/observability/*`) dependem de `app/auth.py`, que ainda não está na `main`; entram quando a autenticação for integrada.
