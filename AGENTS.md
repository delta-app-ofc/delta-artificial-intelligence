# AGENTS.md — Delta Artificial Intelligence

Este arquivo orienta agentes de IA e pessoas que trabalham neste repositório. Leia-o por completo antes de
alterar qualquer arquivo e confirme as instruções específicas da tarefa no `TASK.md` local, quando esse arquivo +existir.

---

## 1. Visão geral do Projeto Delta

O Delta é um projeto acadêmico do Ensino Médio Técnico em Análise e Desenvolvimento de Sistemas. O produto é
uma plataforma IoT para monitoramento inteligente do consumo residencial de água: sensores instalados em
hidrômetros enviam pulsos, o sistema consolida o consumo, identifica anomalias e disponibiliza informações para
aplicações web e mobile.

A arquitetura de dados é multi-banco:

- PostgreSQL mantém dados cadastrais e transacionais;
- MongoDB mantém telemetria IoT de alto volume e dados específicos da aplicação, incluindo dados do chat;
- Redis e Neo4j aparecem na documentação de arquitetura como componentes planejados, mas não devem ser tratados
  como implementados sem evidência no código atual.

Os componentes do Delta são mantidos em repositórios Git independentes da organização `delta-app-ofc`. Faça
branches, commits e comandos Git dentro deste repositório; não inicialize Git na pasta agregadora `Repositorios`
e não presuma a estrutura interna de outros serviços.

## 2. Contexto deste repositório

O `delta-artificial-intelligence` contém o chatbot de IA do Projeto Delta e sua API em FastAPI. O objetivo é
oferecer uma camada HTTP para conversas e integrações do produto, conectando o fluxo conversacional aos serviços
e bancos necessários quando isso estiver implementado e documentado.

O esqueleto de pastas da arquitetura multiagente existe, mas a maior parte dos arquivos ainda está vazia. Não
afirme que rotas, LangGraph, guardrails, memória, observabilidade ou os demais agentes estão funcionais sem
conferir o código real e validar a execução. O que já foi implementado (branch `feat/arquitetura-inicial`):
`app/services/{llms,prompts}.py`; `app/config.py` (dev local); as tools em `app/tools/`; os agentes
`app/agents/{forecast,leak}.py`; o ambiente local `docker-compose.dev.yml` + `db/`; e a suíte `tests/`.

O motor de detecção de vazamento (`anomaly_detected`, `alerts_history`) não usa LLM e por isso não mora aqui —
fica no repositório `delta-business-rules`. Este repositório só lê o que ele já calculou.

Convenção de código: identificadores (arquivo/função/classe/variável) em inglês; comentários, docstrings e o
conteúdo dos prompts em português.

Árvore real das partes implementadas (o restante de `app/` continua como stubs vazios):

```text
delta-artificial-intelligence/
├── app/
│   ├── config.py                 # config de DESENVOLVIMENTO LOCAL (ver README, P4)
│   ├── agents/
│   │   ├── _runtime.py           # laço de tool-calling mínimo (sem LangGraph)
│   │   ├── forecast.py           # Agente de Previsão (standalone, só a cola: prompt + tools)
│   │   └── leak.py               # Agente de Vazamento (standalone, idem)
│   ├── services/
│   │   ├── llms.py               # llm_especialista (Gemini + fallback Groq), llm_rapido
│   │   └── prompts.py            # prompts de sistema dos 7 agentes
│   ├── data/
│   │   ├── db_postgres.py        # leitura crua do PostgreSQL (delta-sql-database)
│   │   └── db_mongo.py           # leitura crua do MongoDB (delta-nosql-database), 2 clusters Atlas
│   └── tools/
│       ├── exceptions.py         # todas as exceções do projeto
│       ├── models.py             # dataclasses (LastWaterBill, ConsumptionPoint, Alert)
│       ├── forecast/             # tools + cálculo do Agente de Previsão
│       │   ├── calculations.py   # cálculo determinístico (sem LLM)
│       │   └── tools.py          # as tools que o LLM chama de verdade
│       └── leak/                 # tools + análise do Agente de Vazamento
│           ├── analysis.py       # resumo descritivo de janelas já sinalizadas
│           └── tools.py          # as tools que o LLM chama de verdade
├── db/
│   └── postgres-init/            # cópias de bootstrap do delta-sql-database (01..06)
│       # Mongo sobe vazio — popule com delta-hardware-data-simulator
├── docker-compose.dev.yml        # Postgres + Mongo locais para dev manual
├── tests/                        # pytest — cobre agentes + cálculo puro, sem banco
├── .env.example                 # nomes de variáveis, sem segredos
├── requirements.txt / requirements-dev.txt
└── README.md
```

