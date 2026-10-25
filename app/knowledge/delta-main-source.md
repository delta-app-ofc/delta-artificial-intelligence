# DOCUMENTO DE REFERÊNCIA DO PRODUTO DELTA

Versão 1.0 | Consolidação em 23 de outubro de 2026

Este documento reúne definições, características, regras e condições funcionais do Delta nos contextos residencial e organizacional. Constitui uma referência de conhecimento sobre o produto. Sua consolidação descreve o escopo funcional e não certifica o estado de implantação de cada recurso.

## CAPÍTULO 1 — IDENTIDADE, FINALIDADE E ABRANGÊNCIA

### 1.1 Definição do Delta

O Delta é uma plataforma de monitoramento inteligente do consumo de água. Sua finalidade é reunir informações de medição, hábitos, metas, custos estimados e alertas para apoiar o acompanhamento do uso da água e a identificação de possíveis desperdícios.

O escopo funcional compreende cadastro de rotina, limites e metas de consumo, monitoramento em tempo semi-real, conversão do consumo em estimativa financeira, alertas inteligentes, identificação de possíveis vazamentos, previsão da conta de água, informações meteorológicas, chatbot e dashboard gerencial.

### 1.2 Contextos residencial e organizacional

O contexto residencial corresponde ao acompanhamento de uma residência e de sua rotina de uso da água. A experiência mobile concentra consumo, hábitos, metas, alertas, possíveis vazamentos e informações do local monitorado.

O contexto organizacional corresponde ao acompanhamento de instalações vinculadas a uma organização, com aplicação comercial ou industrial. A plataforma web reúne comparação de unidades, monitoramento, metas, dispositivos, ocorrências e cenários de investimento. Uma organização pode possuir mais de uma instalação. Informações de uma unidade e informações consolidadas de uma organização constituem recortes distintos.

### 1.3 Imóvel, instalação, unidade e dispositivo

Imóvel, instalação e unidade são denominações utilizadas para o local cujo consumo é acompanhado. No contexto organizacional, uma unidade representa uma instalação da organização. Cada local possui características cadastrais, como nome, tipo, classificação e endereço.

Dispositivo é o equipamento de medição associado ao imóvel. Sua identificação permite relacionar o equipamento ao local correspondente. O cadastro de um dispositivo, sua associação a uma instalação e seu estado de comunicação são informações diferentes. A seleção de uma unidade delimita o contexto dos indicadores, metas e alertas relacionados a ela.

### 1.4 Assistente conversacional Gluh

Gluh é o assistente conversacional do Delta. Seu domínio de atuação abrange consumo, picos, hábitos, metas, possíveis vazamentos, clima, estimativas de gasto e informações cadastrais relacionadas ao usuário e às unidades acompanhadas.

As consultas podem tratar de explicações gerais ou de informações particulares de uma conta. Explicações sobre indicadores e regras do produto são conhecimento de referência. Valores de consumo, alertas ativos, metas cadastradas e previsões individuais dependem dos registros da conta e do período solicitado. Consulta e explicação de uma funcionalidade não constituem confirmação de execução de cadastro, alteração, exclusão ou controle físico de equipamento.

## CAPÍTULO 2 — CONTA, CADASTRO E VÍNCULO DO EQUIPAMENTO

### 2.1 Acesso à conta

O acesso ao Delta distingue entrada em conta existente e criação de conta. O login utiliza identificação por usuário ou e-mail e senha. O fluxo de acesso inclui estado de carregamento antes da área autenticada.

Facebook, Apple e Google aparecem como alternativas visuais na referência de experiência, sem confirmação de integração. A disponibilidade desses métodos e o procedimento de recuperação de senha não estão formalizados nas informações consolidadas. Senhas e credenciais não integram o conteúdo de consultas do assistente.

### 2.2 Etapas do cadastro pessoal

O cadastro mobile é progressivo, organizado em cinco segmentos de preenchimento, seguidos do vínculo do hidrômetro. O primeiro segmento reúne nome completo, data de nascimento e telefone. O segundo reúne e-mail, senha e confirmação da senha. Os segmentos seguintes tratam de hábitos, características do imóvel e localização.

O fluxo admite retorno às etapas anteriores. A preservação de dados já preenchidos ao retornar ou diante de falha de validação é um critério funcional da experiência. A referência de cadastro não estabelece idade mínima, política detalhada de senha ou procedimento de verificação de identidade.

### 2.3 Rotina, características do imóvel e localização

O cadastro considera os hábitos de uso da água e as características do imóvel para contextualizar o acompanhamento. Na experiência mobile, a classificação distingue exemplos residenciais e comerciais; a identificação do tipo de imóvel apresenta exemplos como casa e apartamento. A localização compreende CEP, estado e cidade, com preenchimento a partir do CEP previsto na experiência.

