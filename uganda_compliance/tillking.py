"""Till King provisioning helpers for EFRIS.

Called by the Till King vendor app through ``bench execute``:

    # at provisioning (sandbox)
    bench --site <tenant> execute uganda_compliance.tillking.configure_efris \
        --kwargs "{'company': 'Kampala Fresh Mart Ltd', 'tin': '1000000000', 'device_no': '1000000000_01'}"

    # at go-live
    bench --site <tenant> execute uganda_compliance.tillking.set_efris_mode \
        --kwargs "{'company': 'Kampala Fresh Mart Ltd', 'mode': 'Production'}"

    # after restoring the site from a backup (dry run first, then dry_run 0)
    bench --site <tenant> execute uganda_compliance.tillking.advance_series_after_restore \
        --kwargs "{'company': 'Kampala Fresh Mart Ltd', 'dry_run': 1}"

Private keys and key passwords are never passed on the command line: ops upload them
into E Invoicing Settings at onboarding. Until the key (and its password) for the
selected mode is present the settings stay *disabled*, so nothing is sent to URA.
"""

import re

import frappe
from frappe import _
from frappe.model.naming import NamingSeries
from frappe.utils import add_days, cint, getdate
from frappe.utils.password import get_decrypted_password

MODES = ("Sandbox", "Production")
DEFAULT_MAX_ATTEMPTS = 8


def _normalise_mode(mode):
	for m in MODES:
		if (mode or "").strip().lower() == m.lower():
			return m
	frappe.throw(_("EFRIS mode must be one of {0}").format(", ".join(MODES)))


def _password_is_set(settings_name, fieldname):
	try:
		return bool(
			get_decrypted_password("E Invoicing Settings", settings_name, fieldname, raise_exception=False)
		)
	except Exception:
		return False


def get_missing_credentials(settings):
	"""Credentials missing for the settings' current mode (list of field labels)."""
	missing = []
	if not settings.tin:
		missing.append("TIN")
	if not settings.device_no:
		missing.append("Device No")
	if cint(settings.sandbox_mode):
		if not settings.sandbox_private_key:
			missing.append("Sandbox Private Key")
		if settings.name and not _password_is_set(settings.name, "sandbox_private_key_password"):
			missing.append("Sandbox Private Key Password")
	else:
		if not settings.live_private_key:
			missing.append("Live Private Key")
		if settings.name and not _password_is_set(settings.name, "live_private_key_password"):
			missing.append("Live Private Key Password")
	return missing


def _smoke_test(settings):
	"""T119 taxpayer lookup of the company's own TIN with the configured key/URL."""
	from uganda_compliance.efris.api_classes.efris_api import make_post

	ok, response = make_post(
		interfaceCode="T119",
		content={"tin": settings.tin, "ninBrn": ""},
		company_name=settings.company,
		reference_doc_type="E Invoicing Settings",
		reference_document=settings.name,
	)
	return ok, response


