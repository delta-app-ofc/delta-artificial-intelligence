export default {
  id: 'rag',
  label: 'RAG',
  title: 'Consulte o Delta e fontes públicas sobre uso da água.',
  description:
    'Teste as regras do produto e orientações externas adequadas ao perfil da conta, com trechos e referências.',
  placeholder: 'Pergunte sobre o Delta ou uso consciente da água…',
  examples: [
    'Quais etapas compõem o cadastro pessoal e o vínculo do hidrômetro?',
    'Como o cadastro associa um hidrômetro ao local acompanhado?',
    'O que significam consumo acumulado e vazão média?',
    'Como funcionam as metas diárias e mensais de consumo?',
    'Qual é a diferença entre um sinal de consumo anormal e um alerta registrado?',
    'Quais práticas de uso consciente da água são recomendadas pelas fontes públicas para o perfil da minha conta?',
    'O que as fontes da EPA recomendam para reduzir o uso de água em instalações do meu perfil?',
    'Essas fontes informam uma tarifa pública vigente para calcular a minha conta?',
  ],
  mode: 'agent',
  notes: [
    'As regras do Delta vêm da base local. O conhecimento externo usa MIDR/gov.br e a página EPA residencial ou comercial, conforme o perfil real da conta. O perfil não muda ao escrever “sou residencial” ou “sou comercial” na pergunta.',
    'A primeira chamada pode preparar ou atualizar o índice documental. O backend precisa das credenciais Gemini e Qdrant configuradas e de uma coleção Qdrant preexistente com dimensão compatível; não há índice simulado nesta aba.',
    'Este agente explica regras do produto, mas não consulta dados privados da conta, como consumo, metas cadastradas ou alertas ativos.',
    'O MCP deve estar habilitado no backend. No painel de ferramentas, procure search_external_knowledge e confira os trechos, fontes e eventuais indisponibilidades. Não deve haver recomendações de programas, selos ou produtos WaterSense; a URL original da EPA permanece na citação.',
    'Esta aba executa o RAG com guardrails. Use Chat completo ou Juiz para testar também a avaliação da resposta antes da publicação.',
    'Etiqueta de teste: teste_agentes_25_10. Usuário fixo desta execução: 123456789.',
  ],
};
