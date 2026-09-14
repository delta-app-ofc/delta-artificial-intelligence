# `detection/` — motor de detecção de vazamento

Componente **separado** do chat de IA (`app/`). Não usa LLM. Calcula
`consumption_summary.anomaly_detected` e cria documentos em `alerts_history`
— exatamente os dois campos que o `LeakAgent` (`app/agents/leak.py`) só lê,
nunca decide. Essa separação existe de propósito: o prompt do Agente de
Vazamento proíbe "inventar limiar/padrão"; quem decide o limiar é este motor,
não o LLM do chat.

## Como funciona

Só regras explicáveis (`rules.py`, combinadas em `scorer.evaluate_window`) —
sem modelo de ML:

- **Fluxo contínuo** — janela nunca volta a ~zero por 30+ min.
- **Consumo de madrugada** — 00h–05h, só pra propriedades `RESIDENCIAL`.
- **Desvio extremo da baseline** — z-score por hora do dia, `Z_THRESHOLD`
  calibrado (não chutado). É o sinal mais forte pra propriedades `COMERCIAL`,
  já que se adapta ao padrão de cada uma sem depender de uma janela de
  horário fixa.

`anomaly_detected = True` quando **qualquer** regra dispara.
`scorer.DetectionResult.reasons` sempre traz o(s) motivo(s) — nunca uma
decisão "caixa-preta".

A regra de madrugada (`overnight_rule`) só se aplica a propriedades
`RESIDENCIAL` — nunca dispara pra `COMERCIAL` (ver `rules.py`).

## Baseline por usuário/hora (`baseline.py`)

O `baseline_deviation` (desvio da regra de baseline estatística) compara a
janela atual com a média/desvio daquele usuário naquela hora do dia. Isso é
guardado numa coleção Mongo (`db_delta_app.user_hour_baseline`, um documento
por `user_id` + `hour`) e atualizado de forma **incremental** a cada janela
nova (EWMA — média móvel exponencial), em vez de reler o histórico inteiro do
usuário a cada vez.

`detection/watcher.py` sempre lê a baseline **antes** de atualizá-la com a
janela atual — se atualizasse primeiro, um vazamento grande contaminaria a
própria baseline usada pra detectá-lo.

`detection/train.py` (treino em lote, sobre dados sintéticos) calcula a
baseline direto do próprio lote (`features.hour_baseline_from_history`), sem
usar a coleção incremental — ela só existe pro caminho ao vivo.

## Dados de treino — sem gerador próprio

Este pacote **não** tem um gerador de dados sintéticos próprio. Reaproveita o
`delta-hardware-data-simulator`:

- **Dados "normais"**: `python -m dataload.cli consumption_summary <N> --dry-run --scenario normal`
  (a CLI já suporta `--dry-run`; o flag `--scenario` foi adicionado como parte
  desta tarefa — ver a extensão em `leak_scenario.py`/`cli.py` desse repositório).
- **Dados de "vazamento"**: mesma CLI, `--scenario leak`, usando o novo gerador
  `dataload/generators/leak_scenario.py` (fluxo baixo e nunca-zero por várias
  horas, principalmente de madrugada) — **provisório**, até o hardware real
  contratado enviar dados de vazamento de verdade.

`detection/train.py` chama essa CLI via `subprocess` e faz o parse do JSON de
saída — nunca escreve nem lê do Mongo pra treinar, evitando qualquer
ambiguidade entre os dois cenários.

## Rodando

```bash
# 1. Calibre o Z_THRESHOLD sobre dados sintéticos
#    (aponte pro seu clone do delta-hardware-data-simulator)
python -m detection.train ../repo-simulator/delta-hardware-data-simulator

# 2. Suba o Postgres/Mongo locais (Mongo já em replica set, ver abaixo)
docker compose -f ../docker-compose.dev.yml up -d

# 3. Rode o watcher (fica escutando o Change Stream)
python -m detection.watcher
```

## Por que o Mongo precisa ser um replica set

O motor reage **quase em tempo real** a cada janela nova via
[MongoDB Change Streams](https://www.mongodb.com/docs/manual/changeStreams/):
em vez de ficar perguntando "tem novidade?" de tempos em tempos (*polling*), o
processo assina a coleção e é avisado assim que algo novo é inserido.

Esse recurso depende do *oplog* do Mongo, que só existe quando ele roda como
**replica set** — mesmo que seja de um nó só (não precisa de vários
servidores). O `docker-compose.dev.yml` já sobe o serviço `mongo` com
`--replSet rs0` e inicializa o replica set automaticamente na primeira subida.
Bancos Mongo gerenciados (Atlas etc.) já são replica set por padrão — isso é
uma particularidade só do ambiente local em Docker.

