"""Servidor MCP do Delta AI — expõe as tools de hábitos para Claude Code / Cursor.

Execute com: python app/mcp_server.py
O processo aguarda entrada via stdin (protocolo stdio do MCP).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools import ToolAnnotations

from app.tools.habits.tools import build_tools

mcp = FastMCP("delta-ai")

_PLACEHOLDER_USER_ID = 1

_habits_tools = build_tools(_PLACEHOLDER_USER_ID)
_tools_by_name = {t.name: t for t in _habits_tools}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True),
)
def list_habits(user_id: int) -> dict:
    """Lista todos os hábitos de consumo de água do usuário.

    user_id: identificador do usuário no sistema Delta.
    """
    tools = build_tools(user_id)
    for t in tools:
        if t.name == "list_habits":
            return t.invoke({})
    return {"status": "error", "message": "tool não encontrada"}


@mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=True),
)
def get_habits_by_day(user_id: int, day: str) -> dict:
    """Lista os hábitos de consumo de água para um dia específico da semana.

    user_id: identificador do usuário.
    day: dia da semana em português (ex.: segunda, terça, sábado).
    """
    tools = build_tools(user_id)
    for t in tools:
        if t.name == "get_habits_by_day":
            return t.invoke({"day": day})
    return {"status": "error", "message": "tool não encontrada"}


@mcp.tool()
def create_habit(user_id: int, name: str, frequency: int, days: list[str]) -> dict:
    """Cadastra um novo hábito de consumo de água para o usuário.

    user_id: identificador do usuário.
    name: nome do hábito — um dos seis do catálogo: BANHO LONGO, LAVAR QUINTAL,
      LAVAR ROUPA, REGAR PLANTAS, LAVAR CARRO, LAVAR LOUÇA. Aceita formas
      abreviadas como "banho", "carro", "plantas".
    frequency: vezes por semana (inteiro positivo).
    days: lista de dias em português (ex.: ["segunda", "sexta"]). Pode ser vazia.
    """
    tools = build_tools(user_id)
    for t in tools:
        if t.name == "create_habit":
            return t.invoke({"name": name, "frequency": frequency, "days": days})
    return {"status": "error", "message": "tool não encontrada"}


if __name__ == "__main__":
    mcp.run(transport="stdio")
