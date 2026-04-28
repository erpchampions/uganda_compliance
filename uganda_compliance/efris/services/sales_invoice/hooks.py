"""Doc-event handlers + whitelisted entry points for Sales Invoice.

Everything here is referenced by name from `uganda_compliance/hooks.py` or
called from client scripts via `frappe.call`. The actual heavy lifting is
delegated to `EInvoiceAPI`, the build/credit-note helpers, and `discounts`.
"""
import json

import frappe

from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import (
    get_e_company_settings,
)
from uganda_compliance.efris.utils.utils import efris_log_info

from .api import EInvoiceAPI
from .build import get_einvoice, validate_payment
from .utils import _parse_doc, new_credit_note_rate, validate_company


# ---------------------------------------------------------------------------
# Standard Frappe doc events
# ---------------------------------------------------------------------------


def after_save_sales_invoice(doc, method):
    doc = frappe.as_json(doc)
    sales_invoice = EInvoiceAPI.parse_sales_invoice(doc)
    if sales_invoice.is_return:
        return


def on_submit_sales_invoice(doc, method):
    """EFRIS submission entry on Sales Invoice submit.

    Skips unless the company has `auto_send_submitted_invoice` on, or the user
    explicitly invoked `send_to_efris`.
    """
    auto_send_submitted_invoice = (
        doc.get("efris_invoice")
        and get_e_company_settings(doc.get("company")).auto_send_submitted_invoice
    )

    if (auto_send_submitted_invoice == 1) or (method == "manual_submit"):
        sales_invoice = EInvoiceAPI.parse_sales_invoice(frappe.as_json(doc))
        validate_payment(sales_invoice)
        if not sales_invoice.efris_invoice or sales_invoice.is_consolidated:
            return

        if not validate_company(sales_invoice):
            return
        _handle_efris_logic(sales_invoice, doc)


def _handle_efris_logic(sales_invoice, doc):
    if sales_invoice.is_return:
        _handle_sales_return(sales_invoice)
    else:
        _handle_sales_invoice(sales_invoice, doc)
    efris_log_info("Finished on_submit_sales_invoice")


def _handle_sales_return(sales_invoice):
    original_e_invoice = get_einvoice(sales_invoice.return_against)
    credit_note_status = ""

    if frappe.db.exists("E Invoice", sales_invoice.name):
        creditnote_einvoice = get_einvoice(sales_invoice.name)
        credit_note_status = creditnote_einvoice.status or ""
    else:
        frappe.log_error("Sales return name not set, assumption is it is new")

    if original_e_invoice.status == "EFRIS Generated" and credit_note_status not in [
        "EFRIS Credit Note Pending",
        "EFRIS Generated",
    ]:
        EInvoiceAPI.generate_credit_note_return_application(sales_invoice)


def _handle_sales_invoice(sales_invoice, doc):
    doc = frappe.as_json(doc)
    EInvoiceAPI.synchronize_e_invoice(sales_invoice)

    if sales_invoice.efris_irn:
        return

    einvoice_status = sales_invoice.get("efris_einvoice_status")
    if not einvoice_status or einvoice_status == "EFRIS Pending":
        EInvoiceAPI.generate_irn(doc)
    else:
        efris_log_info("einvoice generation skipped...")


def on_update_sales_invoice(doc, method):
    efris_log_info("on_update_sales_invoice called...")
    doc = frappe.as_json(doc)
    sales_invoice = EInvoiceAPI.parse_sales_invoice(doc)

    if not validate_company(sales_invoice):
        efris_log_info(
            "The company does not have E Invoicing settings! Skipping EFRIS posting."
        )
        return


def on_cancel_sales_invoice(doc, method):
    is_efris = doc.get("efris_invoice")
    efris_log_info("On Cancel Test Is EFRIS {is_efris}")
    if not is_efris:
        return
    EInvoiceAPI.on_cancel_sales_invoice(doc)


def validate_sales_invoice(doc, method):
    """Reject mixed EFRIS / non-EFRIS items; auto-set the sales-tax template for EFRIS items."""
    items = doc.get("items", [])
    company = doc.get("company")

    if not items:
        return

    found_efris_item, found_non_efris_item = _check_efris_items(items)
    if found_efris_item and found_non_efris_item:
        frappe.throw("Cannot sell non-EFRIS and EFRIS items on the same Sales Invoice")

    if found_efris_item:
        _set_sales_taxes_template(doc, company)


def _check_efris_items(items):
    found_efris_item, found_non_efris_item = 0, 0
    for row in items:
        item_code = row.efris_commodity_code
        efris_log_info(f"The EFRIS Goods & Services Code is: {item_code}")
        if item_code:
            found_efris_item = 1
        else:
            found_non_efris_item = 1
    return found_efris_item, found_non_efris_item


def _set_sales_taxes_template(doc, company):
    template_name = get_e_company_settings(company).sales_taxes_and_charges_template
    if template_name:
        doc.taxes_and_charges = template_name
    else:
        frappe.throw("No Sales Taxes and Charges Template found!")


# ---------------------------------------------------------------------------
# Scheduled task
# ---------------------------------------------------------------------------


