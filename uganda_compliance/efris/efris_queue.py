"""Background EFRIS submission for Sales Invoice / POS Invoice with retry.

Flow
----
* ``on_submit_invoice`` (doc_event) flags the invoice ``efris_status = Pending`` and
  enqueues ``process_efris_submission`` after the transaction commits. The sale is
  never blocked by EFRIS (POS must keep trading when URA is unreachable).
* ``process_efris_submission`` claims the invoice in a short transaction: it locks the
  row, checks that the invoice has not been fiscalised and is not being submitted by
  another job, flips ``efris_status`` to ``Submitting`` (lease until
  ``efris_next_retry``), counts the attempt and commits. URA is then called without
  holding any row lock (a POS Closing that consolidates the invoice meanwhile no longer
  waits for URA), and the result is recorded in a new transaction. On a retry the invoice
  is first looked up at URA (T106) so an attempt whose answer was lost is adopted, not
  sent again. It sends either the invoice (T109) or, for returns, the credit note
  application (T110).
  Success -> ``Submitted``. Failure -> ``Failed`` + one ``E Invoice Request Log``
  (status Failed) + exponential back-off in ``efris_next_retry``.
* ``retry_pending_efris_submissions`` (hourly) re-enqueues Pending/Failed invoices
  whose back-off has elapsed, and Submitting invoices whose lease expired (worker died
  mid-call), until ``E Invoicing Settings.efris_max_attempts``.
* ``send_invoice_to_efris`` is the whitelisted "Send to EFRIS" endpoint: it takes a
  document *name*, loads the document server-side and checks permissions.
"""

import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import add_days, cint, flt, get_datetime, get_system_timezone, getdate, now_datetime

from uganda_compliance.efris.api_classes import e_invoice as e_invoice_api
from uganda_compliance.efris.utils.utils import efris_log_info

SUPPORTED_DOCTYPES = ("Sales Invoice", "POS Invoice")

STATUS_PENDING = "Pending"
STATUS_SUBMITTING = "Submitting"
STATUS_SUBMITTED = "Submitted"
STATUS_FAILED = "Failed"
STATUS_CANCELLED = "Cancelled"

DEFAULT_MAX_ATTEMPTS = 8
BACKOFF_BASE_MINUTES = 15
BACKOFF_CAP_MINUTES = 12 * 60
SWEEP_BATCH_SIZE = 500
# A "Pending" invoice whose job was lost (worker/redis restart) is re-queued after this.
STALE_PENDING_MINUTES = 10

# Seller-reference lookups (T106) look this far back: after a restore from backup,
# invoices fiscalised since the backup can be days older than the new sale.
REFERENCE_LOOKUP_DAYS = 60
# URA reports issuedDate in Uganda time as "dd/mm/yyyy HH:MM:SS" (checked on the URA
# sandbox, 29 Sep 2026). A record issued more than ISSUED_SKEW before the invoice was
# created cannot be this invoice. URA's issuedDate was seen up to ~8 minutes away from
# URA's own nowTime, and refusing our own record would fiscalise the sale twice, so the
# allowance is generous; invoices reused after a restore are hours or days older.
URA_TIMEZONE = "Africa/Kampala"
ISSUED_SKEW = timedelta(minutes=15)
# T106 filters referenceNo by exact match and URA keeps references unique per TIN, so a
# lookup returns at most one record; paging is only a safety net (URA's page.pageCount).
REFERENCE_LOOKUP_PAGE_SIZE = 10
REFERENCE_LOOKUP_MAX_PAGES = 5
# A reference found at URA for another invoice moves to "<reference>-R<n>"
MAX_REFERENCE_BUMPS = 5
# URA's T109 answer when the Seller Reference No. was already used under the TIN
DUPLICATE_REFERENCE_ERROR = re.compile(r"same seller'?s reference number.*already been issued", re.I | re.S)

