# delta-artificial-intelligence

Chatbot de IA do Projeto Delta — plataforma de monitoramento inteligente de
consumo residencial de água. Este repositório reúne os agentes especialistas,
as tools de acesso a dados e o motor de detecção de vazamento; a API HTTP
(FastAPI), o roteamento entre agentes (LangGraph), guardrails e memória de
sessão ainda são só o esqueleto de pastas, sem implementação.

Convenção de código: identificadores (nomes de arquivo, função, classe,
variável) em **inglês**; comentários, docstrings e o conteúdo dos prompts em
**português** (é o idioma em que o chatbot conversa com o usuário final).

Este README é incremental: cada agente/componente novo ganha sua própria
seção, descrevendo o que está implementado. Ele não guarda histórico de
mudanças nem lista de pendências — isso mora na conversa/tarefa que criou cada
parte.

---

## Ambiente local de desenvolvimento

Não existe ainda uma conexão oficial do serviço de IA com PostgreSQL/MongoDB
de produção. `docker-compose.dev.yml` sobe um Postgres e um Mongo **locais**
para rodar a aplicação manualmente durante o desenvolvimento. Os testes
automatizados não dependem disso (ver "Testes").

```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps   # espera ficar "healthy"
cp .env.example .env
```

- **Postgres** (porta 5432): schema e funções inicializados por
  `db/postgres-init/`, cópias de bootstrap do repositório
  `delta-app-ofc/delta-sql-database` — a fonte de verdade do schema continua lá
  (detalhe de origem de cada arquivo em `db/README.md`).
- **Mongo** (porta 27017, replica set de 1 nó): inicializado por
  `db/mongo-init/seed.js`, autoral deste repositório. O replica set existe
  porque o motor de detecção de vazamento usa MongoDB Change Streams, que
  exigem isso (ver seção do motor abaixo).

## Testes

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

Todos os testes são puros ou usam LLM falso/tools stubadas — nenhum depende
de Postgres/Mongo rodando. Cobrem os dois agentes, o cálculo determinístico da
previsão e o motor de detecção (regras, EWMA da baseline, scorer).

## Estrutura de `app/tools/`

As tools ficam organizadas por agente, para deixar claro o que pertence a
quem:

```
app/tools/
├── exceptions.py       # todas as exceções do projeto
├── models.py           # dataclasses compartilhados
├── db_postgres.py       # leitura crua do PostgreSQL, sem @tool
├── db_mongo.py           # leitura crua do MongoDB, sem @tool
├── forecast/             # tudo do Agente de Previsão
│   ├── calculations.py   # cálculo determinístico (sem LLM)
│   └── tools.py          # as tools que o LLM chama de verdade
└── leak/                 # tudo do Agente de Vazamento
    ├── analysis.py       # resumo descritivo de janelas já sinalizadas
    └── tools.py          # as tools que o LLM chama de verdade
```

`app/agents/forecast.py` e `app/agents/leak.py` são só a "cola": pegam o
prompt (`app/services/prompts.py`) e as tools prontas (`app/tools/forecast/`,
`app/tools/leak/`) e rodam o laço de tool-calling (`app/agents/_runtime.py`,
um substituto pequeno pro `AgentExecutor` do LangChain, que a versão 1.x
removeu).

## Agente de Previsão

Projeta consumo até o fim do mês, estima a próxima conta, descreve a
tendência de consumo e avalia risco de ultrapassar a meta cadastrada.

- `ForecastAgent(user_id, llm=None, today=None)` — standalone (sem LangGraph,
  sem FastAPI, sem chamar outros agentes). `.run(question)` devolve
  `AgentResult(response, tool_calls)`, com o registro de quais ferramentas
  foram chamadas e o que cada uma retornou.
- Tools (`app/tools/forecast/tools.py`), todas amarradas ao `user_id` (nunca
  exposto ao LLM): `check_can_estimate`, `get_last_bill`,
  `get_consumption_history`, `get_daily_target`, `get_region_rate`,
  `calculate_forecast`.
