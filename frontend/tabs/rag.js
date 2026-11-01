export default {
  id: 'rag',
  label: 'RAG',
  title: 'Consulte a documentação oficial do Delta.',
  description:
    'Faça perguntas sobre as regras e funcionalidades do produto, com trechos e referências da fonte documental.',
  placeholder: 'Pergunte sobre o produto Delta…',
  examples: [
    'Quais etapas compõem o cadastro pessoal e o vínculo do hidrômetro?',
    'Como o cadastro associa um hidrômetro ao local acompanhado?',
    'O que significam consumo acumulado e vazão média?',
    'Como funcionam as metas diárias e mensais de consumo?',
    'Qual é a diferença entre um sinal de consumo anormal e um alerta registrado?',
    'O risco de ultrapassar a meta confirma que uma notificação já foi enviada?',
  ],
  mode: 'agent',
  notes: [
    'A consulta recupera trechos da documentação oficial do produto e pode incluir capítulos e linhas como referências. Se a fonte não trouxer informação suficiente, o agente deve dizer isso em vez de completar com conhecimento geral.',
    'A primeira chamada pode preparar ou atualizar o índice documental. O backend precisa das credenciais Gemini e Qdrant configuradas e de uma coleção Qdrant preexistente com dimensão compatível; não há índice simulado nesta aba.',
    'Este agente explica regras do produto, mas não consulta dados privados da conta, como consumo, metas cadastradas ou alertas ativos.',
    'Etiqueta de teste: teste_agentes_25_10. Usuário fixo desta execução: 123456789.',
  ],
};
