"""Run explicitly with the existing venv; works from any working directory."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from groq import APIConnectionError, APIStatusError, APITimeoutError

from backend.config import get_settings
from backend.services.llm import test_connection


def main() -> int:
    try:
        settings = get_settings()
    except ValueError:
        print("Invalid Groq settings. Check GROQ_TIMEOUT_SECONDS and CORS_ORIGINS.")
        return 1

    def emit(message: str) -> None:
        if settings.groq_api_key:
            message = message.replace(settings.groq_api_key, "[REDACTED]")
        print(message)

    if not settings.llm_configured:
        emit("Set GROQ_API_KEY in the project root .env file, then run the test again.")
        return 1

    emit(f"Model: {settings.groq_model}")
    try:
        completion = test_connection(settings)
        content = completion.choices[0].message.content
        if not content:
            emit("The model returned no text; the connection could not be confirmed.")
            return 1
        emit(f"Response: {content}")
        if completion.usage:
            emit(f"Total tokens: {completion.usage.total_tokens}")
    except APITimeoutError:
        emit("The Groq connection timed out after 30 seconds.")
        return 1
    except APIConnectionError:
        emit("Could not connect to Groq. Check your network and try again.")
        return 1
    except APIStatusError as exc:
        emit(f"Groq rejected the request (HTTP {exc.status_code}). Check your API key, model, and usage limits.")
        return 1
    except Exception:
        # Provider exception text can contain credentials or request internals.
        emit("Could not complete the Groq test. Check the settings and response compatibility.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
