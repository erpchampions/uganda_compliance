from datetime import timedelta

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from uganda_compliance.efris import efris_queue
from uganda_compliance.efris.api_classes import e_invoice
from uganda_compliance.efris.tests.efris_test_utils import (
	approx,
	ensure_masters,
	ensure_settings,
	fake_ura,
	get_company,
	make_pos_invoice,
	reload,
	run_queued,
)


class EfrisTestCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.company = get_company()
		ensure_settings(cls.company, max_attempts=3)
		cls.ctx = ensure_masters(cls.company)

	def setUp(self):
		frappe.set_user("Administrator")
		ensure_settings(self.company, max_attempts=3)
		frappe.local.efris_company_settings_cache = {}


class TestEfrisPosSubmission(EfrisTestCase):
	def test_submit_queues_then_worker_fiscalises(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			inv = reload(inv)
			self.assertEqual(inv.efris_status, "Pending")
			self.assertFalse(inv.efris_irn)
			self.assertEqual(len(ura.enqueued), 1)
			job = ura.enqueued[0]
			self.assertEqual(job.method, "uganda_compliance.efris.efris_queue.process_efris_submission")
			self.assertTrue(job.enqueue_after_commit)
			self.assertTrue(job.deduplicate)
			self.assertEqual(job.queue, "default")
			self.assertEqual(ura.calls, [], "nothing is sent to URA inside the POS submit request")

			(result,) = run_queued(ura)

		self.assertEqual(result["outcome"], "submitted")
		inv = reload(inv)
		self.assertEqual(inv.efris_status, "Submitted")
		self.assertTrue(inv.efris_irn)
		self.assertEqual(inv.efris_einvoice_status, "EFRIS Generated")
		self.assertEqual(len(ura.calls_for("T109")), 1)
		payload = ura.calls_for("T109")[0]["content"]
		self.assertTrue(
			approx(payload["summary"]["grossAmount"], inv.grand_total),
			(payload["summary"], inv.grand_total, inv.net_total, inv.total_taxes_and_charges),
		)
		prefix = frappe.db.get_value(
			"E Invoicing Settings", {"company": self.company}, "seller_reference_prefix"
		)
		self.assertTrue(prefix)
		self.assertEqual(inv.efris_seller_reference_no, f"{prefix}-{inv.name}")
		self.assertEqual(payload["sellerDetails"]["referenceNo"], inv.efris_seller_reference_no)
		einv = frappe.get_doc("E Invoice", inv.name)
		self.assertEqual(einv.source_doctype, "POS Invoice")
		self.assertEqual(einv.docstatus, 1)
		self.assertTrue(einv.antifake_code)

	def test_failure_is_recorded_then_retried_to_success(self):
		with fake_ura() as ura:
			ura.responses["T109"] = [(False, "Connection refused (efristest.ura.go.ug)")]
			inv = make_pos_invoice(self.ctx)
			self.assertEqual(inv.docstatus, 1, "the sale completes even though URA is down")
			(result,) = run_queued(ura)
			self.assertEqual(result["outcome"], "failed")

			inv = reload(inv)
			self.assertEqual(inv.efris_status, "Failed")
			self.assertEqual(inv.efris_attempts, 1)
			self.assertIn("Connection refused", inv.efris_last_error)
			self.assertFalse(inv.efris_irn)
			# the E Invoice is committed before the URA call; it stays a draft and is reused
			self.assertEqual(frappe.db.get_value("E Invoice", inv.name, ["docstatus", "irn"]), (0, None))
			delay = get_datetime(inv.efris_next_retry) - now_datetime()
			self.assertTrue(timedelta(minutes=14) < delay <= timedelta(minutes=15))

			log = frappe.get_all(
				"E Invoice Request Log",
				filters={
					"reference_doc_type": "POS Invoice",
					"reference_document": inv.name,
					"status": "Failed",
				},
				fields=["error_message", "interface_code"],
			)
			self.assertEqual(len(log), 1)
			self.assertEqual(log[0].interface_code, "T109")
			self.assertIn("Connection refused", log[0].error_message)

			# sweep respects the back-off
			self.assertNotIn(("POS Invoice", inv.name), efris_queue.retry_pending_efris_submissions())
			self.assertNotIn(inv.name, [j.name for j in ura.enqueued])

			frappe.db.set_value(
				"POS Invoice", inv.name, "efris_next_retry", add_to_date(now_datetime(), minutes=-1)
			)
			self.assertIn(("POS Invoice", inv.name), efris_queue.retry_pending_efris_submissions())
			(result,) = run_queued(ura, only=inv)

		self.assertEqual(result["outcome"], "submitted")
		inv = reload(inv)
		self.assertEqual(inv.efris_status, "Submitted")
		self.assertTrue(inv.efris_irn)
		self.assertFalse(inv.efris_last_error)
		# retry looked the invoice up at URA first (idempotency), then fiscalised once
		self.assertEqual([c["interfaceCode"] for c in ura.calls], ["T109", "T106", "T109"])
		self.assertEqual(ura.calls_for("T106")[0]["content"]["referenceNo"], inv.efris_seller_reference_no)

	def test_exception_in_worker_is_recorded(self):
		with fake_ura() as ura:
			ura.responses["T109"] = [TimeoutError("read timed out")]
			inv = make_pos_invoice(self.ctx)
			(result,) = run_queued(ura)
		self.assertEqual(result["outcome"], "failed")
		inv = reload(inv)
		self.assertEqual(inv.efris_status, "Failed")
		self.assertIn("read timed out", inv.efris_last_error)

	def test_backoff_is_exponential_and_capped(self):
		self.assertEqual(
			[efris_queue.get_backoff_minutes(n) for n in range(1, 8)], [15, 30, 60, 120, 240, 480, 720]
		)
		self.assertEqual(efris_queue.get_backoff_minutes(20), 720)

	def test_max_attempts_stops_automatic_retries(self):
		ensure_settings(self.company, max_attempts=2)
		with fake_ura() as ura:
			ura.responses["T109"] = [(False, "URA down"), (False, "URA down")]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			frappe.db.set_value(
				"POS Invoice", inv.name, "efris_next_retry", add_to_date(now_datetime(), minutes=-1)
			)
			efris_queue.retry_pending_efris_submissions()
			run_queued(ura, only=inv)

			inv = reload(inv)
			self.assertEqual(inv.efris_status, "Failed")
			self.assertEqual(inv.efris_attempts, 2)
			self.assertIsNone(inv.efris_next_retry)
			self.assertIn("gave up after 2 attempts", inv.efris_last_error)

			# no further automatic attempts
			self.assertNotIn(("POS Invoice", inv.name), efris_queue.retry_pending_efris_submissions())
			calls_before = len(ura.calls)
			result = efris_queue.process_efris_submission("POS Invoice", inv.name)
			self.assertEqual(result["outcome"], "max_attempts")
			self.assertEqual(len(ura.calls), calls_before)

			# a person can still push it through
			result = e_invoice.send_pos_invoice_to_efris(name=inv.name)
		self.assertEqual(result["status"], "success")
		self.assertEqual(reload(inv).efris_status, "Submitted")

	def test_idempotent_never_fiscalises_twice(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			fdn = reload(inv).efris_irn

			# duplicate job (e.g. sweep + on_submit race) and manual resend
			self.assertEqual(
				efris_queue.process_efris_submission("POS Invoice", inv.name)["outcome"], "already_submitted"
			)
			self.assertEqual(
				e_invoice.send_pos_invoice_to_efris(name=inv.name)["outcome"], "already_submitted"
			)
		self.assertEqual(len(ura.calls_for("T109")), 1)
		self.assertEqual(reload(inv).efris_irn, fdn)

	def test_retry_adopts_fdn_found_at_ura(self):
		"""The first attempt reached URA but the answer was lost: the retry must not re-send."""
		with fake_ura() as ura:
			ura.responses["T109"] = [TimeoutError("read timed out")]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			lost_fdn = ura.next_fdn()
			ura.responses["T106"] = [
				(
					True,
					{
						"page": {"pageCount": 1},
						"records": [
							{
								"invoiceNo": "999",
								"referenceNo": "SOMEONE-ELSE",
								"grossAmount": str(inv.grand_total),
							},
							{
								"invoiceNo": lost_fdn,
								"referenceNo": reload(inv).efris_seller_reference_no,
								"grossAmount": str(inv.grand_total),
								"deviceNo": "1000000001_01",
							},
						],
					},
				)
			]
			ura.responses["T108"] = [(True, ura.invoice_response(lost_fdn))]
			result = efris_queue.process_efris_submission("POS Invoice", inv.name)

		self.assertEqual(result["outcome"], "submitted")
		self.assertEqual(len(ura.calls_for("T109")), 1, "no second T109")
		inv = reload(inv)
		self.assertEqual(inv.efris_irn, lost_fdn)
		self.assertEqual(inv.efris_status, "Submitted")

	def test_other_systems_invoice_with_same_reference_is_not_adopted(self):
		"""Sandbox finding: several systems share one TIN and device; URA returned another system's
		invoice for our reference. Only a record with our gross amount may be adopted."""
		with fake_ura() as ura:
			ura.responses["T109"] = [TimeoutError("read timed out")]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			ura.responses["T106"] = [
				(
					True,
					{
						"page": {"pageCount": 1},
						"records": [
							{
								"invoiceNo": "325043814241",
								"referenceNo": reload(inv).efris_seller_reference_no,
								"grossAmount": "53100",
								"deviceNo": "1000000001_01",
							}
						],
					},
				)
			]
			result = efris_queue.process_efris_submission("POS Invoice", inv.name)
		self.assertEqual(result["outcome"], "submitted")
		self.assertEqual(ura.calls_for("T108"), [])
		self.assertEqual(len(ura.calls_for("T109")), 2)
		self.assertNotEqual(reload(inv).efris_irn, "325043814241")

	def test_seller_reference_fixed_before_first_attempt(self):
		# regression (sandbox): reference = invoice name collided with another system on the same TIN
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ref = reload(inv).efris_seller_reference_no
			self.assertNotEqual(ref, inv.name)
			frappe.db.set_value(
				"E Invoicing Settings", {"company": self.company}, "seller_reference_prefix", "OTHER"
			)
			run_queued(ura)
		self.assertEqual(reload(inv).efris_seller_reference_no, ref, "never changes once assigned")
		self.assertEqual(ura.calls_for("T109")[0]["content"]["sellerDetails"]["referenceNo"], ref)

	def test_sweep_requeues_stale_pending(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ura.enqueued.clear()  # job lost (redis restart)
			self.assertNotIn(("POS Invoice", inv.name), efris_queue.retry_pending_efris_submissions())
			frappe.db.set_value(
				"POS Invoice",
				inv.name,
				"creation",
				add_to_date(now_datetime(), minutes=-30),
				update_modified=False,
			)
			self.assertIn(("POS Invoice", inv.name), efris_queue.retry_pending_efris_submissions())

	def test_not_queued_without_enabled_settings(self):
		frappe.db.set_value("E Invoicing Settings", {"company": self.company}, "enabled", 0)
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
		self.assertFalse(reload(inv).efris_status)
		self.assertEqual(ura.enqueued, [])


class TestEfrisPosReturnsAndCancel(EfrisTestCase):
	def _fiscalised_invoice(self, ura):
		inv = make_pos_invoice(self.ctx)
		run_queued(ura)
		inv = reload(inv)
		self.assertEqual(inv.efris_status, "Submitted")
		return inv

	def _make_return(self, inv):
		from erpnext.accounts.doctype.pos_invoice.pos_invoice import make_sales_return

		ret = make_sales_return(inv.name)
		ret.efris_creditnote_reasoncode = "102:Cancellation of the purchase."
		ret.insert(ignore_permissions=True)
		ret.submit()
		return ret

	def test_return_sends_credit_note_application_and_tracks_approval(self):
		with fake_ura() as ura:
			inv = self._fiscalised_invoice(ura)
			ret = self._make_return(inv)
			self.assertEqual(reload(ret).efris_status, "Pending")
			(result,) = run_queued(ura)
			self.assertEqual(result["outcome"], "submitted")

			ret = reload(ret)
			self.assertEqual(ret.efris_status, "Submitted")
			self.assertEqual(ret.efris_einvoice_status, "EFRIS Credit Note Pending")
			t110 = ura.calls_for("T110")
			self.assertEqual(len(t110), 1)
			self.assertEqual(t110[0]["content"]["oriInvoiceNo"], inv.efris_irn)
			self.assertEqual(t110[0]["reference_doc_type"], "POS Invoice")
			einv = frappe.get_doc("E Invoice", ret.name)
			self.assertEqual(einv.source_doctype, "POS Invoice")
			self.assertTrue(einv.credit_note_application_ref_no)

			# idempotent: a second run does not apply twice
			self.assertEqual(
				efris_queue.process_efris_submission("POS Invoice", ret.name)["outcome"], "already_submitted"
			)
			self.assertEqual(len(ura.calls_for("T110")), 1)

			# URA approves -> hourly poll picks up the credit note FDN
			cn_fdn = ura.next_fdn()
			ura.responses["T111"] = [
				(
					True,
					{
						"page": {"pageCount": 1},
						"records": [
							{"approveStatus": "101", "invoiceNo": cn_fdn, "oriInvoiceNo": inv.efris_irn}
						],
					},
				)
			]
			ura.responses["T108"] = [(True, ura.invoice_response(cn_fdn))]
			e_invoice.check_credit_note_approval_status()

		ret = reload(ret)
		self.assertEqual(ret.efris_einvoice_status, "EFRIS Generated")
		self.assertEqual(ret.efris_irn, cn_fdn)
		self.assertEqual(
			frappe.db.get_value("POS Invoice", inv.name, "efris_einvoice_status"), "EFRIS Cancelled"
		)
		self.assertEqual(frappe.db.get_value("E Invoice", inv.name, "status"), "EFRIS Cancelled")

	def test_credit_note_rejected_is_flagged(self):
		with fake_ura() as ura:
			inv = self._fiscalised_invoice(ura)
			ret = self._make_return(inv)
			run_queued(ura)
			ura.responses["T111"] = [
				(True, {"page": {"pageCount": 1}, "records": [{"approveStatus": "103"}]})
			]
			e_invoice.check_credit_note_approval_status()
		ret = reload(ret)
		self.assertEqual(ret.efris_einvoice_status, "EFRIS Credit Note Rejected")
		self.assertEqual(ret.efris_status, "Failed")
		self.assertEqual(
			frappe.db.get_value("POS Invoice", inv.name, "efris_einvoice_status"), "EFRIS Generated"
		)

	def test_return_waits_for_original_to_be_fiscalised(self):
		with fake_ura() as ura:
			ura.responses["T109"] = [(False, "URA down")]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			ret = self._make_return(reload(inv))
			(result,) = run_queued(ura)
		self.assertEqual(result["outcome"], "failed")
		ret = reload(ret)
		self.assertEqual(ret.efris_status, "Failed")
		self.assertIn("not fiscalised yet", ret.efris_last_error)
		self.assertEqual(ura.calls_for("T110"), [])

	def test_cancel_of_fiscalised_pos_invoice_is_blocked(self):
		with fake_ura() as ura:
			inv = self._fiscalised_invoice(ura)
		inv = reload(inv)
		with self.assertRaises(frappe.ValidationError) as cm:
			inv.cancel()
		self.assertIn("Return", str(cm.exception))
		self.assertEqual(frappe.db.get_value("POS Invoice", inv.name, "docstatus"), 1)

	def test_cancel_of_unsent_pos_invoice_stops_submission(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			reload(inv).cancel()
			self.assertEqual(frappe.db.get_value("POS Invoice", inv.name, "efris_status"), "Cancelled")
			(result,) = run_queued(ura)
		self.assertEqual(result["outcome"], "skipped")
		self.assertEqual(ura.calls, [])


class TestEfrisSendEndpoint(EfrisTestCase):
	def _cashierless_user(self):
		email = "efris-noperm@example.ug"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Okello", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		return email

	def test_send_requires_submit_permission(self):
		with fake_ura() as ura:
			ura.responses["T109"] = [(False, "URA down")]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			frappe.set_user(self._cashierless_user())
			try:
				with self.assertRaises(frappe.PermissionError):
					e_invoice.send_pos_invoice_to_efris(name=inv.name)
			finally:
				frappe.set_user("Administrator")
		self.assertEqual(len(ura.calls_for("T109")), 1)

	def test_client_built_doc_is_ignored_except_name(self):
		with fake_ura() as ura:
			ura.responses["T109"] = [(False, "URA down")]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			forged = inv.as_dict()
			forged["grand_total"] = 1
			forged["items"][0]["rate"] = 1
			forged["customer"] = "Forged Customer"
			result = e_invoice.send_pos_invoice_to_efris(doc=frappe.as_json(forged))
		self.assertEqual(result["status"], "success")
		payload = ura.calls_for("T109")[-1]["content"]
		self.assertTrue(
			approx(payload["summary"]["grossAmount"], inv.grand_total),
			(payload["summary"], inv.grand_total, inv.net_total, inv.total_taxes_and_charges),
		)
		self.assertNotEqual(payload["buyerDetails"]["buyerLegalName"], "Forged Customer")

	def test_doctype_mismatch_and_unknown_name_rejected(self):
		with fake_ura():
			inv = make_pos_invoice(self.ctx, submit=False)
			with self.assertRaises(frappe.ValidationError):
				e_invoice.send_to_efris(doc={"doctype": "POS Invoice", "name": inv.name})
			with self.assertRaises(frappe.DoesNotExistError):
				e_invoice.send_pos_invoice_to_efris(name="POS-DOES-NOT-EXIST")
			with self.assertRaises(frappe.ValidationError):
				e_invoice.send_pos_invoice_to_efris(name=inv.name)  # draft

	def test_legacy_generate_irn_endpoint_loads_by_name(self):
		with fake_ura() as ura:
			ura.responses["T109"] = [(False, "URA down"), (True, ura.invoice_response())]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			forged = inv.as_dict()
			forged["grand_total"] = 1
			frappe.set_user(self._cashierless_user())
			try:
				with self.assertRaises(frappe.PermissionError):
					e_invoice.generate_irn(frappe.as_json(forged))
			finally:
				frappe.set_user("Administrator")
			e_invoice.generate_irn(frappe.as_json(forged))
		payload = ura.calls_for("T109")[-1]["content"]
		self.assertTrue(
			approx(payload["summary"]["grossAmount"], inv.grand_total),
			(payload["summary"], inv.grand_total, inv.net_total, inv.total_taxes_and_charges),
		)


class TestEfrisSendEndpointAsCashier(EfrisTestCase):
	def _cashier(self):
		email = "efris-cashier@example.ug"
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Achieng", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Accounts User")
		return email

	def test_cashier_with_submit_permission_can_retry(self):
		with fake_ura() as ura:
			ura.responses["T109"] = [(False, "URA down")]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			frappe.set_user(self._cashier())
			try:
				result = e_invoice.send_pos_invoice_to_efris(name=inv.name)
			finally:
				frappe.set_user("Administrator")
		self.assertEqual(result["status"], "success")
		self.assertEqual(reload(inv).efris_status, "Submitted")


class TestEfrisSalesInvoice(EfrisTestCase):
	def _make_si(self, submit=True):
		from uganda_compliance.efris.tests.efris_test_utils import TEST_CUSTOMER, TEST_ITEM, TEST_UOM

		si = frappe.new_doc("Sales Invoice")
		si.update(
			{
				"company": self.company,
				"customer": TEST_CUSTOMER,
				"currency": frappe.get_cached_value("Company", self.company, "default_currency"),
			}
		)
		si.append(
			"items",
			{
				"item_code": TEST_ITEM,
				"qty": 3,
				"rate": 5900,
				"uom": TEST_UOM,
				"warehouse": self.ctx.warehouse,
			},
		)
		si.set_missing_values()
		si.taxes_and_charges = self.ctx.sales_taxes_template
		si.set("taxes", [])
		si.set_taxes()
		si.efris_invoice = 1
		si.insert(ignore_permissions=True)
		if submit:
			si.submit()
		return si

	def test_sales_invoice_background_submission(self):
		with fake_ura() as ura:
			si = self._make_si()
			self.assertEqual(reload(si).efris_status, "Pending")
			self.assertEqual(ura.calls, [])
			(result,) = run_queued(ura)
		self.assertEqual(result["outcome"], "submitted")
		si = reload(si)
		self.assertEqual(si.efris_status, "Submitted")
		self.assertTrue(si.efris_irn)

	def test_sales_invoice_synchronous_mode_blocks_on_failure(self):
		frappe.db.set_value(
			"E Invoicing Settings", {"company": self.company}, "sales_invoice_submission", "Synchronous"
		)
		with fake_ura() as ura:
			ura.responses["T109"] = [(False, "URA down")]
			si = self._make_si(submit=False)
			with self.assertRaises(frappe.ValidationError):
				si.submit()
			self.assertEqual(ura.enqueued, [])

	def test_consolidated_sales_invoice_is_not_revalidated(self):
		# regression (pos-invoice 27bf2be): POS closing merge must not re-run EFRIS validation
		doc = frappe._dict(
			doctype="Sales Invoice",
			is_consolidated=1,
			efris_invoice=1,
			set_warehouse="Not An EFRIS Warehouse",
		)
		e_invoice.Sales_invoice_is_efris_validation(doc, "before_save")  # must not throw
		with fake_ura() as ura:
			si = self._make_si(submit=False)
			si.is_consolidated = 1
			efris_queue.on_submit_invoice(si)
		self.assertEqual(ura.enqueued, [])


class TestEfrisClaimAndStaleClaims(EfrisTestCase):
	"""The worker claims an invoice (efris_status = Submitting + lease) instead of holding a row lock."""

	def _claimed(self, ura, attempts=1, lease_minutes=5):
		inv = make_pos_invoice(self.ctx)
		ura.enqueued.clear()
		frappe.db.set_value(
			"POS Invoice",
			inv.name,
			{
				"efris_status": "Submitting",
				"efris_attempts": attempts,
				"efris_next_retry": add_to_date(now_datetime(), minutes=lease_minutes),
			},
			update_modified=False,
		)
		return inv

	def test_live_claim_is_not_sent_again(self):
		with fake_ura() as ura:
			inv = self._claimed(ura)
			self.assertEqual(
				efris_queue.process_efris_submission("POS Invoice", inv.name)["outcome"], "in_progress"
			)
			self.assertEqual(e_invoice.send_pos_invoice_to_efris(name=inv.name)["outcome"], "in_progress")
			self.assertNotIn(("POS Invoice", inv.name), efris_queue.retry_pending_efris_submissions())
		self.assertEqual(ura.calls, [])
		self.assertEqual(reload(inv).efris_attempts, 1)

	def test_expired_claim_is_taken_over_and_looked_up_at_ura_first(self):
		# the worker died during the URA call: the invoice may or may not be at URA
		with fake_ura() as ura:
			inv = self._claimed(ura, lease_minutes=-1)
			self.assertIn(("POS Invoice", inv.name), efris_queue.retry_pending_efris_submissions())
			(result,) = run_queued(ura, only=inv)
		self.assertEqual(result["outcome"], "submitted")
		self.assertEqual([c["interfaceCode"] for c in ura.calls], ["T106", "T109"])
		inv = reload(inv)
		self.assertEqual((inv.efris_status, inv.efris_attempts), ("Submitted", 2))

	def test_dead_last_attempt_is_marked_failed_not_left_submitting(self):
		with fake_ura() as ura:
			inv = self._claimed(ura, attempts=3, lease_minutes=-1)  # max_attempts = 3
			self.assertIn(("POS Invoice", inv.name), efris_queue.retry_pending_efris_submissions())
			(result,) = run_queued(ura, only=inv)
		self.assertEqual(result["outcome"], "max_attempts")
		self.assertEqual(ura.calls, [])
		inv = reload(inv)
		self.assertEqual(inv.efris_status, "Failed")
		self.assertIn("stopped while waiting for URA", inv.efris_last_error)

	def test_cancel_blocked_while_submitting(self):
		# without the row lock, a cancel during the URA call would leave a fiscalised cancelled sale
		with fake_ura() as ura:
			inv = self._claimed(ura)
			with self.assertRaises(frappe.ValidationError) as cm:
				reload(inv).cancel()
		self.assertIn("being sent to EFRIS", str(cm.exception))
		self.assertEqual(frappe.db.get_value("POS Invoice", inv.name, "docstatus"), 1)


class TestEfrisRowLockNotHeldDuringUraCall(EfrisTestCase):
	"""Regression: the job held `select ... for update` on the invoice for the whole URA call
	(up to 2 x 120 s), so a POS Closing consolidating that invoice hit a lock-wait timeout.

	Uses real commits (the claim must be visible to other connections)."""

	def _in_second_connection(self, fn):
		# primary_connection() restores the worker's connection afterwards: on first use,
		# FrappeTestCase.secondary_connection() "restores" the new secondary connection
		with self.primary_connection(), self.secondary_connection():
			try:
				return fn()
			finally:
				frappe.db.rollback()

	def _row_lock_is_free(self, name):
		def try_lock():
			try:
				frappe.db.sql("select name from `tabPOS Invoice` where name=%s for update nowait", name)
				return True
			except Exception as e:
				if frappe.db.is_timedout(e) or "lock" in str(e).lower():
					return False
				raise

		return self._in_second_connection(try_lock)

	def test_invoice_not_locked_during_ura_call(self):
		seen = []
		with fake_ura(real_commit=True) as ura:
			inv = make_pos_invoice(self.ctx)

			def during_http_call(code):
				if code != "T109":
					return
				status = self._in_second_connection(
					lambda: frappe.db.get_value("POS Invoice", inv.name, "efris_status")
				)
				# another worker (duplicate job / manual resend) does not send it again
				other = self._in_second_connection(
					lambda: efris_queue.process_efris_submission("POS Invoice", inv.name)["outcome"]
				)
				seen.append((status, self._row_lock_is_free(inv.name), other))

			ura.on_call = during_http_call
			ura.responses["T109"] = [(False, "URA down")]
			(first,) = run_queued(ura)
			self.assertEqual(first["outcome"], "failed")
			self.assertEqual(reload(inv).efris_status, "Failed")

			second = efris_queue.process_efris_submission("POS Invoice", inv.name, manual=True)

		self.assertEqual(seen, [("Submitting", True, "in_progress")] * 2)
		self.assertEqual(second["outcome"], "submitted")
		self.assertEqual([c["interfaceCode"] for c in ura.calls], ["T109", "T106", "T109"])
		inv = reload(inv)
		self.assertEqual((inv.efris_status, inv.efris_attempts), ("Submitted", 2))
		self.assertEqual(frappe.db.count("E Invoice", {"invoice": inv.name}), 1)
