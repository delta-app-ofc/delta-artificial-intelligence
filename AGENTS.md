# AGENTS.md — Contexto do delta-artificial-intelligence

Este arquivo orienta agentes de IA e pessoas desenvolvedoras que atuam neste repositório. Leia-o antes de alterar arquivos e confirme a implementação real, pois algumas pastas ainda são apenas estruturas reservadas.

## 1. Visão geral do Projeto Delta

O Delta é um projeto acadêmico de Ensino Médio Técnico em Análise e Desenvolvimento de Sistemas. A plataforma IoT monitora o consumo residencial de água: dispositivos conectados a hidrômetros enviam leituras para serviços que consolidam o consumo, apoiam a detecção de vazamentos e estimam gastos, com acesso por aplicações e chatbot.

A arquitetura de dados documentada distribui responsabilidades entre PostgreSQL, para dados cadastrais e transacionais, e MongoDB, para telemetria e dados de aplicação. Redis e Neo4j aparecem como componentes planejados; não presuma que estejam implementados neste workspace.

Os repositórios Delta são independentes. Faça alterações e operações Git dentro do repositório responsável, sem presumir estruturas internas de outros repositórios.

## 2. Contexto e estado atual deste repositório

O `delta-artificial-intelligence` contém agentes Python de consumo, previsão,
vazamento, hábitos e RAG, além da API FastAPI, do workflow LangGraph, guardrails,
memória, ferramentas de dados e Agente Juiz com Jev. O grafo revisa a candidata
antes da publicação e limita a uma correção por solicitação. Testes isolados não
comprovam conexão real ou qualidade semântica dos provedores.

A stack inclui Python, FastAPI/Uvicorn, Pydantic, LangChain/LangGraph, OpenAI Responses e Gemini/Groq,
PostgreSQL, MongoDB, Qdrant e langchain-typesafe. Redis consta nas dependências,
sem fluxo de aplicação implementado.

### Componentes implementados

