"""Sales-invoice additional-discount calculation.

URA wants per-row discount + tax adjustments computed locally and stamped
onto the EFRIS-specific item fields (`efris_dsct_*`). This is the only
non-trivial maths in the sales-invoice flow.
"""
import frappe

from uganda_compliance.efris.utils.utils import efris_log_info

from .utils import _parse_doc


def calculate_additional_discounts(doc, method):
    """Stamp `efris_dsct_*` on each item when the invoice carries a header discount."""
    doc = _parse_doc(doc)
    efris_log_info(f"Calculate Additional Discounts called: {doc}")

    discount_percentage = doc.get("additional_discount_percentage", 0) or 0.0
    efris_log_info(f"Issued Discount: {discount_percentage}%")

    if not discount_percentage or not doc.taxes:
        return

    item_taxes: list[dict] = doc.item_wise_tax_details
    initial_tax = doc.total_taxes_and_charges  # noqa: F841 — preserved for log parity.
    efris_log_info(f"Initial Tax: {initial_tax}")

    _process_items(doc, item_taxes, discount_percentage)


def _process_items(doc, item_taxes, discount_percentage):
    total_item_tax = 0.0
    total_discount_tax = 0.0
    discount_amounts = []

    for idx, row in enumerate(doc.get("items", [])):
        item_code = row.get("item_code", "")
        discount_amount = round(-row.amount * (discount_percentage / 100), 4)
        discount_amounts.append(
            {"item_code": item_code, "discount_amount": discount_amount}
        )

        discounted_item = f"{row.get('item_name', '')} (Discount)"
        tax_rate = item_taxes[idx].rate

        if tax_rate > 0:
            _, discount_tax, item_tax = _calculate_tax_adjustments(
                discount_amount, tax_rate, row.amount
            )
            total_item_tax += item_tax
            total_discount_tax += discount_tax
        else:
            discount_tax = 0.0
            item_tax = 0.0

        _update_row_values(
            row,
            discount_amount,
            discount_tax,
            tax_rate,
            item_tax,
            discounted_item,
            doc.get("is_return", False),
        )

    return total_item_tax, total_discount_tax


def _calculate_tax_adjustments(discount_amount, tax_rate, item_amount):
    tax_on_discount = round(discount_amount / (1 + (tax_rate / 100)), 4)
    discount_tax = round(discount_amount - tax_on_discount, 4)
    item_tax = round(item_amount * (tax_rate / (100 + tax_rate)), 4)
    return tax_on_discount, discount_tax, item_tax


def _update_row_values(
    row, discount_amount, discount_tax, tax_rate, item_tax, discounted_item, is_return
):
    values = {
        "efris_dsct_discount_total": -discount_amount if is_return else discount_amount,
        "efris_dsct_discount_tax": -discount_tax if is_return else discount_tax,
        "efris_dsct_discount_tax_rate": (
            f"{tax_rate / 100:.2f}" if tax_rate > 0 else "0.0"
        ),
        "efris_dsct_item_tax": -item_tax if is_return else item_tax,
        "efris_dsct_taxable_amount": -row.amount if is_return else row.amount,
        "efris_dsct_item_discount": discounted_item,
    }
    for key, value in values.items():
        row.db_set(key, value)
    frappe.db.commit()
