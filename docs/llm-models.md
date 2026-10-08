# Provedores e modelos de linguagem

Esta aplicação mantém os identificadores dos modelos já usados pelo projeto e lê os parâmetros de `Settings` da TASK-01. A configuração não é uma afirmação de qualidade comparativa: o projeto não possui benchmark próprio em português. As justificativas abaixo consideram o idioma dos prompts, a finalidade de cada papel e o suporte documentado a chamadas de ferramentas.

As fontes oficiais foram consultadas em **4 de outubro de 2026**. Disponibilidade, modelos e limites podem mudar; verifique os links oficiais antes de alterar os identificadores.

## Modelos por papel

| Papel | Provedor e identificador configurável | Uso no código | Ferramentas e justificativa | Amostragem |
| --- | --- | --- | --- | --- |
| Especialista principal | Google Gemini, `GEMINI_MODEL` (padrão `gemini-2.5-flash`) | Previsão e Vazamento usam `llm_especialista`, cujo primeiro provedor é Gemini. Consumo usará esse papel quando sua implementação entrar na TASK-05. | O modelo consta na documentação oficial e suporta function calling. Os prompts do projeto são em português e os agentes podem consultar ferramentas locais. Isso torna o modelo compatível com o fluxo; não há benchmark próprio que permita afirmar superioridade em português. A documentação atual restringe o acesso ao Gemini 2.5 Flash a projetos/usuários que já tinham uso ativo; instalações sem acesso podem configurar outro modelo Gemini disponível que aceite ferramentas. | `temperature=0.3`; `top_p=0.95`. |
| Especialista alternativo | Groq, `GROQ_SPECIALIST_MODEL` (padrão `openai/gpt-oss-120b`) | Fallback de `llm_especialista`; também preservado como `llm_groq_especialista` para compatibilidade. | O catálogo oficial da Groq lista o identificador e documenta tool use. Ele mantém uma segunda opção de provedor para falhas transitórias do principal. Seu uso com prompts em português é uma escolha operacional, não uma garantia de qualidade medida pelo projeto. | `temperature=0.3`. |
| Modelo rápido | Groq, `GROQ_FAST_MODEL` (padrão `openai/gpt-oss-20b`) | Construído sob demanda em `llm_rapido`. Nenhum roteador ou juiz usa esse modelo atualmente. | O catálogo da Groq lista o identificador e documenta tool use. O nome de configuração separa esse papel para um roteador ou juiz futuro; a aplicação ainda não mede latência nem qualidade para esses usos. | `temperature=0.0`. |
| Embedding | Google, constante pública `EMBEDDING_MODEL_NAME` (`gemini-embedding-2-preview`) | Apenas a constante para compatibilidade com consumidores existentes. | A documentação oficial lista o identificador de embedding. Esta tarefa não cria cliente de embedding, retriever, indexação ou fluxo RAG; a presença da constante não significa que RAG esteja implementado. | Não se aplica. |

Os nomes públicos `llm_especialista`, `llm_gemini`, `llm_groq_especialista`, `llm_rapido` e `EMBEDDING_MODEL_NAME` são mantidos. `llm_especialista` é a interface usada pelos agentes especialistas. Os modelos de provedor individuais não incluem fallback.

## Parâmetros e configuração

| Setting | Padrão da TASK-01 | Efeito |
| --- | ---: | --- |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Identificador do especialista principal. |
| `GROQ_SPECIALIST_MODEL` | `openai/gpt-oss-120b` | Identificador do fallback especialista. |
| `GROQ_FAST_MODEL` | `openai/gpt-oss-20b` | Identificador do modelo rápido ainda sem consumidor. |
| `LLM_FALLBACK_ENABLED` | `true` | Habilita a construção e validação do Groq especialista no papel especialista. Com `false`, esse papel não exige nem cria um cliente Groq. O modelo rápido continua exigindo Groq quando solicitado. |
| `LLM_TIMEOUT_SECONDS` | `15` | Timeout finito aplicado a cada tentativa individual nos dois provedores. |
| `LLM_MAX_RETRIES` | `1` | Número de retries além da tentativa inicial em cada provedor. Deve ser inteiro não negativo. |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | Limite de saída configurado pela aplicação; não é o máximo anunciado pelos provedores. |

As chaves são `GEMINI_API_KEY` e `GROQ_API_KEY`. A construção é lazy: importar `app.services.llms` não cria clientes, não valida chaves e não faz chamadas de rede. A primeira leitura de cada nome público valida os settings do caminho solicitado e então cria o cliente em cache. Após recarregar settings em testes ou desenvolvimento, `clear_llm_cache()` descarta os modelos já construídos.

