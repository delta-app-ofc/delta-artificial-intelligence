# Reutilização de clientes: implementação e comparação

Data: 29/10/2026. Branch local: `fix/reuse-ai-clients`. Base: `799ccc5d29726620f7c2eb475741beefc0d3ff64`, a main remota atualizada no início do trabalho.

## Resultado

Houve melhora prática na busca RAG e eliminação do custo repetido de construção. A amostra real do juiz oscilou e não comprova ganho consistente no tempo total de avaliação. A primeira chamada continua pagando a inicialização.

| Medida após o primeiro uso | Antes | Depois | Redução observada |
| --- | ---: | ---: | ---: |
| Preparação local dos clientes RAG, sem consulta | 940,64 ms | 0,23 ms | 99,98% |
| Preparação local do juiz com fallback simulado | 1.174,52 ms | 0,89 ms | 99,92% |
| Busca RAG real completa, sem geração da resposta | 3,479 s | 2,501 s | 28,1% |
| Avaliação real do juiz especialista | 5,186 s | 4,722 s | 9,0%, sem consistência entre os pares |

As duas primeiras linhas têm seis pares de repetições; as duas últimas, dois pares após a primeira chamada. Os dados frios também foram registrados e não entram nessas medianas.

Os tempos de 4,6–6,1 s do perfil anterior não foram usados como “antes” deste ensaio. O teste atual mediu ambas as versões no mesmo ambiente, com execução nativa permitida e a localização atual do workspace. A construção foi mais rápida neste ensaio, por isso a economia atual não deve ser anunciada como 4–6 s garantidos por chamada.

## O que mudou

- `app/services/rag.py` mantém uma instância de embeddings e uma de Qdrant por processo.
- `app/tools/rag.py` preserva os clientes após a busca. Uma falha não fecha o cliente compartilhado.
- `app/agents/judge_specialist.py` reutiliza um modelo Gemini e um Groq, mantendo parâmetros, callbacks, prompt completo e lógica do fallback.
- `app/main.py` fecha os recursos inicializados no lifespan, após o atendimento das requisições, incluindo transportes síncronos e assíncronos.
- Um lock impede que acessos simultâneos construam clientes duplicados. Falhas de construção não entram no cache.
- O fechamento tenta os demais recursos se um deles falhar, limpa o cache e permite reconstrução com nova configuração.

O cache contém objetos de comunicação. Perguntas, resultados de ferramentas e pareceres continuam sendo montados por solicitação. O usuário e o contexto não viram estado persistente do cliente.

Não houve mudança nos thresholds, rubrica Jev, agentes de negócio, indexação, dimensão dos vetores ou número de retries. Os arquivos `app/config.py`, `app/agents/judge.py` e `app/services/prompts.py` foram conferidos contra a base e permanecem iguais.

Para recarregar configuração manualmente, interrompa novas requisições e aguarde `close_rag_clients()` e `close_judge_clients()` antes de reconstruir. Reiniciar o servidor também aplica a nova configuração. Cada worker tem seu próprio cache.

