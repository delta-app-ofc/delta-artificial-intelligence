"""Contagem oficial fora da resposta, com fila limitada e cache sem texto bruto."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from threading import BoundedSemaphore, Lock

from app.config import get_settings

_lock = Lock()
_slots = BoundedSemaphore(8)
_cache = OrderedDict()
_pool = None
_client = None
_client_key = None


def count_tokens(model, texts):
    """Reutiliza o cliente; timeout em milissegundos e sem retries automáticos."""
    from google import genai
    global _client, _client_key
    key = get_settings().gemini_api_key
    with _lock:
        if _client is None or _client_key != key:
            if _client is not None:
                _client.close()
            _client = genai.Client(api_key=key, vertexai=False, http_options={
                "timeout": 5000, "retry_options": {"attempts": 1},
            })
            _client_key = key
        client = _client
    try:
        return int(client.models.count_tokens(model=model, contents=list(texts)).total_tokens)
    except Exception:
        return None


def submit_count(model, texts, counter):
    """Reutiliza trabalhos em andamento; fila cheia deixa a contagem indisponível."""
    global _pool
    if not texts:
        return None
    identity = json.dumps([get_settings().gemini_api_key, model, texts], ensure_ascii=False)
    key = hashlib.sha256(identity.encode()).hexdigest()
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            if not cached.done() or (not cached.cancelled() and cached.exception() is None
                                     and cached.result() is not None):
                _cache.move_to_end(key)
                return cached
            del _cache[key]
        if not _slots.acquire(blocking=False):
            return None
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embedding-usage")
        try:
            future = _pool.submit(counter, model, tuple(texts))
        except Exception:
            _slots.release()
            raise
        future.add_done_callback(lambda _: _slots.release())
        _cache[key] = future
        while len(_cache) > 256:
            _cache.popitem(last=False)
        return future


def close_usage_clients():
    """Drena somente as chamadas ativas e cancela a fila antes de fechar o cliente."""
    global _pool, _client, _client_key
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=True)
    with _lock:
        if _client is not None:
            _client.close()
        _client, _client_key = None, None
        _cache.clear()