A classificação cadastral e o tipo físico do imóvel não são conceitos equivalentes. As fontes de referência utilizam vocabulários diferentes para o tipo físico, incluindo casa, apartamento e prédio, sem equivalência formal consolidada entre todas as denominações.

### 2.4 Identificação e vínculo do hidrômetro

O vínculo do hidrômetro associa o equipamento de medição ao local acompanhado. A experiência de conclusão do cadastro contempla leitura de QR Code, inserção manual de código como alternativa e confirmação de leitura verificada.

Não estão formalizados o formato e a expiração do código, a possibilidade de dispensar essa etapa, o tratamento de permissão de câmera negada ou os procedimentos para código inválido e equipamento já vinculado. A presença de um fluxo de vínculo não estabelece que qualquer identificador informado corresponda a um equipamento existente ou autorizado.

### 2.5 Informações pessoais e residenciais

A área de configurações compreende informações pessoais, informações residenciais, unidades, sensores cadastrados e desempenho do usuário. As informações pessoais incluem nome, e-mail e telefone, com áreas específicas relacionadas à atualização de e-mail, telefone e senha.

As informações residenciais e de unidades correspondem ao cadastro do local monitorado. Alterações devem preservar a identificação da unidade afetada e evitar solicitação duplicada de informações já existentes. A referência funcional não detalha confirmação de identidade, recuperação de acesso ou regras completas de confirmação de alterações.

## CAPÍTULO 3 — MEDIÇÃO, CONSUMO E HISTÓRICO

### 3.1 Periodicidade e indicadores de medição

O monitoramento do Delta é definido como tempo semi-real, com intervalos configuráveis de 5, 10 ou 15 minutos. Esse conceito corresponde ao acompanhamento por intervalos de atualização e não implica disponibilização instantânea de cada evento de consumo.

Consumo acumulado representa o volume utilizado no período de referência. Vazão média representa o ritmo médio de passagem da água, apresentado em litros por minuto. A atualização e o significado dos indicadores dependem do intervalo, das leituras recebidas e do estado de comunicação do dispositivo.

### 3.2 Síntese de consumo no aplicativo

O dashboard mobile concentra a síntese da unidade selecionada. Os indicadores incluem consumo em litros, comparação com período anterior, custo previsto, percentual da meta mensal, evolução histórica e alertas recentes. A tela também reúne acesso a notificações, configurações e detalhamento de possível vazamento.

Volume observado, custo previsto e desperdício estimado são informações de naturezas diferentes. Valores financeiros e impactos de possíveis vazamentos devem conservar sua identificação como estimativas, com unidade e período associados.

### 3.3 Histórico e comparabilidade

O acompanhamento de consumo abrange recortes diário, semanal e mensal, evolução temporal e picos. Comparações devem identificar o local, o período analisado e a base de referência, como dia anterior, mês anterior ou média de semanas anteriores.

Aumento de consumo e causa do aumento são conclusões distintas. O registro de maior volume não determina sozinho sua origem. A granularidade dos dados limita a análise: uma série diária não comprova a hora de um pico. A ausência de histórico suficiente impede conclusões que dependam desse histórico.

### 3.4 Ausência de dados e leituras desatualizadas

Ausência de dados, falha de consulta e consumo observado igual a zero são estados distintos. Uma instalação sem histórico deve apresentar ausência de informação, sem substituição por valores fictícios.

Dispositivo offline ou sem leituras recentes pode resultar em indicadores que não representam o momento atual. Falta de atualização não equivale a consumo zero e não comprova ausência de vazamento. Leituras, períodos e disponibilidade da informação delimitam as conclusões que podem ser extraídas do acompanhamento.

## CAPÍTULO 4 — HÁBITOS E ROTINA HÍDRICA

### 4.1 Cadastro de hábitos

O cadastro de rotina caracteriza atividades que utilizam água para contextualizar as análises de consumo. O requisito funcional menciona usos como banho, cozinha, lavagem de roupa, rega de plantas e piscina.

O catálogo de hábitos descrito no domínio contém banho longo, lavar quintal, lavar roupa, regar plantas, lavar carro e lavar louça. Os hábitos podem estar associados a frequência e dias da semana. A existência de uma atividade no catálogo não significa que ela faça parte da rotina de todos os usuários, e os exemplos do requisito não constituem uma lista final de opções de interface.

### 4.2 Agenda e estimativa por atividade

A rotina hídrica organiza atividades por dia e horário e relaciona seu planejamento a uma meta diária. Um hábito pode conter nome, categoria, horário inicial e final, duração média, recorrência, consumo estimado em litros e participação estimada na meta da residência.