JOB_QUEUE = "default"
JOB_TIMEOUT = 600  # make_post may do two HTTP calls with a 120 s timeout each
# A claim outlives the job that holds it (RQ kills the job at JOB_TIMEOUT), so an expired
# claim always belongs to a dead job and may be taken over.
CLAIM_LEASE = timedelta(seconds=JOB_TIMEOUT + 60)


class EfrisRetryLater(Exception):
	"""Submission cannot happen yet (e.g. original invoice of a return not fiscalised)."""


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def get_efris_settings(company):
	"""Enabled E Invoicing Settings for ``company`` or None. Never throws."""
	if not company:
		return None
	name = frappe.db.get_value("E Invoicing Settings", {"company": company, "enabled": 1}, "name")
	if not name:
		return None
	return frappe.db.get_value(
		"E Invoicing Settings",
		name,
		[
			"name",
			"company",
			"sandbox_mode",
			"device_no",
			"auto_send_submitted_invoice",
			"sales_invoice_submission",
			"efris_max_attempts",
			"seller_reference_prefix",
		],
		as_dict=True,
	)


def get_max_attempts(settings):
	return cint(settings and settings.get("efris_max_attempts")) or DEFAULT_MAX_ATTEMPTS


def get_backoff_minutes(attempts):
	"""15, 30, 60, 120 ... minutes, capped at 12 h. ``attempts`` = failed attempts so far (>=1)."""
	attempts = max(cint(attempts), 1)
	return min(BACKOFF_BASE_MINUTES * (2 ** (attempts - 1)), BACKOFF_CAP_MINUTES)


def is_efris_applicable(doc, settings=None):
	if doc.doctype not in SUPPORTED_DOCTYPES:
		return False
	if not cint(doc.get("efris_invoice")) or cint(doc.get("is_consolidated")):
		return False
	settings = settings or get_efris_settings(doc.company)
	return bool(settings)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _set_state(doc, **values):
	"""Persist EFRIS tracking fields without touching `modified` or re-running validations."""
	frappe.db.set_value(doc.doctype, doc.name, values, update_modified=False)
	for key, value in values.items():
		doc.set(key, value)


def get_fiscal_state(doc):
	"""Return (fdn, einvoice_name) if the invoice already has an EFRIS document.

	For a normal invoice this is the FDN. For a return it is the credit note
	application (a return is "submitted" once URA has the application; approval is
	tracked separately via ``efris_einvoice_status``).
	"""
	fdn = frappe.db.get_value(doc.doctype, doc.name, "efris_irn")
	einvoice = frappe.db.get_value(
		"E Invoice",
		{"invoice": doc.name},
		["name", "irn", "status", "credit_note_application_ref_no"],
		as_dict=True,
	)
	if cint(doc.get("is_return")):
		if einvoice and (einvoice.credit_note_application_ref_no or einvoice.irn):
			return einvoice.irn or einvoice.credit_note_application_ref_no, einvoice.name
		return None, None
	if fdn:
		return fdn, einvoice and einvoice.name
	if einvoice and einvoice.irn:
		return einvoice.irn, einvoice.name
	return None, None


