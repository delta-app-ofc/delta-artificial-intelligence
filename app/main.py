from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routes.health import router as health_router
from app.routes.chat import router as chat_router
from app.routes.sessions import router as sessions_router
from app.routes.playground import router as playground_router

app = FastAPI(title="Delta AI", version="0.1.0")


def cors_origins() -> list[str]:
    """Origens do CORS vindas de CORS_ALLOWED_ORIGINS; sem valor, aceita qualquer origem."""
    raw = get_settings().cors_allowed_origins
    return [origin.strip() for origin in raw.split(",") if origin.strip()] or ["*"]


# A autenticação é por cabeçalho Bearer, sem cookies: não há motivo para permitir credenciais.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(sessions_router)

app.include_router(playground_router)
