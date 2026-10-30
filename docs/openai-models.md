# Modelos OpenAI no Delta

A geração usa OpenAI por padrão, com o modelo gpt-6-luna e raciocínio medium.
Os papéis de especialista, modelo rápido e segundo juiz continuam com seus
prompts, ferramentas e contratos. Jev mantém a avaliação tipada inicial.

## Configuração

No arquivo .env local ou no ambiente do processo:

```dotenv
OPENAI_API_KEY=
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-6-luna
OPENAI_REASONING_EFFORT=medium
```

A chave não é versionada. Variáveis do processo prevalecem sobre o arquivo.
APP_ENV=test ignora o .env. As configurações são validadas antes do uso;
somente OpenAI é exigida para a geração sem fallback.

LLM_PROVIDER=gemini mantém a configuração anterior: especialistas Gemini,
modelo rápido Groq e segundo juiz definido por JUDGE_SPECIALIST_MODEL.
No modo OpenAI, todos esses papéis usam OPENAI_MODEL; o valor legado
JUDGE_SPECIALIST_MODEL não substitui o modelo OpenAI.

Com LLM_FALLBACK_ENABLED=true e uma chave Groq configurada, os especialistas
podem usar GROQ_SPECIALIST_MODEL em falhas transitórias. O segundo juiz
também preserva esse fallback, validando Groq quando precisar usá-lo.
Erros permanentes, como autenticação inválida, não acionam fallback.
O modelo rápido usa diretamente o provedor selecionado.

## Responses API e ferramentas

gpt-6-luna suporta function calling com raciocínio medium pela Responses API.
Chat Completions permite function calling nesse modelo somente com esforço
none; por isso a fábrica configura use_responses_api=True.
[Modelo oficial](https://developers.openai.com/api/docs/models/gpt-6-luna).

A integração usa langchain-openai sobre o SDK OpenAI, mantendo o runtime
existente e o agente RAG do LangGraph. As respostas usam o formato
responses/v1 para preservar os itens estruturados. Guardrail, roteador e
síntese extraem texto pelo helper existente, sem interpretar os blocos de
raciocínio como texto da resposta.

As chamadas configuram store=False e preservam o raciocínio criptografado
entre a chamada de ferramenta e sua resposta. Os limites existentes de
timeout, retries e saída continuam aplicados. O limite de saída também
abrange tokens de raciocínio. Temperature e top_p não são enviados à
OpenAI nessa configuração.
[Estado e raciocínio na Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses).

## Cache e encerramento

A fábrica mantém uma instância por snapshot imutável dos settings, protegida
por lock. Os três papéis compartilham o cliente quando a configuração é
igual; mensagens e evidências são montadas em cada chamada.

Após get_settings(refresh=True), use clear_llm_cache() para renovar os
aliases. Um snapshot alterado cria o cliente com a nova configuração;
instâncias anteriores ficam registradas até seu fechamento, sem interromper
requisições que ainda as utilizem.

close_openai_clients() fecha os transportes sync/async e limpa os aliases.
O lifespan da API aguarda esse fechamento depois dos clientes RAG e do juiz.
Runners fora da API devem aguardar o fechamento ao terminar. Reiniciar o
processo aplica a configuração e libera todos os clientes.

Os embeddings Gemini, suas dimensões e os índices Qdrant continuam com a
configuração existente. A chave OpenAI não substitui as credenciais de
embeddings; trocar o espaço vetorial exige reindexação própria.

## Validação

```bash
python -m unittest discover -s tests -v
```

Os testes isolados cobrem cache concorrente, recarga, fechamento, erros
transitórios/permanentes e payloads HTTP simulados da Responses API.
Conferem os outputs de ferramentas, o replay do raciocínio criptografado
e o JSON estruturado.

A validação real confirmou acesso da chave a gpt-6-luna, uma chamada de
ferramenta com dados fictícios e um parecer estruturado aprovado pelo juiz
OpenAI. Essa validação não acessou bancos nem chamou Jev e não substitui a
bateria completa de perguntas do playground. Os relatórios de latência
anteriores continuam sendo evidências históricas das versões anteriores.