A experiência contempla agenda vazia, inclusão de hábito, agenda preenchida, detalhamento, edição e exclusão. O consumo atribuído ao hábito é uma estimativa de planejamento. Sua presença na agenda não comprova medição individual daquela atividade pelo hidrômetro.

### 4.3 Sobreposição e conflito de consumo

O conflito de rotina corresponde à sobreposição de atividades cuja vazão combinada pode ultrapassar a referência considerada segura para a residência. O aviso relaciona a coincidência dos horários à demanda simultânea de água.

A experiência contempla ajuste automático para redistribuição de horários e opção de ignorar para manutenção da programação. Não foram consolidados um limite universal de vazão segura, o algoritmo de redistribuição ou todas as consequências operacionais dessas ações. O significado do conflito não estabelece, por si só, um diagnóstico de vazamento.

## CAPÍTULO 5 — METAS, ESTIMATIVA FINANCEIRA E PREVISÃO

### 5.1 Unidades e períodos de meta

As metas de consumo são referências de controle definidas em litros, metros cúbicos ou reais. A experiência do Delta contém acompanhamento diário e mensal. Toda meta deve identificar a instalação, o período e a unidade de medida a que se aplica.

O progresso da meta depende da comparação entre limite e consumo do mesmo contexto. Metas de períodos ou medidas diferentes não são diretamente equivalentes. Não há um valor padrão universal de meta estabelecido para todas as residências ou instalações.

### 5.2 Estimativa monetária e referência tarifária

A conversão de consumo em valor monetário tem caráter estimativo e não substitui a fatura emitida pela concessionária. As referências funcionais incluem o valor do metro cúbico do mês anterior, a última conta conhecida no primeiro uso e a tarifa correspondente à região, categoria do imóvel e período de vigência.

Essas referências não consolidam uma única fórmula aplicável a todos os casos. A base adotada em uma estimativa precisa estar identificada. Não existe uma tarifa única para todas as instalações, e valores ilustrativos de telas não constituem referência de cobrança de uma conta real.

### 5.3 Projeção de consumo e da próxima conta

A previsão utiliza informações de consumo e histórico para estimar volume futuro, valor da próxima conta, tendência e risco de ultrapassagem de meta. A projeção ao final do mês depende do ritmo e dos dados considerados na análise.

Previsões não constituem certeza de consumo ou garantia de cobrança. Devem conservar a identificação da unidade, do período projetado e da base utilizada. A referência de produto não define precisão garantida nem quantidade mínima universal de dias de histórico para toda previsão.

### 5.4 Condições da estimativa residencial

No contexto residencial, as condições cadastrais relacionadas à geração de estimativas incluem existência de usuário ativo, imóvel vinculado, dispositivo ativo e tarifa válida para a região e categoria do imóvel.

O atendimento dessas condições não demonstra, sozinho, a existência de histórico suficiente para qualquer análise. Disponibilidade de cadastro, telemetria e contexto de previsão são requisitos distintos. As condições residenciais não devem ser generalizadas como regra única de elegibilidade de organizações, que possuem outro contexto de unidades e vínculos.

## CAPÍTULO 6 — ALERTAS, ANOMALIAS E POSSÍVEIS VAZAMENTOS

### 6.1 Finalidade e tipos de alerta

Os avisos do Delta ajudam a distinguir situações que merecem atenção: passagem contínua de água, consumo de madrugada, mudança fora do padrão habitual e risco de ultrapassar uma meta. Os três primeiros são sinais usados na análise de consumo; o risco de meta é uma comparação feita na previsão.

Um período marcado como anormal não é necessariamente um alerta separado no histórico. No processamento conferido, o registro específico de alerta é o de possível vazamento por fluxo contínuo. Madrugada e mudança de padrão também podem sinalizar uma leitura, sem criar, por si sós, outro tipo de alerta gravado. Avisos de tarifa, conta disponível e outros tipos apresentados na experiência não têm todas as suas regras de envio confirmadas.

### 6.2 Severidade e situação da ocorrência

A central de alertas apresenta as categorias Crítico, Atenção e Informativo. A classificação indica a atenção atribuída ao aviso; não corresponde automaticamente a uma porcentagem de certeza de vazamento. No registro de fluxo contínuo conferido, a gravidade é intermediária e não aumenta automaticamente pelo número de sinais encontrados.

Ocorrência nova, reconhecida, em investigação e resolvida são situações distintas da severidade. Ocultar um aviso, silenciar notificações e resolver sua causa também são ações diferentes. A ausência de um cartão na tela não comprova reparo, e o efeito completo das ações de fechamento não está consolidado.

