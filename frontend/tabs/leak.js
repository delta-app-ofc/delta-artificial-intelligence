export default {
  id: 'leak',
  label: 'Vazamento',
  title: 'Sinais de consumo atípico',
  description:
    'Explore janelas anômalas e alertas já registrados, incluindo ocorrências de madrugada, para entender os sinais disponíveis no período consultado.',
  placeholder: 'Pergunte sobre anomalias sinalizadas, alertas ativos ou ocorrências de madrugada…',
  examples: [
    'Quais janelas de consumo foram sinalizadas como anômalas nos últimos 7 dias?',
    'Há alertas de consumo ainda ativos nos últimos 30 dias?',
    'As janelas sinalizadas incluem ocorrências que começaram de madrugada?',
    'Qual foi a duração total e o volume somado das janelas anômalas nos últimos 30 dias?',
    'Como os registros de anomalias mudaram entre os últimos 7 e 30 dias?',
  ],
  mode: 'agent',
  notes: [
    'O agente consulta somente janelas e alertas já sinalizados no MongoDB; não executa detecção nem define limiares.',
    'Um sinal é um indício, não um diagnóstico; a ausência de registros no período consultado não garante ausência de vazamento.',
    'Os sinais são consultados no escopo do usuário, sem filtro por imóvel ou unidade organizacional.',
    'O backend fixa o usuário de teste 123456789 e identifica a execução com a etiqueta teste_agentes_25_10; a disponibilidade de dados não está garantida.',
  ],
};
