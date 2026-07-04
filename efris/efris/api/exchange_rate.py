"""T121 Acquire Exchange Rate — whitelisted entry point for client-side use.

Returns the URA exchange rate for a given currency (and optional ISO-date).
The JS helper at ``efris/public/js/exchange_rate.js`` consumes this from any
transactional form (Sales Invoice, Purchase Invoice, …).

``save_exchange_rate`` additionally persists the fetched rate into ERPNext's
``Currency Exchange`` ledger (``foreign -> company currency``), so multi-currency
pricing can fall back on URA's published rate.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from efris.efris.api.client import efris_errors
from efris.efris.api.interfaces import get_exchange_rates as call_t121


_CURRENCY_EXCHANGE = "Currency Exchange"


@frappe.whitelist()
def fetch_rate(
	currency: str, issue_date: str | None = None, company: str | None = None
) -> dict:
	"""Return ``{currency, rate, importDutyLevy, inComeTax, exportLevy}``.

	``rate`` is coerced to float so the caller can drop it straight into a
	``conversion_rate`` field. The other levies are kept as returned by URA.
	"""
	if not currency:
		frappe.throw(_("Currency is required to fetch the EFRIS exchange rate."))

	payload_date = getdate(issue_date).isoformat() if issue_date else ""

	with efris_errors(_("EFRIS Exchange Rate Lookup Failed")):
		response = call_t121(currency=currency, issue_date=payload_date, company=company)

	if isinstance(response, list):
		response = response[0] if response else {}
	response = response or {}

	rate = flt(response.get("rate") or 0)
	if not rate:
		frappe.throw(_("EFRIS returned no exchange rate for {0}.").format(currency))

	return {
		"currency": response.get("currency") or currency,
		"rate": rate,
		"importDutyLevy": response.get("importDutyLevy"),
		"inComeTax": response.get("inComeTax"),
		"exportLevy": response.get("exportLevy"),
	}


@frappe.whitelist()
def save_exchange_rate(
	currency: str,
	issue_date: str | None = None,
	company: str | None = None,
	to_currency: str | None = None,
) -> dict:
	"""Fetch the EFRIS rate (T121) and upsert it into ``Currency Exchange``.

	The rate is stored as ``currency -> to_currency``. ``to_currency`` defaults
	to the company's default currency (URA quotes foreign currencies against
	UGX). ``issue_date`` defaults to today and becomes the Currency Exchange
	``date``. Re-running for the same date/pair updates the existing row instead
	of erroring on a duplicate.

	Returns ``{currency_exchange, from_currency, to_currency, rate, date}``.
	"""
	to_currency = to_currency or _company_currency(company)
	if not to_currency:
		frappe.throw(_("Company default currency is not set; cannot store the exchange rate."))
	if currency == to_currency:
		frappe.throw(_("{0} is the company currency; no exchange rate to store.").format(currency))

	date = (getdate(issue_date) if issue_date else getdate(nowdate())).isoformat()
	rate = fetch_rate(currency, issue_date=date, company=company)["rate"]

	name = _upsert_currency_exchange(date, currency, to_currency, rate)
	return {
		"currency_exchange": name,
		"from_currency": currency,
		"to_currency": to_currency,
		"rate": rate,
		"date": date,
	}


def _company_currency(company: str | None) -> str:
	"""Resolve the target (``to``) currency from the company's default currency."""
	company = company or frappe.defaults.get_global_default("company")
	if company:
		return frappe.db.get_value("Company", company, "default_currency") or ""
	return ""


def _upsert_currency_exchange(
	date: str, from_currency: str, to_currency: str, rate: float
) -> str:
	"""Create or update the Currency Exchange row for ``date`` / currency pair."""
	existing = frappe.db.get_value(
		_CURRENCY_EXCHANGE,
		{"date": date, "from_currency": from_currency, "to_currency": to_currency},
		"name",
	)
	if existing:
		doc = frappe.get_doc(_CURRENCY_EXCHANGE, existing)
		doc.exchange_rate = rate
	else:
		doc = frappe.new_doc(_CURRENCY_EXCHANGE)
		doc.date = date
		doc.from_currency = from_currency
		doc.to_currency = to_currency
		doc.exchange_rate = rate
		doc.for_buying = 1
		doc.for_selling = 1
	doc.save(ignore_permissions=True)
	return doc.name