- `ConsumptionAgent`, `ForecastAgent`, `LeakAgent`, `HabitsAgent` e `RagAgent` estão implementados e podem ser usados diretamente; os agentes disponíveis também são registrados no workflow LangGraph.
- `app/tools/consumption/analysis.py` resolve períodos e calcula totais, médias, comparações e picos em Python. `app/tools/consumption/tools.py` entrega resumos com série diária e metadados, vinculados ao usuário confiável; não usa elegibilidade de previsão para bloquear consumo observado.
- Consumo prioriza o vínculo residencial e lê janelas Mongo pelo usuário. No caminho organizacional, resolve unidades autorizadas antes de consultar a view diária SQL; nomes ambíguos não consultam consumo, e `unit_id` nunca dispensa autorização. A fonte residencial não permite segmentar por imóvel.
- Cada `ConsumptionAgent.run()` captura uma referência temporal única para prompt e tools, renovada na próxima execução. O default é `America/Sao_Paulo`; timestamps Mongo são consultados em UTC. Períodos usam [início, fim), datas customizadas são inclusivas na entrada e o limite é 366 dias.
- Consumo diferencia ausência, zero registrado, lacunas, fonte indisponível e dados inconsistentes. Médias usam dias com registros, duplicatas idênticas do mesmo dispositivo contam uma vez e conflitos são rejeitados. A fonte SQL diária não fornece pico horário nem horário da última leitura. Veja `delta-handbook/DADOS/IA/agentes/consumption-agent.md`.
- `app/agents/_runtime.py` implementa um laço simples de chamadas de ferramentas com limite de iterações e registro dos resultados.
- `app/tools/forecast/calculations.py` realiza os cálculos de previsão em Python puro; o LLM não deve calcular os valores numéricos da previsão.
- `app/tools/forecast/tools.py` reúne ferramentas que consultam dados e chamam os cálculos. O usuário residencial usa PostgreSQL e MongoDB; o caminho organizacional consulta dados consolidados no PostgreSQL.
- `app/tools/leak/tools.py` consulta anomalias e alertas já registrados no MongoDB. `app/tools/leak/analysis.py` resume esses sinais; não implementa o motor que detecta vazamentos.
- `app/data/db_postgres.py` contém consultas PostgreSQL para os caminhos residencial e organizacional; `app/data/db_mongo.py` contém leituras de telemetria e dados da aplicação.
- O conector PostgreSQL usa settings, preserva opções da URI e usa um pool de conexões por processo (`DB_POOL_*`, fechado por `close_pool()` no `lifespan`). Aplica `connect_timeout` e `statement_timeout`, fecha cursor/conexão mesmo em falhas e distingue ausência de dados de erro de banco com mensagens públicas seguras.
- `python -m scripts.check_postgres` valida PostgreSQL com `SELECT 1` sem depender de chaves LLM ou do schema do produto. `delta-handbook/DADOS/IA/agentes/postgres-connection.md` registra configuração e limites; a conexão real continua pendente neste ambiente sem serviço/credenciais.
- O acesso MongoDB mantém clientes lazy independentes para app/telemetria, com timezone, timeouts e fechamento explícito via `close_clients()`. Falhas não viram ausência de registros; `DatabaseDataError` identifica documento inválido sem expor detalhes brutos.
- `python -m scripts.check_mongo` verifica ping e leitura de app/telemetria separadamente. A opção `--fixture` exige `APP_ENV=test`, um endpoint loopback por URI, porta explícita e databases distintos prefixados `delta_test_`; limpa somente os IDs próprios. Veja `delta-handbook/DADOS/IA/agentes/mongo-connection.md`. Leitura real de documento permanece pendente neste ambiente.
- `app/config.py` centraliza settings imutáveis em cache e valida cada componente antes do uso. Variáveis do processo prevalecem sobre `.env`; `APP_ENV=test` ignora qualquer arquivo `.env`. Defaults de bancos locais só existem em `development` e para variáveis ausentes, nunca explicitamente vazias.
- `delta-handbook/DADOS/IA/agentes/settings.md` descreve ambientes, precedência, recarga e validação. `.env.example` usa somente valores descartáveis locais; `tests/.env.example` é explicativo e não é carregado pela suíte.
- `app/services/prompts.py` mantém prompts dos sete agentes planejados. Ter prompt definido não significa que o agente correspondente esteja implementado.
- `app/services/llms.py` usa OpenAI Responses por padrão (`gpt-6-luna`, raciocínio `medium`), com clientes compartilhados por snapshot e fechamento no lifespan. `LLM_PROVIDER=gemini` mantém o modo anterior. Os embeddings continuam Gemini. Os consumidores extraem texto dos blocos Responses pelo helper existente. A fábrica configura modelos sob demanda a partir dos settings. O especialista mantém `bind_tools` nos dois provedores e usa Groq como fallback apenas para falhas transitórias; erros permanentes recebem mensagens públicas seguras e erros de programação propagam. O histórico de ferramentas é preservado sem repetir sua execução.
- `delta-handbook/DADOS/IA/agentes/llm-models.md` registra papéis, modelos, parâmetros, retries e fontes oficiais. A disponibilidade de um modelo depende da conta; testes com clientes substituídos não comprovam acesso real nem qualidade das respostas.
- `tests/` contém testes com modelo falso e ferramentas substituídas; os testes não precisam de banco nem de chamadas reais a provedores de LLM.
- `manual_chat_judge.py` permite exercitar o fluxo integrado com guardrails, especialistas, Jev, eventual revisão e saída. A entrada manual não comprova integração remota sem execução com credenciais e dados reais.
- `manual_chat.py` permite exercitar manualmente consumo, previsão e vazamento quando ambiente, bancos e chaves necessários estão configurados. Os IDs fixos são demonstrativos; uma futura integração deve fornecer o usuário autenticado pelo backend.

### Componentes implementados na branch `feat/langgraph-orquestracao`