- Todo número da resposta vem de `app/tools/forecast/calculations.py`, Python
  puro — o LLM nunca calcula. `check_can_estimate` (que reproduz
  `fn_user_can_estimate` do banco) é sempre checado antes de qualquer
  estimativa; se vier `False`, nenhum cálculo roda.
- Estimativa da próxima conta: usa a última conta cadastrada quando não há
  histórico Mongo suficiente (menos de 7 dias); usa projeção de consumo ×
  tarifa vigente quando há.
- Usa `llm_especialista` (Gemini com fallback Groq, `app/services/llms.py`).

## Agente de Vazamento

Identifica indícios de vazamento a partir de sinais que o motor de detecção
já calculou. Nunca afirma um diagnóstico definitivo — só descreve o padrão
sinalizado e explicita que é um indício, não uma certeza.

- `LeakAgent(user_id, llm=None)` — mesmas garantias de standalone do
  `ForecastAgent`.
- Tools (`app/tools/leak/tools.py`), só MongoDB: `get_anomalous_windows`
  (janelas com `anomaly_detected: true`), `get_alerts_history` (com opção
  `only_active`), `summarize_anomalous_windows` (resumo descritivo puro em
  `app/tools/leak/analysis.py` — quantas janelas, quando, duração, litros,
  quantas de madrugada).
- Sem tool de limiar/detecção própria: quem decide o que é indício é o motor
  de detecção, descrito a seguir.

## Motor de detecção de vazamento (`detection/`)

Componente separado do chat, sem LLM: calcula `anomaly_detected` em
`consumption_summary` e cria alertas em `alerts_history` — exatamente o que o
Agente de Vazamento só lê.

Detecta com regras explicáveis (`detection/rules.py`, combinadas em
`detection/scorer.py`): fluxo contínuo (janela nunca volta a ~zero por 30+
minutos), consumo de madrugada (só para propriedades `RESIDENCIAL`), e desvio
extremo da baseline estatística do próprio usuário. Nenhum modelo de ML —
toda decisão é auditável e vem de um `reasons` explícito, nunca de uma
"caixa-preta".

A baseline por usuário/hora (`detection/baseline.py`) fica guardada no Mongo
(`db_delta_app.user_hour_baseline`) e é atualizada de forma incremental
(EWMA) a cada janela nova, em vez de reler o histórico inteiro do usuário a
cada vez. `detection/watcher.py` reage quase em tempo real via MongoDB Change
Streams — por isso o Mongo local roda como replica set.

Detalhe completo de cada peça, com o motivo de cada escolha, em
[`detection/README.md`](detection/README.md).

## Acesso a dados: SQL direto ao Postgres

`app/tools/db_postgres.py` lê o Postgres direto (SQL + as funções do banco:
`fn_user_can_estimate`, `fn_get_current_region_rate`,
`fn_get_property_classification`), em vez de passar pela API REST
`delta-api-postgres`. Essa API hoje só tem endpoints de CRUD por id
(`/delta/property/{id}`, `/delta/device/{id}`, `/delta/region-rate/{regionId}`
etc.) e nenhum caminho de `user_id` até propriedade/região/última conta — que
é o que toda tool de Previsão precisa.

`get_property_classification` usa uma função nova no banco,
`fn_get_property_classification(property_id)`, no mesmo padrão de
`fn_get_property_region` (que já existia).

## `app/services/prompts.py` e `app/services/llms.py`

Arquivos compartilhados pelos 7 agentes da arquitetura. Os blocos de
ferramentas de `PREVISAO_PROMPT` e `VAZAMENTO_PROMPT` citam só o nome de cada
tool — a descrição de quando/como usá-la mora na docstring da própria tool,
que o LLM já recebe no schema; repetir isso no prompt custaria token à toa.
`llms.py` cria os clientes de LLM sob demanda (no primeiro uso, não no
import), sem alterar provedor ou modelo.