def check_credit_note_approval_status():
    """Daily — poll URA for any pending credit-note applications."""
    sales_invoices = frappe.get_all(
        "Sales Invoice", filters={"efris_einvoice_status": "EFRIS Credit Note Pending"}
    )

    if not sales_invoices:
        efris_log_info("No Sales Invoices found with 'EFRIS Credit Note Pending'.")
        return

    for sales_invoice in sales_invoices:
        try:
            sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice.name)
            efris_log_info(
                f"Checking approval status for Sales Invoice: {sales_invoice.name}"
            )

            status, response = EInvoiceAPI.confirm_irn_cancellation(sales_invoice_doc)

            if status:
                efris_log_info(
                    f"Credit note approval successful for Sales Invoice: {sales_invoice.name}."
                )
            else:
                frappe.logger().error(
                    f"Failed to check approval for Sales Invoice: "
                    f"{sales_invoice.name}. Response: {response}"
                )

        except Exception as e:
            frappe.log_error(
                f"Error checking EFRIS status for Sales Invoice {sales_invoice.name}: {e}",
                "EFRIS Credit Note Approval Check",
            )

    efris_log_info("Completed daily check for EFRIS credit note approval status.")


# ---------------------------------------------------------------------------
# Whitelisted (called from JS)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def send_to_efris(doc):
    if isinstance(doc, str):
        doc = json.loads(doc)
    if isinstance(doc, dict):
        doc = frappe.get_doc(doc)
    on_submit_sales_invoice(doc, "manual_submit")
    return {"message": "Sales Invoice sent to EFRIS successfully.", "status": "success"}


@frappe.whitelist()
def generate_irn(sales_invoice_doc):
    efris_log_info(f"generate_irn for doc: {sales_invoice_doc}")
    return EInvoiceAPI.generate_irn(sales_invoice_doc)


@frappe.whitelist()
def confirm_irn_cancellation(sales_invoice):
    efris_log_info("confirm_irn_cancellation called ...")
    return EInvoiceAPI.confirm_irn_cancellation(sales_invoice)


@frappe.whitelist()
def cancel_irn(sales_invoice, reasonCode, remark):
    return EInvoiceAPI.cancel_irn(sales_invoice, reasonCode, remark)


@frappe.whitelist()
def check_efris_flag_for_sales_invoice(is_return, return_against):
    is_efris_flag = (
        bool(is_return and frappe.db.exists("E Invoice", return_against)) or False
    )
    efris_log_info(f"Returned value is {is_efris_flag}")
    return is_efris_flag


@frappe.whitelist()
def Sales_invoice_is_efris_validation(doc, method):
    efris_log_info("Before Save is called ...")
    try:
        doc = _parse_doc(doc)
        is_efris = doc.get("efris_invoice")
        items = doc.get("items", [])
        if is_efris:
            validate_efris_warehouse(doc)
        else:
            set_efris_based_on_items(doc, items)
    except Exception as e:
        frappe.throw(f"Sales Invoice EFRIS Validation Failed: {str(e)}")


def validate_efris_warehouse(doc):
    set_warehouse = doc.get("set_warehouse")
    target_warehouse = set_warehouse or next(
        (item.get("warehouse") for item in doc.get("items", []) if item.get("warehouse")),
        None,
    )
    if target_warehouse:
        is_efris_warehouse = frappe.db.get_value(
            "Warehouse", {"name": target_warehouse}, "efris_warehouse"
        )
        efris_log_info(
            f"The EFRIS Warehouse Flag for {target_warehouse} is {is_efris_warehouse}"
        )
        if not is_efris_warehouse:
            frappe.throw(f"Warehouse {target_warehouse} must be an EFRIS Warehouse")


def set_efris_based_on_items(doc, items):
    for item in items:
        item_code = item.get("item_code")
        if frappe.db.get_value("Item", {"item_code": item_code}, "efris_item"):
            doc.efris_invoice = 1
            target_warehouse = item.get("warehouse")
            is_efris_warehouse = frappe.db.get_value(
                "Warehouse", {"name": target_warehouse}, "efris_warehouse"
            )
            if not is_efris_warehouse:
                frappe.throw(
                    f"Target Warehouse {target_warehouse} must be an EFRIS Warehouse"
                )
            customer = doc.get("customer")
            efris_customer_type = frappe.db.get_value(
                "Customer", {"customer_name": customer}, "efris_customer_type"
            )
            doc.efris_customer_type = efris_customer_type
            doc.flags.ignore_validate_update_after_submit = True
            efris_log_info("Updated Sales Invoice for EFRIS compliance.")
            break


@frappe.whitelist()
def sales_uom_validation(doc, method):
    doc = _parse_doc(doc)
    if doc.get("is_return") or not doc.get("efris_invoice"):
        return
    for item in doc.get("items", []):
        _validate_item_uom(item)


def _validate_item_uom(item):
    item_code = item.get("item_code")
    sales_uom = item.get("uom")
    if not sales_uom:
        return
    item_doc = frappe.get_doc("Item", {"item_code": item_code})
    uoms_detail = item_doc.get("uoms", [])
    if not any(row.uom == sales_uom for row in uoms_detail):
        frappe.throw(
            f"The Sales UOM ({sales_uom}) must be in the Item's UOMs list for item {item_code}."
        )


def before_save(doc, method):
    """Apply the original invoice's additional-discount rate to a new credit-note's items."""
    if doc.is_new() and doc.is_return and doc.return_against:
        sales_invoice = doc.return_against
        discount = new_credit_note_rate(sales_invoice)
        if discount is None:
            return
        for item in doc.items:
            item.rate = item.rate - (discount * item.rate) / 100
            item.amount = item.rate * item.qty