Os componentes abaixo foram implementados e têm cobertura de testes:

- API e rotas: `app/main.py` (CORS, registro de routers), `app/routes/chat.py`,
  `app/routes/health.py`, `app/routes/sessions.py`, `app/schemas.py`.
- Fluxo LangGraph: `app/graph/workflow.py` (grafo completo com guardrails,
  context-passing, síntese), `app/graph/state.py`, `app/graph/router.py`,
  `app/graph/context.py`.
- Agente `habits`: `app/agents/habits.py`, `app/tools/habits/tools.py`
  (inclui consulta ao histórico de clima no MongoDB `weather_daily`).
- Guardrails: `app/guardrails/input.py` (anonimização PII, detecção de injeção),
  `app/guardrails/output.py` (redação de PII na saída).
- Memória de sessão: `app/memory/session.py` (MongoDB, ownership validado).
- Memória de longo prazo: `app/memory/long_term.py` (Qdrant + embeddings Gemini).
- Observabilidade: `app/observability/` mede tokens, custo, latência por etapa/agente, erros, resolução e ROI; aba Monitor no console, PDF e projeção para 100/1000 usuários. Veja `delta-handbook/IA/observabilidade.md`; LangSmith é opcional e a conexão real não foi validada.

### Componentes ainda sem implementação

- Agente `profile`.

### Conhecimento externo via MCP

`app/integrations/mcp/` contém catálogo fechado, extrator HTML, contrato,
servidor MCP e cliente stdio. O catálogo adota as três fontes propostas no
handbook: MIDR, EPA Start Saving e EPA Types of Facilities. O Senado foi retirado
do catálogo ativo. `app/services/external_knowledge.py` atualiza as fontes no lifespan ou via
`python -m scripts.refresh_external_knowledge`, publica marcadores persistentes
somente para revisões completas e aplica validade máxima da coleta. O chat não
coleta nem indexa páginas: gera um embedding e uma busca para as fontes
autorizadas. `app/tools/external_knowledge.py` recupera artigos públicos
com top-k e filtros exatos de tema/fonte. `RagAgent` vincula a ferramenta ao perfil
confiável: residential para residencial e organizational para comercial. O LLM
não recebe argumento livre de perfil. Sem perfil, somente a fonte geral é usada.
O prompt proíbe recomendar WaterSense, seus programas, selos e produtos, mantendo
a URL original da EPA na citação. Não invente tarifas a partir dessas páginas. A busca exige
`MCP_EXTERNAL_ENABLED=true`, além dos settings Gemini/Qdrant. O subprocesso
recebe somente o identificador da fonte; não recebe perguntas ou credenciais
do backend. O transporte é local, sem serviço HTTP público.

As fontes externas usam o mesmo modelo e esquema de `rag_documents`, com
identificador próprio, revisão, URL e localização no texto extraído. Nunca
recrie uma coleção incompatível. O RAG mantém documentação interna e conteúdo
externo separados e leva os trechos ao Juiz. `scripts/check_mcp.py` verifica
MCP e fonte pública sem banco/LLM; os testes novos distinguem HTTP controlado,
protocolo real, Qdrant em memória e grafo com modelos substituídos. A2A foi
excluído por decisão de negócio em 01/11/2026; não deve ser implementado nem
tratado como pendência desta entrega.

API, grafo, guardrails, memória e agentes registrados têm código. Verifique
o comportamento e as dependências reais antes de descrevê-los como validados.

A fonte documental é `app/knowledge/delta-main-source.md`, caminho padrão de `RAG_DOCUMENT_PATH`, incluída também na imagem Docker. O `RagAgent` usa `app/tools/rag.py` para recuperar trechos de `rag_documents` com fonte, revisão, modelo e linhas, e está registrado no roteador. O modelo de embedding vem de `GEMINI_EMBEDDING_MODEL`; a tool verifica a completude da revisão atual e chama `index_document()` automaticamente quando necessário, antes de consultar. A coleção deve existir previamente com dimensão compatível. O identificador de payload `delta-product-reference` permanece estável ao renomear o arquivo, cuja revisão depende do conteúdo. Testes com Qdrant em memória e embeddings controlados não comprovam Gemini/Qdrant remoto ou qualidade semântica.

