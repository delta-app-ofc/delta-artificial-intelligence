export default {
  id: 'forecast',
  label: 'Previsão',
  title: 'Previsão de consumo e conta',
  description:
    'Consulte projeções de consumo até o fim do mês, estimativas da próxima conta, tendência e risco em relação à meta diária.',
  placeholder: 'Pergunte sobre sua projeção, próxima conta, meta ou histórico de consumo…',
  examples: [
    'Com base no meu histórico, qual é a projeção de consumo até o fim deste mês?',
    'Qual é a estimativa para minha próxima conta de água e em quais dados ela se baseia?',
    'Tenho dados suficientes para receber uma estimativa de consumo?',
    'A projeção indica risco de ultrapassar minha meta diária neste mês?',
    'Como foi meu histórico de consumo nos últimos 45 dias e qual tendência ele mostra?',
  ],
  mode: 'agent',
  notes: [
    'Esta prévia usa os dados reais do usuário fixo 123456789; as respostas dependem do cadastro e dos dados disponíveis para ele.',
    'Projeções e valores de conta são estimativas calculadas pelo backend; dados insuficientes podem limitar ou impedir o cálculo.',
    'O risco em relação à meta só pode ser avaliado se houver uma meta diária cadastrada. Identifique a validação manual com o rótulo teste_agentes_25_10.',
  ],
};