def log_failed_request(doc, error, interface_code=None, traceback=None):
	"""Always-on failure record (make_post only logs URA round-trips, not transport errors)."""
	return (
		frappe.get_doc(
			{
				"doctype": "E Invoice Request Log",
				"user": frappe.session.user,
				"timestamp": now_datetime(),
				"reference_doc_type": doc.doctype,
				"reference_document": doc.name,
				"status": "Failed",
				"interface_code": interface_code or ("T110" if cint(doc.get("is_return")) else "T109"),
				"error_message": (error or "")[:1000],
				"response_data": frappe.as_json({"error": error}),
				"response_full": frappe.as_json({"error": error, "traceback": traceback}),
				"request_data": "{}",
				"request_full": "{}",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


def job_id_for(doctype, name):
	return f"efris-submit::{frappe.local.site}::{doctype}::{name}"


def enqueue_efris_submission(doctype, name, manual=False):
	frappe.enqueue(
		"uganda_compliance.efris.efris_queue.process_efris_submission",
		queue=JOB_QUEUE,
		timeout=JOB_TIMEOUT,
		job_id=job_id_for(doctype, name),
		deduplicate=True,
		enqueue_after_commit=True,
		doctype=doctype,
		name=name,
		manual=manual,
	)


def make_seller_reference(doc, settings):
	"""Seller Reference No. for URA: unique per TIN across systems (URA rejects reuse).

	Also the idempotency key for the T106 lookup, so it is stored on the invoice before the
	first attempt. It only changes when URA holds another invoice under it
	(``_bump_seller_reference``, e.g. after a restore from backup).
	"""
	prefix = (settings.get("seller_reference_prefix") or "").strip()
	return (f"{prefix}-{doc.name}" if prefix else doc.name)[:50]


def ensure_seller_reference(doc, settings):
	if not doc.get("efris_seller_reference_no"):
		_set_state(doc, efris_seller_reference_no=make_seller_reference(doc, settings))


def queue_efris_submission(doc):
	"""Flag ``doc`` Pending and enqueue the background submission."""
	_set_state(doc, efris_status=STATUS_PENDING, efris_next_retry=None)
	enqueue_efris_submission(doc.doctype, doc.name)


def on_submit_invoice(doc, method=None):
	"""doc_event on_submit for Sales Invoice and POS Invoice. Must never block the sale."""
	settings = get_efris_settings(doc.company)
	if not is_efris_applicable(doc, settings):
		return
	if not cint(settings.auto_send_submitted_invoice):
		# Manual mode: the user sends from the form ("Send to EFRIS").
		return

	ensure_seller_reference(doc, settings)

	if doc.doctype == "Sales Invoice" and settings.sales_invoice_submission == "Synchronous":
		# Legacy blocking mode (opt-in, Sales Invoice only): EFRIS errors abort the submit.
		e_invoice_api.on_submit_sales_invoice(doc, method)
		_set_state(doc, efris_status=STATUS_SUBMITTED, efris_last_error=None)
		return

	# Flag Pending + enqueue after commit. If Redis is down when the commit hook pushes
	# the job, the invoice stays Pending and the hourly sweep re-queues it.
	queue_efris_submission(doc)


def on_cancel_invoice(doc, method=None):
	"""EFRIS documents cannot be deleted: a fiscalised invoice must be reversed by a
	Return (credit note application), not cancelled."""
	if doc.doctype not in SUPPORTED_DOCTYPES or not cint(doc.get("efris_invoice")):
		return
	if cint(doc.get("is_consolidated")):
		return

	fdn, _einvoice = get_fiscal_state(doc)
	if fdn:
		if cint(doc.get("is_return")):
			frappe.throw(
				_(
					"{0} {1} has an EFRIS credit note application ({2}). It cannot be cancelled; URA must reject it or a new sale must be made."
				).format(_(doc.doctype), doc.name, fdn),
				title=_("EFRIS Credit Note Exists"),
			)
		frappe.throw(
			_(
				"{0} {1} has been fiscalised by EFRIS (FDN {2}). Fiscal documents cannot be cancelled; create a Return (credit note) instead."
			).format(_(doc.doctype), doc.name, fdn),
			title=_("EFRIS Invoice Cannot Be Cancelled"),
		)

	if frappe.db.get_value(doc.doctype, doc.name, "efris_status") == STATUS_SUBMITTING:
		# The row lock is no longer held during the URA call: without this check the invoice
		# could be cancelled here and fiscalised by the running job a moment later.
		frappe.throw(
			_("{0} {1} is being sent to EFRIS right now. Try again in a few minutes.").format(
				_(doc.doctype), doc.name
			),
			title=_("EFRIS Submission In Progress"),
		)

	if doc.get("efris_status") in (STATUS_PENDING, STATUS_FAILED):
		_set_state(doc, efris_status=STATUS_CANCELLED, efris_next_retry=None)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def _lock_invoice(doctype, name):
	frappe.db.sql(f"select name from `tab{doctype}` where name=%s for update", name)


def process_efris_submission(doctype, name, manual=False):
	"""Background job (also used by the manual endpoint). Returns a result dict.

	Commits: the claim, the invoice's E Invoice (before the URA call) and the result are
	committed separately so that no row lock is held while URA is called.
	"""
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("EFRIS submission is not supported for {0}").format(doctype))

	frappe.flags.efris_failed_requests_logged = set()  # filled by make_post's request log
	doc, settings, result = _claim(doctype, name, manual)
	frappe.db.commit()  # publish the claim (or the skip) and release the row lock
	if result:
		return result

	# Idempotency 2: a previous attempt may have reached URA even though we did not get
	# the answer (timeout, worker killed). Look the invoice up before sending again.
	is_retry = cint(doc.efris_attempts) > 1
	frappe.db.savepoint("efris_submission")
	try:
		if cint(doc.is_return):
			_submit_credit_note(doc)
		elif not (is_retry and _recover_fdn_from_ura(doc, settings)):
			_submit_invoice(doc, settings)
	except Exception as e:
		frappe.db.rollback(save_point="efris_submission")
		frappe.clear_last_message()
		retry_later = isinstance(e, EfrisRetryLater)
		error = _clean_error(e)
		_mark_failed(doc, error, settings, traceback=None if retry_later else frappe.get_traceback())
		frappe.db.commit()
		return _result(doc, "failed", error)

	_mark_submitted(doc)
	frappe.db.commit()
	fdn, _einvoice = get_fiscal_state(doc)
	return _result(doc, "submitted", fdn=fdn)


def _claim(doctype, name, manual):
	"""Lock the invoice, decide whether it must be sent and, if so, claim it.

	Returns ``(doc, settings, None)`` when claimed or ``(doc, settings, result)`` when there
	is nothing to send. The caller commits either way, which releases the lock.
	"""
	_lock_invoice(doctype, name)
	doc = frappe.get_doc(doctype, name)

	if doc.docstatus == 2:
		if doc.get("efris_status") in (STATUS_PENDING, STATUS_FAILED):
			_set_state(doc, efris_status=STATUS_CANCELLED, efris_next_retry=None)
		return doc, None, _result(doc, "skipped", _("Invoice is cancelled"))
	if doc.docstatus != 1:
		return doc, None, _result(doc, "skipped", _("Invoice is not submitted"))

	settings = get_efris_settings(doc.company)
	if not is_efris_applicable(doc, settings):
		return doc, settings, _result(doc, "skipped", _("EFRIS is not enabled for this invoice/company"))

	# Idempotency 1: never re-send an invoice that already has an FDN / credit note application.
	fdn, _einvoice = get_fiscal_state(doc)
	if fdn:
		_mark_submitted(doc)
		return doc, settings, _result(doc, "already_submitted", fdn=fdn)

	was_claimed = doc.get("efris_status") == STATUS_SUBMITTING
	if was_claimed and _claim_is_live(doc):
		return doc, settings, _result(doc, "in_progress", _("Another job is sending this invoice to EFRIS"))

	attempts = cint(doc.get("efris_attempts"))
	if not manual and attempts >= get_max_attempts(settings):
		if was_claimed:
			# last attempt died mid-call: the next (manual) attempt looks it up at URA first
			_mark_failed(doc, _("The EFRIS job stopped while waiting for URA"), settings)
		return doc, settings, _result(doc, "max_attempts", doc.get("efris_last_error"))

	ensure_seller_reference(doc, settings)
	_set_state(
		doc,
		efris_status=STATUS_SUBMITTING,
		efris_attempts=attempts + 1,
		efris_next_retry=now_datetime() + CLAIM_LEASE,
	)
	return doc, settings, None


def _claim_is_live(doc):
	return bool(doc.get("efris_next_retry")) and get_datetime(doc.efris_next_retry) > now_datetime()


def _commit_before_ura_call():
	"""Creating the E Invoice writes the invoice row (``efris_e_invoice``): commit it so the
	URA call does not hold that row lock. A draft E Invoice left by a failed attempt is
	reused by the next one."""
	frappe.db.commit()
	frappe.db.savepoint("efris_submission")


def _result(doc, outcome, message=None, fdn=None):
	return {
		"doctype": doc.doctype,
		"name": doc.name,
		"outcome": outcome,
		"efris_status": frappe.db.get_value(doc.doctype, doc.name, "efris_status"),
		"fdn": fdn,
		"message": message,
	}


def _clean_error(exc):
	return frappe.utils.strip_html(str(exc) or exc.__class__.__name__)[:1000]


def _mark_submitted(doc):
	_set_state(doc, efris_status=STATUS_SUBMITTED, efris_last_error=None, efris_next_retry=None)


def _mark_failed(doc, error, settings, traceback=None):
	attempts = cint(doc.get("efris_attempts"))  # counted when the invoice was claimed
	max_attempts = get_max_attempts(settings)
	if attempts >= max_attempts:
		next_retry = None
		error_text = _("{0} (gave up after {1} attempts; use Send to EFRIS to retry)").format(error, attempts)
		frappe.log_error(
			title=f"EFRIS: {doc.doctype} {doc.name} not fiscalised after {attempts} attempts",
			message=error,
			reference_doctype=doc.doctype,
			reference_name=doc.name,
		)
	else:
		next_retry = now_datetime() + timedelta(minutes=get_backoff_minutes(attempts))
		error_text = error

	_set_state(
		doc,
		efris_status=STATUS_FAILED,
		efris_last_error=error_text,
		efris_next_retry=next_retry,
	)
	if not _ura_failure_already_logged(doc):
		log_failed_request(doc, error, traceback=traceback)
	efris_log_info(f"EFRIS submission failed for {doc.doctype} {doc.name} (attempt {attempts}): {error}")


def _ura_failure_already_logged(doc):
	"""``make_post`` already wrote a Failed request log for this attempt (URA rejected it)."""
	interface_code = "T110" if cint(doc.get("is_return")) else "T109"
	return (doc.doctype, doc.name, interface_code) in (frappe.flags.efris_failed_requests_logged or ())


def _submit_invoice(doc, settings):
	"""T109. ``EInvoiceAPI.generate_irn`` throws on any URA/transport error.

	When URA answers that the Seller Reference No. was already issued (a tenant
	restored from backup reuses invoice names URA has fiscalised), the reference is
	looked up: our own earlier attempt is adopted, another invoice's moves this
	invoice to the next free reference, which is sent once more.
	"""
	e_invoice_api.EInvoiceAPI.create_einvoice(doc.name, source_doctype=doc.doctype)
	_commit_before_ura_call()
	try:
		e_invoice_api.EInvoiceAPI.generate_irn(frappe.as_json(doc))
	except frappe.ValidationError as e:
		if not DUPLICATE_REFERENCE_ERROR.search(str(e)):
			raise
		frappe.db.rollback(save_point="efris_submission")
		frappe.clear_last_message()
		reference = doc.efris_seller_reference_no
		if _recover_fdn_from_ura(doc, settings):
			return
		if doc.efris_seller_reference_no == reference:
			raise
		e_invoice_api.EInvoiceAPI.generate_irn(frappe.as_json(doc))


def _submit_credit_note(doc):
	"""T110 credit note application for a Return (Sales Invoice or POS Invoice)."""
	if not doc.return_against:
		raise frappe.ValidationError(_("Return has no original invoice (Return Against)"))

	original_fdn = frappe.db.get_value(doc.doctype, doc.return_against, "efris_irn")
	original_einvoice = e_invoice_api.get_einvoice(doc.return_against)
	if (
		not original_fdn
		or not original_einvoice
		or original_einvoice.status
		not in (
			"EFRIS Generated",
			"EFRIS Credit Note Pending",
		)
	):
		raise EfrisRetryLater(
			_("Original invoice {0} is not fiscalised yet; the credit note will be sent after it is.").format(
				doc.return_against
			)
		)

	e_invoice_api.EInvoiceAPI.create_einvoice(doc.name, source_doctype=doc.doctype)
	_commit_before_ura_call()
	e_invoice_api.EInvoiceAPI.generate_credit_note_return_application(doc)
	frappe.db.set_value(
		doc.doctype,
		doc.name,
		"efris_einvoice_status",
		"EFRIS Credit Note Pending",
		update_modified=False,
	)


def _recover_fdn_from_ura(doc, settings):
	"""Look up the invoice's Seller Reference No. at URA (T106) before sending it again.

	* This invoice's own record (an earlier attempt reached URA but the answer was
	  lost): adopt its FDN (details via T108) instead of fiscalising it twice.
	* Another invoice's record (another system on the TIN, or — after a restore from
	  backup — the invoice that had this name before): the reference can never be
	  accepted, so the invoice moves to the next free reference. Our own attempts
	  under the old reference were all rejected by URA as duplicates, so this can
	  not fiscalise the sale twice.

	Returns True when the invoice was found and recorded locally.
	"""
	for _attempt in range(MAX_REFERENCE_BUMPS + 1):
		records = _ura_records_for_reference(doc, settings, doc.get("efris_seller_reference_no") or doc.name)
		if not records:
			return False
		own = next((r for r in records if _is_own_ura_record(r, doc, settings)), None)
		if own:
			_adopt_ura_record(doc, own)
			return True
		_bump_seller_reference(doc, records[0])
	raise frappe.ValidationError(
		_("Seller Reference No. of {0} is still in use at URA after {1} changes").format(
			doc.name, MAX_REFERENCE_BUMPS
		)
	)


def _ura_records_for_reference(doc, settings, reference_no):
	"""URA records (T106) issued under ``reference_no``; None when the lookup failed.

	Reads every page URA reports (``page.pageCount``), at most REFERENCE_LOOKUP_MAX_PAGES.
	"""
	records = []
	for page_no in range(1, REFERENCE_LOOKUP_MAX_PAGES + 1):
		query = {
			"referenceNo": reference_no,
			"deviceNo": settings.device_no or "",
			"invoiceType": "1",
			"startDate": str(add_days(getdate(doc.posting_date), -REFERENCE_LOOKUP_DAYS)),
			"endDate": str(add_days(getdate(), 1)),
			"pageNo": str(page_no),
			"pageSize": str(REFERENCE_LOOKUP_PAGE_SIZE),
		}
		ok, response = e_invoice_api.make_post(
			interfaceCode="T106",
			content=query,
			company_name=doc.company,
			reference_doc_type=doc.doctype,
			reference_document=doc.name,
		)
		if not ok or not isinstance(response, dict):
			efris_log_info(f"EFRIS T106 lookup failed for {doc.name} (page {page_no}): {response}")
			# records already read are still URA's answer; none read means unknown
			return records or None
		records += [
			r
			for r in response.get("records") or []
			if r.get("referenceNo") == reference_no and r.get("invoiceNo")
		]
		page_count = cint((response.get("page") or {}).get("pageCount"))
		if page_no >= page_count:
			return records
	efris_log_info(
		f"EFRIS T106 lookup for {doc.name}: more than {REFERENCE_LOOKUP_MAX_PAGES} pages "
		f"for reference {reference_no}; using the first {len(records)} records"
	)
	return records


def _is_own_ura_record(record, doc, settings):
	"""Could URA's ``record`` be this invoice? Same device, same gross amount, and not
	issued before the invoice existed."""
	if record.get("deviceNo") and settings.device_no and record.get("deviceNo") != settings.device_no:
		return False
	gross = record.get("grossAmount")
	if gross not in (None, "") and abs(flt(gross) - flt(doc.grand_total)) > 1:
		return False
	issued = ura_issued_at(record.get("issuedDate"))
	return not issued or issued >= get_datetime(doc.creation) - ISSUED_SKEW


def ura_issued_at(value):
	"""URA's issuedDate (Uganda time, "dd/mm/yyyy HH:MM:SS"; ISO also accepted) as a naive
	system-time datetime; None when unreadable."""
	for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
		try:
			issued = datetime.strptime((value or "").strip()[:19], fmt)
		except ValueError:
			continue
		return (
			issued.replace(tzinfo=ZoneInfo(URA_TIMEZONE))
			.astimezone(ZoneInfo(get_system_timezone()))
			.replace(tzinfo=None)
		)
	return None


def _bump_seller_reference(doc, taken_by):
	"""Move ``doc`` to the next reference: ``<reference>-R1``, ``-R2`` ... (50 chars max)."""
	current = doc.get("efris_seller_reference_no") or doc.name
	match = re.match(r"^(.*)-R(\d+)$", current)
	root, n = (match.group(1), cint(match.group(2)) + 1) if match else (current, 1)
	suffix = f"-R{n}"
	new_reference = root[: 50 - len(suffix)] + suffix
	message = _(
		"EFRIS: Seller Reference No. {0} is already used at URA by FDN {1} (issued {2}), "
		"e.g. after a restore from backup. This invoice is sent as {3}."
	).format(current, taken_by.get("invoiceNo"), taken_by.get("issuedDate") or "?", new_reference)
	_set_state(doc, efris_seller_reference_no=new_reference)
	doc.add_comment("Comment", message)
	efris_log_info(message)
	# the old reference is taken at URA for good: keep the new one even if this attempt
	# fails, and do not hold the invoice row lock during the next URA call
	_commit_before_ura_call()


def _adopt_ura_record(doc, record):
	ok, details = e_invoice_api.make_post(
		interfaceCode="T108",
		content={"invoiceNo": record["invoiceNo"]},
		company_name=doc.company,
		reference_doc_type=doc.doctype,
		reference_document=doc.name,
	)
	if not ok or not isinstance(details, dict):
		raise frappe.ValidationError(
			_("Invoice {0} exists at URA as {1} but its details could not be fetched: {2}").format(
				doc.name, record["invoiceNo"], details
			)
		)

	einvoice = e_invoice_api.EInvoiceAPI.create_einvoice(doc.name, source_doctype=doc.doctype)
	einvoice.fetch_invoice_details()
	e_invoice_api.EInvoiceAPI.handle_successful_irn_generation(einvoice, details)
	efris_log_info(f"EFRIS: recovered FDN {record['invoiceNo']} for {doc.doctype} {doc.name}")


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def retry_pending_efris_submissions():
	"""Hourly: re-enqueue Pending/Failed EFRIS submissions whose back-off has elapsed."""
	now = now_datetime()
	stale_pending = now - timedelta(minutes=STALE_PENDING_MINUTES)
	settings_cache = {}
	queued = []

	for doctype in SUPPORTED_DOCTYPES:
		rows = frappe.get_all(
			doctype,
			filters={
				"docstatus": 1,
				"efris_invoice": 1,
				"efris_status": ["in", [STATUS_PENDING, STATUS_FAILED, STATUS_SUBMITTING]],
			},
			fields=[
				"name",
				"company",
				"efris_status",
				"efris_attempts",
				"efris_next_retry",
				"modified",
				"creation",
			],
			order_by="creation asc",
			limit=SWEEP_BATCH_SIZE,
		)
		for row in rows:
			if row.company not in settings_cache:
				settings_cache[row.company] = get_efris_settings(row.company)
			settings = settings_cache[row.company]
			if not settings:
				continue
			if row.efris_status != STATUS_SUBMITTING and cint(row.efris_attempts) >= get_max_attempts(
				settings
			):
				continue
			if row.efris_status in (STATUS_FAILED, STATUS_SUBMITTING):
				# Failed: back-off; Submitting: claim lease (only a dead job's claim expires)
				if row.efris_next_retry and get_datetime(row.efris_next_retry) > now:
					continue
			elif get_datetime(row.creation) > stale_pending and not row.efris_attempts:
				# fresh Pending: its on_submit job is (probably) still queued
				continue
			enqueue_efris_submission(doctype, row.name)
			queued.append((doctype, row.name))

	if queued:
		efris_log_info(f"EFRIS sweep queued {len(queued)} invoice(s)")
	return queued


# ---------------------------------------------------------------------------
# Whitelisted endpoints
# ---------------------------------------------------------------------------


def _extract_name(doc_or_name):
	"""Accept a name, or (legacy clients) a JSON/dict doc from which ONLY the name is used."""
	if isinstance(doc_or_name, str):
		stripped = doc_or_name.strip()
		if stripped.startswith("{"):
			try:
				doc_or_name = json.loads(stripped)
			except ValueError:
				frappe.throw(_("Invalid document"))
		else:
			return stripped, None
	if isinstance(doc_or_name, dict):
		return doc_or_name.get("name"), doc_or_name.get("doctype")
	if hasattr(doc_or_name, "name"):
		return doc_or_name.name, getattr(doc_or_name, "doctype", None)
	return None, None


def load_invoice_for_efris(doctype, doc_or_name, ptype="submit"):
	"""Check permission, then load the invoice server-side by name.

	The client may send a doc (legacy JS); everything except its name is ignored so a
	forged/edited client document can never be fiscalised.
	"""
	name, doc_doctype = _extract_name(doc_or_name)
	if doctype not in SUPPORTED_DOCTYPES or (doc_doctype and doc_doctype != doctype):
		frappe.throw(_("Expected a Sales Invoice or POS Invoice"))
	if not name or not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} not found").format(_(doctype), name or ""), frappe.DoesNotExistError)
	if not frappe.has_permission(doctype, ptype, name):
		frappe.throw(
			_("Not permitted to {0} {1} {2}").format(ptype, _(doctype), name), frappe.PermissionError
		)
	return frappe.get_doc(doctype, name)


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=30, seconds=60)
def send_invoice_to_efris(doctype, name):
	"""Manual "Send to EFRIS" / "Retry EFRIS". Runs synchronously and returns the outcome."""
	doc = load_invoice_for_efris(doctype, name, "submit")
	if doc.docstatus != 1:
		frappe.throw(_("Only submitted invoices can be sent to EFRIS"))
	if not cint(doc.get("efris_invoice")):
		frappe.throw(_("{0} is not an EFRIS invoice").format(doc.name))
	if cint(doc.get("is_consolidated")):
		frappe.throw(_("Consolidated invoices are fiscalised through their POS Invoices"))
	if not get_efris_settings(doc.company):
		frappe.throw(_("E Invoicing is not enabled for company {0}").format(doc.company))

	return process_efris_submission(doc.doctype, doc.name, manual=True)


@frappe.whitelist()
def get_efris_status(doctype, name):
	doc = load_invoice_for_efris(doctype, name, "read")
	fdn, einvoice = get_fiscal_state(doc)
	return {
		"efris_status": doc.get("efris_status"),
		"efris_einvoice_status": doc.get("efris_einvoice_status"),
		"efris_attempts": doc.get("efris_attempts"),
		"efris_last_error": doc.get("efris_last_error"),
		"efris_next_retry": doc.get("efris_next_retry"),
		"fdn": fdn,
		"e_invoice": einvoice,
	}
