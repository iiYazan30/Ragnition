"""Groq-only communication; no automatic retries or provider fallback."""

import json
import logging
import re

from groq import APIStatusError, Groq
from groq.types.chat import ChatCompletion

from backend.config import Settings

logger = logging.getLogger(__name__)
MAX_COMPLETION_TOKENS = 1800


class IncompleteCompletionError(RuntimeError):
    """The provider did not return a complete answer for validation."""


def rate_limit_category(exc: APIStatusError) -> str:
    body = exc.body
    if isinstance(body, dict):
        body = body.get("error", body)
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, str):
        return "unknown"
    categories = set(re.findall(r"\((RPM|RPD|TPM|TPD|ITPM|OTPM)\)", message, re.IGNORECASE))
    return next(iter(categories)).upper() if len(categories) == 1 else "unknown"


def rate_limit_headers(exc: APIStatusError) -> dict[str, str | None]:
    # Allow only quota numbers/durations and HTTP Retry-After values, never arbitrary header text.
    fields = {}
    for name in ("retry-after", "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests",
                 "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens",
                 "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = exc.response.headers.get(name, "")
        pattern = r"[0-9]+"
        if name == "retry-after":
            pattern = (r"[0-9]+(?:\.[0-9]+)?|"
                       r"[A-Za-z]{3}, [0-9]{2} [A-Za-z]{3} [0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2} GMT")
        elif "reset" in name:
            pattern = r"(?:[0-9]+(?:\.[0-9]+)?(?:ms|s|m|h|d))+"
        fields[name] = value if len(value) <= 128 and re.fullmatch(pattern, value) else None
    return fields


def test_connection(settings: Settings) -> ChatCompletion:
    if not settings.llm_configured:
        raise ValueError("يجب تعبئة GROQ_API_KEY في ملف .env المحلي.")
    # Construct and close the client only for an explicit provider request.
    with Groq(
        api_key=settings.groq_api_key,
        timeout=30.0,
        max_retries=0,
    ) as client:
        return client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": "Reply with READY only."}],
            max_completion_tokens=64,
        )


def generate_grounded(settings: Settings, messages: list[dict]) -> str:
    with Groq(api_key=settings.groq_api_key, timeout=settings.groq_timeout_seconds, max_retries=0) as client:
        try:
            completion = client.chat.completions.create(
                model=settings.groq_model, messages=messages,
                response_format={"type": "json_object"},
                temperature=0, max_completion_tokens=MAX_COMPLETION_TOKENS,
            )
        except APIStatusError as exc:
            if exc.status_code == 429:
                logger.warning("Groq rate limit: %s", json.dumps({
                    "provider_http_status": exc.status_code,
                    "rate_limit_category": rate_limit_category(exc),
                    **rate_limit_headers(exc),
                    "max_completion_tokens": MAX_COMPLETION_TOKENS,
                    "input_characters": sum(len(m["content"]) for m in messages),
                    "input_utf8_bytes": sum(len(m["content"].encode("utf-8")) for m in messages),
                }))
            raise
    if not completion.choices or completion.choices[0].finish_reason != "stop" or not (completion.choices[0].message.content or "").strip():
        logger.warning("Groq response rejected: reason=COMPLETION_INCOMPLETE")
        raise IncompleteCompletionError("COMPLETION_INCOMPLETE")
    return completion.choices[0].message.content
