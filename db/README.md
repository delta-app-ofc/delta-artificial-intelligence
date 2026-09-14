# `db/` — bootstrap dos bancos locais de desenvolvimento

Estes arquivos servem **só** para `docker-compose.dev.yml` subir um Postgres e um
MongoDB locais já populados (ver `TASK.md`, item 0.2). **Não** são fonte de
verdade de schema nem de modelagem.

## `postgres-init/` — cópias do `delta-sql-database`

Rodam em ordem alfabética na primeira inicialização do container
(`/docker-entrypoint-initdb.d`):

| Arquivo local | Origem em `delta-app-ofc/delta-sql-database` |
|---|---|
| `01-schema.sql` | `script-schema.sql` (cria as 12 tabelas) |
| `02-fn_user_is_active.sql` | `functions/fn_user_is_active.sql` |
| `03-fn_get_property_region.sql` | `functions/fn_get_property_region.sql` |
| `04-fn_get_current_region_rate.sql` | `functions/fn_get_current_region_rate.sql` |
| `05-fn_user_can_estimate.sql` | `functions/fn_user_can_estimate.sql` (depende das 3 acima) |
| `06-fn_get_property_classification.sql` | `functions/fn_get_property_classification.sql` (nova, mesmo padrão de `fn_get_property_region`) |
| `07-dataload.sql` | `script-dataload.sql` (~200 usuários e dados verossímeis) |

Cópia feita a partir do commit `35becd9` do `delta-sql-database` (esse
repositório também é conhecido pelo nome `delta-database` no GitHub — a URL
antiga redireciona pra essa). O schema real continua sendo mantido lá — se
ele mudar, estas cópias precisam ser re-sincronizadas (não edite-as à mão).

Fatos do dataload usados pelos testes:

- usuários **1–149**: `fn_user_can_estimate` = `TRUE` (ativo + propriedade +
  dispositivo ativo + tarifa da região cadastrada);
- usuário **150**: dispositivo `is_active = FALSE` → `fn_user_can_estimate` = `FALSE`;
- usuários **151–200**: têm `tb_last_water_bill` mas **não** têm propriedade/dispositivo
  → `fn_user_can_estimate` = `FALSE`;
- `tb_region_rate` tem tarifa vigente (`2025-01-01` → aberto) para as 5 regiões.

## `mongo-init/seed.js` — autoral desta tarefa

**Não** é cópia do `delta-nosql-database`. Segue as estruturas da modelagem
oficial (`consumption_summary`, `user_preferences`, `alerts_history`) e cria os
cenários da seção R8. Os `user_id` (11, 12, 13, 14, 15) são reaproveitados como
constantes nos testes. Detalhe de cada cenário no cabeçalho do próprio `seed.js`.
