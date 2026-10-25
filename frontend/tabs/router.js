export default {
  id: 'router',
  label: 'Roteador',
  title: 'Teste a classificação do roteador.',
  description:
    'Envie uma pergunta ao roteador e confira a intenção, a complexidade e os agentes que ele seleciona.',
  placeholder: 'Pergunte sobre consumo, previsão, vazamentos, hábitos ou o produto Delta…',
  examples: [
    'Quanto consumo foi registrado nos últimos 7 dias?',
    'Qual é a previsão de consumo até o fim deste mês?',
    'Há alertas de consumo atípico ainda ativos?',
    'Como meus hábitos podem afetar a previsão da minha próxima conta?',
    'O que significa um alerta de consumo anormal e tenho algum ativo?',
    'Como vai o Brasil?',
  ],
  mode: 'router',
  notes: [
    'Esta aba envia a pergunta a /playground/router. O backend valida a entrada, prepara o contexto disponível e usa o modelo real do roteador para classificar a pergunta.',
    'Os agentes listados como selecionados representam a classificação; nenhum especialista é executado nesta aba. Use Chat completo para acompanhar a execução dos agentes e ferramentas.',
    'A execução usa o usuário fixo 12345679 e a etiqueta teste_agentes_25_10. As respostas dependem das integrações reais configuradas; esta prévia não usa mocks.',
    'O roteador atende perguntas sobre o Delta e monitoramento de água. Perguntas fora desse escopo devem ficar sem agentes; esta aba não oferece aconselhamento financeiro.',
  ],
};
