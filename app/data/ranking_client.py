"""Cliente do serviço delta-redis-database: lê o ranking mensal de unidades por organização."""

from __future__ import annotations

import httpx

from app.config import ConfigurationError, get_settings
from app.tools.exceptions import DatabaseAccessError

_TIMEOUT_SECONDS = 5.0
_MAX_ITEMS = 100


def get_organization_ranking(organization_id: int, period: str) -> list[dict]:
    """Itens do ranking por consumo médio diário (critério `consumo`) de uma organização no mês
    `AAAA-MM`. O serviço ordena do menor para o maior consumo.
    """
    base_url = get_settings().ranking_service_url
    if not base_url:
        raise ConfigurationError("RANKING_SERVICE_URL não configurada.")
    try:
        response = httpx.get(
            f"{base_url}/get-ranking",
            params={
                "organizationId": organization_id,
                "period": period,
                "criterion": "consumo",
                "limit": _MAX_ITEMS,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        items = response.json().get("items")
    except (httpx.HTTPError, ValueError) as error:
        raise DatabaseAccessError("ranking") from error
    return items if isinstance(items, list) else []