Os modelos consultados anunciam até 65.536 tokens de saída, acima do limite padrão mais conservador de 4.096 usado pela aplicação. Os limites publicados estão sujeitos a mudanças e não substituem os limites aplicados pela conta ou endpoint.

## Chamadas de ferramentas e fallback

O runtime chama `bind_tools(tools)` e, em cada turno, `invoke(messages)`. A integração `RunnableWithFallbacks` disponível na versão instalada do `langchain-core` não expõe `bind_tools`; por isso, `llm_especialista` usa um adaptador pequeno que vincula a mesma lista de ferramentas tanto ao Gemini quanto ao Groq. Em uma falha transitória, o fallback recebe a mesma lista de mensagens daquele turno, incluindo `AIMessage` e `ToolMessage` anteriores.

O adaptador troca de provedor apenas para falhas de transporte/timeout, HTTP 408 ou 429, e indisponibilidade HTTP 5xx reconhecidas pelas integrações dos SDKs. A integração Gemini transforma `google.genai.errors.ClientError` em `ChatGoogleGenerativeAIError`; o adaptador só classifica esse wrapper quando seu `__cause__` é um erro protocolar Google (`APIError`/`ClientError`) e usa o código HTTP dessa causa. Wrapper sem uma causa reconhecida propaga sem fallback nem conversão, para não esconder erros de conversão ou programação. Respostas rejeitadas (por exemplo, HTTP 400, 401 ou 403) viram `LLMProviderError` com uma mensagem pública sem corpo da resposta ou texto do SDK. Se ambos os provedores falharem de forma transitória, a aplicação levanta `LLMUnavailableError` com mensagem genérica. Erros de programação como `TypeError`, `ValueError` e `KeyError` não são convertidos em fallback.

O fallback cobre somente uma chamada do modelo. Se o runtime já recebeu uma chamada de ferramenta, executou-a e recebeu uma falha do modelo no turno seguinte, o fallback recebe o `ToolMessage` daquele resultado. A execução anterior da ferramenta não é repetida pelo adaptador. Ferramentas continuam sendo executadas pela aplicação, não pela API do provedor.

`LLM_MAX_RETRIES=R` limita ambos os provedores a no máximo `R + 1` requisições por invocação: a integração Gemini recebe `R + 1` como total de tentativas, enquanto o cliente Groq recebe `R` como retries além da tentativa inicial. Com fallback habilitado, o pior caso para uma invocação do papel especialista é `2 × (R + 1)` requisições, somando as tentativas do Gemini e do Groq. Com o padrão atual (`R=1`), são no máximo quatro requisições ao todo. O timeout vale por tentativa; intervalos internos de retry também podem aumentar o tempo total do turno.

## Fontes oficiais

- Google, [lista de modelos Gemini](https://ai.google.dev/gemini-api/docs/models?hl=en) e [ficha do Gemini 2.5 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash?hl=en): identificador, disponibilidade atual documentada, function calling e limites publicados.
- Google, [function calling](https://ai.google.dev/gemini-api/docs/generate-content/function-calling?hl=en): fluxo de chamada e retorno de ferramentas.
- Integração LangChain, [ChatGoogleGenerativeAI](https://reference.langchain.com/python/langchain-google-genai/chat_models/ChatGoogleGenerativeAI): interface Python e parâmetros da integração.
- Groq, [GPT-OSS 120B](https://console.groq.com/docs/model/openai/gpt-oss-120b), [GPT-OSS 20B](https://console.groq.com/docs/model/openai/gpt-oss-20b) e [tool use local](https://console.groq.com/docs/tool-use/local-tool-calling): IDs do catálogo, uso de ferramentas e execução local pela aplicação.
- Integração LangChain, [ChatGroq](https://reference.langchain.com/python/langchain-groq/chat_models/ChatGroq) e [bind_tools](https://reference.langchain.com/python/langchain-groq/chat_models/ChatGroq/bind_tools): interface e suporte da integração a ferramentas.
- SDKs oficiais, [Groq Python](https://github.com/groq/groq-python) e [Google Gen AI Python](https://github.com/googleapis/python-genai): categorias de erros, timeout e semântica de retries considerados na configuração.
- LangChain Core, [with_fallbacks](https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/with_fallbacks): abstração genérica de fallback que motivou o adaptador de `bind_tools`.

### Escopo da validação

Os testes desta tarefa usam clientes substituídos e não gastam créditos. Neste ambiente não havia credenciais LLM; portanto, não foi executado smoke test real contra Gemini ou Groq. Os testes verificam o contrato `bind_tools` → `invoke`, os erros transitórios e permanentes, a passagem do histórico com `ToolMessage` e que o efeito da ferramenta ocorre uma única vez.
