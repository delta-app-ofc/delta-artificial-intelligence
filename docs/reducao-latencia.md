# Redução de latência do chat

## Objetivo

Diminuir o tempo de resposta do `POST /chat` e a espera percebida pela pessoa usuária, sem mexer no Agente Juiz,
nos modelos de linguagem, no prompt do agente de consumo nem no `/playground`. Este documento registra **o que foi
feito, por quê, como configurar, o que foi medido e o que ficou de fora**.

## Contexto

Em uma rodada manual com Gemini real, contra bancos locais, o chat levou 1-3 s numa saudação, 4-20 s numa pergunta
com um agente e, em alguns casos, de 37 a 157 s. A leitura do código mostrou estes gargalos que não dependem de
modelo nem de Juiz:

| Gargalo | Onde estava |
| --- | --- |
| Cada operação no PostgreSQL abria uma conexão nova (conectar, autenticar, consultar, fechar) | `app/data/db_postgres.py` |
| A lista de unidades da organização era lida de novo a cada tool; o mesmo resumo de consumo chegava a ser pedido 3-4 vezes | `app/tools/consumption/tools.py`, `app/tools/forecast/tools.py` |
| O classificador de segurança da entrada (uma chamada de LLM) rodava antes de contexto e roteador, em série | `app/graph/workflow.py`, `app/guardrails/input.py` |
| O histórico da sessão era lido duas vezes no MongoDB por pergunta | `app/graph/workflow.py`, `app/graph/context.py` |
| O `/chat` só responde ao final: a pessoa não vê andamento | `app/routes/chat.py` |

## Situação (o que é implementado, medido e pendente)

| Item | Implementado | Testado | Medido |
| --- | --- | --- | --- |
| Pool de conexões PostgreSQL | sim | testes unitários, concorrência e PostgreSQL real (só leitura) | sim, localmente (tabela abaixo) |
| Memória de consumo por pergunta | sim | testes unitários | não (reduz idas ao banco; ganho depende do banco) |
| Guarda em paralelo com contexto e roteador | sim | testes unitários e de grafo com modelos falsos | não com LLM real |
| Histórico lido uma vez | sim | testes unitários | não |
| `OPENAI_FAST_REASONING_EFFORT` | sim (opcional, desligado) | testes de configuração | **não**: depende da chave paga |
| `POST /chat/stream` (SSE) | sim | testes de rota e de gerador; servidor real com `curl -N` | latência percebida não medida |
| Tools em lote / em paralelo | **não** (avaliado) | — | **pendente**: ver "Experimento pendente" |

**Medições com LLM real não foram feitas nesta entrega.** A equipe tem uma camada de observabilidade própria; as
medições de latência, tokens e custo devem ser feitas pelos painéis dela depois que esta mudança for aplicada
(veja "Como medir antes e depois").

## 1. Pool de conexões PostgreSQL

**Motivo.** Abrir uma conexão por operação custa de dezenas de milissegundos (TCP, autenticação, às vezes TLS) em
toda consulta; uma previsão organizacional fazia de 5 a 7 conexões.

**O que mudou** (`app/data/db_postgres.py`):

- `_cursor()` mantém a mesma assinatura e passa a **emprestar** uma conexão de um `ThreadedConnectionPool`
  (`psycopg2.pool`, sem dependência nova), criado no primeiro uso. As funções do módulo e os testes que
  substituem `_cursor` não mudam.
- A cada uso, o `statement_timeout` continua sendo aplicado com `set_config(..., true)`, que só vale dentro da
  transação e **não vaza** para o próximo uso da mesma conexão.
- Ao terminar, a conexão volta ao pool. Se a operação falhou, o `putconn` do psycopg2 desfaz a transação aberta.
  Conexão **fechada ou quebrada** é descartada; um erro de consulta com a conexão saudável (inclusive o timeout
  de consulta) **não** descarta a conexão.
- Se a conexão emprestada estiver quebrada antes do SQL, ela é trocada **uma vez** e a operação segue. A nova
  tentativa só acontece antes de rodar o SQL da operação, então nunca repete uma escrita.
- Quando o pool está cheio, a chamada espera até `DB_POOL_WAIT_SECONDS` e então responde com o mesmo
  `DatabaseConnectionError("PostgreSQL")` público de sempre.
