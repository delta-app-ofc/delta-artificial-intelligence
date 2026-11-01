"""Métricas de operação: custo, latência, erros, resolução e ROI por requisição."""
from __future__ import annotations

from collections import deque
from concurrent.futures import wait
from datetime import datetime, timezone
import hashlib
import hmac
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
    "gemini-embedding-001": (0.15, 0.0),
    "gemini-embedding-2": (0.20, 0.0),
    "jev": (0.042, 0.0),
}
# Fonte de cada preço. "oficial" = página do provedor; "secundária" = agregadores,
# ainda não conferida na página do provedor.
PRICE_SOURCES: dict[str, tuple[str, str]] = {
    "gpt-6-luna": ("https://developers.openai.com/api/docs/pricing", "oficial"),
    "gemini-2.5-flash": ("https://ai.google.dev/gemini-api/docs/pricing", "oficial"),
    "gemini-embedding-001": ("https://ai.google.dev/gemini-api/docs/pricing", "oficial"),
    "gemini-embedding-2": ("https://ai.google.dev/gemini-api/docs/pricing", "oficial"),
    "jev": ("https://typesafe.ai", "oficial"),
    "openai/gpt-oss-120b": ("https://console.groq.com/docs/model/openai/gpt-oss-120b", "oficial"),
    "openai/gpt-oss-20b": ("https://console.groq.com/docs/model/openai/gpt-oss-20b", "oficial"),
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
        "questions_per_user_per_week": settings.obs_questions_per_user_week or None,
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


CLIENTS = ("app", "web", "playground")


def client_from_scope(scope) -> str:
    """Cliente que chamou a API: cabeçalho X-Client (app ou web) ou o console de testes."""
    if scope.get("path", "").startswith("/playground"):
        return "playground"
    for key, value in scope.get("headers", []):
        if key == b"x-client":
            name = value.decode("latin-1").strip().casefold()
            return name if name in CLIENTS else "unknown"
    return "unknown"


def user_hash(user_id) -> str | None:
    """HMAC do usuário com segredo do servidor: conta usuários distintos sem guardar o id."""
    secret = get_observability_config().obs_hash_secret
    if not secret or user_id is None:
        return None
    return hmac.new(secret.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()[:32]


def _price_for(model: str) -> tuple[float, float] | None:
    table = prices()
    model = model.removeprefix("models/")  # o RAG usa "models/gemini-embedding-..."
    if model in table:
        return table[model]
    # Embedding e Jev chegam com sufixo de versão (ex.: gemini-embedding-2-preview, jev-1.14.0).
    matches = [name for name in table if name.startswith(("gemini-embedding", "jev")) and model.startswith(name)]
    return table[max(matches, key=len)] if matches else None


def model_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pair = _price_for(model)
    if pair is None:
        return 0.0
    return (input_tokens * pair[0] + output_tokens * pair[1]) / 1_000_000


def build_record(trace, outcome: str, total_ms: float) -> dict:
    """Resume o Trace sem guardar prompt, resposta nem dados pessoais."""
    with trace.lock:
        events = list(trace.events)
        models = [dict(row) for row in trace.models]
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
        if call.get("kind") in {"embedding", "jev"}:
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

    embedding_tokens, embedding_cost, embedding_uncounted = 0, 0.0, 0
    jev_tokens, jev_cost = 0, 0.0
    for call in models:
        kind = call.get("kind")
        if kind not in {"embedding", "jev"}:
            continue
        if _price_for(call.get("model") or "") is None:
            unknown_models.add(call.get("model"))
        tokens = call.get("input_tokens")  # contagem real: count_tokens (embedding) ou usage da resposta (Jev)
        if kind == "jev":
            jev_tokens += int(tokens or 0)
            jev_cost += model_cost(call.get("model") or "", int(tokens or 0), int(call.get("output_tokens") or 0))
        elif tokens is None:
            embedding_uncounted += 1  # sem contagem oficial: o custo não é estimado
        else:
            embedding_tokens += int(tokens)
            embedding_cost += model_cost(call.get("model") or "", int(tokens), 0)

    embedding_ms = sum(float(c.get("duration_ms") or 0) for c in models if c.get("kind") == "embedding")

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
        "rag_phases_ms": {k.removeprefix("rag_"): round(v, 1) for k, v in stages.items() if k.startswith("rag_")},
        "overhead_ms": round(max(0.0, total_ms - sum(nodes.values())), 1),
        "client": getattr(trace, "client", "unknown"),
        **({"user_hash": digest} if (digest := user_hash(trace.user_id)) else {}),
        "revisions": sum(1 for e in events if e.get("component") == "revise" and e.get("event") == "graph.node.end"),
        "input_tokens": sum(item["input_tokens"] for item in by_agent.values()),
        "output_tokens": sum(item["output_tokens"] for item in by_agent.values()),
        "embedding_tokens": embedding_tokens,
        "embedding_uncounted": embedding_uncounted,
        "embedding_pending": sum(c.get("count_status") == "pending" for c in models),
        "embedding_count_ms": round(sum(float(c.get("count_duration_ms") or 0) for c in models), 1),
        "jev_tokens": jev_tokens,
        "model_calls": sum(item["calls"] for item in by_agent.values()),
        "fallback_calls": sum(1 for c in models if c.get("fallback")),
        "by_component": {
            **{k: {**v, "cost_usd": round(v["cost_usd"], 8), "model_ms": round(v["model_ms"], 1)} for k, v in by_agent.items()},
            **({"embeddings": {"calls": sum(1 for c in models if c.get("kind") == "embedding"), "input_tokens": embedding_tokens,
                               "output_tokens": 0, "model_ms": round(embedding_ms, 1), "cost_usd": round(embedding_cost, 8)}}
               if any(c.get("kind") == "embedding" for c in models) else {}),
        },
        "llm_cost_usd": round(llm_cost, 8),
        "embedding_cost_usd": round(embedding_cost, 8),
        "jev_cost_usd": round(jev_cost, 8),
        "cost_usd": round(llm_cost + embedding_cost + jev_cost, 8),
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
        Thread(target=_finalize_record, args=(trace, outcome, total_ms, record), daemon=True).start()
    except Exception:
        pass


def _finalize_record(trace, outcome, total_ms, record):
    """Espera a contagem somente na thread de persistência, nunca na requisição."""
    if trace.embedding_counts:
        wait(list(trace.embedding_counts), timeout=25)
        final = build_record(trace, outcome, total_ms)
        final["created_at"] = record["created_at"]
        with _lock:
            record.update(final)
    _persist(dict(record))


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
    by_client: dict[str, dict] = {}
    for r in records:
        item = by_client.setdefault(r.get("client", "unknown"), {"requests": 0, "cost_usd": 0.0, "resolutions": 0, "_users": set()})
        item["requests"] += 1
        item["cost_usd"] += r["cost_usd"]
        item["resolutions"] += 1 if r.get("resolved") else 0
        if r.get("user_hash"):
            item["_users"].add(r["user_hash"])
    users = {r["user_hash"] for r in records if r.get("user_hash")}
    stamps = sorted(r["created_at"] for r in records if hasattr(r.get("created_at"), "timestamp"))
    observed_days = round((stamps[-1] - stamps[0]).total_seconds() / 86400, 2) if len(stamps) > 1 else 0.0
    per_user = sum(1 for r in records if r.get("user_hash")) / len(users) if users else None
    return {
        "requests": total,
        "cost_by_client": {name: {"requests": v["requests"], "cost_usd": round(v["cost_usd"], 6),
                                  "cost_per_request_usd": round(v["cost_usd"] / v["requests"], 6),
                                  "resolutions": v["resolutions"], "users": len(v["_users"])}
                           for name, v in sorted(by_client.items(), key=lambda kv: kv[1]["cost_usd"], reverse=True)},
        "distinct_users": len(users),
        "observed_days": observed_days,
        # Só vira taxa semanal depois de uma semana inteira de dados; antes disso não há base para projetar.
        "measured_questions_per_user_week": round(per_user / (observed_days / 7), 2) if per_user and observed_days >= 7 else None,
        "cost_p95_per_request_usd": round(percentile([r["cost_usd"] for r in records], 95), 6) if records else None,
        "questions_per_user": round(sum(1 for r in records if r.get("user_hash")) / len(users), 2) if users else None,
        "embedding_cost_usd": round(sum(r.get("embedding_cost_usd", 0.0) for r in records), 6),
        "jev_cost_usd": round(sum(r.get("jev_cost_usd", 0.0) for r in records), 6),
        "embedding_uncounted": sum(r.get("embedding_uncounted", 0) for r in records),
        "outcomes": {"success": total - errors - rejected - partial, "partial": partial,
                     "error": errors, "rejected": rejected},
        "error_rate": round(error_rate, 4),
        "latency_total_ms": total_lat,
        "latency_by_node_ms": {k: _latency(v) for k, v in nodes.items()},
        "latency_by_agent_ms": {k: _latency(v) for k, v in agents.items()},
        "overhead_ms": _latency([r.get("overhead_ms", 0.0) for r in records]),
        "usage": {"embedding_tokens": sum(r.get("embedding_tokens", 0) for r in records),
                  "jev_tokens": sum(r.get("jev_tokens", 0) for r in records),
                  "input_tokens": sum(r["input_tokens"] for r in records),
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
    questions = ass["questions_per_user_per_week"] or summary.get("measured_questions_per_user_week")
    resolution_rate = summary.get("resolution_rate") or 0.0
    # Base = custo médio medido por requisição; pessimista = custo no p95 das requisições medidas.
    scenarios = (("base", summary.get("cost_per_request_usd")), ("pessimista", summary.get("cost_p95_per_request_usd")))
    rows = []
    for scenario, per_request in scenarios:
        for users in users_list:
            known = questions is not None and per_request is not None
            requests = users * questions if known else None
            week = requests * per_request if known else None
            resolved = requests * resolution_rate if known else None
            rows.append({
                "scenario": scenario, "users_per_week": users,
                "requests_per_week": round(requests) if known else None,
                "cost_week_usd": round(week, 4) if known else None,
                "cost_month_usd": round(week * 52 / 12, 4) if known else None,
                "cost_week_brl": round(week * ass["usd_to_brl"], 2) if known else None,
                "cost_per_resolution_usd": round(week / resolved, 6) if known and resolved else None,
                "roi": roi(round(resolved), week) if known and week else None,
            })
    return rows
