# `db/` — bootstrap dos bancos locais de desenvolvimento

Estes arquivos servem **só** para `docker-compose.dev.yml` subir um Postgres e um
MongoDB locais já populados (ver `TASK.md`, item 0.2). **Não** são fonte de
verdade de schema nem de modelagem.

## `postgres-init/` — cópias do `delta-database`

Rodam em ordem alfabética na primeira inicialização do container
(`/docker-entrypoint-initdb.d`), na mesma ordem do `setup_db.py` oficial:

| Arquivo local | Origem em `delta-app-ofc/delta-database` |
|---|---|
| `01-schema.sql` | `script-schema.sql` (todas as tabelas, inclusive hábitos, municípios e organização) |
| `02-optimization.sql` | `script-optimization.sql` (funções `fn_*`, procedures e triggers de conflito de hábito) |
| `03-audit.sql` | `script-audit.sql` (tabelas e triggers de auditoria; o datamart depende delas) |
| `04-local-roles.sql` | **Só local**, não é cópia: cria as roles `sys_*` citadas nos GRANTs do datamart. O `script-roles.sql` oficial cria usuários com senha e usa o banco `deltadb`, por isso não é copiado |
| `05-dataload.sql` | `script-dataload.sql` (dados verossímeis, 371 municípios, hábitos e organizações) |
| `06-datamart-schema.sql` | `script-datamart.sql` (schemas `stage`/`silver`/`gold`/`dw`) |

Cópia feita a partir da branch `fix/habito-multiplo-por-dia` do `delta-database`,
validada subindo os seis arquivos em um PostgreSQL 16 descartável (sem erros;
`fn_user_habits`, `fn_create_user_habit`, `fn_get_user_property_context` e
`fn_user_access_kind` respondem). O schema real continua sendo mantido lá — se ele
mudar, estas cópias precisam ser re-sincronizadas (não edite-as à mão). Conteúdo
anterior (arquivos 01 a 09, com o dataload organizacional fabricado à mão) foi
substituído; o dataload oficial já traz organizações.

Fatos do dataload conferidos no PostgreSQL descartável (01-11-2026):

- `tb_user` tem 201 usuários e `tb_municipality` 371 municípios;
- dos usuários 1–150, 133 têm `fn_user_can_estimate` = `TRUE`; os múltiplos de 10
  (ex.: 10 e 20) e alguns outros (ex.: 15) retornam `FALSE`, e o 151 também;
- `tb_region_rate` tem 8 linhas de tarifa para cada uma das 9 regiões;
- o usuário 1 é residencial (`fn_user_access_kind` = `residential`) e tem 2 hábitos.

Não presuma outros IDs sem consultar o banco: o dataload oficial muda com o tempo.

## Mongo — sem seed próprio

O container `mongo` do `docker-compose.dev.yml` sobe vazio (não tem mais
`mongo-init/`). Pra popular localmente, use
[`delta-hardware-data-simulator`](https://github.com/delta-app-ofc/delta-hardware-data-simulator)
(`python -m dataload.cli <coleção> <quantidade>`) — possui geradores para as seis coleções atuais de
telemetria/app (`consumption_summary`, `device_status`,
`user_preferences`, `alerts_history`, `chat_sessions`, `chat_feedback`), que
antes eram duplicadas manualmente no `seed.js` deste repositório. Os testes
automatizados não dependem disso (ver README principal, seção "Testes") —
tools de Mongo são stubadas nos testes.

### Contrato MongoDB atualizado

O hardware envia o consumo consolidado diretamente para `consumption_summary`, sem coleção intermediária de pulsos. `db_delta_app` também contém `weather_daily`, com `weather_date` e `wind_speed_mps`; consulte o schema oficial e a [documentação de clima](../../delta-nosql-database/collections/db_delta_app.md). O índice climático ainda usa `date`, divergência pendente nos scripts oficiais.