- `close_pool()` fecha tudo e pode ser chamado mais de uma vez. É chamado no `lifespan` de `app/main.py`.
- **Detalhe importante do psycopg2:** o pool só guarda `minconn` conexões ociosas e fecha as demais ao devolvê-las.
  Com `minconn=1`, sob concorrência as conexões extras eram recriadas a cada uso (nosso teste achou isso: com 8
  threads o pool ficou *mais lento* que não usar pool). Por isso, depois de abrir as conexões iniciais, o código sobe
  `minconn` para o máximo e as conexões ociosas passam a ser mantidas.

**Configuração** (variáveis de ambiente; `.env.example`):

| Variável | Padrão | Significado |
| --- | --- | --- |
| `DB_POOL_MIN_SIZE` | 1 | Conexões abertas ao criar o pool |
| `DB_POOL_MAX_SIZE` | 10 | Máximo de conexões ao mesmo tempo, por processo |
| `DB_POOL_WAIT_SECONDS` | 5 | Quanto esperar por uma conexão livre antes de falhar |

Regra de tamanho: **`workers do Uvicorn × DB_POOL_MAX_SIZE` deve ficar abaixo do `max_connections` do PostgreSQL**
(padrão 100). O `Dockerfile` usa 1 worker, então hoje são no máximo 10 conexões.

**Medição local** (`python -m scripts.bench_pool`, 300 `SELECT 1`, PostgreSQL 16 em Docker na mesma máquina; só
leitura):

| Cenário | Uma conexão por operação | Com pool |
| --- | --- | --- |
| Sequencial, média por operação | 34,1 ms | 5,4 ms |
| 8 threads, total de 300 operações | 1367 ms | 406 ms |

Em banco remoto (a distância aumenta o custo de cada conexão) o ganho tende a ser maior. **Não** foi medido contra o
banco real da equipe.

**Riscos e limites.** (1) Alterar settings em um processo em execução exige `close_pool()` (veja a lista de
recarga no README). (2) Com `pgbouncer` em modo transação, mantenha o `set_config` local (já é o caso). (3) Um pool
cheio por muito tempo vira erro público; ajuste `DB_POOL_MAX_SIZE`.

**Como reverter.** Voltar `_cursor()` ao `get_conn()` direto (a função continua no arquivo) ou definir
`DB_POOL_MAX_SIZE=1`.

## 2. Memória de consumo por pergunta

**Motivo.** Dentro de uma pergunta, o modelo costuma chamar `get_consumption_summary` várias vezes e cada chamada
relia as unidades e o consumo do banco.

**O que mudou.** O conjunto de tools é criado a cada execução do agente (`build_tools`); dentro dele agora existe uma
memória que:

- guarda a **lista de unidades** (`get_user_organization_properties`) na primeira leitura;
- guarda cada **leitura de consumo por período** (chave: tipo de escopo, unidades, período e horário de referência).

Ao terminar a pergunta, o conjunto de tools é descartado e a memória some com ele. **Não é cache entre perguntas nem
entre usuários.** Leituras com unidade, período ou horário de referência diferentes continuam indo ao banco. Erro do
banco não fica guardado. A autorização continua no banco (`fn_user_authorized_property_ids`); o texto do prompt de
consumo **não foi alterado**. Também vale para a previsão (`forecast/tools.py`), só para a lista de unidades.

**Como reverter.** Trocar `_units()` e `_read()` pelas chamadas diretas que eles envolvem.

## 3. Guarda de entrada em paralelo e histórico lido uma vez

**Motivo.** O classificador de segurança é uma chamada de LLM e rodava antes de tudo; o roteador (outra chamada)
só começava depois dele.

**O que mudou** (`app/guardrails/input.py`, `app/graph/workflow.py`, `app/graph/context.py`):

- `validate_input` foi dividida em `validate_input_rules` (tamanho, PII, injeção, dados internos; instantânea) e
  `classify_input` (LLM). `validate_input` continua existindo e compõe as duas, então o `/playground` e os testes
  antigos não mudam.
- No grafo, depois das regras, um único nó `prepare` roda **ao mesmo tempo** o classificador (`guardrail_llm`) e o
  par `context` → `route`. **Nada executa antes do veredito**: se o classificador bloquear, o resultado do roteador é
  descartado e o grafo termina.
