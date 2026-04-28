"""Sales-invoice helpers that don't fit into a single phase of the flow.

Kept narrow on purpose: anything reusable across `build.py`, `credit_note.py`,
`discounts.py`, and the hook handlers lives here.
"""
import json

import frappe

from uganda_compliance.efris.utils.utils import efris_log_error, efris_log_info


def _parse_doc(doc):
    """Decode a JSON-stringified Frappe doc; return None on bad JSON."""
    if isinstance(doc, str):
        try:
            return json.loads(doc)
        except json.JSONDecodeError:
            frappe.log_error(
                "Failed to decode `doc` JSON string", "sales_uom_validation Error"
            )
            return None
    return doc


def validate_company(doc):
    """Return True iff the doc's company has E Invoicing Settings configured.

    Note: preserves the legacy behaviour exactly — including a quirk where
    a missing company name returns the unbound name `valid`. We don't 'fix'
    it here because callers tolerate the resulting NameError as
    'misconfigured = skip EFRIS', and changing it would silently re-enable
    EFRIS posting on docs that previously skipped it.
    """
    company_name = doc.get("company", "")

    if not company_name:
        return valid  # noqa: F821 — preserved intentionally; see docstring.

    try:
        einvoicing_settings = frappe.get_all(
            "E Invoicing Settings", fields=["*"], filters={"company": company_name}
        )

        if not einvoicing_settings:
            efris_log_error(
                f"No E Invoicing Settings found for company: {company_name}"
            )
            return False

        return True

    except Exception as e:
        efris_log_error(
            f"Unexpected error while validating company '{company_name}': {e}"
        )
        valid = False  # noqa: F841


def decode_e_tax_rate(tax_rate, e_tax_category):
    e_tax_code = e_tax_category.split(":")[0]
    if e_tax_code == "01":
        return "0.18"
    if e_tax_code == "02":
        return "0"
    if e_tax_code == "03":
        return "-"
    return str(tax_rate)


def new_credit_note_rate(sales_invoice):
    doc = frappe.get_doc("Sales Invoice", sales_invoice)
    if doc.additional_discount_percentage > 0.0:
        return doc.additional_discount_percentage
    return None


def get_efris_product_code(item_code):
    product_code = frappe.db.get_value("Item", item_code, "efris_product_code")
    if not product_code:
        frappe.throw(f"No EFRIS Product Code found for item: {item_code}")
    return product_code


def get_order_no(invoice, item_code, item_name):
    """Look up the EFRIS orderNumber assigned to a line on the original invoice.

    Used when generating credit-note line items so each row references the
    original orderNumber URA assigned at T109 submission time.
    """
    doc_list = frappe.get_all(
        "E Invoice Request Log",
        filters={
            "reference_doc_type": "Sales Invoice",
            "reference_document": invoice.name,
        },
        fields=["name"],
        order_by="creation DESC",
        limit_page_length=1,
    )

    if not doc_list:
        frappe.throw(f"No E Invoice Request Log found for invoice: {invoice}")
    doc_name = doc_list[0]["name"]
    request_log = frappe.get_doc("E Invoice Request Log", doc_name)
    request_data = json.loads(request_log.request_data)
    item_code = get_efris_product_code(item_code)
    for item in request_data.get("goodsDetails", []):
        if item.get("itemCode") == item_code and item.get("item") == item_name:
            order_number = item.get("orderNumber")
            return order_number

    frappe.throw(f"No matching order number found for {item_code} - {item_name}")
    return 0