Atualize esta seção quando a árvore real mudar de forma relevante. Não existe
mais CHANGES.md versionado no repositório — mudanças em prompts.py/llms.py são
reportadas diretamente a quem pediu a tarefa, não guardadas em arquivo.

## 3. Leitura obrigatória do `TASK.md`

Antes de executar qualquer tarefa:

1. Leia este `AGENTS.md` por completo.
2. Localize e leia integralmente o `TASK.md` na raiz, se ele existir.
3. Verifique o estado do Git e inspecione os arquivos afetados na `main` atual.
4. Restrinja as alterações ao escopo definido no `TASK.md` e nas instruções do solicitante.

Se o `TASK.md` não existir, não o crie e não invente requisitos para substituí-lo. Informe a ausência ao
responsável e solicite o escopo necessário antes de executar uma tarefa que dependa dele.

## 4. FastAPI, configuração e integrações

- Use imports pelo pacote da aplicação (por exemplo, `app.*`) quando a estrutura `app/` existir.
- Registre as rotas da API antes de montar qualquer `StaticFiles` de raiz.
- Use URLs relativas no frontend quando ele for servido pela mesma origem da API.
- Mantenha segredos, tokens, chaves de provedores e credenciais fora do código e do Git; use `.env.example`
  apenas com placeholders.
- Diferencie configuração disponível, exemplo de configuração, integração planejada e conexão realmente validada.
- Isole falhas de roteamento, execução de ferramentas, persistência, banco de dados e provedor de LLM antes de
  atribuir a causa a um único componente.
- Não invente endpoints, ferramentas, agentes, modelos, bancos, bibliotecas ou provedores que não estejam no
  código ou na tarefa.

## 5. Testes e validação

Ao alterar a API, valide em proporção ao risco: compilação/sintaxe, testes automatizados e, quando aplicável,
rotas HTTP reais, formato das respostas e persistência. Não declare que o chatbot está conectado a um banco ou
provedor apenas porque a aplicação inicia.

Prefira verificações que não criem artefatos desnecessários. Em Python, uma checagem com `ast.parse` pode ser usada
quando a compilação gerar `__pycache__` indesejado. Se iniciar um servidor local, use uma porta temporária quando
necessário e encerre o processo iniciado antes da entrega.

## 6. Regras de arquitetura e escopo

- Mantenha controllers/routers focados no HTTP e coloque regras de aplicação em services/agentes apropriados.
- Preserve contratos existentes de status HTTP e payloads; confirme o comportamento real antes de alterá-los.
- Mantenha o código didático, simples, explícito e legível; não adicione abstrações ou frameworks sem necessidade.
- Não remova arquivos nem substitua mudanças locais de outras pessoas sem autorização específica.
- Não inclua dados pessoais, credenciais, chaves ou URLs privadas em commits.
- Não crie Docker, migrations, autenticação, novos workflows ou integrações externas por suposição.

## 7. Workflow e padrão de branches/commits

O workflow `.github/workflows/trigger_actions.yml` chama as verificações reutilizáveis de Pull Request da
organização. Não o modifique nem crie outro workflow sem solicitação explícita.

Branches usam o formato `<tipo>/<descricao-da-alteracao>`, com tipos `feat`, `fix`, `refactor`, `docs`, `test` e
`style`. Use descrição curta, clara, em minúsculas e separada por hífens.

Commits seguem Conventional Commits: `<tipo>: descrição`. Não misture mudanças sem relação no mesmo commit.

## 8. Padrão de documentação

Use Markdown com título claro, objetivo, contexto e justificativas técnicas. Registre comandos reproduzíveis e
diferencie explicitamente o que está implementado, exemplificado, planejado e validado. Atualize a seção de
estrutura deste arquivo quando a árvore real mudar de forma relevante.

## 9. Aviso de manutenção

Este arquivo é contexto, não substituto da inspeção do repositório. Antes de cada tarefa, compare as instruções
com a árvore real, o `README.md`, o `TASK.md` e os workflows atuais.
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
- `app/services/prompts.py` mantém prompts dos sete agentes planejados. Ter prompt definido não significa que o agente correspondente esteja implementado.
- `app/services/llms.py` configura, sob demanda, Gemini como modelo especialista com fallback Groq e um modelo Groq rápido. As chaves vêm de variáveis de ambiente.
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
├── tests/                   # Testes pytest dos agentes e cálculos existentes
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
