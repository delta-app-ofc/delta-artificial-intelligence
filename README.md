# delta-artificial-intelligence

Chatbot de IA do Projeto Delta — plataforma de monitoramento inteligente de
consumo residencial de água. Este repositório reúne os agentes especialistas
e as tools de acesso a dados; a API HTTP (FastAPI), o roteamento entre
agentes (LangGraph), guardrails e memória de sessão ainda são só o esqueleto
de pastas, sem implementação.

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

A suíte versionada em `tests/test_rag.py` verifica o ciclo documental RAG com
Qdrant em memória e modelos controlados. O próprio arquivo isola o ambiente e
o cache de settings; os testes não leem `.env` nem chamam bancos ou provedores remotos.

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

`llm_rapido` usa Groq (`GROQ_FAST_MODEL`, default `openai/gpt-oss-20b`), mas
nenhum roteador ou juiz implementado o consome. Timeout, retries e limite de
saída são configuráveis. A disponibilidade depende da conta e do identificador;
os testes não medem qualidade em português. Justificativas, parâmetros e
fontes oficiais estão em [provedores e modelos](docs/llm-models.md).

## Console de testes dos agentes

O console usa HTML, CSS e JavaScript servidos pelo FastAPI, com as cores,
fontes e identidade visual do **delta-web-app**. Inicie na raiz deste repositório:

~~~bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

Acesse **http://127.0.0.1:8000/playground/**. O console usa o
**user_id 12345679** e o nome de teste **teste_agentes_25_10**, definidos no
servidor. Ele não cadastra esse usuário ou dados de exemplo e não oferece
configuração de perfil. O usuário precisa existir e ter os vínculos/dados
necessários nos bancos configurados.

- **Chat completo:** guardrails, contexto, roteador e especialistas reais,
  com persistência da conversa no MongoDB. Falha de persistência preserva a
  resposta na tela e aparece no painel de erros.
- **Roteador:** classifica a pergunta com contexto real, sem executar os
  especialistas. Selecionar um agente não significa que ele foi executado.
- **Consumo, Previsão, Vazamento, Hábitos e RAG:** executam diretamente o
  mesmo especialista usado pelo grafo, preservando os guardrails. Consumo
  também está registrado no roteador.
- **Juiz:** placeholder pendente, sem avaliação, modelo ou banco acionado.
  Sua integração foi adiada; o chat informa explicitamente que o ignora.

Cada aba mantém seu rascunho, histórico e sessão separados enquanto a página
estiver aberta. A opção **Nova sessão** gera uma nova conversa na próxima
mensagem; não encerra nem resume a anterior. O chat envia a mesma mensagem
pelo fluxo real do aplicativo, enquanto as abas individuais testam apenas o
especialista. O histórico recente alimenta a classificação; os especialistas
continuam recebendo a pergunta atual conforme o contrato existente.

Não há modo demonstrativo. Configure o arquivo .env a partir de
[.env.example](.env.example): Groq para guardrails/roteador/RAG, Gemini e fallback
Groq para os especialistas, PostgreSQL e MongoDB para os dados, Qdrant e Gemini
embeddings para o RAG. O RAG pode indexar a revisão documental antes da primeira
consulta. Ausência de dados não comprova falha de conexão, e erro de conexão
não vira consumo zero.

Os painéis exibem erros, avisos, etapas, agentes selecionados/executados/ignorados,
ferramentas com entradas e resultados e chamadas reais aos modelos, inclusive
fallback e embeddings. Uma configuração de modelo, sozinha, não aparece como
chamada executada. Os diagnósticos são isolados por requisição e não armazenam
prompts nem credenciais. Dados das ferramentas pertencem ao usuário fixo do teste.
O gráfico usa a biblioteca Plotly instalada no servidor, sem script de CDN.

O console e seus assets ficam habilitados por padrão apenas em **development**
e **test**. Em **staging** e **production** ficam desativados. A variável
**DELTA_PLAYGROUND_ENABLED=true|false**, no processo ou .env, altera essa escolha.
Este é um console interno com usuário fixo, sem autenticação própria: se precisar
habilitá-lo fora do desenvolvimento, restrinja o acesso na infraestrutura.

Rotas de teste (também descritas no Swagger em /docs):

| Método | Caminho | Finalidade |
| --- | --- | --- |
| GET | /playground/config | Identidade fixa e implementação dos agentes |
| POST | /playground/chat | Fluxo completo |
| POST | /playground/router | Classificação sem executar especialistas |
| POST | /playground/agents/{name} | Teste individual ou Juiz ignorado |

As requisições aceitam **message** (1 a 2000 caracteres) e **session_id** opcional;
não aceitam sobrescrever o usuário. A resposta inclui status, response,
session_id, chart_data, agent_results e diagnostics. Os estados são
success, partial, error e skipped.

~~~bash
python -m pytest -q --basetemp .pytest_cache/tmp
~~~

[tests/test_playground.py](tests/test_playground.py) verifica contratos HTTP,
isolamento de usuário e diagnósticos, guardrails, falhas parciais, componentes
pendentes, callbacks de modelos/fallback e proteção do console por ambiente.
Usa substitutos controlados: essa suíte não comprova acesso remoto aos
bancos/provedores nem qualidade semântica.
