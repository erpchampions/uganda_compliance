"""Scheduled tasks for the EFRIS app."""

from __future__ import annotations

import frappe


def sync_dictionaries() -> None:
	"""Daily T115 sync — enqueue the shared EFRIS Dictionary refresh.

	The dictionary is company-independent (URA reference data), so a single
	call is enough. The actual sync runs on the ``long`` queue; this
	scheduler entrypoint just enqueues it.
	"""
	from efris.efris.api.dictionary import enqueue_sync

	if not frappe.db.exists("EFRIS Settings", {"enabled": 1}):
		return
	enqueue_sync()


def sync_commodity_categories() -> None:
	"""Daily T124 sync — foreground page-1 + background drain (same path as the button)."""
	from efris.efris.api.commodity_category import sync_commodity_categories as run_sync

	if not frappe.db.exists("EFRIS Settings", {"enabled": 1}):
		return
	run_sync()
	frappe.db.commit()


def sync_excise_duty() -> None:
	"""Daily T125 sync — runs inline (small payload, no queue needed)."""
	from efris.efris.api.excise_duty import sync_excise_duty as run_sync

	if not frappe.db.exists("EFRIS Settings", {"enabled": 1}):
		return
	run_sync()
	frappe.db.commit()


def sync_exchange_rate() -> None:
	"""Daily T121 sync — store today's USD -> UGX rate in Currency Exchange.

	One call per enabled company so the rate lands against the right
	company-default (UGX) currency. ``save_exchange_rate`` defaults the issue
	date to today and upserts, so re-runs are idempotent.
	"""
	from efris.efris.api.exchange_rate import save_exchange_rate

	for company in frappe.get_all("EFRIS Settings", filters={"enabled": 1}, pluck="company"):
		try:
			save_exchange_rate("USD", company=company, to_currency="UGX")
		except Exception:
			frappe.log_error(title=f"EFRIS T121 USD->UGX sync failed ({company})")
	frappe.db.commit()
