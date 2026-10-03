from fastapi import FastAPI

from app.routes.health import router as health_router
from app.routes.chat import router as chat_router
from app.routes.sessions import router as sessions_router

app = FastAPI(title="Delta AI", version="0.1.0")

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(sessions_router)
