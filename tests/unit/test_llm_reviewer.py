import json
import unittest
from types import SimpleNamespace

from claims_engine.config import RulesConfig
from claims_engine.llm_reviewer import (
    ClaudeReviewer,
    LLMVerdict,
    NullReviewer,
    ReviewCase,
    build_system_prompt,
    build_user_prompt,
)
from tests.unit.test_rules import item, ship

SOP = "1. **Time limit.** Claims must be filed within 7 days of delivery."


def case(**kw):
    return ReviewCase(item=kw.get("it", item()), shipment=kw.get("shp", ship()),
                      email_text="Shipment SHP-1 crushed. Claiming Rs 18,000.", attachments=["a.jpg"])


class StubClient:
    """Mimics client.beta.messages.create, records the request."""

    def __init__(self, payload=None, stop_reason="end_turn", raises=None):
        self.payload, self.stop_reason, self.raises, self.calls = payload, stop_reason, raises, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        text = json.dumps(self.payload) if isinstance(self.payload, dict) else (self.payload or "")
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=text)])


class TestPrompts(unittest.TestCase):
    def test_system_prompt_has_sop_and_house_rules(self):
        p = build_system_prompt(SOP, RulesConfig())
        self.assertIn("Claims must be filed within 7 days", p)
        self.assertIn("Zenith Retail", p)
        self.assertIn("5,000", p)
        self.assertIn("need_info", p)

    def test_user_prompt_has_facts_but_not_code_decision(self):
        p = build_user_prompt(case())
        for fact in ["SHP-1", "2026-11-10", "2026-11-07", "60,000", "1 box crushed", "a.jpg", "Rs 18,000"]:
            self.assertIn(fact, p)
        self.assertNotIn("R13", p)  # independent review: no code verdict leaked


class TestClaudeReviewer(unittest.TestCase):
    def test_parses_structured_verdict(self):
        client = StubClient({"decision": "escalate", "sop_refs": ["SOP §6 Approval limit"],
                             "rationale": "over 50k"})
        v = ClaudeReviewer(SOP, RulesConfig(), client=client).review(case())
        self.assertEqual(v, LLMVerdict("escalate", ["SOP §6 Approval limit"], "over 50k"))

    def test_request_shape(self):
        client = StubClient({"decision": "approve", "sop_refs": [], "rationale": "ok"})
        ClaudeReviewer(SOP, RulesConfig(), client=client).review(case())
        req = client.calls[0]
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(req["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", req["betas"])
        self.assertNotIn("temperature", req)

    def test_refusal_returns_none(self):
        client = StubClient({"decision": "approve", "sop_refs": [], "rationale": ""}, stop_reason="refusal")
        self.assertIsNone(ClaudeReviewer(SOP, RulesConfig(), client=client).review(case()))

    def test_invalid_decision_returns_none(self):
        client = StubClient({"decision": "maybe", "sop_refs": [], "rationale": ""})
        self.assertIsNone(ClaudeReviewer(SOP, RulesConfig(), client=client).review(case()))

    def test_bad_json_returns_none(self):
        self.assertIsNone(ClaudeReviewer(SOP, RulesConfig(), client=StubClient("not json")).review(case()))

    def test_api_error_returns_none(self):
        client = StubClient(raises=RuntimeError("network down"))
        self.assertIsNone(ClaudeReviewer(SOP, RulesConfig(), client=client).review(case()))


class TestNullReviewer(unittest.TestCase):
    def test_always_none(self):
        self.assertIsNone(NullReviewer().review(case()))


if __name__ == "__main__":
    unittest.main()
