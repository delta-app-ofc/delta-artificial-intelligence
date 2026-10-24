# Orquestração LangGraph — workflow.md

Este documento descreve o grafo LangGraph do Delta (`app/graph/workflow.py`),
explicando cada nó, as transições condicionais e como adicionar um novo agente.

## Grafo

```
guardrail_input
  │
  ├─ (_blocked=True) → END
  │
  └─ (_blocked=False) → context → route → execute → synthesize → respond → guardrail_output → END
```

A topologia é linear com uma saída antecipada no guardrail de entrada. Não há
ciclos nem bifurcações depois do nó `route`.

## Nós

### `guardrail_input`

Valida a mensagem antes de qualquer lógica de negócio. Chama `validate_input`
de `app/guardrails/input.py`, que:

1. Rejeita mensagens vazias, longas demais ou com `user_id` inválido.
2. Detecta padrões de injeção de prompt.
3. Anonimiza PII (CPF, CNPJ, telefone, e-mail) e armazena o mapa de tokens
   em `GraphState.pii_map`.

Se `state["skip_guardrail_input"]` for `True` (setado pela rota HTTP, que já
validou), o nó passa direto sem re-validar.

Quando bloqueado, `_blocked=True` é setado no estado e a aresta condicional
roteia para `END` sem executar nenhum agente.

### `context`

Recupera contexto externo antes do roteamento:

- Histórico recente da sessão (`app/memory/session.py`).
- Memória de longo prazo relevante para a pergunta (`app/memory/long_term.py`).

Armazena o resultado em `GraphState.recent_messages` e `GraphState.relevant_memory`.

### `route`

Usa `llm_rapido` (Groq) para classificar a intenção e escolher os agentes.
A classificação vem de `app/graph/router.py` — função `classify(question, context)`.

Intenções possíveis:

| Intenção | Agentes selecionados |
|----------|---------------------|
| `consumption` | `["consumption"]` |
| `forecast` | `["forecast"]` |
| `leak` | `["leak"]` |
| `habits` | `["habits"]` |
| `comprehensive` | dois ou mais agentes |
| `privacy_violation` | `[]` — encerra no nó `respond` |
| `unknown` | `[]` |

A intenção `privacy_violation` é ativada quando a pergunta solicita dados de
outros usuários, rankings ou comparações entre residências distintas.

### `execute`

Chama cada agente da lista `selected_agents` em sequência.

**Context-passing entre agentes:** o primeiro agente recebe a pergunta original.
O segundo em diante recebe:

```
{pergunta original}

Contexto dos agentes anteriores:
- forecast: {primeiros 300 chars da resposta do forecast}
```

Isso permite que o LeakAgent mencione, por exemplo, que "o agente de previsão
identificou consumo elevado neste período" sem re-consultar o banco.

Cada resultado é registrado em `GraphState.agent_results` com os campos:
`agent`, `status` (`success` ou `error`), `answer`, `chart_data` e `tool_calls`.

### `synthesize`

Ativado apenas quando ≥ 2 agentes tiveram `status=success`. Usa `llm_rapido`
para unificar as respostas em texto coeso, indicando a origem de cada dado e
sinalizando contradições.

Se `llm_rapido` falhar (exceção), o nó cai silenciosamente para concatenação
bruta com separador `---`.

### `respond`

Verifica se a intenção é `privacy_violation`. Se for, retorna:
> "Não tenho acesso a dados de outros usuários. Posso ajudar apenas com
> informações da sua conta."

Caso contrário, usa o resultado do nó `synthesize` (ou a resposta do único
agente) como resposta final.

### `guardrail_output`

Sanitiza a resposta antes de entregá-la:

- Remove CPF/CNPJ/telefone com `validate_output` de `app/guardrails/output.py`.
- Resolve tokens PII do mapa de entrada (ex.: `[PII_CPF_abc]` → `[CPF OMITIDO]`).
- Persiste o histórico de sessão via `append_turn` (best-effort — falha não
  interrompe o fluxo).

## Estado (`GraphState`)

Definido em `app/graph/state.py` como TypedDict com campos obrigatórios e
opcionais (`total=False`):

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `user_id` | `int` | Usuário autenticado |
| `session_id` | `str` | Identificador da sessão |
| `question` | `str` | Pergunta original (anonimizada após `guardrail_input`) |
| `response` | `str` | Resposta final |
| `agent_results` | `list[dict]` | Resultados de cada agente |
| `selected_agents` | `list[str]` | Agentes escolhidos pelo router |
| `intent` | `str` | Intenção classificada |
| `complexity` | `str` | `simple` ou `medium` |
| `pii_map` | `dict` | Mapa token → valor original (opcional) |
| `_blocked` | `bool` | True se a entrada foi bloqueada |
| `skip_guardrail_input` | `bool` | True quando a rota HTTP já validou |

## Como adicionar um novo agente

1. Implemente o agente em `app/agents/<nome>.py` seguindo o padrão de
   `ForecastAgent` — método `.run(question)` que devolve um objeto com
   `.response`, `.chart_data` e `.tool_calls`.

2. Registre o agente em `app/graph/router.py`, no dicionário `AGENT_REGISTRY`:
   ```python
   from app.agents.meu_agente import MeuAgente
   AGENT_REGISTRY["meu_agente"] = MeuAgente
   ```

3. Adicione a intenção ao `_ROUTER_PROMPT` em `app/graph/router.py` com
   exemplos de perguntas que mapeiam para esse agente.

4. Escreva testes em `tests/` com `ScriptedChatModel` e ferramentas substituídas.

## Limitações conhecidas

- `ConsumptionAgent` ainda não está no `AGENT_REGISTRY` — não é roteável pelo
  workflow. Adicionar é uma task separada.
- Agentes `judge` e `rag` não estão implementados.
- O nó `context` consulta memória de longo prazo mesmo quando a pergunta não
  referencia o passado — custo desnecessário que pode ser otimizado com um filtro.
- Não há rate limiting por `user_id` no workflow — isso cabe a um middleware
  de API.
