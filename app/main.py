from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.observability.http import RequestTracingMiddleware

from app.config import get_settings
from app.routes.health import router as health_router
from app.routes.chat import router as chat_router
from app.routes.sessions import router as sessions_router
from app.routes.playground import router as playground_router
from app.observability.langsmith import enable_langsmith


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Mantém clientes lazy por processo e fecha-os após as requisições terminarem."""
    from app.agents.judge_specialist import close_judge_clients
    from app.data.db_postgres import close_pool
    from app.services.rag import close_rag_clients
    from app.services.llms import close_openai_clients

    try:
        yield
    finally:
        try:
            await close_rag_clients()
        finally:
            try:
                await close_judge_clients()
            finally:
                try:
                    await close_openai_clients()
                finally:
                    close_pool()


enable_langsmith()
app = FastAPI(title="Delta AI", version="0.1.0", lifespan=lifespan)


def cors_origins() -> list[str]:
    """Origens do CORS vindas de CORS_ALLOWED_ORIGINS; sem valor, aceita qualquer origem."""
    raw = get_settings().cors_allowed_origins
    return [origin.strip() for origin in raw.split(",") if origin.strip()] or ["*"]


app.add_middleware(RequestTracingMiddleware)

# A autenticação é por cabeçalho Bearer, sem cookies: não há motivo para permitir credenciais.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(sessions_router)

app.include_router(playground_router)
