"""VAT-inclusive prices, computed the way URA computes them.

URA works from the VAT-inclusive line total: line tax = round(total x rate / (100 + rate), 2), and
Section E (taxDetails) must not be less than the sum of the goods-line taxes.

ERPNext instead back-calculates each line's net (amount / 1.18, rounded) and taxes the rounded
nets. Two prices of 2,500 x 2 and 2,000 x 1 (7,000 inclusive) give nets 4,237.29 + 1,694.92 and a
VAT row of 1,067.80, so net_total + VAT = 7,000.01 while the grand total is 7,000.00 (ERPNext posts
the cent to Round Off), and URA's own figure is 762.71 + 305.08 = 1,067.79.

``line_figures`` gives the URA figures per invoice row; ``reconcile_inclusive_vat`` (validate hook)
writes the same figures into ERPNext, so the line taxes, the VAT row, the EFRIS invoice and the
grand total agree to the cent.
"""

import json

import frappe
from erpnext.controllers.taxes_and_totals import get_itemised_tax_breakup_html
from frappe.utils import cint, flt

EFRIS_PRECISION = 2  # URA wants amounts and taxes with 2 decimals, whatever the currency precision


def vat_in(gross, rate, precision=EFRIS_PRECISION):
	"""VAT contained in a VAT-inclusive ``gross`` at ``rate`` percent."""
	return flt(flt(gross) * flt(rate) / (100 + flt(rate)), precision) if flt(rate) > 0 else 0.0


def allocate(total, weights, precision=EFRIS_PRECISION):
	"""Split ``total`` over ``weights`` pro rata; the last non-zero line takes the rounding rest,
	so the shares add up to ``total`` exactly."""
	weight_sum = sum(weights)
	shares = [0.0] * len(weights)
	if not flt(total, precision) or not weight_sum:
		return shares
	last = max(i for i, w in enumerate(weights) if w)
	for i, w in enumerate(weights):
		if i != last:
			shares[i] = flt(total * w / weight_sum, precision)
	shares[last] = flt(total - sum(shares), precision)
	return shares


def item_vat_rates(doc):
	"""Rate (percent) per item key, as resolved by ERPNext for the (single) VAT row."""
	if not doc.get("taxes"):
		return {}
	detail = doc.taxes[0].item_wise_tax_detail or "{}"
	detail = json.loads(detail) if isinstance(detail, str) else detail
	return {key: flt(value[0]) for key, value in detail.items()}


def _item_key(item):
	return item.item_code or item.item_name


def gross_discount(doc):
	"""The invoice discount as a VAT-inclusive amount (the one the customer sees)."""
	if doc.get("is_return"):
		return 0.0  # credit notes carry the discounted rates; see EInvoiceAPI credit note builder
	if (doc.get("apply_discount_on") or "Grand Total") == "Grand Total":
		return flt(doc.get("discount_amount"))
	return flt(flt(doc.get("total")) * flt(doc.get("additional_discount_percentage")) / 100, EFRIS_PRECISION)


def line_figures(doc):
	"""Per item row, the figures sent to URA: ``total`` and ``tax`` of the goods line and
	``discount_total`` / ``discount_tax`` of its discount line (negative or 0).

	``tax + discount_tax`` is the VAT on the discounted line, so the goods lines add up to the
	invoice VAT and ``total + discount_total`` to the grand total."""
	rates = item_vat_rates(doc)
	totals = [flt(item.amount, EFRIS_PRECISION) for item in doc.items]
	discounts = allocate(gross_discount(doc), totals)
	figures = []
	for item, total, discount in zip(doc.items, totals, discounts, strict=True):
		rate = rates.get(_item_key(item), 0.0)
		tax = vat_in(total, rate)
		figures.append(
			frappe._dict(
				rate=rate,
				total=total,
				tax=tax,
				discount_total=-discount,
				discount_tax=flt(vat_in(total - discount, rate) - tax, EFRIS_PRECISION),
			)
		)
	return figures


