# Conexão MongoDB

`app/data/db_mongo.py` mantém dois clientes lazy: um para a aplicação e outro
para telemetria. O cliente é criado no primeiro uso, reutilizado pelo processo
e não executa ping durante o import do módulo. Em produção, configure URIs
independentes para os clusters Atlas; no ambiente local, ambos podem apontar
para o mesmo serviço e usar databases diferentes.

## Configuração

Configure as variáveis de ambiente ou copie os valores de desenvolvimento de
`.env.example` para `.env`:

| Variável | Uso |
| --- | --- |
| `MONGODB_APP_URI` | URI do cluster que contém preferências e alertas. |
| `MONGODB_TELEMETRY_URI` | URI independente do cluster de telemetria. |
| `MONGO_DB_APP` | Database da aplicação, padrão `db_delta_app` em desenvolvimento. |
| `MONGO_DB_TELEMETRY` | Database de telemetria, padrão `db_delta_telemetry` em desenvolvimento. |
| `DB_CONNECT_TIMEOUT_SECONDS` | Tempo de seleção do servidor e conexão; convertido para milissegundos no driver. |
| `DB_QUERY_TIMEOUT_SECONDS` | Limite de leitura; aplicado como timeout de socket e `maxTimeMS`. |

As URIs são validadas separadamente antes de criar cada cliente. `APP_ENV=test`
não usa valores padrão locais nem lê `.env`; passe as configurações necessárias
explicitamente nesse ambiente. As mensagens de falha não incluem URI,
credenciais ou detalhes internos do driver.

As consultas mantêm os filtros por `user_id` e as ordenações atuais. Se a
consulta falhar, o acesso a dados levanta uma exceção segura; ela não é
convertida em lista vazia ou ausência legítima. Documentos que não atendem aos
campos obrigatórios produzem `DatabaseDataError`, uma subclasse de
`DatabaseQueryError`. O fechamento explícito é feito por
`app.data.db_mongo.close_clients()`, que fecha os dois clientes e limpa ambos
os caches.

## Verificação de conectividade e leitura

Com os dois alvos configurados e acessíveis, execute na raiz do repositório:

```bash
python -m scripts.check_mongo
```

O comando valida cada alvo, executa `ping` e lê no máximo um documento de
`user_preferences` (app) e `consumption_summary` (telemetria), usando o nome de
database configurado. O resultado identifica database e coleção e informa
`documento_encontrado` ou `sem_documento`; nenhum conteúdo do documento é
impresso. Um alvo indisponível faz o comando terminar com código diferente de
zero, mas o outro alvo ainda é verificado. Sucesso sem documento comprova a
consulta à coleção configurada, mas não valida conversão de um documento.

Para inserir, converter e remover documentos sintéticos, use a opção explícita
`--fixture` somente em um Mongo local isolado:

```powershell
$env:APP_ENV = "test"
$env:MONGODB_APP_URI = "mongodb://127.0.0.1:27018"
$env:MONGODB_TELEMETRY_URI = "mongodb://127.0.0.1:27018"
$env:MONGO_DB_APP = "delta_test_app"
$env:MONGO_DB_TELEMETRY = "delta_test_telemetry"
python -m scripts.check_mongo --fixture
```

O modo fixture exige `APP_ENV=test`, URIs `mongodb://` com porta explícita e
um único host loopback (`localhost`, `127.0.0.1` ou `::1`), dois nomes de
database distintos prefixados `delta_test_`, e ambos os alvos configurados.
Ele cria documentos compatíveis em `user_preferences` e
`consumption_summary`, lê-os pelos acessos de dados da aplicação, confere os
valores convertidos e remove somente os dois `_id` que acabou de gerar. Se os
databases ou coleções de teste ainda não existirem, o MongoDB poderá
materializá-los ao inserir a fixture. Nunca use essa opção contra Atlas ou
outro host; o script não cria nem altera schema, índices, validadores ou
permissões de produção.

## Resultado desta execução

Em 4 de outubro de 2026, `python -m scripts.check_mongo` terminou com código
1. Os alvos `app` e `telemetry` retornaram a mensagem segura de falha de
conexão. O ambiente local não tinha `.env` nem variáveis de banco configuradas;
os padrões de desenvolvimento apontaram para `localhost:27018`, mas o Docker
Engine estava desligado e não havia serviço escutando nessa porta. O comando
não tentou reconectar nem acessar clusters Atlas.

Portanto, ping e leitura real de coleção com documento sintético continuam
pendentes. Os 26 testes de `db_mongo` substituem clientes, databases e
coleções; outros 3 testes cobrem o CLI, incluindo a falha independente de um
alvo e a limpeza exata da fixture. Esses testes verificam filtros, ordenações,
conversão, erros e recusa de alvos não isolados, sem comprovar conectividade
real.
