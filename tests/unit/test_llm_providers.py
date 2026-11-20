import json
import unittest
from types import SimpleNamespace

from claims_engine.config import RulesConfig
from claims_engine.llm_providers import (
    FallbackReviewer,
    GeminiReviewer,
    OpenAIReviewer,
    build_reviewer_chain,
)
from claims_engine.llm_reviewer import LLMVerdict, NullReviewer
from tests.unit.test_llm_reviewer import SOP, case

GOOD = {"decision": "escalate", "sop_refs": ["SOP §6 Approval limit"], "rationale": "over 50k"}


class StubOpenAI:
    def __init__(self, payload=GOOD, status="completed", raises=None):
        self.payload, self.status, self.raises, self.calls = payload, status, raises, []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        text = json.dumps(self.payload) if isinstance(self.payload, dict) else self.payload
        return SimpleNamespace(status=self.status, output_text=text)


class StubGemini:
    def __init__(self, payload=GOOD, raises=None):
        self.payload, self.raises, self.calls = payload, raises, []
        self.models = SimpleNamespace(generate_content=self._gen)

    def _gen(self, **kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        text = json.dumps(self.payload) if isinstance(self.payload, dict) else self.payload
        return SimpleNamespace(text=text)


class FixedReviewer:
    def __init__(self, verdict):
        self.verdict, self.calls = verdict, 0

    def review(self, c):
        self.calls += 1
        return self.verdict


class TestOpenAIReviewer(unittest.TestCase):
    def test_parses_verdict_and_tags_provider(self):
        v = OpenAIReviewer(SOP, RulesConfig(), client=StubOpenAI(), model="m1").review(case())
        self.assertEqual((v.decision, v.sop_refs, v.provider), ("escalate", ["SOP §6 Approval limit"], "openai:m1"))

    def test_request_uses_strict_json_schema(self):
        client = StubOpenAI()
        OpenAIReviewer(SOP, RulesConfig(), client=client, model="m1").review(case())
        req = client.calls[0]
        self.assertEqual(req["model"], "m1")
        self.assertIn("Claims must be filed within 7 days", req["instructions"])
        self.assertIn("SHP-1", req["input"])
        fmt = req["text"]["format"]
        self.assertEqual((fmt["type"], fmt["strict"]), ("json_schema", True))
        self.assertTrue(fmt["name"])
        self.assertEqual(fmt["schema"]["additionalProperties"], False)

    def test_incomplete_response_returns_none(self):
        self.assertIsNone(OpenAIReviewer(SOP, RulesConfig(), client=StubOpenAI(status="incomplete")).review(case()))

    def test_error_returns_none(self):
        client = StubOpenAI(raises=RuntimeError("429"))
        self.assertIsNone(OpenAIReviewer(SOP, RulesConfig(), client=client).review(case()))

    def test_invalid_decision_returns_none(self):
        client = StubOpenAI({"decision": "yes", "sop_refs": [], "rationale": ""})
        self.assertIsNone(OpenAIReviewer(SOP, RulesConfig(), client=client).review(case()))


class TestGeminiReviewer(unittest.TestCase):
    def test_parses_verdict_and_tags_provider(self):
        v = GeminiReviewer(SOP, RulesConfig(), client=StubGemini(), model="g1").review(case())
        self.assertEqual((v.decision, v.provider), ("escalate", "gemini:g1"))

    def test_request_uses_json_schema_and_system_instruction(self):
        client = StubGemini()
        GeminiReviewer(SOP, RulesConfig(), client=client, model="g1").review(case())
        req = client.calls[0]
        self.assertEqual(req["model"], "g1")
        self.assertIn("SHP-1", req["contents"])
        cfg = req["config"]
        self.assertEqual(cfg["response_mime_type"], "application/json")
        self.assertIn("decision", cfg["response_json_schema"]["properties"])
        self.assertIn("Claims must be filed", cfg["system_instruction"])

    def test_bad_json_returns_none(self):
        self.assertIsNone(GeminiReviewer(SOP, RulesConfig(), client=StubGemini("oops")).review(case()))

    def test_error_returns_none(self):
        client = StubGemini(raises=RuntimeError("quota"))
        self.assertIsNone(GeminiReviewer(SOP, RulesConfig(), client=client).review(case()))


class TestFallbackReviewer(unittest.TestCase):
    def test_primary_answer_used_and_fallback_not_called(self):
        a, b = FixedReviewer(LLMVerdict("approve", [], "", "openai")), FixedReviewer(LLMVerdict("reject", [], ""))
        v = FallbackReviewer([a, b]).review(case())
        self.assertEqual((v.decision, a.calls, b.calls), ("approve", 1, 0))

    def test_falls_back_when_primary_fails(self):
        a, b = FixedReviewer(None), FixedReviewer(LLMVerdict("reject", [], "", "gemini"))
        v = FallbackReviewer([a, b]).review(case())
        self.assertEqual((v.decision, v.provider, b.calls), ("reject", "gemini", 1))

    def test_all_fail_returns_none(self):
        self.assertIsNone(FallbackReviewer([FixedReviewer(None), FixedReviewer(None)]).review(case()))

    def test_openai_then_gemini_end_to_end(self):
        primary = OpenAIReviewer(SOP, RulesConfig(), client=StubOpenAI(raises=RuntimeError("down")), model="o")
        backup = GeminiReviewer(SOP, RulesConfig(), client=StubGemini(), model="g")
        self.assertEqual(FallbackReviewer([primary, backup]).review(case()).provider, "gemini:g")


class TestBuildReviewerChain(unittest.TestCase):
    def test_no_keys_gives_null_reviewer(self):
        reviewer, status = build_reviewer_chain(["openai", "gemini"], SOP, RulesConfig(), env={})
        self.assertIsInstance(reviewer, NullReviewer)
        self.assertIn("no API key", status)

    def test_skips_provider_without_key(self):
        reviewer, status = build_reviewer_chain(["openai", "gemini"], SOP, RulesConfig(),
                                                env={"GEMINI_API_KEY": "k"})
        self.assertIsInstance(reviewer, FallbackReviewer)
        self.assertEqual([r.name for r in reviewer.reviewers], ["gemini"])
        self.assertIn("openai: skipped", status)

    def test_order_is_openai_then_gemini(self):
        reviewer, status = build_reviewer_chain(["openai", "gemini"], SOP, RulesConfig(),
                                                env={"OPENAI_API_KEY": "k", "GOOGLE_API_KEY": "k"})
        self.assertEqual([r.name for r in reviewer.reviewers], ["openai", "gemini"])

    def test_model_override_from_env(self):
        reviewer, _ = build_reviewer_chain(["openai"], SOP, RulesConfig(),
                                           env={"OPENAI_API_KEY": "k", "OPENAI_MODEL": "custom-1"})
        self.assertEqual(reviewer.reviewers[0].model, "custom-1")

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            build_reviewer_chain(["mystery"], SOP, RulesConfig(), env={})


if __name__ == "__main__":
    unittest.main()