def configure_efris(
	company,
	tin=None,
	mode="Sandbox",
	device_no=None,
	brn=None,
	output_vat_account=None,
	input_vat_account=None,
	auto_send=1,
	sales_invoice_submission="Background",
	max_attempts=DEFAULT_MAX_ATTEMPTS,
	enable=True,
	smoke_test=None,
):
	"""Create/update the company's E Invoicing Settings. Idempotent.

	* ``mode``: "Sandbox" (default) or "Production".
	* ``enable``: enable EFRIS when the credentials for ``mode`` are complete. When
	  they are not, the settings are saved disabled and ``missing`` lists what ops must
	  upload.
	* ``smoke_test``: run a T119 TIN lookup after enabling (default: only for Production).
	  A failed Production smoke test raises, so the transaction (mode switch) is rolled back.

	Returns a dict without secrets.
	"""
	mode = _normalise_mode(mode)
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} not found").format(company))

	name = frappe.db.get_value("E Invoicing Settings", {"company": company}, "name")
	settings = (
		frappe.get_doc("E Invoicing Settings", name) if name else frappe.new_doc("E Invoicing Settings")
	)

	tin = tin or settings.tin or frappe.db.get_value("Company", company, "tax_id")
	if not tin:
		frappe.throw(_("EFRIS TIN is required"))
	device_no = device_no or settings.device_no
	if not device_no:
		frappe.throw(_("EFRIS device number is required (issued by URA with the TIN)"))

	settings.update(
		{
			"company": company,
			"tin": tin,
			"device_no": device_no,
			"sandbox_mode": 1 if mode == "Sandbox" else 0,
			"auto_send_submitted_invoice": cint(auto_send),
			"sales_invoice_submission": sales_invoice_submission,
			"efris_max_attempts": cint(max_attempts) or DEFAULT_MAX_ATTEMPTS,
		}
	)
	if brn is not None:
		settings.brn = brn
	if output_vat_account:
		settings.output_vat_account = output_vat_account
	if input_vat_account:
		settings.input_vat_account = input_vat_account

	if not frappe.db.get_value("Company", company, "tax_id"):
		frappe.db.set_value("Company", company, "tax_id", tin)

	missing = get_missing_credentials(settings)
	if mode == "Production" and missing:
		# Never disable a live tenant's EFRIS because go-live credentials are incomplete.
		frappe.throw(
			_("Cannot switch {0} to EFRIS Production; missing: {1}").format(company, ", ".join(missing)),
			title=_("EFRIS go-live blocked"),
		)
	settings.enabled = 1 if (enable and not missing) else 0
	settings.flags.ignore_permissions = True
	settings.flags.ignore_mandatory = True  # keys are uploaded by ops later
	settings.save()

	from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import (
		clear_e_company_settings_cache,
	)

	clear_e_company_settings_cache(company)

	if smoke_test is None:
		smoke_test = mode == "Production"
	smoke = None
	if smoke_test and settings.enabled:
		ok, response = _smoke_test(settings)
		smoke = {"ok": bool(ok), "message": None if ok else str(response)[:500]}
		if not ok and mode == "Production":
			# Raising rolls back this transaction, i.e. the previous mode is kept.
			frappe.throw(
				_("EFRIS Production smoke test (T119) failed; settings not changed: {0}").format(response),
				title=_("EFRIS go-live failed"),
			)

	return get_efris_config(company, _extra={"missing": missing, "smoke_test": smoke})


def set_efris_mode(company, mode, smoke_test=None):
	"""Switch an already configured company between Sandbox and Production (go-live)."""
	if not frappe.db.exists("E Invoicing Settings", {"company": company}):
		frappe.throw(_("EFRIS is not configured for {0}; call configure_efris first").format(company))
	return configure_efris(company, mode=mode, smoke_test=smoke_test)


def get_efris_config(company, _extra=None):
	"""Non-secret summary of the company's EFRIS configuration (for verify_provisioning)."""
	name = frappe.db.get_value("E Invoicing Settings", {"company": company}, "name")
	if not name:
		return {"company": company, "configured": False, "enabled": False}
	s = frappe.get_doc("E Invoicing Settings", name)
	out = {
		"company": company,
		"configured": True,
		"settings": s.name,
		"enabled": bool(s.enabled),
		"mode": "Sandbox" if cint(s.sandbox_mode) else "Production",
		"tin": s.tin,
		"device_no": s.device_no,
		"auto_send": bool(s.auto_send_submitted_invoice),
		"sales_invoice_submission": s.sales_invoice_submission,
		"max_attempts": s.efris_max_attempts,
		"missing": get_missing_credentials(s),
	}
	out.update(_extra or {})
	return out


# ---------------------------------------------------------------------------
# After a restore from backup
# ---------------------------------------------------------------------------

INVOICE_DOCTYPES = ("Sales Invoice", "POS Invoice")
RESTORE_LOOKUP_DAYS = 60
T106_PAGE_SIZE = 99
T106_MAX_PAGES = 50


