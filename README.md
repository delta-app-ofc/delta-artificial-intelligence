# delta-artificial-intelligence

Chatbot de IA do Projeto Delta — plataforma de monitoramento inteligente de
consumo residencial de água. Este repositório reúne os agentes especialistas,
as tools de acesso a dados, a orquestração LangGraph, guardrails de segurança,
memória de sessão e longo prazo, a API HTTP (FastAPI) e o Agente Juiz com Jev.
O Juiz revisa a candidata antes da publicação e permite uma única correção.
Verificações isoladas não comprovam integração com provedores e bancos reais.

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
  Usa um pool de conexões por processo (`DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE` e
  `DB_POOL_WAIT_SECONDS`; `workers × DB_POOL_MAX_SIZE` deve ficar abaixo do
  `max_connections` do PostgreSQL), preserva opções da URI, aplica timeout de
  conexão/consulta e devolve cursor e conexão ao pool mesmo em falhas.
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
[guia MongoDB](https://github.com/delta-app-ofc/delta-handbook/blob/main/DADOS/IA/agentes/mongo-connection.md) antes de usá-lo.

Settings são snapshots em cache. Ao trocar configuração em um processo já
em execução, recarregue os settings e descarte os clientes afetados:
`clear_llm_cache()` para os modelos gerais, `close_clients()` para os dois
clientes Mongo e `close_pool()` de `app.data.db_postgres` para o pool PostgreSQL. Para liberar os clientes OpenAI, aguarde
`close_openai_clients()` de `app.services.llms`. Para o RAG, aguarde `close_rag_clients()` de
`app.services.rag`; para o segundo juiz, aguarde `close_judge_clients()` de
`app.agents.judge_specialist`. Faça essa recarga sem requisições em andamento.
Reiniciar o processo também aplica a nova configuração.

Detalhes: [settings e ambientes](https://github.com/delta-app-ofc/delta-handbook/blob/main/DADOS/IA/agentes/settings.md),
[conector PostgreSQL](https://github.com/delta-app-ofc/delta-handbook/blob/main/DADOS/IA/agentes/postgres-connection.md) e
[conector MongoDB](https://github.com/delta-app-ofc/delta-handbook/blob/main/DADOS/IA/agentes/mongo-connection.md).

## Rastreamento de requisições

Cada requisição encaminhada à API recebe um `X-Request-ID`. O mesmo contexto
acompanha nós do grafo, ferramentas, modelos e fases do RAG. Falhas preservam
os tipos das causas e a localização do código, sem serializar mensagens brutas
de SDKs ou credenciais. O playground mostra os detalhes seguros da execução.

A base expõe `set_event_sink()` para conectar o logging. Ela não configura
handlers, formatadores ou persistência de logs. Veja o [guia de rastreamento](docs/request-tracking.md)
para integrar o consumidor, consultar os eventos e executar os testes.

## Reutilização de clientes

Os clientes de embeddings e Qdrant do RAG e os modelos do juiz especialista
são criados no primeiro uso e reutilizados por processo. A OpenAI compartilha
uma instância por snapshot de configuração entre os papéis generativos. O cache
guarda clientes de comunicação; perguntas, respostas e evidências continuam
sendo construídas em cada chamada. Cada worker mantém suas próprias instâncias.

Um lock protege a primeira criação contra acessos simultâneos. Construções
que falham não entram no cache. O fallback mantém os mesmos parâmetros e
recebe o contexto da chamada atual. Os clientes permanecem abertos após uma
busca e são fechados, incluindo transportes sync/async, pelo `lifespan` da API.
O encerramento tenta fechar os demais recursos mesmo se um deles falhar.
Runners fora da API devem aguardar as funções de fechamento ao terminar.

As verificações de revisão/índice e a geração do embedding da pergunta
continuam acontecendo em cada busca. O primeiro uso ainda paga a criação dos
clientes; essa reutilização não elimina latência de geração ou erros 429.

A metodologia e os resultados medidos estão em
[comparação de latência](docs/client-reuse-benchmark.md).

Os testes isolados de concorrência, falhas, fechamento e contexto executam com:

```bash
python -m unittest discover -s tests -p test_client_reuse.py -v
```

## Base documental RAG

A fonte do produto é [delta-main-source.md](app/knowledge/delta-main-source.md),
incluída neste repositório e na imagem Docker. Esse é o caminho padrão de
`RAG_DOCUMENT_PATH`; caminhos relativos partem da raiz do projeto.

O `RagAgent` usa `app/tools/rag.py` para consultar a coleção `rag_documents`
no Qdrant. A busca usa `GEMINI_EMBEDDING_MODEL`, vetores de 3072 dimensões
e filtros de fonte, revisão do documento e modelo. O agente recebe trechos
com capítulos, subtópicos e linhas para citar nas respostas.

### Conhecimento externo via MCP

O `RagAgent` também oferece `search_external_knowledge` para orientações gerais
sobre conservação e uso consciente da água. O cliente inicia um servidor MCP
local via stdio, que lê somente artigos públicos cadastrados em
`app/integrations/mcp/sources.py`. Não há porta HTTP nem URL livre escolhida pelo
modelo. Perguntas, histórico, dados da conta e chaves do backend não são enviados
à fonte pública. A dependência `mcp>=2.2,<3` fornece o protocolo.

Habilite `MCP_EXTERNAL_ENABLED=true`; timeout total e cache dos textos usam
`MCP_TIMEOUT_SECONDS=45` e `MCP_CACHE_TTL_SECONDS=3600`. O cache é por processo,
limitado ao catálogo, e não serve conteúdo vencido quando a fonte falha.
Para testar apenas MCP e a página pública, sem embeddings ou banco:

```powershell
python -m scripts.check_mcp --all
```

Esse diagnóstico acessa a internet e pode ser executado mesmo com a consulta
externa desabilitada no chatbot. A busca vetorial exige a mesma configuração
Gemini/Qdrant da base local. As fontes externas são indexadas separadamente por
fonte, revisão e modelo, sem alterar a coleção de memória. O resultado oferece
top-k de 1 a 20, filtros exatos `topic`/`source_id`, URL, título, publicação,
coleta e linhas do texto extraído normalizado. Artigos públicos não comprovam
dados da conta nem definem funcionalidades do Delta.

A pergunta reaproveita o mesmo embedding entre as fontes selecionadas. A coleta,
o cache e a verificação/indexação das revisões continuam no fluxo anterior; a
primeira consulta ou uma revisão nova ainda pode demorar. As citações mostram
título/link uma vez por documento, com datas/revisão/linhas nas evidências do Juiz.

A contagem oficial dos tokens de embeddings ocorre na mesma thread que já grava
as métricas HTTP, depois da resposta. O Monitor indica custo parcial e contagem
pendente até a atualização do mesmo request_id; falhas ficam sem contagem, sem
estimar tokens. O tempo dessa contagem fica separado da latência da resposta.
Os textos usados para contar ficam apenas em memória e não são persistidos.
Se o processo for interrompido antes de concluir, o registro pode permanecer
pendente. Runners que usam Trace fora do HTTP podem chamar
complete_embedding_counts(trace) ao terminar para fechar a contabilização.

O agente preserva os trechos nas evidências do Juiz e monta a lista final de
fontes a partir das ferramentas. Falhas retornam `unavailable`; filtros sem
correspondência retornam `insufficient_data`. O catálogo segue as fontes
propostas no handbook: MIDR/gov.br sobre uso consciente, EPA Start Saving para
residências e EPA Types of Facilities para instalações comerciais. A fonte geral
atende os dois perfis; a ferramenta é vinculada ao perfil confiável do backend
(`residential` ou `organizational`), que o LLM não pode mudar. Chamadas sem perfil
usam somente a fonte geral. O artigo do Senado foi retirado do catálogo ativo.

O prompt proíbe recomendações ou promoção de programas, selos, produtos e
campanhas WaterSense, mantendo a citação da URL original da EPA. As orientações
devem ser adequadas ao perfil e à instalação, com resposta em português. As
páginas educativas não comprovam tarifas vigentes, normas brasileiras ou dados
da conta; a ausência de fonte tarifária deve ser declarada. A publicação da
página MIDR fica sem data quando não confirmada, sem inventar uma data.

```powershell
$env:APP_ENV = 'test'
python -m pytest tests/test_mcp_sources.py tests/test_external_rag.py tests/test_rag_workflow_integration.py -q
```

Os testes usam protocolo MCP e Qdrant em memória, HTTP e modelos controlados.
Não medem a qualidade semântica do Gemini nem validam o Qdrant remoto.
A2A está fora do escopo por decisão de negócio em 01/11/2026.
Contrato, operação e critérios de aceite estão no
[guia MCP/RAG do handbook](https://github.com/delta-app-ofc/delta-handbook/blob/docs/mcp-fontes-externas-rag/IA/mcp-fontes-externas-rag.md).

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

A validação de primeira carga, reutilização do índice, atualização e recuperação
após falha deve considerar a revisão e o modelo efetivos. Acesso remoto e
qualidade semântica das respostas precisam de verificação própria.

## Agente Juiz e revisão

O `JudgeAgent` usa Jev pela integração `langchain-typesafe`. A candidata
composta é avaliada junto com as ferramentas e fontes dos especialistas.
A política Jev consulta gravidade (Choice), suporte factual e relevância (Noul)
na mesma chamada. Seus limites continuam em `JEV_CONFIDENCE_THRESHOLD`,
`JEV_PROBABILITY_THRESHOLD`, `JEV_FACTS_SUPPORTED_THRESHOLD` e
`JEV_RELEVANCE_THRESHOLD`. A rubrica e sua versão ficam em `app/config.py`.
A versão `delta-judge-fixed-v7` trata outputs reais como evidência, aceita
arredondamentos coerentes e distingue limitações verdadeiras de erros
materiais. O nome da ferramenta não basta: valores, períodos e estados devem
sustentar a conclusão. Falha de consulta não comprova ausência de dados;
sinal anômalo, alerta registrado e notificação enviada são fatos distintos.
Os três critérios continuam na mesma chamada, com os mesmos limites e fluxo.
As descrições das categorias também são compartilhadas com o segundo juiz.

O direcionamento usa o mesmo `JEV_CONFIDENCE_THRESHOLD`, com default
**0,70**: confidence maior ou igual mantém o parecer Jev; abaixo desse valor,
o `SpecialistJudgeAgent` dá o segundo parecer com o modelo selecionado.
O padrão é OpenAI `gpt-6-luna` com raciocínio `medium`.
O mesmo limiar de confiança é usado na política Jev e no encaminhamento.
O segundo juiz pode aprovar a candidata, pedir uma correção ou bloquear com
a resposta segura. Uma falha Jev continua bloqueando; não equivale a uma
avaliação de baixa confiança.

O segundo juiz recebe a pergunta e a candidata completas, contexto, evidências,
gráfico e o parecer original Jev, incluindo categoria, valores, critérios
pendentes e justificativa disponível. O prompt diretivo e os novos parâmetros
ficam em `app/config.py`, junto da rubrica compartilhada com o Jev.
No modo OpenAI, o segundo juiz usa `OPENAI_MODEL` e `OPENAI_REASONING_EFFORT`.
No modo `LLM_PROVIDER=gemini`, usa `JUDGE_SPECIALIST_MODEL` e `GEMINI_API_KEY`.
Os limites `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES` e `LLM_MAX_OUTPUT_TOKENS`
continuam configuráveis.

Com `LLM_FALLBACK_ENABLED=true`, falhas transitórias do provedor principal (timeout,
conexão, HTTP 408/429 ou 5xx) encaminham o mesmo prompt e contexto ao Groq,
usando `GROQ_API_KEY` e `GROQ_SPECIALIST_MODEL`. Erros permanentes ou
pareceres inválidos encerram com resposta segura. O log
`Agente Juiz Especialista: openai -> Groq` (ou `google -> Groq` no modo legado) e o evento
`judge.specialist.fallback` registram a transferência; `assessment.provider`
e `assessment.model` identificam o provedor que respondeu. O Groq continua
no papel de juiz especialista e preserva a mesma regra de revisão.

Há no máximo uma correção por solicitação. O juiz que pediu a correção avalia
o retry: Jev quando sua confiança inicial atingiu o limiar; o segundo juiz quando o
parecer veio do especialista. Se o Jev avaliar o retry com baixa confiança,
esse parecer também segue ao segundo juiz. Uma nova solicitação de correção na
segunda rodada bloqueia; candidata e gráfico rejeitados não são publicados.

A transferência gera o log `Jev -> Agente Juiz Especialista` e o evento
`judge.fallback` somente quando ocorre. O parecer do segundo juiz fica no
histórico com `assessment.reviewer=specialist`; o parecer Jev original
permanece em `assessment.jev_result`. O segundo juiz não fornece confidence:
o valor original do Jev é preservado nesse registro, sem inventar outro número.

Os testes em tests/test_client_reuse.py e tests/test_openai_models.py cobrem
cache, fechamento, configuração, tools, JSON e tratamento de falhas com
provedores substituídos. Não medem a qualidade semântica do Jev.

## Validação manual

O arquivo `manual_chat_judge.py` executa guardrails, roteador, especialistas,
tools, Jev, eventual revisão e saída, sem iniciar um servidor HTTP:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manual_chat_judge.py --user-id 1 --no-history
~~~

Troque `1` pelo usuário autorizado do seu ambiente. Com `--no-history`,
nenhum turno é gravado; leituras de contexto e consultas das ferramentas
continuam sendo reais. Sem essa opção, o runner salva os turnos liberados
no MongoDB. Use `--session-id` para continuar uma sessão do mesmo usuário;
uma linha vazia encerra.

O console mostra a resposta final, as decisões, confidence, justificativas
Python e quantidade de revisões. Ele não imprime candidatas bloqueadas.
As dependências e credenciais devem estar configuradas para cada caminho
usado. Não execute em `APP_ENV=test` esperando carregar o `.env`.

As verificações isoladas da implementação cobriram a política, o transporte
com HTTP simulado e o grafo sem consumir crédito. O runner permite validar
os provedores e dados reais; esse teste não foi executado automaticamente.
A integração e o reuso têm testes persistentes na pasta tests/.

## Testes

A suíte usa unittest, clientes substituídos e transportes HTTP simulados.
Execute na raiz do repositório:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Esses testes não acessam bancos nem provedores reais e não comprovam a
qualidade semântica das avaliações. Veja também [modelos OpenAI](docs/openai-models.md).

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
- Usa `llm_especialista` com o provedor selecionado em `app/services/llms.py`.

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
HTTP. Veja [regras e exemplos de uso](https://github.com/delta-app-ofc/delta-handbook/blob/main/DADOS/IA/agentes/consumption-agent.md).

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
`full_consumption_prompt()` monta a referência temporal no uso.

Os clientes de geração são criados sob demanda em app/services/llms.py.
O padrão usa OpenAI Responses com gpt-6-luna e raciocínio medium para os
especialistas, modelo rápido e segundo juiz. O fallback Groq permanece
configurável para falhas transitórias; o modo LLM_PROVIDER=gemini mantém
a seleção anterior. Os parâmetros e contratos estão em
[modelos OpenAI](docs/openai-models.md).

## Console de testes dos agentes

O console usa HTML, CSS e JavaScript servidos pelo FastAPI, com as cores,
fontes e identidade visual do **delta-web-app**. Inicie na raiz deste repositório:

~~~bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
~~~

Acesse **http://127.0.0.1:8000/playground/**. O console usa o
**user_id 123456789** e o nome de teste **teste_agentes_25_10**, definidos no
servidor. Ele não cadastra esse usuário ou dados de exemplo e não oferece
configuração de perfil. O usuário precisa existir e ter os vínculos/dados
necessários nos bancos configurados.

A preparação manual do usuário de teste e a migração dos registros do ID anterior
estão no [guia do usuário do playground](docs/playground-test-user.md), com um
script PostgreSQL e dois scripts mongosh para as conexões de app e telemetria.
Eles não são executados automaticamente pela API.

Na branch do MCP, a aba **RAG** também resolve o perfil desse usuário no backend
antes de construir o especialista. Para testar as fontes externas, habilite
`MCP_EXTERNAL_ENABLED=true` no processo que executa o playground, além das
configurações de geração, Gemini embeddings e Qdrant. A seleção entre EPA
residencial e comercial usa esse perfil real; escrever outro perfil na pergunta
não o substitui. Perfil desconhecido não libera uma fonte específica.

Exemplos para a aba RAG: “Quais práticas de uso consciente são recomendadas pelas
fontes públicas para o perfil da minha conta?” e “Essas fontes informam uma
tarifa vigente para calcular minha conta?”. Confira `search_external_knowledge`
no painel de ferramentas e as URLs dos trechos. Para testar a revisão pelo Juiz,
use **Chat completo** ou **Juiz**; a aba RAG isolada executa o especialista e
os guardrails.

- **Chat completo:** guardrails, contexto, roteador e especialistas reais,
  com persistência da conversa no MongoDB. Falha de persistência preserva a
  resposta na tela e aparece no painel de erros.
- **Roteador:** classifica a pergunta com contexto real, sem executar os
  especialistas. Selecionar um agente não significa que ele foi executado.
- **Consumo, Previsão, Vazamento, Hábitos e RAG:** executam diretamente o
  mesmo especialista usado pelo grafo, preservando os guardrails. Consumo
  também está registrado no roteador.
- **Juiz:** executa o fluxo completo com especialistas, ferramentas e avaliação
  Jev. A aba mostra decisão, confiança, códigos de justificativa Python e os
  subcritérios consultados.

Cada aba mantém seu rascunho, histórico e sessão separados enquanto a página
estiver aberta. A opção **Nova sessão** gera uma nova conversa na próxima
mensagem; não encerra nem resume a anterior. O chat envia a mesma mensagem
pelo fluxo real do aplicativo; as abas individuais testam cada especialista,
e a aba Juiz executa o fluxo completo com a avaliação antes da publicação. O
histórico recente alimenta a classificação e os especialistas continuam
recebendo a pergunta atual conforme o contrato existente.

Não há modo demonstrativo. Configure o arquivo .env a partir de
[.env.example](.env.example): OpenAI para os papéis generativos, Groq opcional
para fallback, PostgreSQL e MongoDB para os dados e Qdrant/Gemini embeddings
para a recuperação documental. O RAG pode indexar a revisão documental antes da primeira
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

- **Sessão** (`app/memory/session.py`): histórico na coleção `chat_sessions` do
  `db_delta_app` (schema oficial do `delta-mongo-database`). O `session_id` da API é o
  `_id` da sessão em texto e é sempre criado pelo servidor (`create_session`); `/chat` só
  continua sessões que o servidor devolveu. `append_turn`, `load_history_validated` e
  `session_belongs_to_user` só operam em sessões do próprio usuário; sessões marcadas
  como excluídas (`is_deleted`) são ignoradas.
- **Título, prévia e ícone** (`app/services/session_meta.py`): na primeira troca da
  conversa, a LLM rápida gera `title`, `preview` e `icon` (um valor de `ICONS`), gravados na
  sessão em segundo plano. Sem eles, a listagem usa o início das mensagens e o ícone `general`.
  Esses três campos estão documentados no `delta-mongo-database` e no `delta-handbook`.
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
| POST | `/chat/stream` | Igual ao `/chat`, com as etapas por SSE (`text/event-stream`); a resposta só sai ao final |
| GET | `/health` | Status dos serviços configurados |
| GET | `/sessions?limit=20&offset=0` | Lista as sessões do usuário autenticado, da mais recente à mais antiga |
| GET | `/sessions/{session_id}/messages` | Histórico de uma sessão do usuário |
| POST | `/sessions/{session_id}/close` | Encerra uma sessão do usuário |

Todas as rotas, exceto `/health` e `/playground`, exigem `Authorization: Bearer <token>`. **Quem emite o token é o
back-end** (`delta-api-postgres`, `POST /delta/auth/login`); a IA só o confere, sem emitir nada.

- **O token do back-end:** JWT assinado com **RS256** (chave privada dele), válido por 15 minutos. O cabeçalho traz
  `kid`; os campos são `sub` (o id do usuário em `tb_user`, inteiro positivo), `iss`, `aud` e `exp`.
- **O que a IA confere** com a **chave pública** do back-end (`AUTH_PUBLIC_KEY`, caminho do PEM com ou sem
  `file:`, ou o próprio texto PEM; RSA de 2048 bits ou mais): assinatura, `exp`, `iss` (`AUTH_ISSUER`), `aud`
  (`AUTH_AUDIENCE`), `kid` (`AUTH_KEY_ID`) e `sub`. Os padrões (`delta-api`, `delta-api`, `delta-1`) são os do back-end.
- **Usuário ativo:** com `AUTH_CHECK_ACTIVE=true` (padrão), cada requisição confere em `tb_user` se o usuário existe e
  está ativo (`fn_user_is_active`), como o back-end faz. É uma consulta pela chave primária na conexão do pool, cerca
  de 5 ms contra os 8 a 12 s de uma resposta do chat. Inativo ou inexistente responde o mesmo 401; se o banco não
  responder, a requisição é bloqueada com 503, sem detalhes.
- **Respostas:** token ausente, inválido, vencido, de outro emissor ou de outro destinatário, ou `sub` fora do padrão, é
  **401** (a mesma mensagem para todos os casos). Sem chave pública configurada, é **503**.
- **Só desenvolvimento e teste:** sem `AUTH_PUBLIC_KEY`, o `JWT_SECRET` (32 caracteres ou mais) habilita um token
  HS256 com `sub` e `exp`. **Nunca valem os dois ao mesmo tempo** (com a chave pública definida o segredo é ignorado)
  e o HS256 é recusado em `staging` e `production`. O algoritmo é escolhido pela configuração, nunca pelo token, o
  que bloqueia o ataque de "confusão de algoritmo".

O `user_id` vem só do token; o cliente não o envia. O app faz o login no back-end, guarda o `accessToken` e o envia
em cada chamada à IA; quando ele vence, renova no back-end (`/delta/auth/refresh`) e tenta de novo.

`POST /chat` aceita `{"message": "Quanto consumi?"}` (e `session_id` para continuar uma conversa existente;
ids que o servidor não devolveu retornam 404) e devolve
`{"response": "...", "agents_used": ["forecast"], "session_id": "...", "chart_data": null}`.
Sessão de outro usuário e sessão inexistente respondem 404 idêntico, sem revelar se ela existe.

`POST /chat/stream` recebe o mesmo corpo e checa JWT, sessão e histórico antes de abrir o fluxo (401, 404, 503).
Depois devolve eventos `stage` (etapa e rótulo fixo em português, incluindo o plano "Vou consultar ..." e uma linha por consulta), um único `result` (mesmo JSON do
`/chat`, depois da validação) ou `error` (`422` mensagem bloqueada, `500` falha). Leia com `fetch`, pois o
`EventSource` não envia `Authorization`. Detalhes e medições em [redução de latência do chat](https://github.com/delta-app-ofc/delta-handbook/blob/main/IA/reducao-latencia.md), no `delta-handbook`.

`GET /sessions` devolve `{"sessions": [{"session_id", "title", "preview", "icon", "created_at",
"updated_at", "is_open"}], "total": N}`. Use `limit=4` para a lista da home e `offset` no "ver todos".
Ícones possíveis: `routine`, `habits`, `summary`, `report`, `savings`, `leak`, `forecast`,
`consumption`, `tips`, `general`.

### Perfis de usuário (residencial e comercial)

A IA é a mesma, mas se comporta conforme o perfil da conta. O perfil vem de `fn_user_access_kind`
(`residential`, `organizational` ou `none`; se houver os dois vínculos, vale o residencial) e é descoberto
**uma vez por pergunta**, no nó de contexto do grafo (`app/graph/profile.py`). Se o banco não responder, o perfil
fica `unknown` e nenhum agente roda; nunca se assume um perfil.

| Perfil | Agentes liberados | Linguagem e regras |
| --- | --- | --- |
| Residencial | consumo, previsão, vazamento, hábitos, RAG | fala de casa e residência; não separa consumo por imóvel |
| Comercial (organização) | consumo, previsão, vazamento, RAG | fala de unidades e organização; declara unidade e período; compara só as próprias unidades; sem hábitos |
| Sem vínculo | nenhum | qualquer pergunta recebe a orientação para vincular a conta, sem chamar o roteador |

- O roteador recebe o perfil e não escolhe agentes que não servem a ele; se alguém pedir hábitos numa conta
  comercial, a resposta explica que hábitos são só residenciais.
- Cada agente, a síntese e o Juiz recebem um trecho de prompt do perfil (`perfil_bloco` em
  `app/services/prompts.py`); o Juiz trata resposta fora do perfil como erro corrigível.
- As tools de consumo, previsão e hábitos usam o perfil já resolvido, sem consultar o banco a cada chamada
  (sem perfil informado, como no `/playground`, continuam consultando como antes).
- **Ainda não implementado:** vazamento por unidade para contas comerciais. Os alertas e janelas anômalas do
  MongoDB só têm `user_id` e `device_id`; separar por unidade exige uma função nova no `delta-sql-database`
  (dispositivos por propriedade autorizada). Até lá o prompt comercial avisa que o vazamento não é separado por
  unidade. O RAG também ainda não filtra capítulos por perfil (só o prompt orienta).
- Os testes (`tests/user_profile/`) usam modelo falso e bancos substituídos; não comprovam a qualidade das
  respostas com os provedores reais.

### Isolamento de dados entre usuários

- O `user_id` entra pelo token e segue preso às tools por `build_tools(user_id)`; o modelo nunca o recebe
  como argumento nem o vê nas saídas das tools.
- As tools de previsão, vazamento e hábitos validam o `user_id` (inteiro positivo) e limitam janelas de
  `days` a 1..366. As funções organizacionais de `app/data/db_postgres.py` enviam o `user_id` ao banco na
  mesma consulta; as funções `fn_organization_*` (e `fn_user_authorized_property_ids`, do
  `delta-sql-database`) descartam ids de propriedades que não sejam das organizações dele, então um id
  alheio devolve resultado vazio. Isso exige a versão do banco com `p_user_id` nessas funções.
- O guardrail de entrada bloqueia tentativas de agir como outro usuário; o de saída bloqueia respostas que
  citem o id de outro usuário e descarta gráficos com `user_id` alheio.
- O checkpoint do LangGraph é apagado depois de cada chat (o histórico vem do MongoDB), o id do ponto de
  memória de longo prazo inclui o `user_id`, o CORS não permite credenciais e `/health` não expõe detalhes.
- Fora do alcance deste repositório: funções SQL `fn_*` e permissões do banco (`delta-sql-database`), papéis
  dentro de uma organização e a emissão do JWT.

#### Critérios da Fase 6

| Critério | Situação | Onde está |
| --- | --- | --- |
| Identidade propagada pelo fluxo | Implementado e testado | `user_id` vem do JWT (`app/auth.py`), passa por `run_workflow` e fica preso nas tools por `build_tools(user_id)` |
| Filtros de autorização nas tools de dados | Implementado e testado | `user_id` enviado às `fn_organization_*`, que filtram no banco com `fn_user_authorized_property_ids`; escritas de sessão filtradas por `user_id`; validação de `user_id` e de `days` nas tools |
| Acesso cruzado bloqueado | Implementado e testado | 404 igual para sessão alheia e inexistente; `validate_ownership` na saída; padrões de personificação na entrada |
| Testes de isolamento | Implementados | `tests/isolation/` (auth, sessões, camada de dados, tools e guardrails); os de sessão usam MongoDB real |

Os testes de tools e da camada de dados usam bancos substituídos (fakes), então não provam o comportamento
do PostgreSQL real.

#### Limites e pendências conhecidos

- Funções SQL `fn_*` e permissões do banco (RLS) ficam no `delta-sql-database` e não foram verificadas aqui.
- Não há papéis dentro de uma organização: todo usuário vinculado a ela vê todas as unidades (decisão de produto).
- O `/playground` não exige autenticação e vem ativo em desenvolvimento e teste; não foi alterado nesta entrega.
- O classificador de injeção do guardrail de entrada segue "fail-open": se a LLM falhar, a mensagem passa
  (disponibilidade acima de bloqueio).
- `create_habit` não é idempotente (depende da função SQL); resumos de longo prazo gravados antes da
  autenticação podem ter `user_id` forjado e não são verificáveis pelo código.
- A emissão do JWT é do back-end e ainda não existe; a checagem de mutação dos filtros ainda não foi executada.

Testes de histórico e de isolamento usam MongoDB real em um banco descartável `delta_test_*`
(`DELTA_TEST_MONGO_URI`, padrão `mongodb://localhost:27018` do `docker-compose.dev.yml`) e são pulados sem
MongoDB. Os de isolamento ficam em `tests/isolation/`. O acesso da IA ao `chat_sessions` exige a role
`role_api_service`.


O playground classifica a entrada uma vez no grafo do chat/Juiz; abas isoladas
mantêm a validação completa. Ao salvar a primeira resposta, o console cria uma
sessão MongoDB válida; UUIDs antigos são substituídos pelo ObjectId retornado.
