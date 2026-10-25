# Agente Juiz com Jev

O Juiz avalia a candidata produzida pelos especialistas antes de o grafo publicar a resposta. Usa a integração langchain-typesafe, seguindo o experimento manual, e recebe a pergunta, a candidata e as evidências efetivamente retornadas pelas ferramentas.

## Regra de decisão

Esta implementação usa a seguinte política de decisão:

| Avaliação | Primeira tentativa | Depois da única revisão |
| --- | --- | --- |
| Sem erro, confidence >= 0,80 | Publicar | Publicar |
| Sem erro, confidence < 0,80 | Pedir revisão com justificativa Python | Mensagem segura |
| Erro corrigível, qualquer confidence | Pedir revisão com justificativa Python | Mensagem segura |
| Erro crítico, qualquer confidence | Mensagem segura imediatamente | Mensagem segura imediatamente |
| Avaliador indisponível ou resultado inválido | Mensagem segura | Mensagem segura |

O limite inclui exatamente 0,80: uma candidata sem erro nessa confiança pode ser publicada. A avaliação crítica tem prioridade: mesmo com confidence baixo, ela não entra na tentativa de correção.

O Jev responde uma única **Choice de gravidade**. O fluxo compara o confidence dessa classificação, entre 0 e 1, com o limite 0,80.
Confidence representa a concentração da classificação; não comprova a taxa de acerto do Juiz.

## Fluxo

~~~text
Contexto → roteador → especialistas → candidata composta → Juiz
  aprovada → resposta final
  correção → especialistas recebem justificativa → nova candidata → Juiz
  rejeitada/indisponível → mensagem segura
~~~

O Juiz não é uma intenção adicional do roteador. Todas as contribuições escolhidas são reunidas antes da avaliação, para permitir conferir também sua coerência conjunta. O grafo preserva chamadas e resultados de tools, fontes, avisos e dados necessários ao julgamento.

A pergunta original do fluxo permanece separada do feedback de revisão. O especialista recebe a justificativa e a candidata anterior para conferir e reformular sua contribuição. A revisão continua sujeita ao escopo do usuário e aos limites das ferramentas.

Há no máximo uma rodada de revisão e dois julgamentos por solicitação. Contadores e histórico de revisão são reiniciados inclusive quando a mesma sessão recebe outra pergunta. O nó final publica a candidata aprovada sem acrescentar afirmações factuais.

A candidata e o gráfico rejeitados não se tornam resposta pública. O histórico interno de julgamentos permite inspecionar decisões; não faz parte do contrato público de resposta do chat. O histórico e a memória de conversas usados como contexto do Jev passam por redação determinística de PII; itens que falham no guardrail de saída são omitidos.

## Como o Python gera a justificativa

O Jev retorna uma classificação tipada. **O Python não pede ao modelo para escrever uma justificativa livre.** Ele aplica a tabela de decisão e seleciona mensagens em português associadas aos motivos encontrados.

- **Sem erro, baixa confiança:** a mensagem informa que a classificação ficou abaixo de 80% e pede conferência usando as evidências disponíveis. Ela não afirma que o conteúdo está errado.
- **Erro corrigível:** a mensagem informa a classificação e solicita ajuste da candidata com base nas ferramentas e fontes. Ela não inventa qual número, frase ou fonte específica está errada.
- **Erro crítico:** a mensagem interna registra o bloqueio; o texto potencialmente problemático não é repetido na resposta pública.
- **Segunda tentativa insuficiente:** a mensagem informa que a rodada de revisão foi esgotada. Não inicia outro ciclo.
- **Falha de configuração/provedor/formato:** registra indisponibilidade sem expor exceções, chaves ou respostas brutas do provedor.

Os códigos da implementação são:

| Código | Por que o Python o escolhe |
| --- | --- |
| ANSWER_APPROVED | Choice sem erro com confidence >= 0,80. |
| LOW_CONFIDENCE | Choice sem erro abaixo de 0,80 na primeira avaliação. |
| CORRECTABLE_ISSUE | Choice com erro corrigível na primeira avaliação. |
| CRITICAL_ISSUE | Choice com erro crítico em qualquer avaliação. |
| REVIEW_EXHAUSTED | Segunda avaliação ainda corrigível ou sem confiança suficiente. |
| JUDGE_CONFIGURATION_INVALID / JUDGE_PROVIDER_UNAVAILABLE / JUDGE_PROVIDER_ERROR / JUDGE_SCHEMA_INVALID / JUDGE_INPUT_INVALID | A avaliação não pôde ser obtida ou interpretada com segurança. |