### 6.3 Indício de vazamento e diagnóstico definitivo

Fluxo contínuo, consumo em períodos incomuns e desvio do padrão histórico são sinais considerados na identificação de possíveis vazamentos. Um sinal estatístico ou alerta de consumo não confirma, isoladamente, a causa física de uma ocorrência.

A análise precisa considerar o contexto residencial ou comercial. A regra de madrugada descrita para o grupo residencial não é automaticamente aplicável ao grupo comercial. O assistente de conversa consulta e descreve sinais e alertas; ele não define novos limiares de detecção. A produção desses sinais é uma responsabilidade distinta da conversa com o usuário.

### 6.4 Informações do diagnóstico

O diagnóstico pode reunir período, volume medido, vazão, duração e comparação com o histórico. A experiência também prevê mapas e estimativas de impacto, mas a presença de um sinal não fornece automaticamente a causa física, o valor perdido ou uma porcentagem de certeza.

A causa pode permanecer desconhecida mesmo com comportamento incomum. A confiança de uma análise não confirma uma tubulação defeituosa. O resumo de consumo anormal soma os volumes e as durações dos períodos sinalizados; esse total não distingue, sozinho, água utilizada normalmente de água desperdiçada. Inspeção do registro e das tubulações são verificações citadas, sem controle físico automático estabelecido por essa funcionalidade.

### 6.5 Ocorrências por instalação

O acompanhamento por instalação distingue alertas ativos, ocorrências em investigação e histórico de resoluções. O registro de fluxo contínuo contém equipamento, usuário, horário de abertura, gravidade e indicação de resolução ainda não preenchida na abertura.

Uma sequência persistente pode produzir novos registros enquanto as leituras continuam atendendo à regra. Portanto, a quantidade de registros não equivale necessariamente à quantidade de vazamentos físicos independentes. O horário de abertura do alerta também não prova quando um defeito começou. A resolução não é confirmada automaticamente pela ausência de novos avisos ou por uma leitura sem sinal.

### 6.6 Da leitura de consumo ao sinal e ao alerta

A análise começa a cada novo período de consumo recebido. São feitas três verificações: se a passagem de água persiste sem interrupção entre os registros, se há consumo na faixa de madrugada e se o volume se afasta do habitual para aquele usuário naquela hora. Basta uma verificação apontar uma ocorrência para o período ser marcado como anormal; mais de um motivo pode existir ao mesmo tempo.

A marcação do período e o aviso guardado no histórico são informações distintas. O alerta específico de fluxo contínuo é registrado quando essa condição ocorre. O assistente explica dados e regras existentes; a conversa não cria um novo limite nem comprova, sozinha, a geração ou o envio de uma notificação ao celular.

### 6.7 Cálculo do sinal de fluxo contínuo

O sinal de fluxo contínuo procura pelo menos seis períodos seguidos do mesmo equipamento, cada um com mais de 0,2 litro registrado. Esse pequeno valor evita tratar variações muito baixas como passagem relevante de água. Um período com 0,2 litro ou menos interrompe a contagem. Uma lacuna entre os horários dos registros também interrompe a sequência: falta de informação não comprova continuidade.

Com leituras de cinco minutos, seis períodos completos correspondem a 30 minutos. Por exemplo, seis registros consecutivos de 1,5 litro representam 9 litros medidos nesses 30 minutos. Os números do exemplo são ilustrativos; os 9 litros não são automaticamente uma perda por vazamento. A regra conta períodos: com outra duração de leitura, não se deve afirmar que o limite continua sendo exatamente 30 minutos.

### 6.8 Cálculo do sinal de consumo de madrugada

O sinal de madrugada verifica se o período começou entre zero hora e antes das seis horas e registrou mais de 1 litro. Uma leitura exatamente igual a 1 litro não ultrapassa esse limite. Essa verificação não exige seis períodos seguidos: uma única leitura que atenda às condições pode receber o sinal.

A condição é desativada quando o perfil comercial está identificado, pois uma operação noturna pode fazer parte da rotina. Na falta dessa identificação, a regra atual não bloqueia automaticamente o sinal; isso não comprova que o uso seja residencial ou indevido. A faixa considera o horário do registro, que não pode ser chamado de horário local sem confirmar o fuso. O sinal isolado não confirma vazamento nem cria necessariamente um alerta separado no histórico.

### 6.9 Comparação com o consumo habitual da mesma hora

O sinal de mudança de padrão compara o volume do período atual com o histórico do mesmo usuário naquela hora do dia. Assim, uma leitura das três horas é comparada à referência das três horas, em vez de ser comparada indistintamente com horários de banho, almoço ou trabalho.

