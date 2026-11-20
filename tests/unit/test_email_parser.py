import unittest
from datetime import date

from claims_engine.email_parser import (
    detect_claim_type,
    extract_claims,
    is_claim_email,
    normalize_shipment_id,
    parse_amount,
    parse_email,
)

SINGLE = """From: ops@apexpharma.in
Date: 2026-11-10 09:12
Subject: Damage claim SHP-1001
Attachments: IMG_4410.jpg, IMG_4411.jpg

Hi team,

Shipment SHP-1001 delivered on 7 Nov had one box completely crushed. Claiming Rs 18,000. Photos attached.
"""

NO_ATTACH_BUT_SAYS_ATTACHED = """From: accounts@novatextiles.in
Date: 2026-11-10 11:02
Subject: Claim - SHP-1005 stained rolls
Attachments: none

Two fabric rolls in SHP-1005 were stained on arrival. Claim amount Rs 14,500. Photos attached for your reference.
"""

MULTI = """From: purchase@orbitauto.in
Date: 2026-11-10 15:00
Subject: Two claims - SHP-1014 and SHP-1015
Attachments: scratch1.jpg, scratch2.jpg

Team,

1) SHP-1014: two units scratched, claiming Rs 6,000. Photos attached.
2) SHP-1015: box corner crushed, one part bent, claiming Rs 4,500. No photo, the box was thrown away already.

Vikram, Orbit Auto Parts
"""

NOT_A_CLAIM = """From: qa@sunrisefoods.in
Date: 2026-11-10 15:30
Subject: Invoice copy for SHP-1016
Attachments: none

Can you send us the invoice copy and POD for SHP-1016? Our finance team needs it for month-end.
"""


class TestNormalizeShipmentId(unittest.TestCase):
    def test_letter_o_typed_for_zero(self):
        self.assertEqual(normalize_shipment_id("SHP-1O10"), "SHP-1010")

    def test_lowercase_and_spaces(self):
        self.assertEqual(normalize_shipment_id("shp 1001"), "SHP-1001")

    def test_already_clean(self):
        self.assertEqual(normalize_shipment_id("SHP-0987"), "SHP-0987")


class TestParseAmount(unittest.TestCase):
    def test_with_commas(self):
        self.assertEqual(parse_amount("Claiming Rs 18,000. Photos"), 18000)

    def test_without_commas(self):
        self.assertEqual(parse_amount("need Rs 3200 refund"), 3200)

    def test_with_dot_and_hinglish_suffix(self):
        self.assertEqual(parse_amount("Rs. 7,500 ka claim"), 7500)

    def test_rupee_symbol_and_inr(self):
        self.assertEqual(parse_amount("₹2,000 please"), 2000)
        self.assertEqual(parse_amount("INR 9000"), 9000)

    def test_missing(self):
        self.assertIsNone(parse_amount("no money mentioned"))


class TestDetectClaimType(unittest.TestCase):
    def test_damage_words(self):
        for text in ["box crushed", "cartons dented", "rolls stained", "arrived wet",
                     "units scratched", "roll was torn", "items are damaged"]:
            self.assertEqual(detect_claim_type(text), "damage", text)

    def test_shortage_words(self):
        for text in ["We received only 37 of 40 cartons", "missing 10 units",
                     "shortage claim", "5 boxes kam aaye hain, 25 bheje the 20 hi mile"]:
            self.assertEqual(detect_claim_type(text), "shortage", text)

    def test_shortage_wins_over_damage_when_both(self):
        self.assertEqual(detect_claim_type("Shortage claim, 3 cartons missing, one torn"), "shortage")

    def test_none(self):
        self.assertIsNone(detect_claim_type("please send invoice copy"))


class TestParseEmail(unittest.TestCase):
    def test_headers(self):
        e = parse_email(SINGLE, "C01")
        self.assertEqual(e.claim_id, "C01")
        self.assertEqual(e.sender, "ops@apexpharma.in")
        self.assertEqual(e.filed_date, date(2026, 11, 10))
        self.assertEqual(e.subject, "Damage claim SHP-1001")
        self.assertEqual(e.attachments, ["IMG_4410.jpg", "IMG_4411.jpg"])
        self.assertIn("crushed", e.body)

    def test_attachments_none(self):
        e = parse_email(NO_ATTACH_BUT_SAYS_ATTACHED, "C05")
        self.assertEqual(e.attachments, [])


class TestIsClaimEmail(unittest.TestCase):
    def test_document_request_is_not_claim(self):
        self.assertFalse(is_claim_email(parse_email(NOT_A_CLAIM, "C15")))

    def test_damage_email_is_claim(self):
        self.assertTrue(is_claim_email(parse_email(SINGLE, "C01")))


class TestExtractClaims(unittest.TestCase):
    def test_single_claim(self):
        items = extract_claims(parse_email(SINGLE, "C01"))
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual((it.shipment_id, it.claim_type, it.amount, it.has_photo),
                         ("SHP-1001", "damage", 18000, True))

    def test_text_says_attached_but_no_attachment_means_no_photo(self):
        it = extract_claims(parse_email(NO_ATTACH_BUT_SAYS_ATTACHED, "C05"))[0]
        self.assertFalse(it.has_photo)

    def test_multi_claim_email_split_per_shipment(self):
        items = extract_claims(parse_email(MULTI, "C14"))
        self.assertEqual([i.shipment_id for i in items], ["SHP-1014", "SHP-1015"])
        self.assertEqual([i.amount for i in items], [6000, 4500])
        self.assertEqual([i.has_photo for i in items], [True, False])
        self.assertTrue(all(i.claim_id == "C14" for i in items))

    def test_not_a_claim_email_yields_non_claim_item(self):
        items = extract_claims(parse_email(NOT_A_CLAIM, "C15"))
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].is_claim)
        self.assertEqual(items[0].shipment_id, "SHP-1016")

    def test_consequential_loss_detected(self):
        e = parse_email(SINGLE.replace("Claiming Rs 18,000.",
                                       "Total loss Rs 95,000 including our production downtime."), "C06")
        self.assertTrue(extract_claims(e)[0].consequential_loss)

    def test_follow_up_detected(self):
        e = parse_email(SINGLE.replace("Subject: Damage claim SHP-1001",
                                       "Subject: Re: Claim SHP-1001 - still not paid??"), "C08")
        self.assertTrue(extract_claims(e)[0].is_follow_up)


if __name__ == "__main__":
    unittest.main()
