"""Offline SDK/API checks: mock HTTP only; never loads real credentials or calls Groq."""

import json
import os
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from groq import APIStatusError, DefaultHttpxClient, Groq as RealGroq

from backend.config import Settings
from backend.schemas import ChatRequest, HistoryMessage
from backend.services import llm, rag
from backend.services.retrieval import get_index


def main():
    settings = Settings("KEY_SENTINEL", "local-test-model", 30, ("http://localhost:5173",))
    question = "ما متطلبات 10221115 في الحاسوب خطة 2021-1؟"
    index = get_index()
    assert index is not None
    with patch.object(rag, "generate_grounded", return_value="") as generated:
        rag.answer(ChatRequest(question=question, history=[
            HistoryMessage(role="user", content="USER_HISTORY_SENTINEL"),
            HistoryMessage(role="assistant", content="ASSISTANT_HISTORY_SENTINEL"),
        ]), index, settings)
    generated.assert_called_once()
    messages = generated.call_args.args[1]
    assert len(messages) == 2 and "HISTORY_SENTINEL" not in json.dumps(messages)
    payload = json.loads(messages[1]["content"])
    assert set(payload) == {"question", "resolved_program_id", "resolved_plan_version", "evidence"}
    assert 1 <= len(payload["evidence"]) <= 6
    assert all(set(b) == {"source_id", "facts", "locator", "quote"} for b in payload["evidence"])
    assert len(json.dumps(payload["evidence"], ensure_ascii=False).encode("utf-8")) <= settings.rag_context_token_budget

    quota_headers = {
        "retry-after": "17", "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "998", "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "2", "x-ratelimit-reset-requests": "23h59m42s",
        "x-ratelimit-reset-tokens": "17.5s",
    }
    scenarios = [
        ("TPM", quota_headers),
        ("TPD", {**quota_headers, "retry-after": "86400"}),
        ("RPD", {k: v for k, v in quota_headers.items() if k != "retry-after"}),
        ("RPM", {"retry-after": "Mon, 09 Nov 2026 12:00:00 GMT"}),
        ("unknown", {}),
        ("unknown", {k: "KEY_SENTINEL PROMPT_SENTINEL" for k in quota_headers}),
    ]
    calls = []

    def reject(request):
        calls.append(None)
        body = json.loads(request.content)
        assert body["model"] == settings.groq_model
        assert body["max_completion_tokens"] == 1800
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(429, request=request, headers={**headers, "x-private": "HEADER_SENTINEL"}, json={
            "error": {"message": f"Rate limit reached ({category}). KEY_SENTINEL PROMPT_SENTINEL",
                      "code": "rate_limit_exceeded"},
        })

    def local_client(**kwargs):
        assert kwargs["max_retries"] == 0 and kwargs["api_key"] == settings.groq_api_key
        return RealGroq(**kwargs, http_client=DefaultHttpxClient(transport=httpx.MockTransport(reject)))

    with patch("dotenv.load_dotenv", return_value=False), patch.dict(os.environ, {
        "GROQ_API_KEY": settings.groq_api_key, "CORS_ORIGINS": settings.cors_origins[0],
    }):
        from fastapi.testclient import TestClient
        from backend.config import get_settings
        from backend.main import app
        get_settings.cache_clear()
        with patch.object(llm, "Groq", side_effect=local_client) as constructed, \
             patch("backend.api.routes.get_settings", return_value=settings):
            with TestClient(app, raise_server_exceptions=False) as client:
                for _ in range(3):
                    assert client.get("/api/health").status_code == 200
                    assert client.get("/api/documents").status_code == 200
                constructed.assert_not_called()
                for category, headers in scenarios:
                    before = len(calls)
                    with TestCase().assertLogs(llm.logger, level="WARNING") as captured:
                        response = client.post("/api/chat", json={"question": question},
                                               headers={"Origin": settings.cors_origins[0]})
                    assert len(calls) == before + 1, "Unexpected retry"
                    assert response.status_code == 429 and response.json()["error"]["code"] == "LLM_RATE_LIMIT"
                    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
                    assert "Retry-After" in response.headers["Access-Control-Expose-Headers"]
                    assert len(captured.records) == 1
                    log = captured.records[0].getMessage()
                    fields = json.loads(log.split(": ", 1)[1])
                    assert fields["provider_http_status"] == 429 and fields["rate_limit_category"] == category
                    assert fields["max_completion_tokens"] == 1800
                    assert fields["input_characters"] == sum(len(m["content"]) for m in messages)
                    assert fields["input_utf8_bytes"] == sum(len(m["content"].encode("utf-8")) for m in messages)
                    assert set(fields) == {*quota_headers, "provider_http_status", "rate_limit_category",
                                           "max_completion_tokens", "input_characters", "input_utf8_bytes"}
                    for name in quota_headers:
                        expected = headers.get(name)
                        if expected and "SENTINEL" in expected:
                            expected = None
                        assert fields[name] == expected
                    assert response.headers.get("Retry-After") == fields["retry-after"]
                    assert ("اليومية" in response.json()["error"]["message"]) == (category in {"RPD", "TPD"})
                    assert captured.records[0].exc_info is None
                    for forbidden in (settings.groq_api_key, "PROMPT_SENTINEL", "HEADER_SENTINEL",
                                      "Authorization", question, rag.SYSTEM, str(ROOT)):
                        assert forbidden not in log and forbidden not in response.text
        get_settings.cache_clear()

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    for body in (None, [], "RAW_SENTINEL", {"error": []}, {"message": []},
                 {"message": "Ambiguous (TPM) and (TPD)"}):
        error = APIStatusError("EXCEPTION_SENTINEL", response=httpx.Response(429, request=request), body=body)
        assert llm.rate_limit_category(error) == "unknown"
        assert all(value is None for value in llm.rate_limit_headers(error).values())
    print("PASS: 6 mocked upstream 429 cases; safe logging, daily/unknown categories, Retry-After seconds/date/absent, CORS, one SDK call per chat, no background calls, bounded context and no serialized history. Live Groq requests: 0.")


if __name__ == "__main__":
    main()