A conta considera quanto o volume se afastou do valor habitual e quanto esse consumo costuma variar. Uma diferença chama mais atenção quando os valores anteriores eram estáveis; pode ser menos excepcional quando a rotina já tem grande variação. A mudança pode ser para mais ou para menos. Como exemplo apenas explicativo, passar de uma referência de 2 litros para uma leitura de 8 litros representa 6 litros acima da referência; essa diferença, sozinha, não define se haverá sinal.

A referência atual é organizada por usuário e hora, sem garantia de separação por cada imóvel ou equipamento desse usuário.

### 6.10 Margem de tolerância e histórico disponível

A margem da comparação com o histórico é ajustada a partir de períodos considerados normais, procurando separar oscilações comuns de mudanças raras. Por isso, o sinal não segue um limite universal como “qualquer aumento de 20%” ou “mais de 10 litros”. A tolerância depende da referência e do ajuste usados na análise.

Histórico escasso ou sem variação torna essa comparação limitada. Com menos de três leituras de referência naquela hora, a medida de oscilação ainda fica zerada; três leituras também não garantem que toda a rotina esteja bem representada. Não há exigência de completar exatamente 30 dias para iniciar o histórico, nem garantia de acerto derivada da calibração. Os sinais de fluxo contínuo e madrugada utilizam condições próprias e não dependem dessa comparação histórica.

### 6.11 Atualização gradual do padrão habitual

O padrão é atualizado aos poucos para acompanhar a rotina. A primeira leitura inicia a referência. Nas seguintes, o valor médio mantém aproximadamente 99,45% da referência anterior e incorpora cerca de 0,55% da nova leitura. Isso faz uma mudança isolada ter pouco peso sobre o que é considerado habitual.

Como exemplo ilustrativo, uma referência de 10 litros seguida de uma leitura de 20 litros passa para aproximadamente 10,06 litros, em vez de saltar imediatamente para 20. A comparação da leitura ocorre antes dessa atualização, para que o próprio aumento não redefina seu padrão antes de ser avaliado. O tamanho das oscilações habituais também é acompanhado. Trata-se de adaptação gradual, sem promessa de que um período fixo de dias seja suficiente para caracterizar qualquer residência.

### 6.12 Soma da duração e do volume dos períodos sinalizados

O volume do resumo é obtido somando os litros registrados nos períodos marcados como anormais. A duração total é obtida somando o tempo de cada um desses períodos. Não é simplesmente o tempo decorrido entre o primeiro e o último registro.

Em um exemplo ilustrativo, três períodos de cinco minutos com 2, 3 e 1 litro somam 15 minutos de registros sinalizados e 6 litros medidos. Se houver intervalos sem sinal entre eles, os 15 minutos não representam fluxo ininterrupto. Mesmo sem intervalos, volume medido não equivale automaticamente a volume desperdiçado: o resumo não separa o uso legítimo de água de uma eventual perda.

### 6.13 Limites da estimativa de perda, custo e certeza

O alerta de fluxo contínuo não informa, por si só, quanto da água passou por um vazamento. Seus dados identificam a ocorrência, o equipamento e o momento do registro. O resumo dos períodos anormais acrescenta litros e duração, sem calcular automaticamente qual parcela corresponde a desperdício.

Também não há nesse cálculo um prejuízo em reais ou uma porcentagem de certeza de defeito. Impactos financeiros e confiança presentes em telas não podem ser deduzidos apenas da gravidade intermediária de um aviso. Qualquer estimativa adicional precisa de base própria, período e identificação do que foi realmente calculado. A ausência de alerta não comprova inexistência de vazamento, especialmente diante de falha de leitura ou histórico insuficiente.

### 6.14 Cálculo do risco de ultrapassar a meta

A análise de risco de meta compara a previsão de consumo ao final do mês com o limite do mesmo mês. No cálculo disponível, a meta mensal em litros é a meta diária multiplicada pelo número de dias do mês. Uma meta de 300 litros por dia, em um mês de 30 dias, corresponde a 9.000 litros. Se a projeção for de 9.600 litros, a diferença será de 600 litros, ou aproximadamente 6,67% acima da meta. Esses valores são um exemplo, não dados de uma conta.

A projeção soma o consumo já registrado no mês à média diária recente multiplicada pelos dias restantes. Essa média considera a faixa entre o primeiro e o último dia com leitura dentro dos últimos 14 dias; lacunas podem limitar a representação da rotina. O risco é indicado quando a projeção supera a meta, não quando apenas a iguala. Sem meta cadastrada, essa avaliação não é realizada. O resultado é uma previsão de risco e não comprova que um alerta automático já tenha sido gravado ou enviado.

