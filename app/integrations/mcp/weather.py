"""Cliente MCP do Tomorrow.io — só Python.

O Delta é CLIENTE de um servidor que a Tomorrow.io hospeda:
https://api.tomorrow.io/v4/tomorrow-weather/mcp (streamable HTTP).

Autenticação: header X-Api-Key com TOMORROW_API_KEY do .env (free tier disponível).
Padrão idêntico ao cliente do Google Calendar — só troca Bearer por X-Api-Key.
"""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import tool

from app.config import TOMORROW_API_KEY, TOMORROW_MCP_URL


def _parse_result(result: Any) -> dict:
    if getattr(result, "structured_content", None):
        data = result.structured_content
        return data if isinstance(data, dict) else {"status": "ok", "result": data}
    texts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    if not texts:
        return {"status": "error", "message": "O servidor MCP não devolveu conteúdo."}
    raw = texts[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "ok", "result": raw}


def _motivo(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return " | ".join(_motivo(sub) for sub in exc.exceptions)
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


async def _chamar_weather_mcp(tool_name: str, args: dict) -> dict:
    if not TOMORROW_API_KEY:
        return {
            "status": "error",
            "message": "TOMORROW_API_KEY ausente no .env. Consulte https://app.tomorrow.io para obter uma chave gratuita.",
        }

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    client = create_mcp_http_client()
    client.headers["X-Api-Key"] = TOMORROW_API_KEY

    async with client:
        async with streamable_http_client(TOMORROW_MCP_URL, http_client=client) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                if getattr(result, "is_error", False):
                    return {"status": "error", "message": _parse_result(result)}
                return _parse_result(result)


def _run(coro_fn) -> dict:
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_fn())).result()


@tool
def get_realtime_weather(location: str) -> dict:
    """Retorna condições climáticas atuais (temperatura, chuva, umidade etc.)
    para uma localização informada, via Tomorrow.io MCP.

    Use quando o usuário perguntar sobre o tempo atual e isso for relevante para
    o consumo de água (ex.: calor intenso, chuva que dispensa irrigação).

    location: nome da cidade ou endereço (ex.: 'São Paulo, Brasil').
    """
    try:
        return _run(lambda: _chamar_weather_mcp("realtime_weather", {"location": location}))
    except BaseException as exc:
        return {"status": "error", "message": _motivo(exc)}


@tool
def get_forecast_timeline(location: str, timesteps: str = "1d") -> dict:
    """Retorna previsão do tempo para os próximos dias na localização informada,
    via Tomorrow.io MCP.

    Use quando o usuário perguntar sobre previsão de chuva ou calor para planejar
    consumo de água (ex.: regar plantas, lavar quintal).

    location: nome da cidade ou endereço.
    timesteps: intervalo da previsão — '1h' (horária) ou '1d' (diária, padrão).
    """
    try:
        return _run(
            lambda: _chamar_weather_mcp(
                "forecast_timeline", {"location": location, "timesteps": timesteps}
            )
        )
    except BaseException as exc:
        return {"status": "error", "message": _motivo(exc)}


WEATHER_TOOLS = [get_realtime_weather, get_forecast_timeline]
