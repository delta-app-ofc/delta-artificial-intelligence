# AGENTS.md — Contexto do delta-artificial-intelligence

Este arquivo orienta agentes de IA e pessoas desenvolvedoras que atuam neste repositório. Leia-o antes de alterar arquivos e confirme a implementação real, pois algumas pastas ainda são apenas estruturas reservadas.

## 1. Visão geral do Projeto Delta

O Delta é um projeto acadêmico de Ensino Médio Técnico em Análise e Desenvolvimento de Sistemas. A plataforma IoT monitora o consumo residencial de água: dispositivos conectados a hidrômetros enviam leituras para serviços que consolidam o consumo, apoiam a detecção de vazamentos e estimam gastos, com acesso por aplicações e chatbot.

A arquitetura de dados documentada distribui responsabilidades entre PostgreSQL, para dados cadastrais e transacionais, e MongoDB, para telemetria e dados de aplicação. Redis e Neo4j aparecem como componentes planejados; não presuma que estejam implementados neste workspace.

Os repositórios Delta são independentes. Faça alterações e operações Git dentro do repositório responsável, sem presumir estruturas internas de outros repositórios.

## 2. Contexto e estado atual deste repositório

O `delta-artificial-intelligence` contém código Python para agentes especialistas de previsão e vazamento, ferramentas de acesso a dados, cálculos determinísticos, prompts e testes. A API HTTP e a orquestração geral continuam como espaço reservado: a presença de dependências ou arquivos vazios não comprova que estejam implementadas.

A stack declarada inclui Python, FastAPI/Uvicorn, Pydantic, LangChain/LangGraph, integrações Gemini e Groq, PostgreSQL (`psycopg2`), MongoDB (`pymongo`) e Redis. No código atual, os agentes usam LangChain, Gemini/Groq e acessos PostgreSQL/MongoDB; FastAPI, LangGraph e Redis não têm fluxo de aplicação implementado.

### Componentes implementados

- `ForecastAgent` e `LeakAgent` funcionam de forma independente, sem depender de uma API FastAPI ou do grafo LangGraph.
- `app/agents/_runtime.py` implementa um laço simples de chamadas de ferramentas com limite de iterações e registro dos resultados.
- `app/tools/forecast/calculations.py` realiza os cálculos de previsão em Python puro; o LLM não deve calcular os valores numéricos da previsão.
- `app/tools/forecast/tools.py` reúne ferramentas que consultam dados e chamam os cálculos. O usuário residencial usa PostgreSQL e MongoDB; o caminho organizacional consulta dados consolidados no PostgreSQL.
- `app/tools/leak/tools.py` consulta anomalias e alertas já registrados no MongoDB. `app/tools/leak/analysis.py` resume esses sinais; não implementa o motor que detecta vazamentos.
- `app/data/db_postgres.py` contém consultas PostgreSQL para os caminhos residencial e organizacional; `app/data/db_mongo.py` contém leituras de telemetria e dados da aplicação.
- O conector PostgreSQL usa settings, preserva opções da URI e abre uma conexão por operação, sem pool. Aplica `connect_timeout` e `statement_timeout`, fecha cursor/conexão mesmo em falhas e distingue ausência de dados de erro de banco com mensagens públicas seguras.
- `python -m scripts.check_postgres` valida PostgreSQL com `SELECT 1` sem depender de chaves LLM ou do schema do produto. `docs/postgres-connection.md` registra configuração e limites; a conexão real continua pendente neste ambiente sem serviço/credenciais.
- O acesso MongoDB mantém clientes lazy independentes para app/telemetria, com timezone, timeouts e fechamento explícito via `close_clients()`. Falhas não viram ausência de registros; `DatabaseDataError` identifica documento inválido sem expor detalhes brutos.
- `python -m scripts.check_mongo` verifica ping e leitura de app/telemetria separadamente. A opção `--fixture` exige `APP_ENV=test`, um endpoint loopback por URI, porta explícita e databases distintos prefixados `delta_test_`; limpa somente os IDs próprios. Veja `docs/mongo-connection.md`. Leitura real de documento permanece pendente neste ambiente.
- `app/config.py` centraliza settings imutáveis em cache e valida cada componente antes do uso. Variáveis do processo prevalecem sobre `.env`; `APP_ENV=test` ignora qualquer arquivo `.env`. Defaults de bancos locais só existem em `development` e para variáveis ausentes, nunca explicitamente vazias.
- `docs/settings.md` descreve ambientes, precedência, recarga e validação. `.env.example` usa somente valores descartáveis locais; `tests/.env.example` é explicativo e não é carregado pela suíte.
- `app/services/prompts.py` mantém prompts dos sete agentes planejados. Ter prompt definido não significa que o agente correspondente esteja implementado.
- `app/services/llms.py` configura modelos sob demanda a partir dos settings. O especialista mantém `bind_tools` nos dois provedores e usa Groq como fallback apenas para falhas transitórias; erros permanentes recebem mensagens públicas seguras e erros de programação propagam. O histórico de ferramentas é preservado sem repetir sua execução.
- `docs/llm-models.md` registra papéis, modelos, parâmetros, retries e fontes oficiais. A disponibilidade de um modelo depende da conta; testes com clientes substituídos não comprovam acesso real nem qualidade das respostas.
- `tests/` contém testes com modelo falso e ferramentas substituídas; os testes não precisam de banco nem de chamadas reais a provedores de LLM.
- `manual_chat.py` permite exercitar manualmente os agentes de previsão e vazamento quando ambiente, bancos e chaves necessários estão configurados.

