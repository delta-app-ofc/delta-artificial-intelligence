export default {
  id: 'habits',
  label: 'Hábitos',
  title: 'Hábitos e rotina',
  description:
    'Consulte os hábitos cadastrados, os dias da semana associados e estimativas de impacto hídrico por frequência.',
  placeholder: 'Pergunte sobre seus hábitos cadastrados, dias da semana ou estimativas de água…',
  examples: [
    'Quais hábitos estão cadastrados para mim, com frequência e dias da semana?',
    'Quais hábitos estão cadastrados para terça-feira?',
    'Qual é a estimativa de água por semana para lavar roupa duas vezes por semana?',
    'Quanto representa por mês regar plantas três vezes por semana, como estimativa?',
    'Que dados recentes de chuva e temperatura existem para minha localização?',
    'O histórico recente de chuva pode ajudar a analisar minha rotina de regar plantas?',
  ],
  mode: 'agent',
  notes: [
    'Esta prévia consulta o usuário fixo 12345679 e usa o rótulo de teste teste_agentes_25_10; os resultados dependem dos dados disponíveis para essa conta.',
    'A consulta de hábitos está disponível para contas residenciais. A frequência e os dias cadastrados descrevem a rotina informada, não comprovam quando a atividade ocorreu.',
    'As estimativas usam médias de referência para os hábitos do catálogo. Não são medições do hidrômetro nem consumo observado da conta.',
    'O catálogo inclui banho longo, lavar quintal, lavar roupa, regar plantas, lavar carro e lavar louça.',
    'O histórico meteorológico contém registros recentes da localização, não previsão do tempo; a disponibilidade depende dos dados existentes.',
  ],
};
