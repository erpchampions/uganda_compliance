"""Regressions found while running the guide against the real URA sandbox (28 Sep 2026)."""

import json
from unittest.mock import patch

import frappe

from uganda_compliance.efris.doctype.e_invoice_request_log import e_invoice_request_log
from uganda_compliance.efris.tests.efris_test_utils import TEST_ITEM
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase


class TestSandboxRegressions(EfrisTestCase):
	def test_request_log_enqueued_after_commit_and_ignores_links(self):
		# regression: the log job ran before the Item/Invoice was committed, failed link
		# validation and the request (needed later for credit notes) was lost
		calls = []
		with patch.object(e_invoice_request_log, "enqueue", lambda *a, **kw: calls.append(kw)):
			e_invoice_request_log.log_request_to_efris(
				{"a": 1},
				"{}",
				{"b": 2},
				{},
				reference_doc_type="Item",
				reference_document="NOT-YET-COMMITTED",
			)
		self.assertTrue(calls[0]["enqueue_after_commit"])

		e_invoice_request_log.enqueue_log_request(
			{"a": 1}, "{}", {"b": 2}, {}, "Item", "NOT-YET-COMMITTED", status="Success", interface_code="T130"
		)
		self.assertTrue(
			frappe.db.exists(
				"E Invoice Request Log", {"reference_document": "NOT-YET-COMMITTED", "interface_code": "T130"}
			)
		)

	def test_item_registration_flag_is_persisted(self):
		# regression: efris_registered was set on the in-memory doc in on_update only, so every
		# later save of the item re-queried (T144) and re-uploaded (T130) it to URA
		from uganda_compliance.efris.api_classes import e_goods_services

		frappe.db.set_value("Item", TEST_ITEM, "efris_registered", 0)
		item = frappe.get_doc("Item", TEST_ITEM)
		with patch.object(e_goods_services, "make_post", lambda **kw: (True, {})):
			e_goods_services.upload_item_to_efris(item, self.company, [{}])
		self.assertEqual(frappe.db.get_value("Item", TEST_ITEM, "efris_registered"), 1)

	def test_ugx_exchange_rate_query_does_not_call_ura(self):
		# regression: `if e_company == 'UGX'` never matched, so UGX documents called URA T121
		from uganda_compliance.efris.api_classes import stock_in

		calls = []
		with patch.object(stock_in, "make_post", lambda **kw: calls.append(kw) or (True, {"rate": 1})):
			stock_in.query_currency_exchange_rate(json.dumps({"currency": "UGX", "company": self.company}))
			self.assertEqual(calls, [])
			stock_in.query_currency_exchange_rate(json.dumps({"currency": "USD", "company": self.company}))
		self.assertEqual(calls[0]["interfaceCode"], "T121")

	def test_sandbox_key_password_has_no_bogus_default(self):
		# regression: default "''" was stored as the key password when the field was not typed in
		meta = frappe.get_meta("E Invoicing Settings")
		self.assertFalse(meta.get_field("sandbox_private_key_password").default)
		self.assertFalse(frappe.new_doc("E Invoicing Settings").sandbox_private_key_password)

	def test_seller_reference_prefix_generated(self):
		s = frappe.get_doc("E Invoicing Settings", {"company": self.company})
		s.seller_reference_prefix = None
		s.flags.ignore_mandatory = True
		s.save(ignore_permissions=True)
		self.assertEqual(len(s.seller_reference_prefix), 5)

	def test_http_audit_line_per_ura_call(self):
		from uganda_compliance.efris.api_classes import request_utils

		class Resp:
			ok = True
			text = "{}"

		lines = []
		with (
			patch.object(request_utils.requests, "post", lambda *a, **kw: Resp()),
			patch.object(
				request_utils.frappe,
				"logger",
				lambda *a, **kw: type(
					"L", (), {"setLevel": lambda s, level: None, "info": lambda s, m: lines.append(m)}
				)(),
			),
		):
			request_utils.post_req(
				json.dumps({"globalInfo": {"interfaceCode": "T109"}}), "https://efristest.example/x"
			)
		self.assertEqual(lines, ["EFRIS POST T109 -> https://efristest.example/x"])
