import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgres",
)
HOST_DB = os.getenv("HOST_DB")
PORT_DB = os.getenv("PORT_DB")
USER_DB = os.getenv("USER_DB")
PASSWORD_DB = os.getenv("PASSWORD_DB")
NAME_DB = os.getenv("NAME_DB")

MONGODB_APP_URI = os.getenv("MONGODB_APP_URI", "mongodb://localhost:27018")
MONGODB_TELEMETRY_URI = os.getenv("MONGODB_TELEMETRY_URI", "mongodb://localhost:27018")
MONGO_DB_TELEMETRY = os.getenv("MONGO_DB_TELEMETRY", "db_delta_telemetry")
MONGO_DB_APP = os.getenv("MONGO_DB_APP", "db_delta_app")


def _has_split_postgres_vars() -> bool:
    return all((HOST_DB, PORT_DB, USER_DB, PASSWORD_DB, NAME_DB))


def validate_config() -> list[str]:
    problems: list[str] = []

    if not GEMINI_API_KEY:
        problems.append("GEMINI_API_KEY ausente no .env (necessária para o llm_especialista).")
    if not GROQ_API_KEY:
        problems.append("GROQ_API_KEY ausente no .env (necessária para o fallback e o llm_rapido).")

    if not DATABASE_URL and not _has_split_postgres_vars():
        problems.append(
            "Configure DATABASE_URL ou as cinco variáveis HOST_DB, PORT_DB, "
            "USER_DB, PASSWORD_DB e NAME_DB."
        )

    if not MONGODB_APP_URI:
        problems.append("MONGODB_APP_URI ausente no .env.")
    if not MONGODB_TELEMETRY_URI:
        problems.append("MONGODB_TELEMETRY_URI ausente no .env.")

    return problems