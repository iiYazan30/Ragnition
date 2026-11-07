"""Offline catalog, profile-context and chat contract checks using the actual bundle."""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services import rag
from backend.services.ingestion import TARGETS
from backend.services.retrieval import get_index


class CatalogContextChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment = patch.dict(os.environ, {"GROQ_API_KEY": "LOCAL_TEST_KEY", "CORS_ORIGINS": "http://localhost:5173"})
        cls.environment.start()
        cls.dotenv = patch("dotenv.load_dotenv", return_value=False)
        cls.dotenv.start()
        cls.provider_guard = patch("backend.services.llm.Groq", side_effect=AssertionError("Unexpected live provider call"))
        cls.provider_guard.start()
        from fastapi.testclient import TestClient
        from backend.config import get_settings
        from backend.main import app
        get_settings.cache_clear()
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.client.__enter__()
        cls.index = get_index()
        assert cls.index is not None

    @classmethod
    def tearDownClass(cls):
        from backend.config import get_settings
        cls.client.__exit__(None, None, None)
        get_settings.cache_clear()
        cls.dotenv.stop()
        cls.provider_guard.stop()
        cls.environment.stop()

    def context(self, pid="computer_engineering"):
        return {"program_id": pid, "plan_version": TARGETS[pid][1], "completed_course_codes": []}

    def test_exactly_four_programs_and_source_rows(self):
        with patch.object(rag, "generate_grounded", side_effect=AssertionError("Unexpected provider call")):
            response = self.client.get("/api/programs")
            self.assertEqual(response.status_code, 200)
            programs = response.json()["programs"]
            self.assertEqual({p["program_id"] for p in programs}, set(TARGETS))
            self.assertEqual(len(programs), 4)
            for program in programs:
                pid = program["program_id"]
                major, version, count, total = TARGETS[pid]
                self.assertEqual((program["major_code"], len(program["plans"])), (major, 1))
                self.assertIsNone(program["faculty_name_ar"])
                plan = program["plans"][0]
                self.assertEqual((plan["plan_version"], plan["course_count"], plan["total_required_credits"]), (version, count, total))
                data = self.client.get(f"/api/programs/{pid}/plans/{version}/courses").json()
                rows = data["courses"]
                self.assertEqual(len(rows), count)
                self.assertEqual(len({c["course_code"] for c in rows}), count)
                source = {c["course_code"]: c for c in self.index.courses if c["program_id"] == pid}
                for row in rows:
                    original = source[row["course_code"]]
                    for key in ("course_name_ar", "credits", "source_locator", "prerequisite_status", "prerequisite_expression_raw"):
                        if key == "source_locator":
                            self.assertEqual({k: row[key][k] for k in original[key]}, original[key])
                        else:
                            self.assertEqual(row[key], original[key])
                    self.assertIn(row["requirement_group_ar"], {g["name_ar"] for g in plan["credit_groups"]})
                    self.assertFalse(row["course_code"].startswith("COMP"))
                self.assertTrue(any(row["credits"] == 0 for row in rows))
                if pid == "vehicle_engineering":
                    self.assertTrue(plan["is_partial"])
                    self.assertTrue(all(row["prerequisite_status"] == "not_provided_for_this_plan" for row in rows))
                    self.assertTrue(all(row["prerequisite_expression_raw"] is None for row in rows))
                    self.assertGreaterEqual(len(plan["coverage_limitations"]), 4)
                self.assertNotIn("relative_path", json.dumps(data))
                self.assertNotIn("sha256", json.dumps(data))
            self.assertEqual(self.client.get("/api/programs/mechanical_engineering/plans/2021-1/courses").status_code, 404)
            self.assertEqual(self.client.get("/api/programs/medicine/plans/2021-1/courses").status_code, 404)

    def test_unavailable_catalog_is_an_api_error(self):
        with patch("backend.api.routes.get_index", return_value=None):
            for path in ("/api/programs", "/api/programs/computer_engineering/plans/2021-1/courses"):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["error"]["code"], "CATALOG_UNAVAILABLE")

    def test_invalid_context_is_rejected_before_generation(self):
        other_code = next(c["course_code"] for c in self.index.courses if c["program_id"] == "medicine"
                          and c["course_code"] not in {r["course_code"] for r in self.index.courses if r["program_id"] == "computer_engineering"})
        for updates in ({"program_id": "mechanical_engineering"}, {"plan_version": "2025-1"},
                        {"completed_course_codes": ["COMP133"]}, {"completed_course_codes": [other_code]},
                        {"completed_course_codes": [True]}, {"user_declared_completed_credits": -1},
                        {"name": "PRIVATE_NAME"}, {"registrationNumber": "PRIVATE_REGISTRATION"}):
            with self.subTest(fields=list(updates)), patch.object(rag, "generate_grounded") as generate:
                response = self.client.post("/api/chat", json={"question": "كم مجموع الساعات؟", "academic_context": {**self.context(), **updates}})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
                self.assertNotIn("PRIVATE_", response.text)
                generate.assert_not_called()

    def test_profile_defaults_explicit_precedence_and_legacy_requests(self):
        cases = [
            ("كم مجموع الساعات؟", self.context(), [], "computer_engineering", True),
            ("كم مجموع ساعات الحاسوب خطة 2021-1؟", self.context("medicine"), [], "computer_engineering", False),
            ("كم مجموع ساعات الحاسوب؟", self.context("medicine"), [], "computer_engineering", False),
            ("كم مجموع ساعات الحاسوب خطة 2021-1؟", None, [], "computer_engineering", False),
            ("كم مجموع الساعات؟", self.context(), [{"role": "user", "content": "أنا في الطب خطة 2025-1"}], "medicine", False),
        ]
        for question, context, history, pid, includes_context in cases:
            with self.subTest(pid=pid, context=context):
                summary = self.index.programs[pid]
                output = json.dumps({"status": "answered", "answer": f"خطة {summary['plan_version']}: {summary['total_required_credits']} ساعة [S1].", "cited_source_ids": ["S1"]}, ensure_ascii=False)
                with patch.object(rag, "generate_grounded", return_value=output) as generate:
                    response = self.client.post("/api/chat", json={"question": question, "history": history, **({"academic_context": context} if context else {})})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["status"], "answered")
                    self.assertIsNone(response.json()["citations"][0]["page"])
                    model_input = json.loads(generate.call_args.args[1][1]["content"])
                    self.assertEqual(model_input["resolved_program_id"], pid)
                    self.assertEqual(model_input["resolved_plan_version"], summary["plan_version"])
                    self.assertEqual("user_declared_context" in model_input, includes_context)
                    self.assertNotIn("history", model_input)
        with patch.object(rag, "generate_grounded") as generate:
            response = self.client.post("/api/chat", json={"question": "كم مجموع الساعات خطة 2025-1؟", "academic_context": self.context()})
            self.assertEqual(response.json()["status"], "insufficient_evidence")
            generate.assert_not_called()  # Keep the explicit unavailable plan; never substitute the profile's plan.
            legacy = self.client.post("/api/chat", json={"question": "كم مجموع الساعات؟"})
            self.assertEqual(legacy.json()["status"], "needs_clarification")

    def test_user_selections_are_context_not_evidence(self):
        code = next(c["course_code"] for c in self.index.courses if c["program_id"] == "computer_engineering")
        context = {**self.context(), "completed_course_codes": [code, code], "user_declared_completed_credits": 75}
        with patch.object(rag, "generate_grounded", return_value="invalid JSON") as generate:
            self.client.post("/api/chat", json={"question": "كم مجموع الساعات؟", "academic_context": context})
            model_input = json.loads(generate.call_args.args[1][1]["content"])
            self.assertEqual(model_input["user_declared_context"]["completed_course_codes"], [code])
            self.assertEqual(model_input["user_declared_context"]["user_declared_completed_credits"], 75)
            self.assertNotIn("user_declared_context", json.dumps(model_input["evidence"]))
            self.assertIn("ليست كشف علامات", generate.call_args.args[1][0]["content"])

    def test_refusals_and_429_are_preserved_with_context(self):
        for question, context in (("ما رسوم دراسة هندسة الطيران؟", self.context()),
                                  ("شو بدها 10620422؟", self.context("vehicle_engineering"))):
            with patch.object(rag, "generate_grounded") as generate:
                response = self.client.post("/api/chat", json={"question": question, "academic_context": context})
                self.assertEqual(response.json()["status"], "insufficient_evidence")
                generate.assert_not_called()
        import httpx
        from groq import APIStatusError
        request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        failure = APIStatusError("PRIVATE_ERROR", response=httpx.Response(429, request=request, headers={"Retry-After": "60"}), body=None)
        with patch.object(rag, "generate_grounded", side_effect=failure):
            response = self.client.post("/api/chat", json={"question": "كم مجموع الساعات؟", "academic_context": self.context()})
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["Retry-After"], "60")
            self.assertEqual(response.json()["error"]["code"], "LLM_RATE_LIMIT")
            self.assertNotIn("status", response.json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