### 6.15 Outros avisos e identificação do motivo de uma ocorrência

A experiência do Delta também apresenta limite ultrapassado, consumo acima do esperado, mudança anormal de padrão, tarifa atualizada e previsão da conta disponível. Esses rótulos não comprovam que todos tenham um processo automático de geração e envio. Não há base para atribuir um mesmo cálculo ou um limite inventado a todos eles.

A explicação de uma ocorrência particular depende do motivo e dos dados efetivamente disponíveis. Uma marcação genérica de período anormal não identifica, sozinha, qual das três verificações foi responsável. O tipo fluxo contínuo permite explicar sua regra, mas não prova que também houve sinal de madrugada ou mudança de padrão. Múltiplos registros não devem ser convertidos automaticamente em múltiplos defeitos ou em maior certeza de vazamento.

## CAPÍTULO 7 — INFORMAÇÕES METEOROLÓGICAS

### 7.1 Clima e contexto do uso da água

Temperatura, probabilidade de chuva e condições meteorológicas da região compõem o contexto de planejamento da rotina, especialmente para atividades externas que utilizam água. A experiência contempla clima atual, probabilidade de chuva e associação entre previsão e instalação.

Condições do tempo são informações temporais e localizadas. Conhecimento geral sobre o clima não substitui a previsão atual da região. A relação entre uma condição meteorológica e uma mudança de consumo requer evidência; temperatura elevada ou chuva prevista não determinam, por si só, a causa de um comportamento de consumo.

## CAPÍTULO 8 — CONVERSAS, PRIVACIDADE E PREFERÊNCIAS

### 8.1 Sessões, histórico e avaliação de atendimento

A experiência conversacional contempla perguntas sugeridas, mensagens, histórico, nova conversa e avaliação por feedback. O histórico reúne interações anteriores, enquanto a sessão mantém o contexto do atendimento corrente.

A proposta de memória entre conversas não significa disponibilidade irrestrita de todo o histórico em qualquer nova interação. Não foram consolidados prazo de retenção, procedimento de exclusão e mensagens de falha do histórico na experiência do produto. O feedback registra avaliação da ajuda recebida, sem equivalência com uma alteração cadastral ou execução de ação na conta.

### 8.2 Privacidade e delimitação de acesso

As consultas de dados pessoais e de consumo devem respeitar a identidade, a sessão e o contexto autorizado do usuário. Informações de terceiros não devem ser expostas em uma consulta sem vínculo de acesso. Senhas e credenciais não constituem dados de resposta do assistente.

No contexto organizacional, a identificação textual de uma instalação não concede acesso aos seus dados. A instalação ou conjunto de unidades efetivamente consultado delimita a informação apresentada. Exemplos cadastrais e dados de demonstração não substituem registros particulares de uma pessoa ou organização.

### 8.3 Preferências de acompanhamento

As preferências de aplicativo consideram notificações, metas e aparência. O domínio inclui ativação de notificações, intervalo de silêncio e tema escuro. A presença dessas preferências no domínio não define todos os controles disponíveis em uma versão da interface.

Não há meta ou intervalo de silêncio universal estabelecido para todos os usuários. Preferências de apresentação não alteram o consumo observado. Silenciamento de notificação e resolução de ocorrência são conceitos distintos. O estado atual de uma preferência depende da configuração da conta correspondente.

## CAPÍTULO 9 — GESTÃO DE INSTALAÇÕES E DISPOSITIVOS

### 9.1 Áreas da plataforma organizacional

A organização funcional da plataforma web compreende Dashboard, Instalações, Monitoramento, Alertas, Vazamentos, Ranking, Metas, Investimentos, Dispositivos, Gluh e Configurações.

Essas áreas distinguem visão consolidada, acompanhamento por local, gestão de equipamentos e análises especializadas. O conteúdo mantém o contexto da organização e da instalação selecionadas. As denominações residente, gestor e indústria não estabelecem, por si só, uma matriz completa de permissões ou hierarquia de acesso.

### 9.2 Visão gerencial consolidada

O dashboard gerencial apresenta uma visão mensal com consumo, custo estimado, percentual da meta geral, evolução histórica dos últimos seis meses, ranking resumido, alertas ativos, previsão financeira e clima.

A consolidação corresponde ao período e ao conjunto de instalações considerados. Indicadores observados e estimativas podem coexistir no mesmo painel, preservando a distinção entre suas naturezas. A visão geral não elimina o recorte por unidade necessário à investigação de um comportamento específico.

### 9.3 Identificação e comparação de instalações

A relação de instalações considera busca por nome ou região, comparação de consumo, comparação por área, mapa e lista de unidades. A síntese por local reúne consumo mensal, progresso de meta e estado.

