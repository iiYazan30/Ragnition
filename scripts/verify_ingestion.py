"""Offline smoke/regression check against the actual bundle, with isolated outputs."""

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.ingestion import (
    TARGETS, headings, ingest, page_quality, page_spans, read_json,
)


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def expect_rejection(root, output, path, invalid):
    original = path.read_bytes()
    snapshot = {p.name: p.read_bytes() for p in output.iterdir()}
    try:
        path.write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
        try:
            ingest(root, output)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid bundle was accepted")
        assert {p.name: p.read_bytes() for p in output.iterdir()} == snapshot
    finally:
        path.write_bytes(original)


def main():
    socket_connect = socket.socket.connect
    # Neither source inspection nor API checks may open the real .env or use the network.
    with patch("dotenv.load_dotenv", side_effect=AssertionError("Unexpected .env read")), \
         patch("socket.socket.connect", side_effect=AssertionError("Unexpected network call")), \
         TemporaryDirectory() as directory:
        fixture = Path(directory)
        shutil.copytree(ROOT / "data/data", fixture / "data/data")
        output = fixture / "storage"
        report = ingest(fixture, output)
        chunks = jsonl(output / "chunks.jsonl")
        courses = [c for c in chunks if c["chunk_type"] == "course"]
        summaries = [c for c in chunks if c["chunk_type"] == "program_summary"]
        guide = [c for c in chunks if c["chunk_type"] == "guide_page"]
        programs = read_json(output / "programs.json")
        documents = {d["document_id"]: d for d in read_json(output / "documents.json")}
        pages = {p["page"]: p for p in jsonl(output / "guide_pages.jsonl")}
        original = {c["id"]: c for c in jsonl(fixture / "data/data/knowledge/courses.jsonl")}
        assert len(courses) == len({c["id"] for c in courses}) == 372
        assert Counter(c["program_id"] for c in courses) == {k: v[2] for k, v in TARGETS.items()}
        assert len(programs) == 4 and {p["program_id"] for p in programs} == set(TARGETS)
        assert len(summaries) == report["program_summary_chunks_count"] == 4
        assert {c["program_id"] for c in summaries} == set(TARGETS)
        assert next(p for p in programs if p["program_id"] == "physical_education")["major_code"] == "11350"
        assert len(documents) == 5 and len(pages) == 135
        assert report["chunks_count"] == len(chunks) and report["index_ready"] is False
        assert len({c["chunk_id"] for c in chunks}) == len(chunks)
        assert len(guide) == report["guide_chunks_count"]
        for course in courses:
            # All raw fields, especially AND/OR/concurrency and blank statuses, survive unchanged.
            assert all(course[key] == value for key, value in original[course["id"]].items())
            assert isinstance(course["course_code"], str)
            if course["program_id"] == "vehicle_engineering":
                assert course["prerequisite_expression_raw"] is None
                assert course["prerequisite_status"] == "not_provided_for_this_plan"
                assert course["index_as_official"] is False
                assert "transcription" in course["evidence_status"]
        for chunk in chunks:
            citation = chunk["citation"]
            doc = documents[chunk["document_id"]]
            assert citation["document_id"] == doc["document_id"]
            assert citation["filename"] == doc["filename"] and citation["quote"].strip()
            assert "reference_only" not in doc["relative_path"]
            assert (ROOT / doc["relative_path"]).is_file()
            if doc["filename"].endswith(".htm"):
                assert citation["page"] is None and citation["article"]
                if chunk["chunk_type"] == "course":
                    assert chunk["source_locator"]["course_code"] == chunk["course_code"]
                else:
                    assert str(chunk["total_required_credits"]) in citation["quote"]
            else:
                assert type(citation["page"]) is int and 1 <= citation["page"] <= doc["page_count"]
        by_page = defaultdict(list)
        for chunk in guide:
            locator = chunk["source_locator"]
            page = pages[locator["page"]]
            assert page["quality"] == "usable_text_layer"
            assert chunk["citation"]["quote"] == page["text"][locator["char_start"]:locator["char_end"]]
            assert chunk["text"] == chunk["citation"]["quote"]
            assert chunk["plan_version"] is None
            if 93 <= page["page"] <= 110:
                assert chunk["program_id"] == "medicine"
                assert chunk["academic_phase"] == ("biomedical_basic" if page["page"] < 97 else "clinical")
            else:
                assert chunk["program_id"] is None and chunk["academic_phase"] is None
            for heading in chunk["headings"]:
                assert heading["text"] in page["text"]
            by_page[page["page"]].append(chunk)
        assert set(by_page) == {p for p, row in pages.items() if row["quality"] == "usable_text_layer"}
        for page, page_chunks in by_page.items():
            spans = [c["source_locator"] for c in page_chunks]
            assert spans[0]["char_start"] == 0 and spans[-1]["char_end"] == len(pages[page]["text"])
            assert all(a["char_end"] > b["char_start"] for a, b in zip(spans, spans[1:]))
        assert page_quality("") == "empty_or_image_only"
        assert page_quality("An-Najah National University | جامعة النجاح الوطنية\n4") == "header_only"
        assert page_quality("(cid:123) نص غير صالح " * 10) == "corrupt_text"
        assert headings("): الامتحانات والعلامات والمعدلات :7( مادة\n")[0]["text"].endswith("مادة")
        assert not headings("لتقييم مدرس المساق أو لمعدل تقييم مدرسي المادة لأداء الطالب\n")
        for text in ("x" * 5000, ("سطر عربي طويل للاختبار\n" * 200)):
            spans = list(page_spans(text))
            assert spans[0][0] == 0 and spans[-1][1] == len(text)
            assert all(0 <= start < end <= len(text) and end - start <= 1400 for start, end in spans)
            assert all(a[0] < b[0] < a[1] for a, b in zip(spans, spans[1:]))
        for name, checksum in report["artifacts_sha256"].items():
            assert hashlib.sha256((output / name).read_bytes()).hexdigest() == checksum
        before = {p.name: p.read_bytes() for p in output.iterdir()}
        assert ingest(fixture, output) == report
        assert before == {p.name: p.read_bytes() for p in output.iterdir()}

        knowledge = fixture / "data/data/knowledge"
        invalid = read_json(knowledge / "programs.json")
        next(p for p in invalid if p["program_id"] == "physical_education")["major_code"] = "80531"
        expect_rejection(fixture, output, knowledge / "programs.json", invalid)
        invalid = read_json(knowledge / "sources.json")
        invalid[0]["relative_path"] = "../reference_only/mechanical_engineering_10621_2021_1.htm"
        expect_rejection(fixture, output, knowledge / "sources.json", invalid)
        course_path = knowledge / "courses.jsonl"
        original_bytes = course_path.read_bytes()
        invalid = jsonl(course_path)
        next(c for c in invalid if c["program_id"] == "vehicle_engineering")["prerequisite_expression_raw"] = "inferred"
        try:
            course_path.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in invalid), encoding="utf-8")
            try:
                ingest(fixture, output)
            except ValueError as exc:
                assert "Vehicle" in str(exc)
            else:
                raise AssertionError("Inferred vehicle prerequisites were accepted")
            assert before == {p.name: p.read_bytes() for p in output.iterdir()}
        finally:
            course_path.write_bytes(original_bytes)

        # Patch the config loader before importing the application, preserving the public contract.
        with patch("dotenv.load_dotenv", return_value=False), \
             patch("socket.socket.connect", socket_connect), \
             patch("backend.api.routes.get_index", return_value=None), \
             patch.dict("os.environ", {"GROQ_API_KEY": "", "CORS_ORIGINS": "http://localhost:5173"}), \
             patch("groq.Groq", side_effect=AssertionError("Unexpected provider call")):
            from fastapi.testclient import TestClient
            from backend.config import get_settings
            from backend.main import app
            get_settings.cache_clear()
            with TestClient(app) as client:
                health = client.get("/api/health").json()
                assert health["index_ready"] is False and health["status"] == "degraded"
                response = client.post("/api/chat", json={"question": "ما متطلبات التخرج؟"})
                assert response.status_code == 503
                assert response.json()["error"]["code"] == "KNOWLEDGE_NOT_READY"
                assert len(client.get("/api/documents").json()["documents"]) == 5
            get_settings.cache_clear()
    print(f"PASS: 372 courses, 4 programs, 11350 sports, vehicle provenance, valid quotes/locators, "
          f"{len(guide)} guide chunks, byte-identical rebuilds, invalid-input rejection and chat 503; no provider calls/.env reads.")


if __name__ == "__main__":
    main()
