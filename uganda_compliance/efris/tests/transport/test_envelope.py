"""Unit tests for the URA request envelope."""
import unittest

from uganda_compliance.efris.client.envelope import (
    build_envelope,
    get_ug_time_str,
    guidv4,
)


class EnvelopeTests(unittest.TestCase):
    def test_build_envelope_shape(self):
        env = build_envelope()
        self.assertIn("globalInfo", env)
        self.assertIn("data", env)
        self.assertIn("returnStateInfo", env)
        gi = env["globalInfo"]
        self.assertEqual(gi["appId"], "AP04")
        self.assertEqual(gi["requestCode"], "TP")
        self.assertEqual(gi["responseCode"], "TA")
        # Defaults are empty so callers must populate per call — no leaked sample TIN.
        self.assertEqual(gi["tin"], "")
        self.assertEqual(gi["deviceNo"], "")

    def test_each_call_has_unique_data_exchange_id(self):
        a = build_envelope()
        b = build_envelope()
        self.assertNotEqual(
            a["globalInfo"]["dataExchangeId"],
            b["globalInfo"]["dataExchangeId"],
        )

    def test_guidv4_format(self):
        g = guidv4()
        self.assertEqual(len(g), 32)
        self.assertNotIn("-", g)
        # All hex.
        int(g, 16)

    def test_get_ug_time_str_format(self):
        s = get_ug_time_str()
        self.assertRegex(s, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
