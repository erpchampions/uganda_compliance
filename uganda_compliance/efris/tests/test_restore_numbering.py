"""Runbook 04/05 gap: after a tenant is restored from a backup, new invoices reuse the
names — and Seller Reference Nos. — of invoices URA fiscalised after the backup.

* The submission guard: when URA holds another invoice under the reference (URA's
  "same Seller's Reference Number have already been issued", or the retry lookup),
  the invoice moves to ``<reference>-R1`` and is sent again; an invoice that was
  issued before this one existed is never adopted, even with the same amount.
* ``tillking.advance_series_after_restore`` moves the naming series past the last
  number URA fiscalised, so the tills stop reusing names at all.

URA is faked (``fake_ura``); no HTTP call is made.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import cint, get_datetime, get_system_timezone, now_datetime

from uganda_compliance import tillking
from uganda_compliance.efris import efris_queue
from uganda_compliance.efris.tests.efris_test_utils import (
	TEST_DEVICE,
	fake_ura,
	make_pos_invoice,
	reload,
	run_queued,
)
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase

DUPLICATE_ANSWER = (
	"Invoice(s)/receipt(s) (325043814241) with the same Seller's Reference Number have "
	"already been issued! Total invoices Issued(1)!"
)


def _ura_time(dt):
	"""``dt`` (system time) as URA prints it: Uganda time, dd/mm/yyyy HH:MM:SS."""
	aware = dt.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return aware.astimezone(ZoneInfo("Africa/Kampala")).strftime("%d/%m/%Y %H:%M:%S")


def _t106(*records):
	return (True, {"page": {"pageCount": 1}, "records": list(records)})


def _record(reference, fdn, gross, issued):
	return {
		"invoiceNo": fdn,
		"referenceNo": reference,
		"grossAmount": str(gross),
		"deviceNo": TEST_DEVICE,
		"issuedDate": _ura_time(issued),
	}


class TestRestoredSiteReusedInvoiceNumber(EfrisTestCase):
	def _before_restore(self, inv):
		"""When the invoice that had this name before the restore was fiscalised."""
		return get_datetime(inv.creation) - timedelta(days=2)

	def test_restored_site_reused_invoice_number_moves_to_next_reference(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ref = reload(inv).efris_seller_reference_no
			ura.responses["T109"] = [(False, DUPLICATE_ANSWER)]
			ura.responses["T106"] = [_t106(_record(ref, "325043814241", 12345, self._before_restore(inv)))]
			(result,) = run_queued(ura)

		inv = reload(inv)
		self.assertEqual(result["outcome"], "submitted")
		self.assertEqual(inv.efris_seller_reference_no, f"{ref}-R1")
		self.assertNotEqual(inv.efris_irn, "325043814241")
		sent = [c["content"]["sellerDetails"]["referenceNo"] for c in ura.calls_for("T109")]
		self.assertEqual(sent, [ref, f"{ref}-R1"])
		# the new reference was checked at URA before it was used
		self.assertEqual([c["content"]["referenceNo"] for c in ura.calls_for("T106")], [ref, f"{ref}-R1"])
		self.assertTrue(
			frappe.db.exists(
				"Comment",
				{
					"reference_doctype": "POS Invoice",
					"reference_name": inv.name,
					"content": ("like", f"%{ref}-R1%"),
				},
			)
		)

	def test_pre_restore_invoice_with_same_amount_is_not_adopted(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ref = reload(inv).efris_seller_reference_no
			ura.responses["T109"] = [(False, DUPLICATE_ANSWER)]
			ura.responses["T106"] = [
				_t106(_record(ref, "325043814241", inv.grand_total, self._before_restore(inv)))
			]
			(result,) = run_queued(ura)

		self.assertEqual(result["outcome"], "submitted")
		self.assertEqual(ura.calls_for("T108"), [], "never adopt another invoice's FDN")
		self.assertNotEqual(reload(inv).efris_irn, "325043814241")

	def test_own_lost_attempt_is_adopted_not_sent_twice(self):
		"""Duplicate answer for our own earlier attempt (worker killed after URA accepted it)."""
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ref = reload(inv).efris_seller_reference_no
			own_fdn = ura.next_fdn()
			ura.responses["T109"] = [(False, DUPLICATE_ANSWER)]
			ura.responses["T106"] = [_t106(_record(ref, own_fdn, inv.grand_total, now_datetime()))]
			ura.responses["T108"] = [(True, ura.invoice_response(own_fdn))]
			(result,) = run_queued(ura)

		inv = reload(inv)
		self.assertEqual(result["outcome"], "submitted")
		self.assertEqual(inv.efris_irn, own_fdn)
		self.assertEqual(inv.efris_seller_reference_no, ref)
		self.assertEqual(len(ura.calls_for("T109")), 1)

	def test_duplicate_answer_without_a_record_fails_visibly(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ura.responses["T109"] = [(False, DUPLICATE_ANSWER)]
			(result,) = run_queued(ura)

		inv = reload(inv)
		self.assertEqual(result["outcome"], "failed")
		self.assertEqual(inv.efris_status, "Failed")
		self.assertIn("already been issued", inv.efris_last_error)
		self.assertEqual(len(ura.calls_for("T109")), 1)

	def test_retry_moves_off_a_reference_taken_before_restore(self):
		with fake_ura() as ura:
			ura.responses["T109"] = [TimeoutError("read timed out")]
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			ref = reload(inv).efris_seller_reference_no
			ura.responses["T106"] = [
				_t106(_record(ref, "325043814241", inv.grand_total, self._before_restore(inv)))
			]
			result = efris_queue.process_efris_submission("POS Invoice", inv.name)

		self.assertEqual(result["outcome"], "submitted")
		self.assertEqual(reload(inv).efris_seller_reference_no, f"{ref}-R1")
		self.assertEqual(ura.calls_for("T108"), [])

	def test_bumped_reference_is_bumped_again(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ref = reload(inv).efris_seller_reference_no
			earlier = self._before_restore(inv)
			ura.responses["T109"] = [(False, DUPLICATE_ANSWER)]
			ura.responses["T106"] = [
				_t106(_record(ref, "1", 1, earlier)),
				_t106(_record(f"{ref}-R1", "2", 1, earlier)),
			]
			run_queued(ura)
		self.assertEqual(reload(inv).efris_seller_reference_no, f"{ref}-R2")

	def test_ura_issued_date_is_read_as_uganda_time(self):
		issued = efris_queue.ura_issued_at("01/10/2026 12:00:00")
		expected = (
			get_datetime("2026-10-01 12:00:00")
			.replace(tzinfo=ZoneInfo("Africa/Kampala"))
			.astimezone(ZoneInfo(get_system_timezone()))
			.replace(tzinfo=None)
		)
		self.assertEqual(issued, expected)
		self.assertIsNone(efris_queue.ura_issued_at(""))


class TestAdvanceSeriesAfterRestore(EfrisTestCase):
	def setUp(self):
		super().setUp()
		self.prefix = frappe.db.get_value(
			"E Invoicing Settings", {"company": self.company}, "seller_reference_prefix"
		)
		with fake_ura() as ura:
			self.inv = make_pos_invoice(self.ctx)
			run_queued(ura)
		# e.g. "ACC-PSINV-2026-" and 17
		self.series = self.inv.name.rstrip("0123456789")
		self.current = int(self.inv.name[len(self.series) :])

	def _name(self, number):
		digits = len(self.inv.name) - len(self.series)
		return f"{self.series}{number:0{digits}d}"

	def _ura_has(self, *references):
		records = [{"invoiceNo": str(i), "referenceNo": r} for i, r in enumerate(references)]
		return [(True, {"page": {"pageCount": 1}, "records": records})]

	def _counter(self):
		return cint(frappe.db.get_value("Series", self.series, "current", order_by="name"))

	def test_restored_series_moves_past_last_fiscalised_number(self):
		last = self.current + 5
		with fake_ura() as ura:
			ura.responses["T106"] = self._ura_has(
				f"{self.prefix}-{self._name(self.current + 2)}",
				f"{self.prefix}-{self._name(last)}-R1",
				f"OTHERSYSTEM-{self._name(self.current + 90)}",
			)
			dry = tillking.advance_series_after_restore(self.company)
			self.assertEqual(self._counter(), self.current, "dry run changes nothing")
			ura.responses["T106"] = self._ura_has(f"{self.prefix}-{self._name(last)}-R1")
			result = tillking.advance_series_after_restore(self.company, dry_run=0)

		self.assertEqual(dry[self.series], {"current": self.current, "last_fiscalised": last, "new": last})
		self.assertEqual(result[self.series]["new"], last)
		self.assertEqual(self._counter(), last)
		self.assertTrue(frappe.db.exists("Version", {"ref_doctype": "Series", "docname": self.series}))

		with fake_ura():
			nxt = make_pos_invoice(self.ctx)
		self.assertEqual(nxt.name, self._name(last + 1))

	def test_counter_never_moves_back(self):
		with fake_ura() as ura:
			ura.responses["T106"] = self._ura_has(f"{self.prefix}-{self._name(1)}")
			result = tillking.advance_series_after_restore(self.company, dry_run=0)
		self.assertEqual(result[self.series]["new"], self.current)
		self.assertEqual(self._counter(), self.current)

	def test_lookup_failure_changes_nothing(self):
		with fake_ura() as ura:
			ura.responses["T106"] = [(False, "Connection refused")]
			with self.assertRaises(frappe.ValidationError):
				tillking.advance_series_after_restore(self.company, dry_run=0)
		self.assertEqual(self._counter(), self.current)

	def test_all_pages_are_read(self):
		with fake_ura() as ura:
			ura.responses["T106"] = [
				(True, {"page": {"pageCount": 2}, "records": []}),
				(
					True,
					{
						"page": {"pageCount": 2},
						"records": [
							{"invoiceNo": "9", "referenceNo": f"{self.prefix}-{self._name(self.current + 3)}"}
						],
					},
				),
			]
			result = tillking.advance_series_after_restore(self.company)
		self.assertEqual([c["content"]["pageNo"] for c in ura.calls_for("T106")], ["1", "2"])
		self.assertEqual(result[self.series]["last_fiscalised"], self.current + 3)
