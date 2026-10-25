export default {
  id: 'judge',
  label: 'Juiz',
  title: 'Juiz · revisão Jev',
  description:
    'Executa o fluxo completo do chatbot e mostra as decisões do Agente Juiz com Jev antes da resposta final.',
  placeholder: 'Pergunte algo sobre o Delta para testar especialistas e Juiz.',
  examples: [],
  mode: 'judge',
  notes: [
    'Esta aba executa os especialistas, suas ferramentas e o Juiz Jev; configure as credenciais e os bancos necessários.',
    'A decisão e as justificativas são geradas pelo Python a partir dos sinais tipados do Jev.',
    'Sem candidata elegível, o fluxo informa que não houve avaliação. Uma revisão do especialista é limitada a uma tentativa.',
  ],
};
