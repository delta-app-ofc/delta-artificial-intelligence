from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from app.config import TOMORROW_API_KEY, TOMORROW_MCP_URL

_cached_tools: list[BaseTool] | None = None


def _run(coro) -> Any:
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


def _motivo(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return " | ".join(_motivo(sub) for sub in exc.exceptions)
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


async def _call_tool(tool_name: str, args: dict) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    client = create_mcp_http_client()
    client.headers["X-Api-Key"] = TOMORROW_API_KEY

    async with client:
        async with streamable_http_client(TOMORROW_MCP_URL, http_client=client) as (
            read,
            write,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, args)
                if getattr(result, "is_error", False):
                    return {"status": "error", "message": str(result)}
                texts = [
                    getattr(b, "text", None)
                    for b in (getattr(result, "content", []) or [])
                    if getattr(b, "text", None)
                ]
                if not texts:
                    return {"status": "error", "message": "Sem conteúdo retornado."}
                try:
                    return json.loads(texts[0])
                except json.JSONDecodeError:
                    return {"status": "ok", "result": texts[0]}


async def _discover_tools() -> list[BaseTool]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    if not TOMORROW_API_KEY:
        return []

    client = create_mcp_http_client()
    client.headers["X-Api-Key"] = TOMORROW_API_KEY

    langchain_tools: list[BaseTool] = []

    async with client:
        async with streamable_http_client(TOMORROW_MCP_URL, http_client=client) as (
            read,
            write,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                catalog = await session.list_tools()

                for mcp_tool in catalog.tools:
                    schema = mcp_tool.input_schema or {}
                    props = schema.get("properties", {})
                    required = set(schema.get("required", []))

                    fields: dict[str, Any] = {}
                    for field_name, field_info in props.items():
                        desc = field_info.get("description", field_name)
                        if field_name in required:
                            fields[field_name] = (str, Field(..., description=desc))
                        else:
                            default = field_info.get("default", None)
                            fields[field_name] = (
                                str | None,
                                Field(default=default, description=desc),
                            )

                    args_model: type[BaseModel] = create_model(
                        f"{mcp_tool.name}_args", **fields
                    )

                    # sem captura explícita, todas as closures referenciariam
                    # o mesmo mcp_tool.name ao final do loop
                    captured_name = mcp_tool.name

                    def _make_fn(name: str):
                        def fn(**kwargs: Any) -> dict:
                            try:
                                return _run(_call_tool(name, kwargs))
                            except BaseException as exc:
                                return {"status": "error", "message": _motivo(exc)}

                        fn.__name__ = name
                        return fn

                    tool = StructuredTool(
                        name=captured_name,
                        description=mcp_tool.description or captured_name,
                        args_schema=args_model,
                        func=_make_fn(captured_name),
                    )
                    langchain_tools.append(tool)

    return langchain_tools


def get_weather_tools() -> list[BaseTool]:
    """Tools do Tomorrow.io descobertas via list_tools() — cache por processo."""
    global _cached_tools
    if _cached_tools is not None:
        return _cached_tools

    if not TOMORROW_API_KEY:
        _cached_tools = []
        return _cached_tools

    try:
        _cached_tools = _run(_discover_tools())
    except BaseException:
        _cached_tools = []

    return _cached_tools