Os estados apresentados na experiência são Normal, Atenção e Crítico. O fluxo de instalações não estabelece um limiar numérico universal para todos eles. Consumo absoluto, consumo por área e severidade de um alerta são medidas diferentes, cuja interpretação depende do contexto de cada instalação.

### 9.4 Dados cadastrais da instalação

O cadastro de instalação reúne nome, tipo de imóvel, CEP, cidade e estado. A referência de consumo contempla volume mensal em metros cúbicos e meta mensal. A associação de equipamento utiliza a identificação do hidrômetro ou dispositivo.

O consumo pode permanecer sem preenchimento quando não existe histórico de leituras. Ausência de histórico não requer criação de um valor fictício. A edição deve preservar a identificação do local, os dados existentes e o preenchimento diante de erro de validação. Os campos inválidos devem ser identificados sem perda indevida das informações já fornecidas.

### 9.5 Perfil operacional comercial e industrial

O contexto organizacional compreende identificação da organização, segmento de atividade e unidades associadas. O domínio considera varejo, indústria, condomínio e facilities. A organização pode reunir uma ou mais instalações.

O perfil operacional de uma instalação pode conter fonte principal de água, turnos, dias de funcionamento e tipos de uso. As fontes descritas são concessionária, poço artesiano, cisterna e reúso. As finalidades incluem limpeza, consumo humano, processo produtivo e irrigação. Essas informações contextualizam a operação, sem constituir medição individual de cada finalidade de consumo.

### 9.6 Indicadores e dimensões do detalhe da instalação

O detalhamento de uma instalação reúne consumo atual, vazão média, custo previsto, progresso da meta, evolução histórica, limite diário e volume restante na meta. As dimensões de análise são Consumo, Vazão, Alertas e vazamentos, Previsão e clima e Histórico.

Todos esses indicadores conservam o contexto da instalação selecionada. O volume restante depende da meta cadastrada e do consumo do período correspondente. Valores apresentados em diferentes locais ou recortes temporais não são diretamente comparáveis sem identificação dessas diferenças.

### 9.7 Monitoramento agregado e situação das instalações

O monitoramento organizacional reúne consumo do dia, vazão média, quantidade de leituras recentes, instalações online, evolução temporal agregada e situação por instalação. O intervalo de acompanhamento considera 5, 10 ou 15 minutos.

Consumo diário, consumo mensal e vazão atual são indicadores distintos. Um agregado organizacional depende das instalações e leituras incluídas. O estado de conectividade e a atualização dos registros delimitam a interpretação de indicadores apresentados como recentes ou atuais.

### 9.8 Acompanhamento de metas por unidade

A área de metas organizacionais reúne limite, consumo, progresso e estado por unidade. A visão geral também contempla cumprimento médio, quantidade de unidades dentro da meta, unidades críticas e potencial anual estimado de economia.

As metas conservam unidade de medida e período próprios. A comparação de limite mensal em metros cúbicos com leitura diária em litros exige compatibilização do recorte, sem equivalência direta entre os valores. As fórmulas completas de cumprimento médio, criticidade e potencial anual de economia não estão estabelecidas pela referência de interface.

### 9.9 Vínculo, conectividade e informação de bateria

O vínculo de dispositivo identifica o equipamento associado à instalação. A condição online corresponde ao estado de comunicação, não à existência do vínculo cadastral. Um dispositivo pode estar associado a uma unidade sem apresentar leitura recente.

A experiência de gestão reúne identificação, instalação, conectividade, dispositivos pareados, equipamentos online, referência de bateria e unidades sem dispositivo. A apresentação de bateria não comprova disponibilidade dessa informação para todo modelo de equipamento. Falta de leitura ou comunicação recente não constitui medição de consumo igual a zero.

### 9.10 Seleção de unidade e conjunto de análise

Consultas organizacionais podem tratar de uma instalação específica ou de um conjunto de unidades. A identificação do local e do período delimita a análise de consumo, meta, custo ou alerta. O total de uma organização e o resultado de uma única unidade são recortes diferentes.

Nomes semelhantes podem corresponder a mais de uma instalação. Correspondência ambígua não estabelece uma seleção válida de unidade. A identificação pelo nome também não substitui vínculo de acesso. Resultados agregados devem conservar a indicação do conjunto efetivamente considerado.

## CAPÍTULO 10 — RANKING E EFICIÊNCIA HÍDRICA

### 10.1 Critérios de comparação

O Delta reúne referências de ranking por consumo, economia, evolução e eficiência. Esses critérios não são equivalentes. Consumo total expressa volume utilizado; eficiência por área relaciona consumo ao tamanho da instalação; economia e evolução dependem de uma base de comparação.

