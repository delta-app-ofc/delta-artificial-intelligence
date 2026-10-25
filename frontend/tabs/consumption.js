export default {
  id: 'consumption',
  label: 'Consumo',
  title: 'Consumo registrado',
  description:
    'Consulte totais, compare períodos e encontre os dias de maior consumo nos registros disponíveis.',
  placeholder: 'Pergunte sobre seu consumo registrado, um período ou uma unidade autorizada…',
  examples: [
    'Quanto consumo foi registrado nos últimos 30 dias?',
    'Compare meu consumo registrado nos últimos 7 dias com os 7 dias anteriores.',
    'Em qual dia ocorreu meu maior consumo diário nos últimos 30 dias?',
    'Quais unidades organizacionais estão disponíveis para consulta?',
    'Quanto consumo foi registrado nas unidades organizacionais autorizadas neste mês?',
    'Quanto foi registrado na unidade organizacional que escolhi entre 1º e 15 de outubro de 2026?',
  ],
  mode: 'agent',
  notes: [
    'As consultas usam o usuário de teste 12345679 e a etiqueta de teste teste_agentes_25_10; os resultados dependem dos registros disponíveis nas fontes configuradas.',
    'Na residência, as janelas armazenadas são agrupadas pelo dia local em que começaram. Para organizações, a fonte oferece consolidados diários por unidade autorizada.',
    'A cobertura não é garantida: dias sem registro ficam sem preenchimento e a média considera apenas dias com registros. O dia atual e as bordas do período podem estar parciais.',
    'Picos são diários; a fonte organizacional não fornece picos por hora nem o horário da última atualização.',
    'Este agente descreve consumo registrado. Não calcula tarifas ou contas, não prevê consumo futuro e não diagnostica vazamentos.',
  ],
};
