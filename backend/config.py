"""Load root .env without overriding process environment variables."""

from dataclasses import dataclass, field
from functools import lru_cache
import math
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = field(repr=False)
    groq_model: str
    groq_timeout_seconds: float
    cors_origins: tuple[str, ...]
    rag_context_token_budget: int = 6000

    @property
    def llm_configured(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env", override=False, encoding="utf-8")
    try:
        timeout = float(os.getenv("GROQ_TIMEOUT_SECONDS", "30"))
    except ValueError:
        raise ValueError("يجب أن تكون مهلة Groq رقماً موجباً.") from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("يجب أن تكون مهلة Groq رقماً موجباً.")
    origins = tuple(
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    )
    if "*" in origins:
        raise ValueError("يجب تحديد عناوين الواجهة المسموحة صراحةً في CORS_ORIGINS.")
    try:
        context_budget = int(os.getenv("RAG_CONTEXT_TOKEN_BUDGET", "6000"))
    except ValueError:
        raise ValueError("ميزانية سياق RAG يجب أن تكون عدداً صحيحاً.") from None
    if not 512 <= context_budget <= 20000:
        raise ValueError("ميزانية سياق RAG يجب أن تكون بين 512 و20000.")
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip(),
        groq_timeout_seconds=timeout,
        cors_origins=origins,
        rag_context_token_budget=context_budget,
    )
