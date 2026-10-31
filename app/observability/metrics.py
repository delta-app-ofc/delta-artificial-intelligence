"""Métricas de operação: custo, latência, erros, resolução e ROI por requisição."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import math
from time import monotonic
from threading import Lock, Thread
from typing import Any

from app.config import get_observability_config, get_settings

# USD por 1 milhão de tokens: (entrada, saída), prompts de até 272 mil tokens, tarifa Standard.
# Sobrescreva com OBS_PRICES_JSON (lido em app/config.py). Fontes em PRICE_SOURCES.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    "gpt-6-luna": (0.10, 0.50),
}
# Fonte de cada preço. "oficial" = página do provedor; "secundária" = agregadores,
# ainda não conferida na página do provedor.
PRICE_SOURCES: dict[str, tuple[str, str]] = {
    "gpt-6-luna": ("https://developers.openai.com/api/docs/pricing", "oficial"),
    "gemini-2.5-flash": ("https://ai.google.dev/gemini-api/docs/pricing", "oficial"),
    "openai/gpt-oss-120b": ("https://groq.com/pricing", "secundária"),
    "openai/gpt-oss-20b": ("https://groq.com/pricing", "secundária"),
}
UNCONFIRMED_PRICE_MODELS = {model for model, (_, kind) in PRICE_SOURCES.items() if kind != "oficial"}

COLLECTION = "observability_requests"
RECORDED_MODES = {"chat", "judge"}
AGENT_NAMES = {"consumption", "forecast", "leak", "habits", "rag"}
_MAX_MEMORY = 2000
_recent: deque = deque(maxlen=_MAX_MEMORY)
_lock = Lock()
# Depois de uma falha no MongoDB, o banco é ignorado por alguns segundos para o painel não travar no timeout.
DB_RETRY_SECONDS = 60
_db_retry_at = 0.0


def assumptions() -> dict:
    """Premissas de negócio vindas dos settings (variáveis OBS_*)."""
    settings = get_observability_config()
    return {
        "support_cost_per_resolution_usd": settings.obs_support_cost_usd,
        "jev_cost_per_evaluation_usd": settings.obs_jev_cost_usd,
        "questions_per_user_per_week": settings.obs_questions_per_user_week,
        "usd_to_brl": settings.obs_usd_to_brl,
    }


def prices() -> dict[str, tuple[float, float]]:
    """Tabela interna, sobrescrita pelos preços de OBS_PRICES_JSON, se houver."""
    table = dict(DEFAULT_PRICES)
    raw = get_observability_config().obs_prices_json
    if raw:
        for model, pair in json.loads(raw).items():
            table[model] = (float(pair[0]), float(pair[1]))
    return table


def model_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pair = prices().get(model)
    if pair is None:
        return 0.0
    return (input_tokens * pair[0] + output_tokens * pair[1]) / 1_000_000


def build_record(trace, outcome: str, total_ms: float) -> dict:
    """Resume o Trace sem guardar prompt, resposta nem dados pessoais."""
    events = list(trace.events)
    models = list(trace.models)
    stages: dict[str, float] = {}
    for item in trace.stages:
        stages[item["stage"]] = stages.get(item["stage"], 0.0) + float(item.get("duration_ms") or 0)
    nodes: dict[str, float] = {}
    for event in events:
        if event.get("event") == "graph.node.end" and event.get("duration_ms") is not None:
            name = event.get("component")
            nodes[name] = nodes.get(name, 0.0) + event["duration_ms"]

    by_agent: dict[str, dict] = {}
    unknown_models = set()
    for call in models:
        if call.get("kind") == "embedding":
            continue
        tokens_in = int(call.get("input_tokens") or 0)
        tokens_out = int(call.get("output_tokens") or 0)
        if call.get("model") not in prices():
            unknown_models.add(call.get("model"))
        agent = by_agent.setdefault(call.get("component") or "request", {
            "calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model_ms": 0.0})
        agent["calls"] += 1
        agent["input_tokens"] += tokens_in
        agent["output_tokens"] += tokens_out
        agent["model_ms"] += float(call.get("duration_ms") or 0)
        agent["cost_usd"] += model_cost(call.get("model") or "", tokens_in, tokens_out)

    judge_runs = sum(1 for e in events if e.get("event") == "graph.node.end" and e.get("component") == "judge")
    jev_cost = judge_runs * assumptions()["jev_cost_per_evaluation_usd"]
    llm_cost = sum(item["cost_usd"] for item in by_agent.values())
    blocked = any(e.get("component") == "block" and e.get("event") == "graph.node.end" for e in events)
    resolved = outcome == "success" and not blocked and trace.mode in RECORDED_MODES
    return {
        "request_id": trace.request_id,
        "created_at": datetime.now(timezone.utc),
        "mode": trace.mode,
        "outcome": outcome,
        "resolved": resolved,
        "total_ms": round(total_ms, 1),
        "nodes_ms": {k: round(v, 1) for k, v in nodes.items()},
        "agents_ms": {k: round(v, 1) for k, v in stages.items() if k in AGENT_NAMES},
        "overhead_ms": round(max(0.0, total_ms - sum(nodes.values())), 1),
        "revisions": sum(1 for e in events if e.get("component") == "revise" and e.get("event") == "graph.node.end"),
        "input_tokens": sum(item["input_tokens"] for item in by_agent.values()),
        "output_tokens": sum(item["output_tokens"] for item in by_agent.values()),
        "model_calls": sum(item["calls"] for item in by_agent.values()),
        "fallback_calls": sum(1 for c in models if c.get("fallback")),
        "by_component": {k: {**v, "cost_usd": round(v["cost_usd"], 8), "model_ms": round(v["model_ms"], 1)}
                         for k, v in by_agent.items()},
        "llm_cost_usd": round(llm_cost, 8),
        "jev_cost_usd": round(jev_cost, 8),
        "cost_usd": round(llm_cost + jev_cost, 8),
        "unpriced_models": sorted(m for m in unknown_models if m),
    }


def record_request(trace, outcome: str, total_ms: float) -> None:
    """Guarda em memória e, se possível, no MongoDB; nunca altera a resposta."""
    if trace.mode not in RECORDED_MODES:
        return
    try:
        record = build_record(trace, outcome, total_ms)
        with _lock:
            _recent.append(record)
        # A gravação é síncrona e pode demorar; sai do event loop numa thread.
        Thread(target=_persist, args=(dict(record),), daemon=True).start()
    except Exception:
        pass


def _db_available() -> bool:
    return monotonic() >= _db_retry_at


def _mark_db_failed() -> None:
    global _db_retry_at
    _db_retry_at = monotonic() + DB_RETRY_SECONDS


def _persist(record: dict) -> None:
    if not _db_available():
        return
    try:
        from app.data.db_mongo import get_app_client
        get_app_client()[get_settings().mongo_db_app][COLLECTION].insert_one(record)
    except Exception:
        # O registro continua em memória; a falha não pode afetar a aplicação.
        _mark_db_failed()


def load_records(limit: int = 1000) -> list[dict]:
    """Lê do MongoDB; sem banco, usa os registros do processo atual."""
    found = []
    if _db_available():
        try:
            from app.data.db_mongo import get_app_client
            cursor = (get_app_client()[get_settings().mongo_db_app][COLLECTION]
                      .find({}, {"_id": 0}).sort("created_at", -1).limit(limit))
            found = list(reversed(list(cursor)))
        except Exception:
            _mark_db_failed()
    with _lock:
        pending = list(_recent)
    saved = {item["request_id"] for item in found}
    # Registros recentes que ainda não chegaram ao banco (ou cuja gravação falhou).
    merged = found + [item for item in pending if item["request_id"] not in saved]
    merged.sort(key=lambda item: item["created_at"])
    return merged[-limit:]


def clear_memory() -> None:
    with _lock:
        _recent.clear()


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank: menor valor que cobre pct% das amostras."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = math.ceil(pct / 100 * len(ordered)) - 1
    return float(ordered[min(max(index, 0), len(ordered) - 1)])


def _latency(values: list[float]) -> dict:
    return {"avg": round(sum(values) / len(values), 1) if values else 0.0,
            "p50": round(percentile(values, 50), 1), "p95": round(percentile(values, 95), 1),
            "p99": round(percentile(values, 99), 1)}


def roi(resolutions: int, cost_usd: float, support_cost: float | None = None) -> float | None:
    """ROI = (economia de atendimento − custo de IA) ÷ custo de IA."""
    support = assumptions()["support_cost_per_resolution_usd"] if support_cost is None else support_cost
    if cost_usd <= 0:
        return None
    return round((resolutions * support - cost_usd) / cost_usd, 4)


def summarize(records: list[dict]) -> dict:
    total = len(records)
    errors = sum(1 for r in records if r["outcome"] == "error")
    rejected = sum(1 for r in records if r["outcome"] == "rejected")
    partial = sum(1 for r in records if r["outcome"] == "partial")
    resolutions = sum(1 for r in records if r.get("resolved"))
    cost = sum(r["cost_usd"] for r in records)
    total_lat = _latency([r["total_ms"] for r in records])
    error_rate = errors / total if total else 0.0
    settings = get_observability_config()
    p95_limit, error_limit = settings.obs_latency_p95_limit_ms, settings.obs_error_rate_limit
    nodes: dict[str, list[float]] = {}
    agents: dict[str, list[float]] = {}
    cost_by_component: dict[str, float] = {}
    for r in records:
        for name, ms in r.get("nodes_ms", {}).items():
            nodes.setdefault(name, []).append(ms)
        for name, ms in r.get("agents_ms", {}).items():
            agents.setdefault(name, []).append(ms)
        for name, item in r.get("by_component", {}).items():
            cost_by_component[name] = cost_by_component.get(name, 0.0) + item["cost_usd"]
    return {
        "requests": total,
        "outcomes": {"success": total - errors - rejected - partial, "partial": partial,
                     "error": errors, "rejected": rejected},
        "error_rate": round(error_rate, 4),
        "latency_total_ms": total_lat,
        "latency_by_node_ms": {k: _latency(v) for k, v in nodes.items()},
        "latency_by_agent_ms": {k: _latency(v) for k, v in agents.items()},
        "overhead_ms": _latency([r.get("overhead_ms", 0.0) for r in records]),
        "usage": {"input_tokens": sum(r["input_tokens"] for r in records),
                  "output_tokens": sum(r["output_tokens"] for r in records)},
        "cost_usd": round(cost, 6),
        "cost_per_request_usd": round(cost / total, 6) if total else 0.0,
        "cost_by_component_usd": {k: round(v, 6) for k, v in sorted(
            cost_by_component.items(), key=lambda kv: kv[1], reverse=True)},
        "volume_per_request": round((sum(r["input_tokens"] + r["output_tokens"] for r in records)) / total) if total else 0,
        "model_calls_per_request": round(sum(r["model_calls"] for r in records) / total, 2) if total else 0.0,
        "revision_rate": round(sum(1 for r in records if r.get("revisions")) / total, 4) if total else 0.0,
        "savings_usd": round(resolutions * assumptions()["support_cost_per_resolution_usd"] - cost, 4),
        "resolutions": resolutions,
        "resolution_rate": round(resolutions / total, 4) if total else 0.0,
        "cost_per_resolution_usd": round(cost / resolutions, 6) if resolutions else None,
        "roi": roi(resolutions, cost),
        "fallback_calls": sum(r.get("fallback_calls", 0) for r in records),
        "unpriced_models": sorted({m for r in records for m in r.get("unpriced_models", [])}),
        "slo": {"latency_p95_limit_ms": p95_limit, "error_rate_limit": error_limit,
                "ok": (total_lat["p95"] <= p95_limit and error_rate <= error_limit) if total else None},
        "series": [{"at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                    "total_ms": r["total_ms"], "cost_usd": r["cost_usd"]} for r in records[-100:]],
        "unconfirmed_price_models": sorted(UNCONFIRMED_PRICE_MODELS),
        "price_sources": {m: {"url": url, "kind": kind} for m, (url, kind) in PRICE_SOURCES.items()},
        "assumptions": assumptions(),
    }


def project(summary: dict, users_list: tuple[int, ...] = (100, 1000)) -> list[dict]:
    """Projeta custo e ROI por semana/mês a partir do custo médio real por pergunta."""
    ass = assumptions()
    per_request = summary.get("cost_per_request_usd") or 0.0
    resolution_rate = summary.get("resolution_rate") or 0.0
    rows = []
    for scenario, factor in (("base", 1.0), ("pessimista", 1.5)):
        for users in users_list:
            requests = users * ass["questions_per_user_per_week"]
            week = requests * per_request * factor
            resolved = requests * resolution_rate
            rows.append({
                "scenario": scenario, "users_per_week": users, "requests_per_week": round(requests),
                "cost_week_usd": round(week, 4), "cost_month_usd": round(week * 4.33, 4),
                "cost_week_brl": round(week * ass["usd_to_brl"], 2),
                "cost_per_resolution_usd": round(week / resolved, 6) if resolved else None,
                "roi": roi(round(resolved), week) if week else None,
            })
    return rows