def advance_series_after_restore(company, days=RESTORE_LOOKUP_DAYS, dry_run=True):
	"""Move the Sales/POS Invoice naming series past every invoice URA fiscalised for the
	company's device in the last ``days`` days.

	A site restored from a backup forgets the invoices fiscalised after the backup, and
	its series counters go back with it: new sales would reuse those invoice names (and
	Seller Reference Nos.), which URA rejects. Run this before reopening the tills.
	It reads URA (T106) only; ``dry_run`` (the default) changes nothing. Each counter
	only ever moves forward, and every change is recorded as a Version of the Series.

	Returns ``{series prefix: {"current", "last_fiscalised", "new"}}``.
	"""
	from uganda_compliance.efris.efris_queue import get_efris_settings

	settings = get_efris_settings(company)
	if not settings:
		frappe.throw(_("EFRIS is not enabled for {0}").format(company))

	own_prefix = f"{settings.seller_reference_prefix}-" if settings.seller_reference_prefix else ""
	series_prefixes = _invoice_series_prefixes()
	last = {}
	for reference in _fiscalised_references(company, settings, cint(days)):
		if not reference.startswith(own_prefix):
			continue  # another system on the same TIN
		name = re.sub(r"-R\d+$", "", reference[len(own_prefix) :])
		prefix = max((p for p in series_prefixes if name.startswith(p)), key=len, default=None)
		number = prefix and re.match(r"\d+", name[len(prefix) :])
		if number:
			last[prefix] = max(last.get(prefix, 0), int(number.group()))

	result = {}
	for prefix, number in sorted(last.items()):
		current = cint(frappe.db.get_value("Series", prefix, "current", order_by="name", for_update=True))
		result[prefix] = {"current": current, "last_fiscalised": number, "new": max(current, number)}
		if number > current and not cint(dry_run):
			_set_series_counter(prefix, current, number)

	frappe.logger("uganda_compliance").info(
		f"advance_series_after_restore {company} dry_run={cint(dry_run)}: {result}"
	)
	return result


def _invoice_series_prefixes():
	"""Counter keys (tabSeries names): this year's Sales/POS Invoice series, and every
	existing counter (earlier years). Only this site's invoice names are matched."""
	series = frappe.qb.DocType("Series")  # a table, not a DocType
	prefixes = set(frappe.qb.from_(series).select(series.name).run(pluck=True))
	for doctype in INVOICE_DOCTYPES:
		options = frappe.get_meta(doctype).get_field("naming_series").options or ""
		prefixes.update(NamingSeries(o.strip()).get_prefix() for o in options.split("\n") if o.strip())
	return prefixes


def _fiscalised_references(company, settings, days):
	"""Seller Reference Nos. of the invoices URA issued on the company's device (T106, paged)."""
	from uganda_compliance.efris.api_classes import e_invoice as e_invoice_api

	references = []
	for page in range(1, T106_MAX_PAGES + 1):
		ok, response = e_invoice_api.make_post(
			interfaceCode="T106",
			content={
				"deviceNo": settings.device_no or "",
				"invoiceType": "1",
				"startDate": str(add_days(getdate(), -days)),
				"endDate": str(add_days(getdate(), 1)),
				"pageNo": str(page),
				"pageSize": str(T106_PAGE_SIZE),
			},
			company_name=company,
			reference_doc_type="E Invoicing Settings",
			reference_document=settings.name,
		)
		if not ok or not isinstance(response, dict):
			# A partial list could leave a counter too low: fail rather than advance.
			frappe.throw(_("EFRIS invoice lookup (T106) failed: {0}").format(response))
		references += [r["referenceNo"] for r in response.get("records") or [] if r.get("referenceNo")]
		if page >= cint((response.get("page") or {}).get("pageCount")):
			return references
	frappe.throw(_("More than {0} pages of invoices at URA; use fewer days").format(T106_MAX_PAGES))


def _set_series_counter(prefix, old, new):
	series = frappe.qb.DocType("Series")
	if frappe.db.get_value("Series", prefix, "name", order_by="name") is not None:
		frappe.qb.update(series).set(series.current, new).where(series.name == prefix).run()
	else:
		frappe.qb.into(series).insert(prefix, new).columns("name", "current").run()
	version = frappe.new_doc("Version")
	version.ref_doctype = "Series"
	version.docname = prefix
	version.data = frappe.as_json({"changed": [["current", old, new]]})
	version.flags.ignore_links = True  # Series is not a real doctype
	version.insert(ignore_permissions=True)
