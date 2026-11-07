"""Source-backed local retrieval/API checks; never uses real credentials or a provider."""

import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import Settings
from backend.schemas import ChatRequest, HistoryMessage
from backend.services.ingestion import atomic_write, encode_json
from backend.services.rag import evidence_context, validate_answer
from backend.services.retrieval import RetrievalIndex, STORAGE


CASES = [
    ("ce_prerequisite", "ما متطلبات 10221115 في الحاسوب خطة 2021-1؟", "evidence", "computer_engineering", "zajel_10636_2021_1_course_10221115:chunk:001"),
    ("medicine_course", "ما متطلبات 10231214 في الطب خطة 2025-1؟", "evidence", "medicine", "zajel_10702_2025_1_course_10231214:chunk:001"),
    ("sports_course", "ما متطلبات 10531320 في التربية الرياضية؟", "evidence", "physical_education", "zajel_11350_2025_1_course_10531320:chunk:001"),
    ("vehicle_course", "ما مساق 10620422 في المركبات؟", "evidence", "vehicle_engineering", "vehicle_10624_2026_1_course_10620422:chunk:001"),
    ("ce_total", "كم مجموع ساعات الحاسوب خطة 2021-1؟", "evidence", "computer_engineering", "zajel_10636_2021_1:program_summary"),
    ("medicine_total", "كم ساعات الطب خطة 2025-1؟", "evidence", "medicine", "zajel_10702_2025_1:program_summary"),
    ("sports_total", "كم مجموع ساعات الرياضة؟", "evidence", "physical_education", "zajel_11350_2025_1:program_summary"),
    ("vehicle_total", "كم ساعات المركبات خطة 2026-1؟", "evidence", "vehicle_engineering", "najah_vehicle_plan_2026_1_user_screenshots_extract:program_summary"),
    ("arabic_digits", "ما متطلبات ١٠٢٢١١١٥ في الحاسوب خطة ٢٠٢١-١؟", "evidence", "computer_engineering", "zajel_10636_2021_1_course_10221115:chunk:001"),
    ("persian_digits", "ما متطلبات ۱۰۲۲۱۱۱۵ في الحاسوب؟", "evidence", "computer_engineering", "zajel_10636_2021_1_course_10221115:chunk:001"),
    ("colloquial", "شو بدها 10221115 في الحاسوب؟", "evidence", "computer_engineering", "zajel_10636_2021_1_course_10221115:chunk:001"),
    ("ambiguous_code", "شو بدها 10211102؟", "needs_clarification", None, None),
    ("ambiguous_name", "ما متطلبات تفاضل وتكامل 2؟", "needs_clarification", None, None),
    ("unsupported_academic", "ما متطلبات مساق 99999999 في الحاسوب؟", "insufficient_evidence", "computer_engineering", None),
    ("vehicle_prerequisites", "شو بدها 10620422 في المركبات؟", "insufficient_evidence", "vehicle_engineering", None),
    ("vehicle_electives", "ما خيارات الاختياري في المركبات؟", "insufficient_evidence", "vehicle_engineering", None),
    ("unknown_plan", "كم ساعات الحاسوب خطة 2025-1؟", "insufficient_evidence", "computer_engineering", None),
    ("medicine_stage", "ما شروط التسجيل في الطب؟", "needs_clarification", "medicine", None),
    ("unrelated", "اكتب وصفة كعكة شوكولاتة", "out_of_scope", None, None),
    ("unsupported_named_program", "ما رسوم دراسة هندسة الطيران؟", "insufficient_evidence", None, None),
    ("clinical_guide_bm25", "ما الحد الأعلى للعبء الدراسي في المرحلة السريرية في الطب؟", "evidence", "medicine", "najah_student_guide_2026_2027:page:099:chunk:001"),
    ("unknown_semester", "كم ساعات الحاسوب خطة 2021-3؟", "insufficient_evidence", "computer_engineering", None),
    ("partial_plan", "كم ساعات الحاسوب خطة 2020؟", "needs_clarification", "computer_engineering", None),
]


