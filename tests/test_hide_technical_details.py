"""Garante que o usuário não recebe agentes, ferramentas nem erros técnicos."""

from app.guardrails.output import TECHNICAL_FALLBACK, hide_technical_details, validate_output
from app.schemas import ChatResponse


def test_chat_response_does_not_expose_agents():
    assert "agents_used" not in ChatResponse.model_fields


def test_technical_sentences_are_removed_and_the_rest_is_kept():
    text = (
        "Seu consumo ontem foi de 320 litros. "
        "O agente de hábitos retornou status: rate_unavailable. "
        "A ferramenta estimate_habit_water_cost falhou."
    )
    assert hide_technical_details(text) == "Seu consumo ontem foi de 320 litros."


def test_api_and_database_failures_are_hidden():
    for text in [
        "A API retornou erro 500 ao consultar.",
        "Houve uma falha no banco de dados PostgreSQL.",
        "Traceback (most recent call last): timeout na conexão.",
        "O serviço de linguagem está indisponível.",
        "O especialista de previsão não respondeu.",
    ]:
        assert hide_technical_details(text) == TECHNICAL_FALLBACK, text


def test_normal_answers_are_untouched():
    text = "Lavar roupa 3 vezes por semana custa cerca de R$ 12,99 por mês.\n\nÉ uma estimativa."
    assert hide_technical_details(text) == text
    assert hide_technical_details("Seu hidrômetro está ativo.") == "Seu hidrômetro está ativo."


def test_validate_output_keeps_diagnostic_fields_intact():
    # O console de testes passa o rastro técnico por validate_output; ele não pode ser filtrado.
    assert validate_output("agent_results") == {"ok": True, "response": "agent_results"}


def test_habit_names_are_capitalized():
    from app.guardrails.output import capitalize_habit_names

    text = "Hábito **REGAR PLANTAS** cadastrado. Também LAVAR LOUÇA e BANHO LONGO; lavar roupa fica."
    assert capitalize_habit_names(text) == (
        "Hábito **Regar Plantas** cadastrado. Também Lavar Louça e Banho Longo; lavar roupa fica."
    )
    assert capitalize_habit_names("PLANTAS e LAVAR CARROS") == "PLANTAS e LAVAR CARROS"
