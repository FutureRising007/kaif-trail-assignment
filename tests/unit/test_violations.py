import unittest
from datetime import date

from claims_engine.config import RulesConfig
from claims_engine.violations import detect_violations
from tests.unit.test_rules import item, ship


def codes(vs):
    return [v.code for v in vs]


class TestDetectViolations(unittest.TestCase):
    def setUp(self):
        self.cfg = RulesConfig()

    def test_clean_claim_has_no_violations(self):
        self.assertEqual(detect_violations(item(), ship(), self.cfg), [])

    def test_late_is_sop_1(self):
        vs = detect_violations(item(), ship(delivered=date(2026, 11, 2)), self.cfg)
        self.assertEqual(codes(vs), ["LATE"])
        self.assertEqual(vs[0].sop_ref, "SOP §1 Time limit")
        self.assertIn("8 days", vs[0].detail)

    def test_key_account_window_is_not_a_violation(self):
        s = ship(customer="Zenith Retail", delivered=date(2026, 10, 29))  # 12 days, 15-day window
        self.assertEqual(detect_violations(item(), s, self.cfg), [])

    def test_missing_photo_is_sop_2(self):
        vs = detect_violations(item(photo=False), ship(), self.cfg)
        self.assertEqual(codes(vs), ["NO_PHOTO"])
        self.assertEqual(vs[0].sop_ref, "SOP §2 Evidence")

    def test_photo_not_required_for_shortage(self):
        s = ship(pieces=25, declared=30000, remarks="20 received")
        self.assertEqual(detect_violations(item(ctype="shortage", amount=7500, photo=False), s, self.cfg), [])

    def test_clean_pod_damage_is_sop_3(self):
        s = ship(status="Signed - received in good condition", remarks="")
        self.assertEqual(codes(detect_violations(item(amount=12000), s, self.cfg)), ["POD_CLEAN"])

    def test_full_count_shortage_is_sop_3(self):
        s = ship(pieces=12, status="Signed - received in good condition", remarks="12 pieces received")
        vs = detect_violations(item(ctype="shortage", amount=30000, photo=False), s, self.cfg)
        self.assertEqual(codes(vs), ["POD_FULL_COUNT"])
        self.assertEqual(vs[0].sop_ref, "SOP §3 Proof of delivery")

    def test_shortage_not_on_pod_is_sop_4(self):
        vs = detect_violations(item(ctype="shortage", amount=7500, photo=False),
                               ship(remarks="outer carton damaged"), self.cfg)
        self.assertEqual(codes(vs), ["POD_NO_SHORTAGE"])
        self.assertEqual(vs[0].sop_ref, "SOP §4 Shortage")

    def test_over_declared_is_sop_5(self):
        vs = detect_violations(item(amount=30000), ship(declared=26000), self.cfg)
        self.assertEqual(codes(vs), ["OVER_DECLARED"])
        self.assertEqual(vs[0].sop_ref, "SOP §5 Maximum payout")

    def test_over_limit_is_sop_6(self):
        vs = detect_violations(item(amount=58000), ship(declared=120000), self.cfg)
        self.assertEqual(codes(vs), ["OVER_LIMIT"])
        self.assertEqual(vs[0].sop_ref, "SOP §6 Approval limit")

    def test_over_limit_judged_after_cap(self):
        # claim 60k, declared 45k -> payable 45k is under the limit: only §5
        vs = detect_violations(item(amount=60000), ship(declared=45000), self.cfg)
        self.assertEqual(codes(vs), ["OVER_DECLARED"])

    def test_two_violations_reported_together(self):
        vs = detect_violations(item(amount=95000), ship(declared=72000), self.cfg)
        self.assertEqual(codes(vs), ["OVER_DECLARED", "OVER_LIMIT"])

    def test_late_and_no_photo(self):
        vs = detect_violations(item(amount=2000, photo=False), ship(delivered=date(2026, 11, 2)), self.cfg)
        self.assertEqual(codes(vs), ["LATE", "NO_PHOTO"])


if __name__ == "__main__":
    unittest.main()
