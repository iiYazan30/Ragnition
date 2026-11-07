"""Explicit live smoke: at most two Groq requests, no retries, no secret output."""

from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.services.ingestion import atomic_write, encode_json
from backend.services.retrieval import get_index


def main():
    settings = get_settings()
    report = {"model": settings.groq_model, "results": []}
    if not settings.llm_configured or get_index() is None:
        report["skipped_reason"] = "Missing configured credentials or a usable current index."
    else:
        from fastapi.testclient import TestClient
        from backend.main import app
        # No connection probe: each API request below is the smoke request itself.
        with TestClient(app, raise_server_exceptions=False) as client:
            for question in ("شو بدها 10221115 في الحاسوب خطة 2021-1؟", "كم مجموع ساعات الحاسوب خطة 2021-1؟"):
                started = perf_counter()
                response = client.post("/api/chat", json={"question": question})
                item = {"request": {"question": question}, "http_status": response.status_code,
                        "wall_latency_ms": round((perf_counter() - started) * 1000), "response": response.json()}
                report["results"].append(item)
                if response.status_code != 200:
                    report["stopped_reason"] = "Upstream/API error; no retries or provider changes."
                    break
    atomic_write(ROOT / "storage/live_smoke.json", encode_json(report))
    for item in report["results"]:
        print(f"HTTP {item['http_status']}, {item['wall_latency_ms']} ms, "
              f"status={item['response'].get('status', item['response'].get('error', {}).get('code'))}")
        print(item["response"].get("answer", "Safe API error; see storage/live_smoke.json."))
    if "skipped_reason" in report:
        print(report["skipped_reason"])
    print("Public responses saved to storage/live_smoke.json; at most two live requests.")


if __name__ == "__main__":
    main()
