# Segmentação e recuperação da base Delta

## Objetivo e escopo

Esta primeira etapa prepara a base Markdown e recupera os trechos mais próximos
da pergunta. Não gera respostas, não implementa o `RagAgent` e não modifica o
roteamento, o Judge ou a memória de conversas.

A fonte é o documento `IA/RAG/base-conhecimento-delta.md` do repositório
`delta-handbook`. O caminho é passado explicitamente: o serviço não depende da
estrutura de pastas dos outros repositórios nem copia o documento para cá.

## Como funciona

1. `#` identifica o documento, `##` identifica capítulos e `###` identifica
   subtópicos. Cada corpo de seção vira um trecho, acompanhado da hierarquia
   completa de títulos. Texto antes dos capítulos, incluindo versão e ressalvas,
   também é preservado. Títulos sem corpo não geram vetores vazios.
2. O texto enviado ao embedding contém títulos e conteúdo. Assim, por exemplo,
   um subtópico de chuva mantém sua ligação ao capítulo de clima. Uma pergunta
   busca todos os trechos e devolve os mais próximos, com seus respectivos
   capítulos; não há classificação prévia que restrinja a busca a um só capítulo.
3. `gemini-embedding-001` produz vetores de 3072 dimensões. Documentos usam
   `RETRIEVAL_DOCUMENT`; a pergunta usa `RETRIEVAL_QUERY`. É um modelo textual,
   adequado a esta etapa com Markdown. A integração usa a dependência existente
   `langchain-google-genai`, com timeout HTTP de 30 segundos.
4. Qdrant armazena os vetores com distância Cosine na coleção fixa
   `rag_documents`, separada de `session_summaries`. Os metadados incluem fonte,
   hash da revisão, modelo, hierarquia, texto e linhas inicial/final (inclusivas).
5. A busca devolve até três trechos por padrão, com IDs, scores e metadados.
   Similaridade não é probabilidade nem garantia de relevância. O limiar opcional
   precisa ser calibrado com perguntas reais; nenhum limiar arbitrário é imposto.

A separação reconhece títulos no início das linhas e ignora títulos dentro de
blocos de código cercados por crases ou tils. Não separa pelo caractere `#`
encontrado no meio de frases. Para evitar truncamento silencioso pelo provedor,
seções acima de 6000 caracteres (corpo e títulos) são rejeitadas: subdivida-as
com `###` na fonte. Esse limite conservador em caracteres não é um tokenizador.
Títulos `####` e posteriores permanecem no corpo.

## Comandos

Execute na raiz de `delta-artificial-intelligence`. No workspace com os dois
repositórios lado a lado:

```powershell
# Somente leitura local: não exige chaves nem Qdrant.
python -m scripts.rag inspect ../delta-handbook/IA/RAG/base-conhecimento-delta.md

# Gera embeddings pela API Gemini e grava no Qdrant configurado.
python -m scripts.rag index ../delta-handbook/IA/RAG/base-conhecimento-delta.md

# Gera o embedding da pergunta e recupera os trechos, sem chamar LLM de resposta.
python -m scripts.rag search ../delta-handbook/IA/RAG/base-conhecimento-delta.md --question "Como funciona o vínculo do hidrômetro?" --top-k 3
```

Antes de `index` e `search`, configure `GEMINI_API_KEY`, `QDRANT_URL` e, quando
exigido pelo servidor, `QDRANT_API_KEY`. Use `.env` ou variáveis do processo,
conforme os settings existentes. Não há fallback implícito para Qdrant local;
o destino deve ser explícito. Qdrant aplica timeout de 30 segundos. As credenciais
precisam permitir criar a coleção, os índices de payload e gravar/ler pontos.
O comando de indexação faz chamadas cobradas ao provedor de embeddings.

Use `--source` para identificar outra fonte e `--score-threshold` para aplicar
um limiar Cosine entre -1 e 1. Na API Python, `load_document`, `index_document`
e `search_document` estão em `app/services/rag.py`; os clientes são injetáveis.
O chamador deve fechar o cliente Qdrant; o CLI faz isso em `finally`.

## Revisões e falhas

Reindexar o mesmo conteúdo atualiza os mesmos IDs, sem duplicar pontos. O hash
inclui conteúdo e versão do segmentador. Após alterar o Markdown, execute
`index` novamente antes de `search`. A busca filtra fonte, revisão e modelo;
revisões antigas continuam armazenadas, mas não participam da consulta atual.
O arquivo precisa estar acessível também na consulta para identificar a revisão.

Uma revisão ausente ou incompleta falha antes de consultar embeddings. Erros
de provedor/banco propagam na API Python; não viram uma resposta vazia. O CLI
retorna código 1 com mensagem segura, sem imprimir erros externos ou credenciais.
Erros de configuração indicam o nome da variável ausente, sem mostrar seu valor.
Lista vazia significa que a busca executada não encontrou pontos aceitos pelo
limiar. Coleções incompatíveis são recusadas, nunca apagadas ou recriadas.

Revisões antigas não são removidas automaticamente. Trocar modelo ou dimensões
exige uma migração explícita, não comparação entre espaços vetoriais diferentes.

## Validação e limites

`python -m pytest tests/test_rag.py -q` verifica segmentação, rastreabilidade,
idempotência, isolamento de fontes/revisões, erros e consulta vetorial usando
Qdrant real em memória e embeddings controlados. Não acessa Gemini nem Qdrant
remoto e não comprova qualidade semântica ou disponibilidade dos serviços.

Na validação desta implementação, a suíte completa passou com 214 testes. O
diretório temporário padrão do Windows sandbox negou escrita nos testes com
arquivos; a execução usou `--basetemp` em um diretório novo e isolado dentro do
workspace. Isso não exige mudar os testes ou a configuração da aplicação.

A inspeção local da base de referência encontrou 12 capítulos e 58 trechos,
incluindo a apresentação. Credenciais Gemini e URL Qdrant estavam ausentes:
geração dos embeddings reais, persistência remota e avaliação temática com
perguntas reais continuam pendentes. O documento original não foi alterado.

Referências técnicas: [embeddings Gemini](https://ai.google.dev/gemini-api/docs/embeddings)
e [documentação Qdrant](https://qdrant.tech/documentation/).