A reutilização de conexões e o gerenciamento do ciclo de vida seguem os mecanismos descritos pela [documentação HTTPX](https://www.python-httpx.org/advanced/clients/) e pelo [lifespan do FastAPI](https://fastapi.tiangolo.com/advanced/events/).

## Método

Foi congelada uma cópia do código da main antes da alteração. As duas versões foram carregadas no mesmo processo e usaram os mesmos settings. A ordem alternou AB/BA para reduzir viés de ordem.

### Teste local

Uma rodada fria seguida de seis pares para cada componente:

- RAG: criação dos clientes reais de Qdrant e embeddings.
- Juiz: clientes reais Gemini/Groq, com invocação substituída e falha transitória simulada para exercitar os dois.
- Credenciais fictícias e conexões externas bloqueadas pelo próprio script.
- A verificação de compatibilidade remota do Qdrant foi desabilitada somente nesse teste sem rede, nas duas versões.
- Nenhuma geração ou embedding remoto; nenhum token consumido.
- O fechamento do baseline fica fora do cronômetro de preparação.

Todos os seis pares locais favoreceram o reuso. Esse é um ganho na preparação, não uma previsão de redução percentual da resposta completa.

### Teste real

Foram seis buscas RAG e seis avaliações do especialista, três antes e três depois para cada tarefa. A primeira chamada de cada versão foi separada das duas seguintes.

O RAG usou a mesma pergunta sobre metas e as mesmas fontes, com embeddings e Qdrant reais. A medição cobre a tool completa, incluindo leitura da fonte, verificação do índice, embedding da pergunta e recuperação; não inclui o LLM que redige uma resposta RAG.

O juiz recebeu a mesma candidata e as mesmas evidências congeladas do caso C01 histórico. O parecer Jev foi reaproveitado; nenhuma nova chamada ao Jev foi feita. O contexto conversacional original não estava disponível como campo isolado e foi definido como vazio nas duas versões. Foram usados Gemini e Groq reais, sem salvar conversas.

O benchmark preservou timeouts e retries existentes e não repetiu requisições por conta própria. Configuração secreta não foi gravada nos resultados.

## Resultados reais por par

| Tarefa | Par | Antes | Depois | Observação |
| --- | --- | ---: | ---: | --- |
| RAG | Primeiro uso | 3,788 s | 4,194 s | Ambos constroem clientes |
| RAG | Repetição 1 | 3,563 s | 2,454 s | Mesmo conteúdo recuperado |
| RAG | Repetição 2 | 3,395 s | 2,547 s | Mesmo conteúdo recuperado |
| Juiz | Primeiro uso | 5,014 s | 5,263 s | Gemini nas duas versões |
| Juiz | Repetição 1 | 5,415 s | 6,081 s | Gemini; geração mais lenta depois |
| Juiz | Repetição 2 | 4,957 s | 3,363 s | Google falha e Groq responde nas duas versões |

Todas as seis buscas retornaram três trechos com hash idêntico. Todas as seis avaliações terminaram com aprovação. Isso verifica os resultados destes casos, sem estabelecer acurácia geral do juiz.

No primeiro par quente do juiz, o callback Gemini passou de 4,702 s para 6,077 s, anulando a economia da preparação. No segundo, a falha Google e a resposta Groq também variaram. O primeiro uso do Groq na versão nova ainda precisou construir esse cliente, mesmo com o Gemini já em cache.

A parte do juiz fora dos callbacks dos modelos caiu de mediana de 1,026 s para 0,238 s nos dois pares quentes. Essa diferença inclui outras operações além de criação de clientes. Ela ajuda a separar preparação da variação de geração; não equivale a um tempo puro de rede.

No RAG quente, as etapas `rag_create_client` e `rag_create_embeddings` ficaram abaixo da resolução de 0,1 ms do trace. A verificação do índice ainda leva cerca de 1,03 s e a busca, incluindo embedding da pergunta, aproximadamente 1,4–1,5 s.

## Validação e limites

Oito testes isolados passaram, cobrindo criação simultânea deliberadamente lenta, fechamento lazy/idempotente, falha de construção, tentativa de fechamento após erro, nova configuração após fechamento, contexto atual no fallback, recuperação de busca após falha e encerramento da API. Compilação e `git diff --check` também passaram.

Comando dos testes:

```bash
python -m unittest discover -s tests -p test_client_reuse.py -v
```

A amostra real é pequena. O ganho de aproximadamente um segundo por busca RAG é relevante para essa etapa e coerente com a preparação removida; não permite estimar p95 de produção. A variação do juiz não permite afirmar melhora consistente de seu tempo total.

O fluxo HTTP completo do playground, roteador, demais agentes e guardrails não foi cronometrado neste ensaio. Portanto, 28,1% é redução da busca RAG medida, não do chat completo.

Os arquivos de evidência incluem `local.json`, `live.json`, `resumo.json`, `live-method.json`, `benchmark.py`, `analisar.py` e `testes.txt`. O resumo registra versões instaladas, hashes das fontes e commit de base. Os resultados frios foram preservados.

A próxima investigação pode focar a verificação repetida do índice no RAG e a variabilidade de geração/429 no juiz. Essas outras mudanças não foram implementadas nesta branch.