- Por que um nó só e não ramos do LangGraph: o LangGraph executa em passos com barreira, então `route` só
  começaria depois que o classificador terminasse e não haveria ganho. Dentro de `prepare`, cada ramo usa uma cópia
  do contexto da requisição (`contextvars.copy_context()`), e os eventos `graph.node.*` de `guardrail_llm`,
  `context` e `route` continuam sendo emitidos como antes (o nó `prepare` em si não emite eventos).
- Se o classificador falhar, a regra anterior vale: a mensagem **não** é bloqueada e o erro vai ao diagnóstico.
- O perfil da conta (PostgreSQL) e o histórico/memória (MongoDB, Qdrant) são lidos juntos no nó de contexto.
- O histórico validado é lido **uma vez** em `_start_run` e reaproveitado pelo contexto (`_history` no estado).
  Se a leitura inicial falhar, o contexto tenta de novo e registra o erro, como antes.

**Ganho esperado.** Sai do caminho crítico uma chamada de LLM rápida (a menor das duas), tipicamente de 0,5 a 2 s por
pergunta com provedor externo. **Não medido com LLM real.** Quando a guarda bloqueia, uma chamada do roteador pode ter
sido gasta à toa (aceito).

**Como reverter.** Religar `guardrail_input → context → route` em série e chamar `validate_input` no nó de entrada.

## 4. Menos raciocínio nas chamadas rápidas (só configuração)

`OPENAI_FAST_REASONING_EFFORT` (`none`, `low`, `medium`, `high`, `xhigh` ou `max`) define o nível de raciocínio
**só** das chamadas rápidas (guarda, roteador, síntese e título da sessão) quando `LLM_PROVIDER=openai`. Sem a
variável, vale `OPENAI_REASONING_EFFORT`, ou seja, **nada muda até a equipe ligar**. Nenhum modelo, prompt ou o Juiz
foi alterado. Recomendação para testar: `low`, conferindo antes se o roteamento continua correto. O efeito em
latência e custo deve ser medido nos painéis.

## 5. Etapas por SSE: `POST /chat/stream`

**Motivo.** O `/chat` pode levar dezenas de segundos sem dar sinal. Isso reduz a espera **percebida**, não o tempo total.

**Contrato.** Mesmo JWT e mesmo corpo do `/chat` (`message`, `session_id` opcional). JWT, dono da sessão e
disponibilidade do histórico são checados **antes** de abrir o fluxo, com os mesmos códigos do `/chat` (401, 404
idêntico para sessão alheia ou inexistente, 503). Depois de aberto, o status é sempre 200 e as falhas vêm como evento.

| Evento | Conteúdo |
| --- | --- |
| `stage` | `{"stage": "checking\|understanding\|querying\|composing\|validating\|revising\|finishing", "label": "texto em português"}`. Só indica a etapa: **não carrega dados da conta, da pergunta ou da resposta** |
| `result` | O mesmo JSON do `/chat`, enviado **uma única vez, depois da validação** (Juiz e guardrail de saída) |
| `error` | `{"status": 422, "detail": "..."}` se a mensagem foi bloqueada; `{"status": 500, "detail": "...", "request_id": "..."}` se o processamento falhou |
| `: keep-alive` | Comentário SSE a cada 15 s sem evento, para proxies não derrubarem a conexão |

**A resposta nunca é enviada aos poucos.** Ela só sai depois de julgada, então não há risco de mostrar texto não
validado. Uma sessão criada para uma mensagem bloqueada ou que falhou é removida, como no `/chat`.

**Implementação** (`run_workflow_events` em `app/graph/workflow.py`): o grafo roda numa thread própria
(`workflow.stream`, modos `updates` e `values`) dentro do contexto de rastreamento da requisição; os eventos voltam
por uma fila e o endpoint os lê. O `RequestTracingMiddleware` é ASGI puro, compatível com streaming. O checkpoint do
grafo é apagado ao final, como no `/chat`.

**Para o app.** Leia com `fetch` e `ReadableStream` (o `EventSource` do navegador não envia `Authorization`). Se
houver proxy reverso, mantenha `X-Accel-Buffering: no` (já enviado) e desative buffer de resposta.

Verificado com o servidor real (`uvicorn`) e `curl -N`: cinco eventos `stage`, depois `result`; 401 sem token e 404 em
sessão inexistente.

## Experimento pendente: consumo em lote e tools em paralelo

Pedido: avaliar se compensam e **medir antes de decidir**, com receio de o modelo alucinar números numa tool nova.
Não foi implementado, porque depende de rodadas reais com o modelo, que ficaram para os painéis de observabilidade.

