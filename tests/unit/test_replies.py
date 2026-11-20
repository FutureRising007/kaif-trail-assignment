import unittest

from claims_engine.replies import draft_reply


class TestDraftReply(unittest.TestCase):
    def test_approve_states_amount_and_reason(self):
        r = draft_reply("approve", "SHP-1001", 18000, "damage confirmed on POD with photos")
        self.assertIn("SHP-1001", r)
        self.assertIn("approved", r.lower())
        self.assertIn("Rs 18,000", r)
        self.assertIn("damage confirmed on POD with photos", r)

    def test_reject_states_reason(self):
        r = draft_reply("reject", "SHP-1012", 0, "filed 8 days after delivery; limit is 7 days")
        self.assertIn("unable to approve", r.lower())
        self.assertIn("8 days", r)

    def test_need_info(self):
        r = draft_reply("need_info", "SHP-1005", 0, "photos of the damaged goods are required")
        self.assertIn("photos", r)

    def test_escalate_does_not_promise_payment(self):
        r = draft_reply("escalate", "SHP-1013", 58000, "above Rs 50,000 approval limit")
        self.assertNotIn("approved", r.lower())
        self.assertIn("review", r.lower())

    def test_not_a_claim_reply(self):
        r = draft_reply("not_a_claim", "SHP-1016", 0, "request for invoice copy and POD")
        self.assertIn("not a claim", r.lower())

    def test_all_replies_signed(self):
        for d in ["approve", "reject", "need_info", "escalate", "duplicate", "not_a_claim"]:
            self.assertIn("RouteMax Claims Team", draft_reply(d, "SHP-1", 1000, "x"))

    def test_unknown_decision_raises(self):
        with self.assertRaises(ValueError):
            draft_reply("maybe", "SHP-1", 0, "x")


if __name__ == "__main__":
    unittest.main()
