# delta-artificial-intelligence

Chatbot de IA do Projeto Delta — plataforma de monitoramento inteligente de
consumo residencial de água. Este repositório reúne os agentes especialistas,
as tools de acesso a dados, a orquestração LangGraph, guardrails de segurança,
memória de sessão e longo prazo, e a API HTTP (FastAPI).

O motor de detecção de vazamento (regras que calculam `anomaly_detected` e
criam alertas) não usa LLM e por isso mora em outro repositório,
[`delta-business-rules`](https://github.com/delta-app-ofc/delta-business-rules)
— o `LeakAgent` aqui só lê o que ele já sinalizou.

Convenção de código: identificadores (nomes de arquivo, função, classe,
variável) em **inglês**; comentários, docstrings e o conteúdo dos prompts em
**português** (é o idioma em que o chatbot conversa com o usuário final).

Este README é incremental: cada agente/componente novo ganha sua própria
seção, descrevendo o que está implementado. Ele não guarda histórico de
mudanças nem lista de pendências — isso mora na conversa/tarefa que criou cada
parte.

---

## Ambiente local de desenvolvimento

Consulte [DOCKER-HELP.md](DOCKER-HELP.md) para usar o ambiente Docker local.

## Settings e conexões

Copie [`.env.example`](.env.example) para `.env` e configure os componentes
que vai usar. `app/config.py` centraliza os settings; variáveis do processo
prevalecem sobre `.env`. `APP_ENV` aceita `development`, `test`, `staging` e
`production`. O modo `test` ignora `.env`; staging/produção exigem conexões
explícitas, sem substituir uma variável vazia por um default local.

- PostgreSQL aceita `DATABASE_URL` ou o conjunto completo `HOST_DB`,
  `PORT_DB`, `USER_DB`, `PASSWORD_DB`, `NAME_DB`, que tem precedência.
  Abre uma conexão por operação, preserva opções da URI, aplica timeout de
  conexão/consulta e fecha cursor e conexão mesmo em falhas.
- MongoDB mantém clientes lazy separados para app e telemetria, reutilizados
  pelo processo, com datas aware, timeouts e fechamento explícito.
- Credenciais não são exigidas no import. A validação ocorre por componente
  antes do uso, com erros que não expõem senhas, chaves ou URIs.

Para verificar os bancos configurados sem chamar LLM:

```bash
python -m scripts.check_postgres
python -m scripts.check_mongo
```

O primeiro executa `SELECT 1`; o segundo verifica ping e leitura de uma
coleção em cada alvo Mongo, sem imprimir documentos. Conectividade não
comprova que o schema/views do produto ou os dados necessários existam.
O modo Mongo `--fixture` insere, converte e remove documentos sintéticos
somente em databases de teste isolados em loopback; veja os requisitos no
[guia MongoDB](docs/mongo-connection.md) antes de usá-lo.

Settings são snapshots em cache. Ao trocar configuração em um processo já
em execução, recarregue os settings e descarte os clientes afetados:
`clear_llm_cache()` para modelos e `close_clients()` para os dois clientes
Mongo. Reiniciar o processo também aplica a nova configuração.

Detalhes: [settings e ambientes](docs/settings.md),
[conector PostgreSQL](docs/postgres-connection.md) e
[conector MongoDB](docs/mongo-connection.md).

## Base documental RAG

A fonte do produto é [delta-main-source.md](app/knowledge/delta-main-source.md),
incluída neste repositório e na imagem Docker. Esse é o caminho padrão de
`RAG_DOCUMENT_PATH`; caminhos relativos partem da raiz do projeto.

O `RagAgent` usa `app/tools/rag.py` para consultar a coleção `rag_documents`
no Qdrant. A busca usa `GEMINI_EMBEDDING_MODEL`, vetores de 3072 dimensões
e filtros de fonte, revisão do documento e modelo. O agente recebe trechos
com capítulos, subtópicos e linhas para citar nas respostas.

### Indexação automática antes da consulta

A coleção `rag_documents` precisa existir no Qdrant, com vetores de 3072 dimensões.
Configure `GEMINI_API_KEY`, `GEMINI_EMBEDDING_MODEL`, `QDRANT_URL` e, quando exigido,
`QDRANT_API_KEY` com permissão de leitura e escrita nessa coleção. A fonte vem de
`RAG_DOCUMENT_PATH`; o agente não aceita caminhos de arquivo fornecidos pelo LLM.

Em cada chamada a `search_knowledge_base`, a aplicação executa este fluxo:

1. Lê e segmenta o documento por `#`, `##` e `###`, preservando hierarquia e linhas.
2. Calcula a revisão SHA-256 e verifica se todos os trechos dessa fonte, revisão e
   modelo já estão indexados.
3. Se a revisão estiver ausente ou incompleta, chama `index_document()` e aguarda
   a gravação. Confirma a quantidade de trechos antes de continuar.
4. Gera o embedding da pergunta, recupera os trechos atuais e entrega as fontes
   para o `RagAgent` elaborar a resposta.

A primeira consulta e a primeira consulta após uma alteração da fonte ou do modelo
podem levar mais tempo, pois também geram os embeddings do documento. Com a revisão
completa, as próximas consultas reutilizam os vetores existentes. A atualização
acontece durante a chamada da tool, sem comando manual ou decisão adicional do LLM.

Os IDs derivam da fonte, revisão, modelo e posição do trecho. Uma tentativa repetida
sobrescreve os mesmos pontos, sem duplicá-los. Renomear ou mover o arquivo sem alterar
seu conteúdo não muda a revisão. Revisões anteriores permanecem como histórico,
excluídas da recuperação pelo filtro de revisão atual; trechos removidos deixam de
ser recuperados. Um lock evita indexações simultâneas no mesmo processo; processos
diferentes mantêm a idempotência pelos IDs, mas podem gerar embeddings em paralelo.

Se a preparação ou consulta falhar, a tool retorna `unavailable` sem recuperar a
revisão antiga. Uma nova chamada tenta completar a revisão automaticamente. A tool
não cria nem recria a coleção; coleção ausente ou dimensão incompatível exige ajuste
da infraestrutura. A dimensão permanece fixa em 3072.

Os testes em `tests/test_rag.py` cobrem primeira carga automática, reutilização do
índice, edição, inclusão, remoção, renomeação, troca de modelo, consultas simultâneas
e recuperação após falha. Usam Qdrant em memória, embeddings controlados e um modelo
de resposta controlado; o acesso remoto e a qualidade semântica exigem validação própria.

## Testes

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

Os testes usam cálculos puros, LLM roteirizado e clientes/leitores substituídos.
Cobrem settings, provedores/fallback, recursos e erros dos conectores, os agentes
e seus cálculos, o workflow LangGraph (guardrails, context-passing, síntese,
roteamento), as rotas HTTP e cenários de anti-alucinação. Nenhum depende de
Postgres/Mongo ou de uma chamada real de LLM. `tests/conftest.py` isola o
ambiente e o cache de settings.

Esses testes não comprovam acesso real, disponibilidade do modelo para a
conta ou qualidade da redação. Na validação local deste conjunto, Docker
Engine e serviços de banco estavam indisponíveis e não havia credenciais
LLM. Os checks reais de PostgreSQL/Mongo falharam com diagnósticos seguros;
a avaliação ponta a ponta continua pendente. O workflow organizacional de
PR não executa pytest: rode a suíte antes de enviar alterações.

## Estrutura de `app/data/` e `app/tools/`

`app/data/` tem a leitura crua dos bancos, sem `@tool`. `app/tools/` tem as
tools organizadas por agente, que chamam `app/data/` por baixo:

```
app/data/
├── db_postgres.py       # leitura crua do PostgreSQL
└── db_mongo.py           # leitura crua do MongoDB (2 clusters Atlas: app + telemetria)

app/tools/
├── exceptions.py       # todas as exceções do projeto
├── models.py           # dataclasses compartilhados
├── consumption/          # tudo do Agente de Consumo
│   ├── analysis.py       # períodos e cálculos descritivos (sem LLM)
│   └── tools.py          # resumo, série diária, comparação, picos e unidades
├── forecast/             # tudo do Agente de Previsão
│   ├── calculations.py   # cálculo determinístico (sem LLM)
│   └── tools.py          # as tools que o LLM chama de verdade
└── leak/                 # tudo do Agente de Vazamento
    ├── analysis.py       # resumo descritivo de janelas já sinalizadas
    └── tools.py          # as tools que o LLM chama de verdade
```

`app/agents/consumption.py`, `forecast.py` e `leak.py` são a "cola": pegam o
prompt (`app/services/prompts.py`) e as tools prontas (`app/tools/forecast/`,
`app/tools/consumption/`, `app/tools/leak/`) e rodam o laço de tool-calling (`app/agents/_runtime.py`,
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

## Agente de Consumo

Descreve consumo registrado, histórico diário, comparação de períodos e picos
diários. O LLM consulta as tools e interpreta os resultados; totais, médias,
diferenças, percentuais e ranking são calculados em Python.

- `ConsumptionAgent(user_id, llm=None, *, now=None, clock=None,
  timezone_name="America/Sao_Paulo")` retorna `AgentResult` em `.run(question)`.
  Cada execução captura um único instante para prompt e consultas; a próxima
  execução renova essa referência. `now` ou `clock` podem ser injetados em testes.
- Tools: `get_consumption_summary`, `compare_consumption_periods`,
  `get_consumption_peaks` e `list_consumption_units`. O resumo entrega série
  diária agregada, litros, dias com registros, média e contexto de qualidade.
  O `user_id` fica vinculado às tools e não é argumento livre do modelo.
- O vínculo residencial tem prioridade: consulta janelas Mongo pelo usuário,
  com limites UTC e somente janelas finalizadas. O caminho organizacional
  resolve unidades autorizadas e consulta `dw.vw_ft_consumption_daily`.
  Nomes ambíguos pedem esclarecimento; IDs são conferidos antes da leitura.
- Períodos internos usam início inclusivo e fim exclusivo. Hoje termina no
  instante consultado, semana começa na segunda e mês no dia 1. Últimos 7/30
  dias são janelas móveis; datas customizadas são inclusivas na entrada e
  limitadas a 366 dias. Histórico/picos usam últimos 30 dias por padrão.
- Ausência não vira zero. A média usa dias com registros e lacunas conhecidas
  indicam resultado parcial. Base anterior zero deixa o percentual indisponível.
  Duplicatas idênticas no mesmo dispositivo contam uma vez; valores conflitantes,
  negativos ou não finitos produzem inconsistência.

O Mongo atual não segmenta registros residenciais por imóvel. O SQL fornece
totais diários, sem horário de leitura ou pico horário, e depende da view e
do carregamento do ETL. Janelas de fronteira não são rateadas. Nenhuma das
fontes garante cobertura contínua; o agente informa esses limites e não
calcula custo, previsão futura ou diagnóstico de vazamento.

```bash
python manual_chat.py consumption "Quanto consumi ontem?"
```

O modo manual usa um ID demonstrativo definido no arquivo e precisa dos
bancos e do LLM configurados. Uma integração deve fornecer o usuário
autenticado pelo backend; este repositório ainda não implementa autenticação
HTTP. Veja [regras e exemplos de uso](docs/consumption-agent.md).

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

### Limitação conhecida — cobertura organizacional

O Agente de Vazamento ainda não distingue unidades de uma organização
multi-propriedade: as coleções do MongoDB (`consumption_summary`,
`alerts_history`) são indexadas só por `user_id`, sem `property_id`/
`organization_id` consultável. Um usuário "gestor" (vínculo só via
`tb_user_organization`) recebe respostas de "sem indícios"/"dados
insuficientes" quando não há documentos Mongo associados ao seu `user_id` —
não é um erro, é a ausência de dado granular por propriedade nessa camada.
Corrigir isso depende de mudança no pipeline de ingestão/`delta-business-rules`
(fora de escopo desta tarefa) para gravar `property_id` nos documentos.

## Motor de detecção de vazamento — repositório `delta-business-rules`

Quem calcula `anomaly_detected` em `consumption_summary` e cria alertas em
`alerts_history` não mora aqui: é um componente sem LLM (regras explicáveis +
baseline estatística incremental), e por não precisar de IA generativa vive
no repositório
[`delta-app-ofc/delta-business-rules`](https://github.com/delta-app-ofc/delta-business-rules)
(pasta `detection/` lá). O Agente de Vazamento deste repositório só lê o que
já foi sinalizado — nunca decide um limiar sozinho.

## Acesso a dados: SQL direto ao Postgres

`app/data/db_postgres.py` lê o Postgres direto (SQL + as funções do banco:
`fn_user_can_estimate`, `fn_get_current_region_rate`), em vez de passar pela
API REST `delta-api-postgres`. Essa API hoje só tem endpoints de CRUD por id
(`/delta/property/{id}`, `/delta/device/{id}`, `/delta/region-rate/{regionId}`
etc.) e nenhum caminho de `user_id` até propriedade/região/última conta — que
é o que toda tool de Previsão precisa.

## `app/services/prompts.py` e `app/services/llms.py`

Arquivos compartilhados pelos 7 agentes da arquitetura. Os blocos de
ferramentas de `PREVISAO_PROMPT` e `VAZAMENTO_PROMPT` citam só o nome de cada
tool — a descrição de quando/como usá-la mora na docstring da própria tool,
que o LLM já recebe no schema; repetir isso no prompt custaria token à toa.
`CONSUMO_PROMPT` exige contexto do período, escopo, granularidade e lacunas;
`consumo_prompt_completo()` monta a referência temporal no uso.

`llms.py` cria os clientes sob demanda a partir dos settings. Os três agentes
usam `llm_especialista`: Gemini (`GEMINI_MODEL`, default `gemini-2.5-flash`)
com fallback Groq (`GROQ_SPECIALIST_MODEL`, default `openai/gpt-oss-120b`).
O fallback preserva `bind_tools` e histórico, sem repetir tools já executadas,
e só é acionado para erros transitórios reconhecidos. Pode ser desativado
com `LLM_FALLBACK_ENABLED=false`.

`llm_rapido` usa Groq (`GROQ_FAST_MODEL`, default `openai/gpt-oss-20b`) e é
usado pelo router e pelo nó de síntese do workflow. Timeout, retries e limite
de saída são configuráveis. A disponibilidade depende da conta e do identificador;
os testes não medem qualidade em português. Justificativas, parâmetros e
fontes oficiais estão em [provedores e modelos](docs/llm-models.md).

## Agente de Hábitos

Analisa hábitos de consumo registrados, estima seu impacto hídrico e relaciona
com dados de clima (histórico e previsão) para contextualizar variações sazonais.

- `HabitsAgent(user_id, llm=None)` — standalone, sem dependência de FastAPI ou LangGraph.
- Tools (`app/tools/habits/tools.py`), todas vinculadas ao `user_id`:
  - `list_habits` — lista hábitos cadastrados.
  - `get_habits_by_day` — filtra por dia da semana.
  - `create_habit` — cadastra um novo hábito (grava em `tb_user_habit` + `tb_user_habit_day`).
  - `estimate_habit_water_impact` — calcula impacto médio em litros.
  - `get_weather_history` — lê a coleção `weather_daily` (MongoDB) e devolve
    temperatura, chuva e condição predominante dos últimos N dias. Requer
    localização do usuário (cidade/estado via `tb_address`).

O agente não envia o `user_id` como argumento livre ao LLM; a localização é
obtida internamente em `get_user_location`.

## Orquestração LangGraph

`run_workflow(user_id, session_id, question)` em `app/graph/workflow.py` é o
ponto de entrada para o chatbot. O grafo executa os nós nesta ordem:

```
guardrail_input → context → route → execute → synthesize → respond → guardrail_output → END
                ↘ (_blocked)
                END
```

- **guardrail_input**: valida a mensagem (veja "Guardrails"). Se bloqueada,
  retorna imediatamente sem chamar nenhum agente. A rota HTTP pode setar
  `skip_guardrail_input=True` para evitar dupla validação.
- **context**: recupera histórico de sessão e memória de longo prazo.
- **route**: `llm_rapido` classifica a intenção e escolhe os agentes. Intenção
  `privacy_violation` (pergunta sobre outros usuários) bloqueia a execução antes
  do nó execute.
- **execute**: chama cada agente em sequência. O segundo agente em diante recebe
  a pergunta original **mais** um bloco "Contexto dos agentes anteriores:" com os
  primeiros 300 caracteres da resposta de cada agente anterior — sem re-consultar
  o banco, preservando a rastreabilidade da origem.
- **synthesize**: quando ≥ 2 agentes têm sucesso, `llm_rapido` unifica as
  respostas em texto coeso, indicando a origem de cada dado. Falha silenciosa
  (concatenação bruta como fallback).
- **respond**: monta a resposta final.
- **guardrail_output**: sanitiza a resposta (PII, credenciais) e persiste o
  histórico de sessão.

## Guardrails

Aplicados em duas camadas (defesa em profundidade): na rota HTTP
(`app/routes/chat.py`) e no workflow (`app/graph/workflow.py`).

**Entrada** (`app/guardrails/input.py` — `validate_input`):
- Bloqueia mensagens vazias, muito longas (> 2000 chars) ou com `user_id` inválido.
- Detecta padrões de injeção de prompt (15 regras regex) e palavras-chave internas.
- Anonimiza PII (CPF, CNPJ, telefone, e-mail) com tokens `[PII_TIPO_hash]` antes
  de repassar ao LLM. O mapa de tokens é armazenado em `GraphState.pii_map`.

**Saída** (`app/guardrails/output.py` — `validate_output`):
- Bloqueia respostas vazias ou com padrões de credencial ("senha:", "token:").
- Redige CPF/CNPJ/telefone que apareçam diretamente no texto como `[TIPO OMITIDO]`.
- Resolve tokens PII da entrada (substitui o token pelo indicador `[TIPO OMITIDO]`,
  nunca devolve o valor original).

## Memória de sessão e longo prazo

- **Sessão** (`app/memory/session.py`): histórico de mensagens por `session_id`
  no MongoDB. `append_turn` valida ownership antes de gravar. `load_history_validated`
  verifica que a sessão pertence ao usuário antes de retornar.
- **Longo prazo** (`app/memory/long_term.py`): embeddings Gemini armazenados no
  Qdrant. Consultada pelo nó `context` quando a pergunta referencia o passado.

## API HTTP

```bash
uvicorn app.main:app --reload
# Swagger UI: http://localhost:8000/docs
```

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/chat` | Envia mensagem ao chatbot |
| GET | `/health` | Status dos serviços configurados |
| GET | `/users/{user_id}/sessions` | Lista sessões do usuário |
| GET | `/sessions/{session_id}/messages` | Histórico de uma sessão |
| POST | `/sessions/{session_id}/close` | Encerra uma sessão |

`POST /chat` aceita `{"user_id": 1, "message": "Quanto consumi?"}` e devolve
`{"response": "...", "agents_used": ["forecast"], "session_id": "...", "chart_data": null}`.

O `user_id` deve vir do backend autenticado — este repositório não implementa
autenticação HTTP.