- **Tools em paralelo na mesma volta do modelo** (`app/agents/_runtime.py`): cerca de 25 linhas; nenhuma tool nem
  prompt muda. Só ajuda se o modelo emitir várias chamadas **na mesma volta**; se emitir uma por volta, o ganho é zero.
  O pool (item 1) e a memória por pergunta (item 2) já são pré-requisitos satisfeitos.
- **Tool em lote** (`get_consumption_by_unit`): uma consulta de leitura agrupada por unidade (sem criar função nem
  view no banco), devolvendo totais por unidade **e o ranking já calculado em Python**, para o modelo só copiar. Cerca
  de 150-200 linhas, com testes. Risco: mudar o que o agente chama.
- **Como decidir** (regra proposta): medir, em 3-5 repetições de duas perguntas comerciais, o número de voltas e de
  chamadas, tokens, latência e **acerto numérico** (resposta do modelo contra o total calculado direto no banco).
  Adotar só se houver ganho relevante **e** zero divergência numérica. Caso contrário, não adotar.
- A medição da linha de base já pode ser feita com esta entrega, pois o pool e a memória por pergunta reduzem o
  custo de cada chamada.

## Como medir antes e depois

1. **Pool:** `python -m scripts.bench_pool --ops 300 --threads 8` (só `SELECT 1`; usa `DATABASE_URL`).
2. **Chat:** cada resposta traz o cabeçalho `X-Request-ID`; as etapas (`input_guard`, `context`, `router`, agentes,
   `judge`, ...) ficam no rastro da requisição, com `duration_ms`. Compare os mesmos cenários nos painéis antes e
   depois de aplicar esta mudança, e com `OPENAI_FAST_REASONING_EFFORT` ligado e desligado.
3. **Streaming:** `curl -N -X POST .../chat/stream` com um JWT de teste mostra as etapas chegando.

## Fora do escopo (decisão da equipe)

Agente Juiz e Jev (timeout, payload, fallback, número de revisões), escolha e parâmetros de modelos e provedores
(inclusive circuito aberto para falhas do provedor), prompt do agente de consumo, agentes em paralelo e `/playground`.

## Texto sugerido para o handbook

O `delta-handbook/DADOS/IA/agentes/postgres-connection.md` está desatualizado: cita `HOST_DB`, `PORT_DB` etc. e o
`scripts.check_postgres`, que não existem neste código (a conexão usa `DATABASE_URL`). Sugestão de trecho:

> O conector PostgreSQL usa um pool de conexões por processo (`psycopg2.pool.ThreadedConnectionPool`), criado no
> primeiro uso e fechado no encerramento da aplicação (`close_pool()`). A conexão vem de `DATABASE_URL`, com
> `connect_timeout` e `statement_timeout` aplicados por operação (`set_config` local à transação). O tamanho é
> configurado por `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE` e `DB_POOL_WAIT_SECONDS`; `workers × DB_POOL_MAX_SIZE`
> deve ficar abaixo do `max_connections` do PostgreSQL. Ao recarregar settings, chame `close_pool()`.

## O que foi implementado

Branch `feat/reduz-latencia-chat` (a partir de `feat/historico-conversas`):

- [x] Settings do pool e do raciocínio rápido (`0d60887`): `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`,
  `DB_POOL_WAIT_SECONDS`, `OPENAI_FAST_REASONING_EFFORT`, com validação e `.env.example`.
- [x] Raciocínio menor nas chamadas rápidas por configuração (`9465ea4`), sem mudar o padrão.
- [x] Pool de conexões PostgreSQL em `_cursor()` (`04f4630`), com `close_pool()` no `lifespan`.
- [x] Correção das conexões ociosas, testes do pool (18) e `scripts/bench_pool.py` (`0838942`).
- [x] Memória de consumo por pergunta: unidades e leituras por período (`b8e6101`), com 9 testes.
- [x] Guarda de entrada em paralelo com contexto e roteador; histórico lido uma vez (`7935429`), com 12 testes.
- [x] `POST /chat/stream` por SSE e `run_workflow_events` (`3304f72`), com 17 testes.
- [x] Documentação (este arquivo, README e AGENTS.md).
- [ ] Medição de latência, tokens e custo com LLM real: **pendente**, pelos painéis de observabilidade.
- [ ] Tools em paralelo e tool em lote: **pendentes**, dependem dessa medição.
