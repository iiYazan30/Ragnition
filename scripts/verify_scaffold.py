"""Small local assert-based check; no provider request or real credentials."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    # Exercise the unavailable-index contract independently of the workspace's built index.
    with patch.dict(os.environ, {"GROQ_API_KEY": "", "CORS_ORIGINS": "http://localhost:5173"}), \
         patch("backend.api.routes.get_index", return_value=None), \
         patch("backend.api.routes.get_catalog", return_value=({}, 0)):
        from fastapi.testclient import TestClient
        from backend.config import get_settings
        from backend.main import app

        get_settings.cache_clear()
        # Any attempted provider-client construction makes this check fail.
        with patch("backend.services.llm.Groq", side_effect=AssertionError("Unexpected provider call")):
            with TestClient(app, raise_server_exceptions=False) as client:
                health = client.get("/api/health")
                assert health.status_code == 200
                assert health.json() == {
                    "status": "degraded", "index_ready": False, "llm_configured": False,
                    "documents_count": 0, "chunks_count": 0,
                }
                docs = client.get("/api/documents")
                assert docs.status_code == 200 and docs.json() == {"documents": []}
                ids = set()

                def check_error(response, status, code):
                    assert response.status_code == status
                    error = response.json()["error"]
                    assert set(error) == {"code", "message", "request_id"}
                    assert error["code"] == code
                    assert any("\u0600" <= ch <= "\u06ff" for ch in error["message"])
                    assert str(UUID(error["request_id"])) == response.headers["X-Request-ID"]
                    assert error["request_id"] not in ids
                    ids.add(error["request_id"])
                    for forbidden in ("Traceback", str(ROOT), "gsk_", "Authorization"):
                        assert forbidden not in response.text

                check_error(client.post("/api/chat", json={"question": "سؤال"}), 503, "KNOWLEDGE_NOT_READY")
                for body in (
                    {}, {"question": ""}, {"question": " \t\n"}, {"question": "x" * 2001},
                    {"question": "x", "history": [{"role": "user", "content": "x"}] * 9},
                    {"question": "x", "history": [{"role": "system", "content": "x"}]},
                    {"question": "x", "history": [{"role": "user", "content": "x" * 4001}]},
                    {"question": "x", "history": [{"role": "user", "content": "  "}]},
                ):
                    check_error(client.post("/api/chat", json=body), 422, "VALIDATION_ERROR")
                check_error(client.post("/api/chat", content="{", headers={"Content-Type": "application/json"}), 422, "VALIDATION_ERROR")
                check_error(client.post("/api/chat", json={
                    "question": "x" * 2000,
                    "history": [{"role": "assistant", "content": "x" * 4000}] * 8,
                }), 503, "KNOWLEDGE_NOT_READY")
                check_error(client.get("/api/documents/unknown/file"), 404, "NOT_FOUND")
                check_error(client.get("/api/documents/..%2F.env/file"), 404, "NOT_FOUND")
                check_error(client.get("/missing"), 404, "NOT_FOUND")
                schema = client.get("/openapi.json").json()["components"]["schemas"]
                assert {"ChatResponse", "Citation", "DocumentEntry", "ErrorResponse"} <= schema.keys()
                allowed = client.options("/api/chat", headers={
                    "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type",
                })
                assert allowed.status_code == 200
                assert allowed.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
                denied = client.get("/api/health", headers={"Origin": "https://untrusted.example"})
                assert "Access-Control-Allow-Origin" not in denied.headers
                with patch.dict(os.environ, {"GROQ_API_KEY": "   "}):
                    get_settings.cache_clear()
                    assert not client.get("/api/health").json()["llm_configured"]
                with patch.dict(os.environ, {"GROQ_API_KEY": "local-test-value"}):
                    get_settings.cache_clear()
                    assert client.get("/api/health").json()["llm_configured"]
                    check_error(client.post("/api/chat", json={"question": "x"}), 503, "KNOWLEDGE_NOT_READY")
                with patch("backend.api.routes.get_settings", side_effect=RuntimeError("local-test-value " + str(ROOT))):
                    failure = client.get("/api/health")
                    check_error(failure, 500, "INTERNAL_ERROR")
                    assert "local-test-value" not in failure.text

        # Explicitly empty process key overrides .env, even if later filled manually.
        environment = dict(os.environ, GROQ_API_KEY="", PYTHONIOENCODING="utf-8")
        with TemporaryDirectory() as working_directory:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/test_groq_connection.py")],
                cwd=working_directory, env=environment, capture_output=True,
                text=True, encoding="utf-8", timeout=10,
            )
        assert result.returncode == 1 and "GROQ_API_KEY" in result.stdout
        assert not result.stderr and "Traceback" not in result.stdout
        get_settings.cache_clear()
    print("PASS: API startup, contract, validation, CORS, unique IDs, missing-key script and independent working directory; no provider requests.")


if __name__ == "__main__":
    main()
