"""T106 (invoice lookup) against the shapes the real URA sandbox returned on 29 Sep 2026
(artifacts/tillking/efris-sandbox/T106-CHECK.md):

* ``issuedDate`` is Uganda time, "dd/mm/yyyy HH:MM:SS" (response ``timeFormat``
  "dd/MM/yyyy HH24:mi:ss"); URA's ``nowTime`` is Uganda time too.
* Every answer carries ``page`` {pageCount, pageNo, pageSize, totalSize}; pageCount is 0
  when nothing matched. ``referenceNo`` is an exact-match filter.

URA is faked (``fake_ura``); no HTTP call is made.
"""

import copy
from datetime import timedelta
from zoneinfo import ZoneInfo

from frappe.utils import get_datetime, get_system_timezone

from uganda_compliance.efris import efris_queue
from uganda_compliance.efris.tests.efris_test_utils import (
	TEST_DEVICE,
	fake_ura,
	make_pos_invoice,
	reload,
	run_queued,
)
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase
from uganda_compliance.efris.tests.test_restore_numbering import DUPLICATE_ANSWER

# One T106 record as the URA sandbox returned it (ids, TIN and device redacted).
OBSERVED_RECORD = {
	"branchId": "<BRANCH_ID>",
	"branchName": "ERP CHAMPIONS LTD",
	"businessName": "ERP CHAMPIONS LTD",
	"buyerBusinessName": "Walk-in Customer ECET",
	"buyerLegalName": "<BUYER>",
	"currency": "UGX",
	"dataSource": "103",
	"dateFormat": "dd/MM/yyyy",
	"deviceNo": "<DEVICE>",
	"grossAmount": "5000",
	"id": "<ID>",
	"invoiceIndustryCode": "101",
	"invoiceKind": "1",
	"invoiceNo": "326044253116",
	"invoiceType": "1",
	"isInvalid": "0",
	"isRefund": "1",
	"issuedDate": "28/09/2026 04:14:50",
	"issuedDateStr": "28/09/2026",
	"legalName": "ERP CHAMPIONS LTD",
	"nowTime": "2026/09/29 21:14:21",
	"operator": "Administrator",
	"pageIndex": 0,
	"pageNo": 0,
	"pageSize": 0,
	"referenceNo": "9A2D5-ACC-PSINV-2026-00002",
	"taxAmount": "762.71",
	"uploadingTime": "28/09/2026 04:14:50",
	"userName": "ERP CHAMPIONS LTD",
}


def _answer(records, page_no=1, page_count=None, page_size=10):
	"""A T106 answer in the observed envelope."""
	total = len(records) if page_count is None else page_count * page_size
	count = (1 if records else 0) if page_count is None else page_count
	return (
		True,
		{
			"dateFormat": "dd/MM/yyyy",
			"nowTime": "2026/09/29 21:14:21",
			"page": {"pageCount": count, "pageNo": page_no, "pageSize": page_size, "totalSize": total},
			"records": records,
			"timeFormat": "dd/MM/yyyy HH24:mi:ss",
		},
	)


def _ura_time(dt):
	aware = dt.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return aware.astimezone(ZoneInfo("Africa/Kampala")).strftime("%d/%m/%Y %H:%M:%S")


def _record(reference, fdn, gross, issued):
	record = copy.deepcopy(OBSERVED_RECORD)
	record.update(
		referenceNo=reference,
		invoiceNo=fdn,
		grossAmount=str(gross),
		deviceNo=TEST_DEVICE,
		issuedDate=_ura_time(issued),
		uploadingTime=_ura_time(issued),
	)
	return record


class TestUraIssuedDate(EfrisTestCase):
	def test_observed_issued_date_is_uganda_time(self):
		# the POS sale was fiscalised at 01:14:50 UTC = 04:14:50 in Kampala (UTC+3)
		expected = (
			get_datetime("2026-09-28 01:14:50")
			.replace(tzinfo=ZoneInfo("UTC"))
			.astimezone(ZoneInfo(get_system_timezone()))
			.replace(tzinfo=None)
		)
		self.assertEqual(efris_queue.ura_issued_at(OBSERVED_RECORD["issuedDate"]), expected)
		self.assertEqual(efris_queue.ura_issued_at(OBSERVED_RECORD["uploadingTime"]), expected)

	def test_unreadable_issued_date_is_none(self):
		self.assertIsNone(efris_queue.ura_issued_at(OBSERVED_RECORD["issuedDateStr"]))
		self.assertIsNone(efris_queue.ura_issued_at(None))

	def test_own_record_a_few_minutes_early_is_still_ours(self):
		"""URA's issuedDate was seen minutes away from its own clock: allow for it."""
		with fake_ura():
			inv = reload(make_pos_invoice(self.ctx))
		settings = efris_queue.get_efris_settings(inv.company)
		early = get_datetime(inv.creation) - timedelta(minutes=8)
		record = _record(inv.efris_seller_reference_no, "1", inv.grand_total, early)
		self.assertTrue(efris_queue._is_own_ura_record(record, inv, settings))
		days_before = get_datetime(inv.creation) - timedelta(days=1)
		record = _record(inv.efris_seller_reference_no, "1", inv.grand_total, days_before)
		self.assertFalse(efris_queue._is_own_ura_record(record, inv, settings))