Redis aparece nas dependências, mas não há integração de aplicação implementada aqui.
A ingestão e a consulta documental compartilham `app/services/rag.py`. A tool chama
`ensure_document_indexed()` antes de `search_document()`, sem CLI manual. A preparação
verifica fonte, revisão e modelo e indexa apenas se faltar conteúdo. IDs estáveis
preservam a idempotência, e um lock evita gerações simultâneas no mesmo processo.
Revisões anteriores são preservadas e excluídas da consulta. Uma falha retorna
indisponibilidade, e a próxima chamada tenta completar a revisão automaticamente.
Acesso ao Qdrant remoto e fidelidade do modelo precisam de validação real;
este checkout não contém a antiga suíte RAG versionada.

O `JudgeAgent` recebe pergunta, candidata composta e evidências reais.
A política consulta Choice de gravidade e Noul de suporte factual/relevância
em uma chamada. Python exige os quatro limites inclusivos configurados em
`app/config.py`: confidence 0,70, probabilidade da categoria 0,50, suporte factual
0,60 e relevância 0,25. Não há Score nem etapa de subcritérios. Erro crítico
bloqueia sempre; erro corrigível ou limite não atingido pede uma revisão e,
se persistir, bloqueia. Veja `manual_chat_judge.py` e a documentação no `delta-handbook`.
O runner permite `--no-history` e não imprime candidatas bloqueadas.

### Estrutura atual