As justificativas são mensagens determinísticas vinculadas à decisão e aos códigos do resultado. Isso torna seu comportamento legível e permite revisar os textos sem outra chamada ao modelo. Um sinal global não autoriza explicar uma suposta falha específica: para fazer isso, seria necessário avaliar afirmações identificadas individualmente.

A resposta segura ao usuário é separada dessas instruções internas. O Juiz decide a liberação da candidata; ele não substitui os guardrails de entrada/saída nem a autorização aplicada pelas ferramentas.

## Avaliação e evidências

A rubrica distingue:

- Consistência: compatibilidade entre afirmações, números, períodos e fontes retornadas.
- Relevância: atendimento ao pedido atual.
- Adequação: escopo, privacidade e linguagem de incerteza.
- Completude: partes do pedido e limitações necessárias.

Uma resposta que reconhece ausência de dados pode estar correta. Não exigir que ela invente um valor ou responda com conhecimento externo quando as evidências não permitem.

O texto da candidata e os documentos são conteúdo a avaliar. Ordens contidas neles não devem alterar os critérios do Juiz. A garantia de saída tipada não equivale a garantia de conteúdo verdadeiro.

## Configuração

A integração lê a chave TYPESAFE_API_KEY pelos settings da aplicação, sem exigir credenciais durante a importação. Os defaults são JEV_MODEL=jev-1.14.0 e JEV_TIMEOUT_SECONDS=5, também descritos em .env.example. Em APP_ENV=test, nenhum .env deve ser lido.

As integrações Gemini/Groq dos especialistas permanecem separadas. O Juiz não precisa criar conta, comprar créditos ou alterar coleções. O cliente Jev é criado no primeiro uso e reutilizado pelo processo. Ao substituir a chave temporária do professor ou o modelo, reinicie o processo para recarregar settings e cliente.

Não versionar a chave nem enviá-la ao frontend. Erros de acesso, saldo, timeout e indisponibilidade não podem ser interpretados como aprovação.

## Validação manual do fluxo

O arquivo **manual_chat_judge.py** permite exercitar o caminho de entrada, grafo, especialistas, ferramentas, julgamento, eventual correção e saída, sem iniciar um servidor HTTP. Ele é a entrada manual da implementação; manual_jev.py permanece como experimento isolado de Gemini + Jev.

Execute na raiz deste repositório com o Python do ambiente que contém as dependências:

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manual_chat_judge.py --user-id 1 --no-history
~~~

Use um usuário e dados autorizados do seu ambiente. O ID informado no teste manual não substitui autenticação. As consultas particulares precisam de PostgreSQL/MongoDB; o caminho RAG precisa de Gemini embeddings/Qdrant; o roteador e especialistas dependem dos respectivos provedores. A validação completa pode requerer todos esses componentes.

O runner deve mostrar a resposta final e os metadados de revisão, como gravidade, confidence e justificativa Python. Candidatas bloqueadas não são apresentadas como resposta final. Sem --no-history, turnos liberados são gravados no MongoDB. Com essa opção, as gravações são puladas; leituras de contexto e ferramentas continuam no fluxo. --session-id permite continuar uma sessão do mesmo usuário. Se a gravação falhar, o runner avisa e ainda mostra a resposta que já passou pelos gates.

## O que foi verificado

Nesta revisão, a compilação e a importação do workflow passaram. Cinco casos simulados cobriram o limite 0,80, baixa confiança, erro corrigível, erro crítico e revisão esgotada; um timeout simulado confirmou o bloqueio seguro. Não houve chamadas aos provedores. Isso não comprova a qualidade semântica do Jev, a disponibilidade dos provedores, os bancos remotos ou a configuração do ambiente de demonstração.

O teste real fica disponível no runner manual, para execução pela pessoa responsável. Não foi adicionada uma suíte persistente de testes ao repositório.

## Referências

- [Integração TypeSafe no LangChain](https://docs.langchain.com/oss/python/integrations/providers/typesafe).
- [Probabilidade e confidence](https://docs.typesafe.ai/confidence).
- [Choice](https://docs.typesafe.ai/primitives/choice).