def main():
    index = RetrievalIndex(ROOT, STORAGE)
    outcomes = []
    for name, question, expected_status, program, chunk_id in CASES:
        result = index.search(question)
        ids = [h["chunk"]["chunk_id"] for h in result.hits]
        passed = result.status == expected_status and result.program_id == program
        if chunk_id:
            passed = passed and bool(ids) and ids[0] == chunk_id
            assert all(h["chunk"].get("program_id") in {None, program} for h in result.hits)
        outcomes.append({"name": name, "question": question, "expected_status": expected_status,
                         "actual_status": result.status, "expected_top_chunk_id": chunk_id,
                         "actual_chunk_ids": ids, "passed": bool(passed)})
        print(("PASS" if passed else "FAIL") + f": {name}: {result.status}: {ids[:2]}")
    atomic_write(STORAGE / "retrieval_checks.json", encode_json(outcomes))
    assert all(row["passed"] for row in outcomes), "See storage/retrieval_checks.json"
    original_rows = {row["id"]: row for row in
                     (json.loads(l) for l in (ROOT / "data/data/knowledge/courses.jsonl").read_text(encoding="utf-8").splitlines())}
    for course in index.courses:
        assert course["citation"] == original_rows[course["id"]]["citation"]
        assert course["prerequisite_expression_raw"] == original_rows[course["id"]]["prerequisite_expression_raw"]
    assert index.programs["computer_engineering"]["total_required_credits"] == 162
    assert "162" in index.programs["computer_engineering"]["citation"]["quote"]
    followup = index.search("شو بدها 10211102؟", [HistoryMessage(role="user", content="أنا في الحاسوب خطة 2021-1")])
    assert followup.status == "evidence" and followup.program_id == "computer_engineering"
    reference = index.search("شو متطلبها؟", [HistoryMessage(role="user", content="ما مساق 10221115 في الحاسوب؟")])
    assert reference.hits[0]["chunk"]["course_code"] == "10221115"
    assert index.search("اكتب وصفة كعكة شوكولاتة", [HistoryMessage(role="user", content="أنا في الحاسوب")]).status == "out_of_scope"
    assistant_only = index.search("شو بدها 10211102؟", [HistoryMessage(role="assistant", content="أنت في الحاسوب")])
    assert assistant_only.status == "needs_clarification"
    result = index.search(CASES[0][1])
    context, sources = evidence_context(result, 6000)
    assert sources and len(context.encode("utf-8")) <= 6000
    assert not evidence_context(result, 10)[1]
    expression = sources["S1"]["prerequisite_expression_raw"]
    valid = {"status": "answered", "answer": f"هندسة الحاسوب، خطة 2021-1: {expression} [S1]", "cited_source_ids": ["S1"]}
    status, text, citations = validate_answer(json.dumps(valid, ensure_ascii=False), sources, index, CASES[0][1])
    assert status == "answered" and citations[0].page is None
    bad_outputs = ["not JSON", "{}", json.dumps({**valid, "cited_source_ids": ["S999"]}),
                   json.dumps({**valid, "answer": "ادعاء [S999]"}),
                   json.dumps({**valid, "answer": "لا يوجد متطلب [S1]"}),
                   json.dumps({**valid, "answer": valid["answer"].replace("أو", "و")}),
                   json.dumps({**valid, "answer": valid["answer"] + " [R99]"}),
                   json.dumps({**valid, "answer": valid["answer"] + "\nادعاء بلا مصدر"}),
                   json.dumps({**valid, "filename": "invented.pdf"}),
                   json.dumps({**valid, "answer": valid["answer"] + " 9876543210"})]
    for raw in bad_outputs:
        try:
            validate_answer(raw, sources, index, CASES[0][1])
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid model output accepted")

    # API requests use ASGI in-process; prevent configuration from reading the real .env.
    with patch("dotenv.load_dotenv", return_value=False), patch.dict(os.environ, {"GROQ_API_KEY": "local-test", "CORS_ORIGINS": "http://localhost:5173"}):
        from fastapi.testclient import TestClient
        from backend.config import get_settings
        from backend.main import app
        from groq import APITimeoutError, APIStatusError
        import httpx
        get_settings.cache_clear()
        with patch("backend.services.rag.generate_grounded", return_value=json.dumps(valid, ensure_ascii=False)) as generated:
            with TestClient(app, raise_server_exceptions=False) as client:
                health = client.get("/api/health").json()
                assert health["index_ready"] and health["documents_count"] == 5 and health["chunks_count"] == 545
                response = client.post("/api/chat", json={"question": CASES[0][1]})
                assert response.status_code == 200, response.text
                data = response.json()
                assert data["status"] == "answered" and data["citations"][0]["quote"] == sources["S1"]["citation"]["quote"]
                assert data["request_id"] == response.headers["X-Request-ID"]
                for case in (CASES[11], CASES[13], CASES[14], CASES[18]):
                    generated.reset_mock()
                    response = client.post("/api/chat", json={"question": case[1]})
                    assert response.json()["status"] == case[2]
                    generated.assert_not_called()
                generated.return_value = "not JSON"
                assert client.post("/api/chat", json={"question": CASES[0][1]}).json()["status"] == "insufficient_evidence"
                docs = client.get("/api/documents").json()["documents"]
                assert len(docs) == 5 and sum(d["page_count"] is None for d in docs) == 3
                download = client.get("/api/documents/zajel_10636_2021_1/file")
                assert download.status_code == 200 and "attachment" in download.headers["Content-Disposition"]
                assert download.content == (ROOT / "data/data/raw/computer_engineering_10636_2021_1.htm").read_bytes()
                assert client.get("/api/documents/..%2F.env/file").status_code == 404
                assert client.post("/api/chat", json={"question": " "}).status_code == 422
                with patch("backend.api.routes.get_index", return_value=None):
                    unready = client.get("/api/health").json()
                    assert unready["index_ready"] is False and unready["chunks_count"] == 545
                    assert len(client.get("/api/documents").json()["documents"]) == 5
                    assert client.post("/api/chat", json={"question": "سؤال"}).status_code == 503
                req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
                for error, http_status, code in (
                    (APITimeoutError(request=req), 504, "LLM_TIMEOUT"),
                    (APIStatusError("secret-provider-error", response=httpx.Response(429, request=req), body=None), 429, "LLM_RATE_LIMIT"),
                    (APIStatusError("secret-provider-error", response=httpx.Response(500, request=req), body=None), 502, "LLM_UNAVAILABLE"),
                ):
                    generated.side_effect = error
                    failure = client.post("/api/chat", json={"question": CASES[0][1]})
                    assert failure.status_code == http_status and failure.json()["error"]["code"] == code
                    assert "secret-provider-error" not in failure.text and str(ROOT) not in failure.text
        get_settings.cache_clear()

    with TemporaryDirectory() as directory:
        fixture = Path(directory)
        shutil.copytree(ROOT / "data/data", fixture / "data/data")
        shutil.copytree(STORAGE, fixture / "storage", ignore=shutil.ignore_patterns("*.tmp"))
        source = fixture / "data/data/raw/computer_engineering_10636_2021_1.htm"
        from backend.services import retrieval
        with patch.object(retrieval, "PROJECT_ROOT", fixture), patch.object(retrieval, "STORAGE", fixture / "storage"):
            retrieval._cached_index.cache_clear()
            assert retrieval.get_index() is not None
            knowledge = fixture / "data/data/knowledge/courses.jsonl"
            original = knowledge.read_bytes()
            knowledge.write_bytes(original + b"\n")
            assert retrieval.get_index() is None, "Changed knowledge records were accepted"
            knowledge.write_bytes(original)
            assert retrieval.get_index() is not None
            source.write_bytes(source.read_bytes() + b" ")
            assert retrieval.get_index() is None, "Changed source was accepted by the cached loader"
            retrieval._cached_index.cache_clear()
    print(f"PASS: {len(outcomes)} retrieval cases; raw prerequisites/quotes, history scope, output validation, API, downloads, upstream errors and stale-source rejection; no live provider requests.")


if __name__ == "__main__":
    main()
