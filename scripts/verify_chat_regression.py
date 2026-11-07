"""Offline regressions for the browser's explicit plan-total question."""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import Settings
from backend.schemas import ChatRequest, HistoryMessage
from backend.services import rag
from backend.services.llm import IncompleteCompletionError, generate_grounded
from backend.services.retrieval import get_index

QUESTION = "كم مجموع ساعات الحاسوب خطة 2021-1؟"


class ChatRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = get_index()
        assert cls.index is not None
        cls.result = cls.index.search(QUESTION)
        _, cls.sources = rag.evidence_context(cls.result, 6000)
        cls.summary = cls.sources["S1"]
        cls.settings = Settings("LOCAL_TEST_KEY", "local-test-model", 30, ("http://localhost:5173",))

    def model_answer(self, text=None, ids=None):
        return json.dumps({
            "status": "answered",
            "answer": text or f"خطة {self.summary['plan_version']}: المجموع {self.summary['total_required_credits']} ساعة [S1].",
            "cited_source_ids": ["S1"] if ids is None else ids,
        }, ensure_ascii=False)

    def test_explicit_scope_beats_conflicting_history(self):
        for history in ([], [HistoryMessage(role="user", content="أنا في الطب خطة 2025-1")],
                        [HistoryMessage(role="user", content="أنا في الحاسوب خطة 2020-1")]):
            result = self.index.search(QUESTION, history)
            self.assertEqual((result.status, result.program_id, result.plan_version),
                             ("evidence", "computer_engineering", "2021-1"))
            self.assertEqual(result.hits[0]["chunk"]["chunk_type"], "program_summary")

    def test_source_backed_credit_groups(self):
        groups = "، ".join(f"{g['name_ar']}: {g['required_credits']}" for g in self.summary["credit_groups"])
        text = f"خطة {self.summary['plan_version']}: المجموع {self.summary['total_required_credits']} ساعة؛ {groups} [S1]."
        status, _, citations = rag.validate_answer(self.model_answer(text), self.sources, self.index, QUESTION)
        self.assertEqual(status, "answered")
        self.assertIsNone(citations[0].page)
        self.assertEqual(citations[0].quote, self.summary["citation"]["quote"])

    def test_citation_formatting(self):
        for marker in ("[ S1 ]", "[s1]", "[S١]", "[S1, S2]", "[S1، S2]"):
            with self.subTest(marker=marker):
                ids = ["S1", "S2"] if "S2" in marker else ["S1"]
                text = json.loads(self.model_answer())["answer"].replace("[S1]", marker)
                status, answer, citations = rag.validate_answer(self.model_answer(text, ids), self.sources, self.index, QUESTION)
                self.assertEqual(status, "answered")
                self.assertIn("[S1]", answer)
                self.assertEqual([c.source_id for c in citations], ids)

    def test_unsupported_claims_still_rejected(self):
        base = json.loads(self.model_answer())
        for updates in ({"answer": base["answer"] + " 9876543210"},
                        {"answer": base["answer"] + "\nادعاء بلا مصدر"},
                        {"answer": base["answer"].replace("[S1]", "[S999]")},
                        {"answer": base["answer"].replace("[S1]", "[R99]")},
                        {"cited_source_ids": ["S1", "S1"]},
                        {"source_ids": ["S1"]}):
            with self.subTest(fields=list(updates)):
                with self.assertRaises(ValueError):
                    rag.validate_answer(json.dumps({**base, **updates}, ensure_ascii=False), self.sources, self.index, QUESTION)
        # Conflict metadata inside S1 never substitutes for citing the conflicting document S2.
        conflict = self.summary["known_conflicts"][0]["guide_summary_value"]
        with self.assertRaises(ValueError):
            rag.validate_answer(self.model_answer(f"إجمالي الدليل {conflict} [S1]."), self.sources, self.index, QUESTION)

    def test_unsupported_questions_never_call_provider(self):
        for question in ("ما رسوم دراسة هندسة الطيران؟", "شو بدها 10620422 في المركبات؟"):
            with patch.object(rag, "generate_grounded", side_effect=AssertionError("Unexpected provider call")):
                status, _, citations = rag.answer(ChatRequest(question=question), self.index, self.settings)
                self.assertEqual((status, citations), ("insufficient_evidence", []))

    def test_rejection_logs_only_reason_and_request_id(self):
        for raw, reason in ((self.model_answer("ادعاء غير مسند 9876543210 [S1]."), "ANSWER_NUMBER_UNSUPPORTED"),
                            ('{"answer":"FULL_PROMPT_SENTINEL"}', "MODEL_SCHEMA_INVALID"),
                            ("not JSON FULL_PROMPT_SENTINEL", "MODEL_JSON_INVALID")):
            with self.subTest(reason=reason), patch.object(rag, "generate_grounded", return_value=raw):
                with self.assertLogs(rag.logger, level="WARNING") as captured:
                    status, _, _ = rag.answer(ChatRequest(question=QUESTION), self.index, self.settings, request_id="local-request")
                self.assertEqual(status, "insufficient_evidence")
                log = " ".join(captured.output)
                self.assertIn(f"reason={reason}", log)
                self.assertIn("request_id=local-request", log)
                for secret in ("FULL_PROMPT_SENTINEL", self.settings.groq_api_key, QUESTION, raw):
                    self.assertNotIn(secret, log)

    def test_incomplete_provider_response_is_an_error(self):
        from types import SimpleNamespace
        for choices in ([], [SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="partial"))],
                        [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=None))],
                        [SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="   "))]):
            with self.subTest(choices=len(choices)), patch("backend.services.llm.Groq") as sdk:
                sdk.return_value.__enter__.return_value.chat.completions.create.return_value = SimpleNamespace(choices=choices)
                with self.assertRaises(IncompleteCompletionError):
                    generate_grounded(self.settings, [])

    def test_degraded_api_and_html_download(self):
        with patch("dotenv.load_dotenv", return_value=False), patch.dict(os.environ, {
            "GROQ_API_KEY": "LOCAL_TEST_KEY", "CORS_ORIGINS": "http://localhost:5173",
        }):
            from fastapi.testclient import TestClient
            from backend.config import get_settings
            from backend.main import app
            get_settings.cache_clear()
            with patch.object(rag, "generate_grounded", return_value=self.model_answer()) as generated:
                with TestClient(app, raise_server_exceptions=False) as client:
                    health = client.get("/api/health").json()
                    self.assertEqual((health["status"], health["index_ready"]), ("degraded", True))
                    response = client.post("/api/chat", json={"question": QUESTION, "history": [
                        {"role": "user", "content": "أنا في الطب خطة 2025-1"},
                    ]})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["status"], "answered")
                    citation = response.json()["citations"][0]
                    self.assertIsNone(citation["page"])
                    download = client.get(f"/api/documents/{citation['document_id']}/file")
                    self.assertEqual(download.status_code, 200)
                    self.assertIn("attachment", download.headers["Content-Disposition"])
                    payload = json.loads(generated.call_args.args[1][1]["content"])
                    self.assertEqual((payload["question"], payload["resolved_program_id"], payload["resolved_plan_version"]),
                                     (QUESTION, "computer_engineering", "2021-1"))
                    self.assertNotIn("history", payload)
                    generated.side_effect = IncompleteCompletionError("COMPLETION_INCOMPLETE")
                    failure = client.post("/api/chat", json={"question": QUESTION})
                    self.assertEqual(failure.status_code, 502)
                    self.assertEqual(failure.json()["error"]["code"], "LLM_UNAVAILABLE")
                    self.assertNotIn("status", failure.json())
            get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
