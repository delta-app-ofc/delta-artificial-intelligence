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
`app/agents/{forecast,leak}.py`; o motor de detecção `detection/`; o ambiente local `docker-compose.dev.yml` +
`db/`; e a suíte `tests/`.

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
│   └── tools/
│       ├── exceptions.py         # todas as exceções do projeto
│       ├── models.py             # dataclasses (LastWaterBill, ConsumptionPoint, Alert)
│       ├── db_postgres.py        # leitura crua do PostgreSQL (delta-database)
│       ├── db_mongo.py           # leitura crua do MongoDB (delta-nosql-database)
│       ├── forecast/             # tools + cálculo do Agente de Previsão
│       │   ├── calculations.py   # cálculo determinístico (sem LLM)
│       │   └── tools.py          # as tools que o LLM chama de verdade
│       └── leak/                 # tools + análise do Agente de Vazamento
│           ├── analysis.py       # resumo descritivo de janelas já sinalizadas
│           └── tools.py          # as tools que o LLM chama de verdade
├── detection/                     # motor de detecção de vazamento (regras + Isolation Forest)
├── db/
│   ├── postgres-init/            # cópias de bootstrap do delta-database (01..07)
│   └── mongo-init/seed.js        # seed de teste autoral
├── docker-compose.dev.yml        # Postgres + Mongo locais para dev manual (Mongo em replica set)
├── tests/                        # pytest — cobre agentes + cálculo puro + detection, sem banco
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
