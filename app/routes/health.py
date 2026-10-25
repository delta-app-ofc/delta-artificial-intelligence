from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    issues = []
    try:
        get_settings()
    except Exception as exc:
        issues.append(str(exc))
    return {"status": "ok" if not issues else "degraded", "issues": issues}