class TestT106Paging(EfrisTestCase):
	def _lookup(self, ura, inv):
		settings = efris_queue.get_efris_settings(inv.company)
		return efris_queue._ura_records_for_reference(inv, settings, inv.efris_seller_reference_no)

	def test_single_page_answer_is_one_call(self):
		with fake_ura() as ura:
			inv = reload(make_pos_invoice(self.ctx))
			own = _record(inv.efris_seller_reference_no, "326044253116", inv.grand_total, inv.creation)
			ura.responses["T106"] = [_answer([own])]
			records = self._lookup(ura, inv)
		self.assertEqual([r["invoiceNo"] for r in records], ["326044253116"])
		self.assertEqual([c["content"]["pageNo"] for c in ura.calls_for("T106")], ["1"])

	def test_no_match_answer_is_one_call(self):
		with fake_ura() as ura:
			inv = reload(make_pos_invoice(self.ctx))
			ura.responses["T106"] = [_answer([])]  # observed: pageCount 0, totalSize 0
			self.assertEqual(self._lookup(ura, inv), [])
		self.assertEqual(len(ura.calls_for("T106")), 1)

	def test_all_pages_are_read(self):
		with fake_ura() as ura:
			inv = reload(make_pos_invoice(self.ctx))
			ref = inv.efris_seller_reference_no
			ura.responses["T106"] = [
				_answer([_record(ref, "1", 1, inv.creation)], page_no=1, page_count=2),
				_answer([_record(ref, "2", 1, inv.creation)], page_no=2, page_count=2),
			]
			records = self._lookup(ura, inv)
		self.assertEqual([r["invoiceNo"] for r in records], ["1", "2"])
		self.assertEqual([c["content"]["pageNo"] for c in ura.calls_for("T106")], ["1", "2"])

	def test_paging_is_capped(self):
		with fake_ura() as ura:
			inv = reload(make_pos_invoice(self.ctx))
			ura.responses["T106"] = [
				_answer([], page_no=n, page_count=99)
				for n in range(1, efris_queue.REFERENCE_LOOKUP_MAX_PAGES + 2)
			]
			self.assertEqual(self._lookup(ura, inv), [])
		self.assertEqual(len(ura.calls_for("T106")), efris_queue.REFERENCE_LOOKUP_MAX_PAGES)

	def test_failed_later_page_keeps_records_already_read(self):
		with fake_ura() as ura:
			inv = reload(make_pos_invoice(self.ctx))
			ref = inv.efris_seller_reference_no
			ura.responses["T106"] = [
				_answer([_record(ref, "1", 1, inv.creation)], page_no=1, page_count=2),
				(False, "Connection refused"),
			]
			self.assertEqual([r["invoiceNo"] for r in self._lookup(ura, inv)], ["1"])

		with fake_ura() as ura:
			ura.responses["T106"] = [(False, "Connection refused")]
			self.assertIsNone(self._lookup(ura, inv))

	def test_own_record_on_second_page_is_adopted(self):
		"""A pre-restore invoice on page 1, this invoice's lost attempt on page 2."""
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ref = reload(inv).efris_seller_reference_no
			creation = get_datetime(reload(inv).creation)
			own_fdn = ura.next_fdn()
			ura.responses["T109"] = [(False, DUPLICATE_ANSWER)]
			ura.responses["T106"] = [
				_answer([_record(ref, "325043814241", 1, creation - timedelta(days=2))], 1, 2),
				_answer([_record(ref, own_fdn, reload(inv).grand_total, creation)], 2, 2),
			]
			ura.responses["T108"] = [(True, ura.invoice_response(own_fdn))]
			(result,) = run_queued(ura)

		inv = reload(inv)
		self.assertEqual(result["outcome"], "submitted")
		self.assertEqual(inv.efris_irn, own_fdn)
		self.assertEqual(inv.efris_seller_reference_no, ref)
		self.assertEqual(len(ura.calls_for("T109")), 1, "not fiscalised twice")
