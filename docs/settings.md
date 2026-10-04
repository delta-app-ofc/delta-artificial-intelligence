# Configuração da aplicação

`app/config.py` reúne as variáveis de ambiente em `Settings`. O carregamento não abre conexões nem exige credenciais: cada caminho valida apenas o componente que vai usar. Isso mantém imports, cálculos puros e agentes com LLM falso independentes de bancos e provedores reais.

## Precedência e recarga

As variáveis do processo prevalecem sobre o arquivo `.env`. Em desenvolvimento, o módulo lê `.env` sem alterar `os.environ`; o modo `APP_ENV=test` não lê nenhum arquivo `.env`, mesmo quando passado explicitamente. Uma chamada `load_settings(environ=...)` usa apenas o mapa recebido, sem ler arquivo por padrão, para permitir testes isolados. Um caminho de arquivo pode ser passado explicitamente para testar a precedência com dados temporários.

`get_settings()` devolve um snapshot em cache. Use `get_settings(refresh=True)` ou `reload_settings()` depois de alterar variáveis durante a execução; não recarregue por requisição. `clear_settings_cache()` limpa o snapshot para testes. Os nomes uppercase existentes continuam disponíveis como aliases de compatibilidade. Para receber a configuração atualizada depois de uma recarga, use os campos de `get_settings()`.

A representação de `Settings` omite chaves, senhas e URIs de conexão. Erros de validação identificam os nomes das variáveis, sem incluir seus valores. A checagem das URIs é local e sintática; não tenta conectar nem consultar DNS.

## Comportamento por ambiente

| `APP_ENV` | Comportamento |
| --- | --- |
| `development` (padrão) | Pode usar os serviços descartáveis definidos em [`docker-compose.dev.yml`](../docker-compose.dev.yml): PostgreSQL local e as duas URIs Mongo locais. O fallback local só é aplicado quando a variável correspondente não foi informada. |
| `test` | Não usa defaults locais e não lê `.env`. Testes injetam valores sintéticos com `load_settings(environ=...)` ou `monkeypatch`; a suíte não precisa de banco, rede ou chave de LLM. |
| `staging` / `production` | Não recebe URI local automaticamente. O componente precisa de configuração explícita antes de ser usado. Os nomes dos bancos Mongo mantêm os defaults `db_delta_app` e `db_delta_telemetry`. |

Em desenvolvimento, `DATABASE_URL` usa a conta pública e descartável do container local. Se for informado um conjunto PostgreSQL separado, as cinco variáveis `HOST_DB`, `PORT_DB`, `USER_DB`, `PASSWORD_DB` e `NAME_DB` precisam estar preenchidas; esse conjunto completo tem precedência sobre `DATABASE_URL`. Se qualquer nome do conjunto for informado, inclusive vazio, o código não troca silenciosamente para a URL.

As conexões Mongo de aplicação e telemetria sempre permanecem independentes. Os dois exemplos locais podem apontar para o mesmo container; staging e produção devem informar cada URI do cluster correspondente.

## Variáveis disponíveis

| Variável | Default | Regra de uso |
| --- | --- | --- |
| `APP_ENV` | `development` | Aceita `development`, `test`, `staging` ou `production`. |
| `GEMINI_API_KEY` | vazio | Exigida ao selecionar o caminho Gemini. Sem segredo default. |
| `GROQ_API_KEY` | vazio | Exigida para o caminho rápido Groq, Groq especialista ou fallback Groq habilitado. |
| `DATABASE_URL` | URI do PostgreSQL local em desenvolvimento | Alternativa às cinco variáveis PostgreSQL separadas. A URI inteira é repassada para preservar senha codificada e opções como TLS. |
| `HOST_DB`, `PORT_DB`, `USER_DB`, `PASSWORD_DB`, `NAME_DB` | não definidos | Formato separado PostgreSQL; use os cinco juntos. A porta deve estar entre 1 e 65535. |
| `MONGODB_APP_URI` | `mongodb://localhost:27018` em desenvolvimento | Cluster Mongo de dados do aplicativo. |
| `MONGODB_TELEMETRY_URI` | `mongodb://localhost:27018` em desenvolvimento | Cluster Mongo de telemetria; variável separada da URI de aplicação. Aceita `mongodb://` com vários hosts e `mongodb+srv://`. |
| `MONGO_DB_APP` | `db_delta_app` | Nome não vazio do banco de aplicação. |
| `MONGO_DB_TELEMETRY` | `db_delta_telemetry` | Nome não vazio do banco de telemetria. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Modelo configurável para o provedor Gemini. |
| `GROQ_SPECIALIST_MODEL` | `openai/gpt-oss-120b` | Modelo configurável para o caminho especialista Groq. |
| `GROQ_FAST_MODEL` | `openai/gpt-oss-20b` | Modelo configurável para o caminho rápido Groq. |
| `LLM_FALLBACK_ENABLED` | `true` | Aceita explicitamente `true` ou `false`. |
| `LLM_TIMEOUT_SECONDS` | `15` | Tempo positivo em segundos. |
| `LLM_MAX_RETRIES` | `1` | Número inteiro não negativo. |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | Limite inteiro positivo de saída. |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | Timeout inteiro positivo de conexão com banco. |
| `DB_QUERY_TIMEOUT_SECONDS` | `30` | Timeout inteiro positivo para operações de banco. |

Temperatura e `top_p` continuam como parâmetros fixos do código dos provedores. A seleção dos modelos e os parâmetros LLM são aplicados em `app/services/llms.py`; os drivers PostgreSQL/MongoDB aplicam os timeouts de banco. Consulte [provedores](llm-models.md), [PostgreSQL](postgres-connection.md) e [MongoDB](mongo-connection.md) para a semântica de cada parâmetro.

## Validação por componente

```python
from app.config import (
    get_postgres_connection_args,
    validate_llm_config,
    validate_mongo_config,
    validate_postgres_config,
)

validate_llm_config("specialist")  # Gemini e fallback Groq, se habilitado
validate_llm_config("gemini")      # somente Gemini
validate_llm_config("fast")        # somente Groq rápido
validate_postgres_config()          # URL ou conjunto separado completo
validate_mongo_config("app")       # URI e nome do banco de aplicação
validate_mongo_config("telemetry") # URI e nome do banco de telemetria

postgres_args = get_postgres_connection_args()
```

Os validadores lançam `ConfigurationError` se o componente não estiver pronto. Eles verificam esquema de URI, variáveis obrigatórias, nomes e intervalos numéricos sem tentar conectar. `validate_config()` permanece disponível por compatibilidade para retornar uma lista agregada de problemas; chamadas isoladas devem usar o validador do componente correspondente.

O arquivo [`tests/.env.example`](../tests/.env.example) documenta o modo de teste e não é carregado pela suíte. `tests/conftest.py` remove settings herdadas do processo, força `APP_ENV=test` e limpa o cache após cada caso.
