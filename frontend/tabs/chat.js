export default {
  id: 'chat', label: 'Chat completo', title: 'Uma conversa, todos os agentes.',
  description: 'Converse com o Delta e acompanhe o caminho de cada resposta, do roteamento às ferramentas.',
  placeholder: 'O que você quer entender sobre o consumo de água?',
  examples: ['Como foi meu consumo de água nos últimos 7 dias?', 'Qual é a previsão de consumo para este mês?', 'Há alertas recentes que eu deva verificar?'],
  mode: 'chat',
  notes: ['O chat completo executa o fluxo disponível no backend. A seleção e a execução dos agentes aparecem no painel ao lado.', 'O usuário de teste é fixo: 123456789. Cada aba mantém seu próprio histórico e sua própria sessão.'],
};