def _inclusive_vat_row(doc):
	"""The one VAT row this reconciliation handles: included in the price, On Net Total.

	Anything else (several tax rows, exclusive VAT, consolidated POS invoices whose taxes are
	copied from the POS invoices, discount on Net Total, cash discounts) is left to ERPNext."""
	taxes = doc.get("taxes") or []
	if len(taxes) != 1 or doc.get("is_consolidated"):
		return None
	tax = taxes[0]
	if (
		not cint(tax.included_in_print_rate)
		or tax.charge_type != "On Net Total"
		or tax.get("dont_recompute_tax")
	):
		return None
	if flt(doc.get("discount_amount")) and (
		doc.get("apply_discount_on") != "Grand Total" or doc.get("is_cash_or_non_trade_discount")
	):
		return None
	return tax


def reconcile_inclusive_vat(doc, method=None):
	"""Validate hook (Sales Invoice, POS Invoice): make each line's tax the VAT contained in its
	discounted inclusive amount, and the net the rest, so that

	    sum(line net) + sum(line tax) = net_total + VAT row = grand_total

	exactly, the VAT row equals what EFRIS reports, and no Round Off entry is posted.
	The grand total (what the customer pays) never changes."""
	tax = _inclusive_vat_row(doc)
	if not tax:
		return

	rates = item_vat_rates(doc)
	tax_precision = tax.precision("tax_amount")
	amounts = [flt(item.amount) for item in doc.items]
	discounts = allocate(flt(doc.discount_amount), amounts, doc.precision("discount_amount"))
	if flt(sum(amounts) - sum(discounts) - flt(doc.grand_total), doc.precision("grand_total")):
		return  # grand total is not total - discount (other charges): not a case handled here

	conversion_rate = flt(doc.conversion_rate) or 1
	net_total = tax_total = 0.0
	item_wise_tax = {}
	for item, amount, discount in zip(doc.items, amounts, discounts, strict=True):
		key = _item_key(item)
		gross = amount - discount
		line_tax = vat_in(gross, rates.get(key, 0.0), tax_precision)
		item.net_amount = flt(gross - line_tax, item.precision("net_amount"))
		item.net_rate = flt(item.net_amount / item.qty, item.precision("net_rate")) if item.qty else 0
		item.base_net_amount = flt(item.net_amount * conversion_rate, item.precision("base_net_amount"))
		item.base_net_rate = flt(item.net_rate * conversion_rate, item.precision("base_net_rate"))
		net_total += item.net_amount
		tax_total += line_tax
		if key in rates:
			previous = item_wise_tax.get(key, [rates[key], 0.0])[1]
			item_wise_tax[key] = [rates[key], flt(previous + line_tax * conversion_rate, tax_precision)]

	doc.net_total = flt(net_total, doc.precision("net_total"))
	doc.base_net_total = flt(doc.net_total * conversion_rate, doc.precision("base_net_total"))
	tax_total = flt(tax_total, tax_precision)
	base_tax_total = flt(doc.base_grand_total - doc.base_net_total, tax_precision)

	tax.tax_amount = tax.tax_amount_after_discount_amount = tax_total
	tax.base_tax_amount = tax.base_tax_amount_after_discount_amount = base_tax_total
	if tax.meta.has_field("net_amount"):
		tax.net_amount, tax.base_net_amount = doc.net_total, doc.base_net_total
	tax.total, tax.base_total = doc.grand_total, doc.base_grand_total
	tax.item_wise_tax_detail = json.dumps(item_wise_tax, separators=(",", ":"))
	doc.total_taxes_and_charges = tax_total
	doc.base_total_taxes_and_charges = base_tax_total
	if doc.meta.get_field("other_charges_calculation"):
		doc.other_charges_calculation = get_itemised_tax_breakup_html(doc)
