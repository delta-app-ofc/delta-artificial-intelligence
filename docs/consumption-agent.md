# Agente de Consumo

O agente ConsumptionAgent responde sobre consumo efetivamente registrado. Ele é
standalone: run(question) devolve AgentResult(response, tool_calls) pelo runtime
compartilhado, sem API, grafo, previsão ou agente de vazamento. user_id vem do
chamador e fica preso às tools; não aparece nos argumentos do modelo.

Para execução manual:

~~~powershell
python manual_chat.py consumption "Quanto consumi ontem?"
~~~

O usuário dessa entrada manual é uma constante de demonstração no próprio
manual_chat.py. Em uma integração de aplicação, construa o agente com o
identificador autenticado pelo backend.

## Tools

| Tool | Uso |
| --- | --- |
| get_consumption_summary | Soma litros registrados, devolve totais por dia em ordem crescente e mostra dias registrados, média e qualidade dos dados. |
| compare_consumption_periods | Consulta os dois períodos e devolve diferença e variação percentual determinísticas. |
| get_consumption_peaks | Ordena até dez totais diários; empate é ordenado por data crescente. |
| list_consumption_units | Lista somente unidades organizacionais autorizadas, com property_id para desambiguar nomes. |

Os períodos aceitos são today, yesterday, this_week, this_month,
last_7_days, last_30_days, previous_7_days, previous_30_days,
previous_month_same_days e custom. A ferramenta recebe now com fuso
explícito no relógio do agente. O padrão é America/Sao_Paulo; pode ser
injetado em testes e em outras integrações. Cada execução do agente captura um
único instante para o prompt e todas as tools daquela execução.

Períodos locais usam limites [início, fim). Datas customizadas de início e
fim são inclusivas e viram meias-noites locais consecutivas; uma data final
igual a hoje termina no instante consultado. A semana começa na segunda-feira.
Períodos móveis cobrem exatamente 7 ou 30 dias até o instante da consulta.
Datas futuras, intervalos invertidos e períodos acima de 366 dias são
rejeitados. Se a consulta acontece exatamente à meia-noite, o período today
tem duração zero e retorna ausência sem chamar o leitor de consumo.

## Autorização e fontes

O caminho residencial tem prioridade se o usuário também possuir outro vínculo.
Ele consulta o histórico de consumption_summary no MongoDB apenas pelo
user_id autenticado e por limites UTC de window_started_at. Só inclui
janelas finalizadas até o instante da consulta. Essa coleção não contém
property_id, portanto o agente não finge separar uma residência por imóvel.

Para usuários organizacionais, as unidades vêm de
get_user_organization_properties. Sem seleção, a consulta agrega todas as
unidades retornadas para o usuário. Uma seleção por property_id é conferida
contra esse conjunto antes da consulta; nome exato tem prioridade sobre
correspondência parcial. Nomes que continuam ambíguos pedem esclarecimento e
não consultam consumo. Os registros vêm da view diária
dw.vw_ft_consumption_daily; a consulta recebe somente os IDs autorizados.
Esse caminho não chama fn_user_can_estimate, pois descreve dados observados e
não cria estimativas.

## Granularidade e limites

No MongoDB, cada janela é atribuída ao dia local em que começou. Janelas que
cruzam a meia-noite ou o fim do período não são rateadas; a resposta sinaliza
essa fronteira. Duplicatas idênticas para o mesmo dispositivo e limites contam
uma vez. Duplicatas conflitantes, valores negativos ou não finitos, fim antes
do início e documentos inválidos são tratados como dados inconsistentes.
Janelas de dispositivos distintos não são deduplicadas.

No PostgreSQL, cada registro é um total diário por unidade. As bordas de um
período móvel podem incluir dias inteiros; o agente não distribui seu total por
hora nem inventa horário da última leitura. A resposta usa last_available_date
para essa fonte e last_reading_at somente para janelas Mongo finalizadas.
Não há garantia de cadência ou cobertura na view, e o ETL pode ainda não ter
carregado um dia.

Uma data sem registro permanece ausente, nunca vira zero. A média usa somente
dias com registro, e a ferramenta lista as datas sem registro dentro do
intervalo sem calcular percentual de cobertura. Um zero observado é preservado
como leitura real. Comparações só produzem diferença quando ambos os lados têm
registros; se o total anterior for zero, o percentual é null. Diferenças de
duração, quantidade de datas ou quantidade de dias observados são informadas
para contextualizar os totais.

Os estados de retorno são ok, insufficient_data, ambiguous, invalid_input,
source_unavailable e inconsistent_data. Falha ou indisponibilidade da fonte
não é convertida em zero. As tools retornam metadados técnicos para
processamento, mas o prompt orienta o agente a não expor nomes de bancos,
coleções, tabelas ou consultas ao usuário.

Este agente não consulta tarifa nem conta de água, não estima custo, não prevê
consumo e não diagnostica vazamentos. Um pico diário descreve volume agregado,
não vazão instantânea.

## Verificação

Rode a suíte com:

~~~powershell
python -m pytest -q -p no:cacheprovider
~~~

Os testes do agente usam relógio injetado, leitores substituídos e LLM
roteirizado; verificam filtros, escopo, cálculos e o laço AgentResult sem
credenciais ou banco real. Eles não validam a qualidade da redação de um LLM
real nem comprovam a integração com serviços externos. A validação com MongoDB,
PostgreSQL e provedor LLM reais continua dependente desses serviços e de suas
credenciais.
