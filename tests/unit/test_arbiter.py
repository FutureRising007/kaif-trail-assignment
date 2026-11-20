import unittest
from datetime import date

from claims_engine.arbiter import adjudicate
from claims_engine.config import RulesConfig
from claims_engine.llm_reviewer import LLMVerdict
from claims_engine.models import PastDecision
from tests.unit.test_rules import item, ship


class FakeReviewer:
    def __init__(self, decision="need_info", refs=None, rationale="fake"):
        self.verdict = None if decision is None else LLMVerdict(decision, refs or [], rationale)
        self.calls = 0

    def review(self, case):
        self.calls += 1
        return self.verdict


class ArbiterBase(unittest.TestCase):
    def setUp(self):
        self.cfg = RulesConfig()

    def adj(self, it, shp, reviewer, past=None):
        return adjudicate(it, "email text", [], {shp.shipment_id: shp}, past or {}, set(), self.cfg, reviewer)


class TestPrechecksSkipLLM(ArbiterBase):
    def test_not_a_claim_no_llm_call(self):
        r = FakeReviewer("approve")
        d, audit = self.adj(item(is_claim=False, ctype=None, amount=None), ship(), r)
        self.assertEqual(d.decision, "not_a_claim")
        self.assertEqual((r.calls, audit.path), (0, "precheck"))

    def test_duplicate_no_llm_call(self):
        r = FakeReviewer("approve")
        past = {"SHP-1": PastDecision("C-1", "SHP-1", "approved", 100, "")}
        d, audit = self.adj(item(), ship(), r, past)
        self.assertEqual((d.decision, r.calls), ("duplicate", 0))


class TestNoViolation(ArbiterBase):
    def test_clean_claim_decided_by_code_only(self):
        r = FakeReviewer("reject")
        d, audit = self.adj(item(), ship(), r)
        self.assertEqual((d.decision, d.approved_amount_inr), ("approve", 18000))
        self.assertEqual((r.calls, audit.path), (0, "no_violation"))


class TestSingleViolation(ArbiterBase):
    def over_limit(self):
        return item(amount=58000), ship(declared=120000)

    def test_llm_agrees(self):
        r = FakeReviewer("escalate", ["SOP §6 Approval limit"])
        d, audit = self.adj(*self.over_limit(), r)
        self.assertEqual(d.decision, "escalate")
        self.assertEqual((r.calls, audit.path, audit.agreement), (1, "single_violation", "agree"))

    def test_llm_disagrees_code_wins_and_team_alerted(self):
        r = FakeReviewer("approve")
        d, audit = self.adj(*self.over_limit(), r)
        self.assertEqual(d.decision, "escalate")
        self.assertEqual((audit.code_decision, audit.llm_decision, audit.agreement),
                         ("escalate", "approve", "disagree"))
        self.assertTrue(any("LLM" in a and "code decision kept" in a for a in d.alerts))

    def test_llm_unavailable_code_decides(self):
        d, audit = self.adj(*self.over_limit(), FakeReviewer(None))
        self.assertEqual(d.decision, "escalate")
        self.assertEqual(audit.agreement, "llm_unavailable")

    def test_late_reject(self):
        d, _ = self.adj(item(), ship(delivered=date(2026, 11, 2)), FakeReviewer("reject"))
        self.assertEqual(d.decision, "reject")

    def test_goodwill_with_missing_photo_still_code_decision(self):
        d, audit = self.adj(item(amount=3200, photo=False), ship(), FakeReviewer("approve"))
        self.assertEqual((d.decision, d.approved_amount_inr), ("approve", 3200))
        self.assertEqual(audit.violations, ["SOP §2 Evidence"])


class TestMultipleViolations(ArbiterBase):
    def two(self):
        return item(amount=95000), ship(declared=72000)  # §5 + §6

    def test_marked_need_info_with_sop_references(self):
        r = FakeReviewer("need_info", ["SOP §5 Maximum payout", "SOP §6 Approval limit"])
        d, audit = self.adj(*self.two(), r)
        self.assertEqual((d.decision, d.approved_amount_inr), ("need_info", 0))
        self.assertIn("SOP §5 Maximum payout", d.reason)
        self.assertIn("SOP §6 Approval limit", d.reason)
        self.assertIn("SOP §5", d.draft_reply)
        self.assertEqual((r.calls, audit.path, audit.agreement), (1, "multi_violation", "agree"))

    def test_llm_cannot_approve_multi_violation(self):
        d, audit = self.adj(*self.two(), FakeReviewer("approve"))
        self.assertEqual((d.decision, d.approved_amount_inr), ("need_info", 0))
        self.assertEqual(audit.agreement, "disagree")

    def test_llm_unavailable_still_need_info(self):
        d, _ = self.adj(*self.two(), FakeReviewer(None))
        self.assertEqual(d.decision, "need_info")

    def test_late_plus_no_photo_even_if_small(self):
        d, _ = self.adj(item(amount=2000, photo=False), ship(delivered=date(2026, 11, 2)), FakeReviewer(None))
        self.assertEqual(d.decision, "need_info")
        self.assertIn("SOP §1 Time limit", d.reason)
        self.assertIn("SOP §2 Evidence", d.reason)

    def test_team_alerted(self):
        d, _ = self.adj(*self.two(), FakeReviewer(None))
        self.assertTrue(any("Multiple SOP violations" in a for a in d.alerts))


if __name__ == "__main__":
    unittest.main()