As opções de ranking das experiências mobile e web não estão totalmente harmonizadas. A regra específica de eficiência comercial por área e por dia não deve ser generalizada para rankings residenciais, de economia ou de evolução. A posição depende do critério, do período e das unidades participantes.

### 10.2 Eficiência organizacional em litros por área e por dia

O ranking de eficiência organizacional utiliza litros por metro quadrado por dia. A média diária corresponde à soma do consumo dos dias fechados com leitura dividida pela quantidade desses dias. A pontuação de eficiência é essa média dividida pela área construída da unidade. Menor pontuação representa melhor posição nesse critério.

A comparação é segmentada por organização e mês e se aplica ao contexto comercial. O dia corrente não compõe o cálculo até seu fechamento, para evitar vantagem artificial de um dia parcial. O consumo total mensal constitui critério secundário informativo.

### 10.3 Elegibilidade, cobertura e desempate no ranking

A participação no ranking organizacional exige leituras em pelo menos 50% dos dias fechados do mês. O dia corrente pode ter consumo registrado, mas permanece fora do cálculo até fechar.

Unidade sem área construída não participa da eficiência por área; pode participar da comparação por consumo total quando cumprir a cobertura. Área menor ou igual a zero é inválida. Em empate de pontuação, o desempate segue o identificador numérico da unidade em ordem crescente. Esses critérios pertencem ao ranking comercial específico e não definem automaticamente todos os rankings do produto.

## CAPÍTULO 11 — CENÁRIOS DE ECONOMIA E INVESTIMENTO

### 11.1 Natureza dos cenários de referência

A comparação de investimentos considera torneiras ou registros economizadores, reúso de água cinza, captação de chuva e situação sem investimento adicional. As medidas de comparação incluem investimento, redução estimada de consumo, economia anual estimada e prazo de retorno.

Os três cenários numéricos consolidados são referências ilustrativas de porte comercial ou industrial, reunidas em 27 de setembro de 2026. Não constituem cotações auditadas, propostas de fornecedor, orçamento de uma instalação real ou garantia de retorno. Não possuem atualização automática. Valores de demonstração das telas não substituem essas referências nem comprovam desempenho real.

### 11.2 Aeradores e registros economizadores

O cenário de referência de aeradores e registros economizadores estabelece investimento ilustrativo de R$ 15.000,00, redução estimada de 12% no consumo total, economia anual estimada de R$ 22.500,00 e prazo de retorno de 8 meses.

Os percentuais do cenário se referem ao consumo total de uma unidade comercial, e não à redução isolada em uma torneira. Economia anunciada para um ponto de uso não se estende automaticamente ao consumo de todo o prédio. Os valores pertencem à pesquisa de 27 de setembro de 2026, sem equivalência com cotação atual, orçamento individual ou resultado medido no Delta.

### 11.3 Reúso de água cinza

O cenário de referência de reúso de água cinza estabelece investimento ilustrativo de R$ 90.000,00, redução estimada de 22%, economia anual estimada de R$ 11.250,00 e prazo de retorno de 96 meses.

O prazo representa uma hipótese conservadora ou pessimista do cenário, não uma média universal de mercado. Porte, perfil de uso e custos alteram o resultado de uma instalação. A referência é comercial ou industrial e não se transfere automaticamente ao contexto residencial. Os valores foram reunidos em 27 de setembro de 2026 e não constituem promessa de economia ou retorno.

### 11.4 Captação de água de chuva

O cenário de referência de captação de chuva estabelece investimento ilustrativo de R$ 70.000,00, redução estimada de 18%, economia anual estimada de R$ 14.000,00 e prazo de retorno de 60 meses.

O investimento foi extrapolado de sistemas residenciais e pequenos comerciais, sem referência direta de cotação para instalação industrial de grande porte. Essa limitação integra o significado dos valores. O cenário, reunido em 27 de setembro de 2026, não corresponde a orçamento de uma unidade específica, redução garantida ou retorno confirmado.

## CAPÍTULO 12 — EXPORTAÇÃO DE INFORMAÇÕES

### 12.1 Abrangência da referência de exportação

A exportação em PDF aparece como funcionalidade prevista na experiência web de instalações, monitoramento, metas e ranking. Sua finalidade é permitir registro ou compartilhamento de informações do acompanhamento.

A referência visual de exportação não comprova disponibilidade em todas as versões do produto. Não estão consolidados formato final, conteúdo completo ou permissões do relatório. Uma solicitação em conversa não equivale à geração de arquivo; a existência de um documento exportado depende da conclusão efetiva da operação correspondente.
