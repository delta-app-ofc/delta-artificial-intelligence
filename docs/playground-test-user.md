# Usuário de teste 123456789 no playground

O backend, a validação de configuração do frontend e os rótulos do console usam
o usuário fixo **123456789**. O perfil continua sendo consultado no PostgreSQL;
não é um perfil simulado nem um argumento livre do modelo.

## Ordem de execução manual

Os arquivos abaixo foram preparados para o cenário desta atividade. Eles não
são executados pela inicialização da API. Execute primeiro o SQL e depois os
dois arquivos MongoDB, cada qual na sua conexão correta.

1. [PostgreSQL](../scripts/playground_user.sql): no mesmo banco configurado para
   a IA. Cria a conta fictícia se faltar, associa ao imóvel **178 — AGENTE DO
   FBI DELTA**, e cadastra o dispositivo `ESP32-TEST-JUIZ-123456789` nesse imóvel.
   O script recusa imóvel divergente e dispositivo já associado a outro imóvel.
2. [MongoDB app](../scripts/playground_user_app.js): na conexão
   `MONGODB_APP_URI`, database `db_delta_app`. Migra preferências, sessões e
   alertas do ID anterior `12345679` para `123456789`.
3. [MongoDB telemetria](../scripts/playground_user_telemetry.js): na conexão
   `MONGODB_TELEMETRY_URI`, database `db_delta_telemetry`. Migra as leituras e
   alinha o identificador do dispositivo de teste com o cadastro SQL.

**As conexões de app e telemetria são diferentes no ambiente consultado.**
Use uma sessão mongosh para cada conexão, ou carregue as duas URIs no seu
terminal antes destes comandos, executados na raiz do repositório de IA:

```powershell
mongosh "$env:MONGODB_APP_URI" --file scripts/playground_user_app.js
mongosh "$env:MONGODB_TELEMETRY_URI" --file scripts/playground_user_telemetry.js
```

As variáveis de ambiente acima precisam estar preenchidas no terminal; um `.env`
da API não as exporta automaticamente para o PowerShell. Também é possível
colar cada arquivo no mongosh da conexão correspondente.

## Efeito dos scripts

Na inspeção de 01/11/2026, nenhum dos dois IDs existia no SQL. O imóvel 178 já
existia como residencial, sem vínculo ou dispositivo. No MongoDB, o ID antigo
possuía **1 preferência, 30 sessões, 21 alertas e 720 leituras**; o ID novo não
possuía registros nessas coleções. Esses números são o estado consultado,
não uma quantidade que os scripts inventam ou impõem.

O usuário SQL recebe nome e e-mail fictícios, sem privilégios administrativos.
O hash Argon2id foi gerado a partir de uma senha aleatória descartada: o script
não fornece uma senha de login. Esse cadastro serve ao playground por ID;
para uma conta com login, use o fluxo oficial de cadastro/recuperação do produto.
Se o ID já existir, o script preserva seus dados e exige que a conta esteja ativa.

O SQL reutiliza classificação, endereço, região e tarifa existentes do imóvel.
Não cria valores de tarifa. O `SELECT` final deve retornar `access_kind =
'residential'`; `can_estimate` também depende da tarifa vigente. O ID explícito
do fixture não modifica a sequência de cadastro dos demais usuários.

Os scripts Mongo preservam `_id`, conteúdo, datas das leituras e mensagens.
As referências de `chat_feedback` às sessões continuam válidas. O dispositivo
de teste antigo `ESP32-TEST-JUIZ-12345679` é renomeado nos registros migrados
para `ESP32-TEST-JUIZ-123456789`, que é o identificador cadastrado no SQL.
Outros identificadores de dispositivo não são alterados.

Se já houver preferências no novo ID, elas são preservadas; o registro de
preferências antigo também fica intacto para evitar conflito no índice único.
Se faltarem preferências, cria-se uma meta fictícia de 400 litros/dia, modo
escuro desativado e notificações desativadas. Uma sessão vazia e um status
sintético de dispositivo só são criados quando necessários. Não são fabricados
consumo, alertas, clima ou valores financeiros.

Cada script pode ser repetido sem duplicar a migração. O SQL é transacional;
PostgreSQL e as duas conexões MongoDB não compartilham uma transação. Se uma etapa
falhar, corrija a causa e repita essa etapa. Os arquivos não alteram schemas,
índices, usuários antigos no SQL, tarifas ou coleções Qdrant. Resumos de memória
de longo prazo do usuário antigo no Qdrant não são transferidos por estes scripts.

Depois da execução, recarregue o playground, inicie uma nova sessão e confira
o ID **123456789** no cabeçalho. Para testar RAG externo, mantenha o processo da
branch com `MCP_EXTERNAL_ENABLED=true` e as configurações Gemini/Qdrant.

## Verificação desta entrega

Os campos e vínculos SQL e os validadores Mongo foram conferidos por leitura
nos destinos configurados. Os scripts de carga não foram executados nesses
bancos. A sintaxe JavaScript passou em `node --check`; testes com coleções em
memória cobrem migração, repetição, preservação de dados de outro usuário,
preferências já existentes e bloqueio por conexão sem as coleções esperadas.
O conjunto direcionado de console, scripts e RAG passou com 35 testes.