### Componentes ainda sem implementação

Os arquivos abaixo existem, mas estão vazios na `main` inspecionada. Não descreva seu comportamento como funcional nem os preencha fora do escopo da tarefa:

- API e rotas: `app/main.py`, `app/routes/`, `app/schemas.py`;
- fluxo LangGraph: `app/graph/workflow.py` e `app/graph/state.py`;
- agentes `consumption`, `habits`, `judge`, `profile` e `rag`;
- guardrails de entrada e saída em `app/guardrails/`;
- memória de sessão ou de longo prazo em `app/memory/`;
- métricas em `app/observability/`.

LangGraph está listado nas dependências, mas o fluxo em `app/graph/` ainda não foi implementado. Os prompts para RAG existem, mas não há retriever implementado neste repositório. Redis aparece nas dependências, mas não há integração de aplicação implementada aqui.

### Estrutura atual

```text
delta-artificial-intelligence/
├── .github/workflows/       # Verificações organizacionais de Pull Request
├── app/
│   ├── agents/              # ForecastAgent, LeakAgent, runtime e módulos reservados
│   ├── data/                # Acesso PostgreSQL e MongoDB
│   ├── graph/               # Reservado para estado e workflow LangGraph
│   ├── guardrails/          # Reservado para validações de entrada e saída
│   ├── memory/              # Reservado para memória
│   ├── observability/       # Reservado para métricas
│   ├── routes/              # Reservado para rotas HTTP
│   ├── services/            # Configuração de LLMs e prompts
│   ├── tools/               # Modelos, ferramentas e cálculos dos agentes existentes
│   ├── config.py
│   └── main.py              # Vazio na main inspecionada
├── db/
│   ├── postgres-init/       # Cópias locais de bootstrap PostgreSQL, arquivos 01 a 09
│   └── README.md
├── docs/                    # Configuração e guias técnicos das integrações
├── scripts/                 # Verificações explícitas de conectividade, sem clientes LLM
├── tests/                   # Testes pytest; conftest isola ambiente e cache de settings
├── .env.example
├── AGENTS.md
├── docker-compose.dev.yml   # PostgreSQL e MongoDB locais para desenvolvimento manual
├── LICENSE
├── manual_chat.py
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
- Diferencie residência e organização nas consultas de previsão. Para organizações, respeite a seleção de unidade e os resultados ambíguos das ferramentas.
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

As dependências de aplicação estão em `requirements.txt`; `requirements-dev.txt` inclui as dependências de desenvolvimento e testes. Os testes registrados no `README.md` são executados com:

```bash
python -m pytest -q
```

Eles usam fakes e stubs e não validam conexão real com PostgreSQL, MongoDB, Gemini ou Groq. O ambiente local de desenvolvimento manual usa `docker-compose.dev.yml`; ele não transforma os testes automatizados em testes de integração. Só declare um fluxo como validado após executar a verificação correspondente e informar seus limites.

O workflow `.github/workflows/trigger_actions.yml` chama as verificações compartilhadas da organização para Pull Requests. Ele não executa a suíte pytest. Não altere ou duplique esse workflow sem solicitação explícita.

## 7. Branches e commits

Siga `delta-handbook/DEVOPS/convencoes-desenvolvimento.md`. Crie cada branch dentro deste repositório, a partir da `main` atualizada, usando o formato:

```text
<tipo>/<descricao-da-alteracao>
```

Tipos permitidos: `feat`, `fix`, `refactor`, `docs`, `test` e `style`, `chore`. Use uma descrição curta, clara, em minúsculas e separada por hífens, por exemplo `fix/consulta-historico`.

Os commits seguem Conventional Commits no formato `<tipo>: descrição`, com os mesmos tipos. Mantenha cada alteração coesa e restrita ao repositório e à tarefa correspondente.

## 8. Padrão de documentação

Siga o padrão do `delta-handbook`: use Markdown, título e objetivo claros, contexto e justificativas relevantes, seções com hierarquia coerente e nomes de arquivo em minúsculas separados por hífens. Use listas, tabelas, comandos e diagramas quando ajudarem a explicar o conteúdo. Prefira links relativos e confira se apontam para arquivos existentes.

Ao documentar, diferencie o que está implementado, planejado, exemplificado e validado. Mantenha o `README.md` incremental conforme sua orientação; não crie histórico separado de mudanças sem solicitação.

## 9. Manutenção deste arquivo

Revise a seção **Estrutura atual** periodicamente nesta conversa após commits oficiais que alterem arquivos ou responsabilidades do repositório. Antes de usar este guia, compare as informações com a árvore, o `README.md`, o `TASK.md` e os workflows atuais.

## 10. Execução orquestrada das TASK-01 a TASK-05

Durante esta execução, as orientações diretas da pessoa usuária prevalecem sobre o fluxo sequencial antigo do `TASK.md`:

- Há um subagente independente por tarefa, todos em `gpt-6-luna` com esforço `xhigh`, cada um em worktree e branch exclusivos.
- Antes de implementar, leia integralmente nesta ordem: `AGENTS.md` → `TASK.md` → `TASK-<número>.md`. Não altere o checkout ou arquivos de outro agente.
- Dependência não mergeada não bloqueia implementação: use a branch/commit estável do pré-requisito como base, informado pelo orquestrador. Não modifique `main` nem faça merges no GitHub.
- Cada tarefa terá de 5 a 15 commits próprios e coesos, contados após a base de dependência. Não use commits vazios nem conte commits herdados para preencher essa faixa.
- Após revisão local, termine com `git push origin <branch>`. PRs serão abertas pela pessoa usuária; agentes não devem abrir PRs.
- O orquestrador mantém este `AGENTS.md` conforme o código revisado avança. O `README.md` será atualizado somente depois da finalização das cinco implementações; subagentes entregam sugestões sem editá-lo.
- Indisponibilidade de rede, bancos, credenciais ou ferramentas deve ser comunicada imediatamente, com continuidade do trabalho independente e registro dos testes reais pendentes.
- Evite tentativas repetidas de recuperação de infraestrutura. Testes automatizados necessários continuam obrigatórios; valide cada alteração com os testes pertinentes e faça regressão completa quando o conjunto estiver pronto.

A pasta agrupadora e os repositórios irmãos continuam fora do escopo de edição. Os worktrees não têm os mesmos caminhos relativos do checkout principal: consulte schemas oficiais usando o caminho confirmado da pasta agrupadora, sem criar cópias para simular schema ausente.
