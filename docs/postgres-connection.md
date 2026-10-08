# Conexão PostgreSQL

O módulo `app/data/db_postgres.py` abre uma conexão `psycopg2` por operação e
fecha cursor e conexão ao concluir a consulta ou ao ocorrer uma falha. O
projeto não mantém um pool de conexões.

## Configuração

Use `DATABASE_URL` para uma URI PostgreSQL completa ou configure as cinco
variáveis `HOST_DB`, `PORT_DB`, `USER_DB`, `PASSWORD_DB` e `NAME_DB`. Um conjunto
separado completo tem precedência sobre `DATABASE_URL`; se qualquer variável
separada for informada sem completar o conjunto, a validação falha antes de
chamar o driver. A URI completa é passada ao `psycopg2` sem ser remontada, para
preservar opções como TLS e senhas percent-encoded.

Os limites são definidos em segundos:

| Variável | Aplicação |
| --- | --- |
| `DB_CONNECT_TIMEOUT_SECONDS` | Passado ao `psycopg2` como `connect_timeout`, em segundos. |
| `DB_QUERY_TIMEOUT_SECONDS` | Convertido para milissegundos e aplicado à sessão PostgreSQL como `statement_timeout`. |

Se a URI já declarar opções do libpq, como `search_path`, a aplicação acrescenta
`statement_timeout` às opções existentes. O timeout de conexão limita a abertura
da conexão; o timeout de consulta limita a execução no servidor.

## Verificação

Com as variáveis de ambiente configuradas e o PostgreSQL acessível, execute:

```bash
python -m scripts.check_postgres
```

O comando valida somente a configuração PostgreSQL, abre a conexão e executa
`SELECT 1`. Ele não exige chaves de LLM nem depende das tabelas, funções ou views
do produto. Sucesso retorna código zero; falha retorna código diferente de zero
e imprime somente um diagnóstico seguro.

Uma resposta de `SELECT 1` confirma conectividade, autenticação e acesso ao banco
indicado. Ela não comprova que esse banco tenha as tabelas e funções usadas pelo
Agente de Previsão.

Na execução de **4 de outubro de 2026**, o comando retornou código 1 com o
diagnóstico seguro `Não foi possível conectar ao PostgreSQL.`. O Docker Engine
local estava indisponível, a porta local 5432 não tinha serviço escutando e
esta execução não dispunha de `DATABASE_URL` nem das variáveis separadas. A
configuração padrão de desenvolvimento apontou para o serviço local. Portanto,
o `SELECT 1` real continua pendente; a verificação usa um serviço local quando
ele estiver disponível e não foi executada contra o banco oficial.

## Banco local e banco oficial

`docker-compose.dev.yml` oferece um PostgreSQL local para desenvolvimento. Os
arquivos de `db/postgres-init/` são cópias de bootstrap desse ambiente; a fonte
oficial do schema permanece no repositório
[`delta-sql-database`](../../delta-sql-database/). Uma conexão validada no
container local não valida acesso ao PostgreSQL oficial nem garante que suas
views e dados organizacionais estejam disponíveis.