```text
delta-artificial-intelligence/
├── .github/workflows/       # Verificações organizacionais de Pull Request
├── app/
│   ├── agents/              # Especialistas, JudgeAgent e runtime
│   ├── data/                # Acesso PostgreSQL e MongoDB
│   ├── graph/               # Workflow LangGraph, router, state, context e revisão do Juiz
│   ├── guardrails/          # Validações de entrada e saída (PII, injeção)
│   ├── integrations/mcp/    # Catálogo público, servidor e cliente MCP stdio
│   ├── memory/              # Sessão (MongoDB) e longo prazo (Qdrant)
│   ├── observability/       # Traces, métricas e contagem de embeddings em segundo plano
│   ├── routes/              # API HTTP: chat, health, sessions e playground
│   ├── services/            # LLMs, Jev, prompts e segmentação/recuperação documental RAG
│   ├── tools/               # consumption/, forecast/, leak/, habits/, modelos e exceções
│   ├── config.py
│   └── main.py              # FastAPI app com CORS e routers registrados
├── frontend/                # Console de testes com abas por agente e roteador
├── db/
│   ├── postgres-init/       # Cópias locais de bootstrap PostgreSQL, arquivos 01 a 09
│   └── README.md
├── tests/                   # Testes com provedores, bancos e ferramentas substituídos
├── scripts/                 # Diagnóstico MCP e atualização das fontes externas
├── .env.example
├── AGENTS.md
├── docker-compose.dev.yml   # PostgreSQL e MongoDB locais para desenvolvimento manual
├── LICENSE
├── manual_chat.py
├── manual_chat_judge.py      # Fluxo manual com guardrails e revisão
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

`db/postgres-init/` contém cópias para o ambiente local; o repositório `delta-sql-database` é a fonte de verdade do schema. O `db/README.md` ainda lista os arquivos 01 a 06, enquanto a árvore atual contém também 07 a 09. Confira o conteúdo e a origem desses scripts antes de sincronizar ou alterar qualquer cópia. O MongoDB local inicia vazio; o README aponta o simulador de hardware como fonte para carga de dados.

## 3. Leitura obrigatória do `TASK.md`

Antes de executar qualquer tarefa, leia integralmente o `TASK.md` da raiz deste repositório, quando existir. Confira o escopo, as restrições, os critérios de aceite e os arquivos relacionados antes de editar.

Se o `TASK.md` não existir, não o crie nem invente requisitos. Siga a solicitação explícita da pessoa usuária e peça esclarecimento somente quando faltar uma decisão necessária para executar o escopo com segurança.

## 4. Regras técnicas do projeto

- Use identificadores de arquivos, funções, classes e variáveis em inglês.
- Escreva comentários, docstrings e prompts destinados ao chatbot em português, conforme o padrão descrito no `README.md`.
- Mantenha `app/data/` como acesso direto a dados e `app/tools/` como ferramentas dos agentes. Não duplique consultas ou cálculos já existentes.
- Mantenha cálculos determinísticos em Python; não delegue ao LLM aritmética que o código pode calcular e validar.
- O `LeakAgent` apenas lê e descreve sinais já detectados por `delta-business-rules`; não invente limiares nem conclua que há vazamento confirmado.
- Nunca exponha `user_id` como argumento livre do LLM; preserve o escopo de usuário aplicado ao construir as ferramentas.
- Diferencie residência e organização nas consultas de previsão e consumo. Para organizações, respeite a seleção de unidade autorizada e os resultados ambíguos das ferramentas.
- Consumo descreve registros: não calcula tarifa, conta, previsão futura ou diagnóstico de vazamento. Declare recorte, granularidade e lacunas; não transforme ausência em zero nem invente cobertura contínua.
- Separe configuração local, exemplos de `.env`, integração planejada e conexão realmente validada. Nunca versione chaves, senhas ou strings de conexão reais.
- Não trate arquivos de bootstrap locais como fonte oficial do schema PostgreSQL.
- Preserve contratos e comportamento já cobertos pelos testes. Ao alterar um módulo, leia também suas ferramentas, prompts e testes diretamente relacionados.

## 5. Complexidade e nível técnico esperado

O código deve ser compreensível para estudantes do Ensino Médio Técnico em Análise e Desenvolvimento de Sistemas. Prefira soluções diretas, nomes claros, funções pequenas e conceitos que a equipe consiga explicar e manter. Evite abstrações prematuras, dependências extras, arquitetura desnecessária e refatorações amplas para tarefas localizadas.

| Tecnologia ou assunto | Nível atual | Limite esperado |
| --- | --- | --- |
| Lógica de programação | Intermediário | Avançado |
| Git e GitHub | Intermediário | Avançado |
| HTML e CSS | Básico | Intermediário |
| JavaScript | Básico | Intermediário |
| Java | Intermediário | Avançado |
| Spring Boot | Básico | Avançado |
| Python | Intermediário | Avançado |
| FastAPI | Básico | Intermediário |
| SQL e PostgreSQL | Avançado | Avançado |
| MongoDB | Básico | Intermediário |
| APIs REST | Intermediário | Intermediário |
| Testes automatizados | Básico | Intermediário |
| Docker e CI/CD | Básico | Intermediário |
| Arquitetura e padrões de projeto | Básico | Intermediário |
| IoT e comunicação com hardware | Básico | Básico |

O nível atual representa o conhecimento que a equipe aplica com autonomia; o limite esperado é o aprofundamento máximo padrão para as soluções. Quando usar conceitos acima do nível atual, explique-os de forma didática e relacione-os à implementação. Se uma tarefa exigir algo acima do limite esperado, explique a necessidade e proponha uma alternativa mais simples antes de implementar.

## 6. Testes e execução local

Instale as dependências de `requirements.txt`. A entrada manual do fluxo com
Juiz é:

~~~powershell
python manual_chat_judge.py --user-id 1 --no-history
~~~

Use um ID autorizado. Sem `--no-history`, turnos liberados são gravados no
MongoDB. Bancos, ferramentas e provedores continuam reais no runner. Os
checks isolados de política e grafo usam substitutos; não declare integração
remota validada por esses resultados.

Não foi adicionada suíte persistente nesta entrega, conforme a solicitação.
O workflow organizacional de PR continua separado desta validação; não o
altere sem solicitação explícita.

## 7. Branches e commits

Siga `delta-handbook/DEVOPS/convencoes-desenvolvimento.md`. Crie cada branch dentro deste repositório, a partir da `main` atualizada, usando o formato:

```text
<tipo>/<descricao-da-alteracao>
```

Tipos permitidos: `feat`, `fix`, `refactor`, `docs`, `test` e `style`, `chore`. Use uma descrição curta, clara, em minúsculas e separada por hífens, por exemplo `fix/consulta-historico`.

Os commits seguem Conventional Commits no formato `<tipo>: descrição`, com os mesmos tipos. Mantenha cada alteração coesa e restrita ao repositório e à tarefa correspondente.

## 8. Padrão de documentação

**Não crie a pasta `docs/` neste repositório.** Toda documentação técnica, de arquitetura e de operação fica no `delta-handbook` (por exemplo, `IA/observabilidade.md`), em branch própria daquele repositório. Aqui só entram o `README.md` e o `AGENTS.md`; comentários e docstrings continuam no código.

Siga o padrão do `delta-handbook`: use Markdown, título e objetivo claros, contexto e justificativas relevantes, seções com hierarquia coerente e nomes de arquivo em minúsculas separados por hífens. Use listas, tabelas, comandos e diagramas quando ajudarem a explicar o conteúdo. Prefira links relativos e confira se apontam para arquivos existentes.

Ao documentar, diferencie o que está implementado, planejado, exemplificado e validado. Mantenha o `README.md` incremental conforme sua orientação; não crie histórico separado de mudanças sem solicitação.

## 9. Manutenção deste arquivo

Revise a seção **Estrutura atual** periodicamente nesta conversa após commits oficiais que alterem arquivos ou responsabilidades do repositório. Antes de usar este guia, compare as informações com a árvore, o `README.md`, o `TASK.md` e os workflows atuais.

## 10. Execução histórica das TASK-01 a TASK-05

As regras abaixo descrevem a execução anterior das TASK-01 a TASK-05. Não as aplique automaticamente a tarefas novas; siga o escopo atual solicitado pela pessoa usuária:

- Há um subagente independente por tarefa, todos em `gpt-6-luna` com esforço `xhigh`, cada um em worktree e branch exclusivos.
- Antes de implementar, leia integralmente nesta ordem: `AGENTS.md` → `TASK.md` → `TASK-<número>.md`. Não altere o checkout ou arquivos de outro agente.
- Dependência não mergeada não bloqueia implementação: use a branch/commit estável do pré-requisito como base, informado pelo orquestrador. Não modifique `main` nem faça merges no GitHub.
- Cada tarefa terá de 5 a 15 commits próprios e coesos, contados após a base de dependência. Não use commits vazios nem conte commits herdados para preencher essa faixa.
- Após revisão local, termine com `git push origin <branch>`. PRs serão abertas pela pessoa usuária; agentes não devem abrir PRs.
- O orquestrador mantém este `AGENTS.md` conforme o código revisado avança. O `README.md` será atualizado somente depois da finalização das cinco implementações; subagentes entregam sugestões sem editá-lo.
- Indisponibilidade de rede, bancos, credenciais ou ferramentas deve ser comunicada imediatamente, com continuidade do trabalho independente e registro dos testes reais pendentes.
- Evite tentativas repetidas de recuperação de infraestrutura. Testes automatizados necessários continuam obrigatórios; valide cada alteração com os testes pertinentes e faça regressão completa quando o conjunto estiver pronto.

A pasta agrupadora e os repositórios irmãos continuam fora do escopo de edição. Os worktrees não têm os mesmos caminhos relativos do checkout principal: consulte schemas oficiais usando o caminho confirmado da pasta agrupadora, sem criar cópias para simular schema ausente.
