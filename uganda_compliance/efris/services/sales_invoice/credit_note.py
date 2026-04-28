"""Credit-note construction, submission outcomes, and FDN reconciliation.

There are two distinct shapes here:

- **Rebuild from existing E Invoice** (`create_credit_note`): build a new T110
  payload from scratch — used by `EInvoiceAPI.make_cancel_irn_request`.
- **Negate-original** (`initialize_credit_note` + `build.get_*` helpers):
  reuse the original invoice payload structure and negate values where needed
  — used by `EInvoiceAPI.make_credit_note_return_application_request`.

After a credit note is approved by URA, `handle_approved_credit_note` fetches
the FDN details and reconciles the local Sales Invoice / E Invoice state.
"""
from datetime import datetime

import frappe
from frappe.utils.user import get_users_with_role

from uganda_compliance.efris.client.dispatch import dispatch_legacy
from uganda_compliance.efris.utils.utils import efris_log_info, get_qr_code

from .build import get_einvoice


def create_credit_note(einvoice, reason_code, remark):
    """Build a fresh T110 payload from an existing E Invoice doc."""
    return {
        "oriInvoiceId": einvoice.invoice_id,
        "oriInvoiceNo": einvoice.irn,
        "reasonCode": reason_code,
        "reason": "",
        "applicationTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "invoiceApplyCategoryCode": "101",
        "currency": einvoice.currency,
        "contactName": "",
        "contactMobileNum": "",
        "contactEmail": "",
        "source": "103",
        "remarks": remark,
        "sellersReferenceNo": einvoice.seller_reference_no,
        "goodsDetails": _create_goods_details(einvoice.items),
        "taxDetails": _create_tax_details(einvoice.taxes),
        "summary": _create_summary(einvoice),
        "buyerDetails": _create_buyer_details(einvoice),
        "payWay": _create_payment_details(einvoice),
        "importServicesSeller": {
            "importBusinessName": "",
            "importEmailAddress": "",
            "importContactNumber": "",
            "importAddress": "",
            "importInvoiceDate": "",
            "importAttachmentName": "",
            "importAttachmentContent": "",
        },
        "basicInformation": {
            "operator": einvoice.operator,
            "invoiceKind": "1",
            "invoiceIndustryCode": "102",
            "branchId": "",
        },
    }


def initialize_credit_note(einvoice, irn, original_einvoice_id, reason, reason_code):
    """Skeleton for a *return-application* credit note; callers append the section blocks."""
    return {
        "oriInvoiceId": original_einvoice_id,
        "oriInvoiceNo": irn,
        "reasonCode": reason_code,
        "reason": reason,
        "applicationTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "invoiceApplyCategoryCode": "101",
        "currency": einvoice.currency,
        "contactName": "",
        "contactMobileNum": "",
        "contactEmail": "",
        "source": "103",
        "remarks": einvoice.remarks,
        "sellersReferenceNo": einvoice.seller_reference_no,
    }


def _create_goods_details(items):
    return [
        {
            "item": item.item_name,
            "itemCode": item.item_code,
            "qty": str(item.quantity),
            "unitOfMeasure": frappe.get_doc("UOM", item.unit).efris_uom_code,
            "unitPrice": item.rate,
            "total": item.amount,
            "taxRate": str(item.gst_rate),
            "tax": item.tax,
            "orderNumber": str(item.order_number),
            "deemedFlag": "2",
            "exciseFlag": "2",
            "categoryId": "",
            "categoryName": "",
            "goodsCategoryId": item.efris_commodity_code,
            "goodsCategoryName": "",
            "exciseRate": "",
            "exciseRule": "",
            "exciseTax": "",
            "pack": "",
            "stick": "",
            "exciseUnit": "",
            "exciseCurrency": "",
            "exciseRateName": "",
            "vatApplicableFlag": "1",
        }
        for item in items
    ]


def _create_tax_details(taxes):
    return [
        {
            "taxCategoryCode": tax.tax_category_code.split(":")[0],
            "netAmount": tax.net_amount,
            "taxRate": str(tax.tax_rate),
            "taxAmount": tax.tax_amount,
            "grossAmount": tax.gross_amount,
            "exciseUnit": tax.excise_unit,
            "exciseCurrency": tax.excise_currency,
            "taxRateName": tax.tax_rate_name,
        }
        for tax in taxes
    ]


def _create_summary(einvoice):
    return {
        "netAmount": einvoice.net_amount,
        "taxAmount": einvoice.tax_amount,
        "grossAmount": einvoice.gross_amount,
        "itemCount": str(einvoice.item_count),
        "modeCode": "0",
        "qrCode": einvoice.efris_qr_code,
    }


def _create_buyer_details(einvoice):
    return {
        "buyerTin": einvoice.buyer_gstin,
        "buyerNinBrn": "",
        "buyerPassportNum": "",
        "buyerLegalName": "",
        "buyerBusinessName": "",
        "buyerAddress": "",
        "buyerEmail": "",
        "buyerMobilePhone": "",
        "buyerLinePhone": "",
        "buyerPlaceOfBusi": "",
        "buyerType": "1",
        "buyerCitizenship": "1",
        "buyerSector": "1",
        "buyerReferenceNo": "",
    }


def _create_payment_details(einvoice):
    payment_code_map = {
        "Credit": "101",
        "Cash": "102",
        "Cheque": "103",
        "Demand draft": "104",
        "Mobile money": "105",
        "Visa/Master card": "106",
        "EFT": "107",
        "POS": "108",
        "RTGS": "109",
        "Swift transfer": "110",
    }

    if not einvoice.e_payments:
        return [
            {"paymentMode": "102", "paymentAmount": einvoice.credit, "orderNumber": "a"}
        ]

    payments = []
    for payment in einvoice.e_payments:
        mode_of_payment = payment_code_map.get(payment.mode_of_payment, "Unknown")
        if mode_of_payment == "Unknown":
            efris_log_info(f"Unsupported Payment Method")
            continue
        payments.append(
            {
                "paymentMode": mode_of_payment,
                "paymentAmount": round(payment.amount, 2),
                "orderNumber": "a",
            }
        )
    return payments


# Public re-exports for callers that pull these directly (legacy test code).
create_goods_details = _create_goods_details
create_tax_details = _create_tax_details
create_summary = _create_summary
create_buyer_details = _create_buyer_details
create_payment_details = _create_payment_details


def negate_credit_note_values(credit_note):
    """In-place: flip sign on every quantity / amount / tax in the credit note."""
    for item in credit_note["goodsDetails"]:
        item["qty"] = str(-abs(float(item["qty"])))
        item["total"] = str(-abs(float(item["total"])))
        item["tax"] = str(-abs(float(item["tax"])))

    for tax in credit_note["taxDetails"]:
        tax["netAmount"] = str(-abs(float(tax["netAmount"])))
        tax["taxAmount"] = str(-abs(float(tax["taxAmount"])))
        tax["grossAmount"] = str(-abs(float(tax["grossAmount"])))

    credit_note["summary"]["netAmount"] = str(
        -abs(float(credit_note["summary"]["netAmount"]))
    )
    credit_note["summary"]["taxAmount"] = str(
        -abs(float(credit_note["summary"]["taxAmount"]))
    )
    credit_note["summary"]["grossAmount"] = str(
        -abs(float(credit_note["summary"]["grossAmount"]))
    )

    credit_note["payWay"][0]["paymentAmount"] = str(
        -abs(float(credit_note["payWay"][0]["paymentAmount"]))
    )


def handle_rejected_credit_note(einvoice, response):
    efris_log_info(f"The Approval status is {response['records'][0]['approveStatus']}")

    einvoice.flags.ignore_permissions = True
    einvoice.status = "Credit Note Rejected"
    einvoice.credit_note_approval_status = "103:Rejected"
    einvoice.docstatus = "2"
    einvoice.save()

    sales_invoice_return = frappe.get_doc("Sales Invoice", einvoice.name)
    sales_invoice_return.efris_einvoice_status = "Credit Note Rejected"
    sales_invoice_return.flags.ignore_permissions = True
    sales_invoice_return.docstatus = "Return Cancelled"
    sales_invoice_return.save()
    notify_system_managers(sales_invoice_return)

    original_einvoice = get_einvoice(sales_invoice_return.return_against)
    original_sales_invoice = frappe.get_doc("Sales Invoice", original_einvoice)
    original_sales_invoice.efris_einvoice_status = "EFRIS Generated"
    original_sales_invoice.status = "Return Cancelled"
    original_sales_invoice.save()

    original_einvoice.status = "EFRIS Generated"
    original_einvoice.save()

    return True, "Credit Note Cancelled Successfully"


def notify_system_managers(credit_note_name):
    """Email Sales Manager users that a credit note was rejected by URA."""
    system_managers = get_users_with_role("Sales Manager")
    if not system_managers:
        efris_log_info("No system managers found to notify.")
        return

    subject = f"Credit Note Rejected: {credit_note_name}"
    message = f"""
	Dear System Manager,

	The credit note with reference {credit_note_name} has been rejected.
	Please follow up with the relevant team to resolve this issue.

	Best regards,
	ERPNext System
	"""

    for user in system_managers:
        frappe.sendmail(recipients=[user.email], subject=subject, message=message)
        efris_log_info(
            f"Email sent to {user.email} about rejected credit note {credit_note_name}."
        )


def handle_approved_credit_note(einvoice, response):
    credit_invoice_no = response["records"][0]["invoiceNo"]
    oriInvoiceNo = response["records"][0]["oriInvoiceNo"]

    fdn_response = fetch_fdn_details(einvoice, credit_invoice_no)
    if not fdn_response:
        frappe.throw("Failed to get credit note invoice details.")

    update_einvoice_with_fdn_details(
        einvoice, fdn_response, credit_invoice_no, oriInvoiceNo
    )
    update_sales_invoice_return_status(einvoice)
    update_original_invoice_status(einvoice)

    return (
        True,
        f"Credit Note Approved! New Credit Note Invoice No: {credit_invoice_no}",
    )


def fetch_fdn_details(einvoice, credit_invoice_no):
    """Fetch FDN details using the T108 interface."""
    credit_note_no_query = {"invoiceNo": credit_invoice_no}
    status, fdn_response = dispatch_legacy(
        company=einvoice.company,
        interface_code="T108",
        payload=credit_note_no_query,
        doc=einvoice,
        force_sync=True,
    )
    return fdn_response if status else None


def update_einvoice_with_fdn_details(
    einvoice, fdn_response, credit_invoice_no, oriInvoiceNo
):
    invoice_id = fdn_response["basicInformation"]["invoiceId"]
    efris_creditnote_reasoncode = fdn_response["extend"]["reason"]
    antifake_code = fdn_response["basicInformation"]["antifakeCode"]
    efris_qr_code = fdn_response["summary"]["qrCode"]
    qrcode = get_qr_code(efris_qr_code)
    invoice_datetime = datetime.strptime(
        fdn_response["basicInformation"]["issuedDate"], "%d/%m/%Y %H:%M:%S"
    )

    einvoice.update(
        {
            "irn": credit_invoice_no,
            "credit_note_approval_status": "101:Approved",
            "antifake_code": antifake_code,
            "invoice_id": invoice_id,
            "qr_code_data": qrcode,
            "invoice_date": invoice_datetime.date(),
            "issued_time": invoice_datetime.time(),
            "status": "EFRIS Generated",
            "original_fdn": oriInvoiceNo,
            "efris_creditnote_reasoncode": efris_creditnote_reasoncode,
            "is_return": 1,
            "efris_qr_code": efris_qr_code,
        }
    )
    einvoice.flags.ignore_permissions = True
    einvoice.save()
    einvoice.submit()


def update_sales_invoice_return_status(einvoice):
    sales_invoice_return = frappe.get_doc("Sales Invoice", einvoice.name)
    sales_invoice_return.efris_einvoice_status = "EFRIS Generated"
    sales_invoice_return.submit()


def update_original_invoice_status(einvoice):
    original_einvoice = get_einvoice(einvoice.return_against)
    original_sales_invoice = frappe.get_doc("Sales Invoice", original_einvoice)
    original_sales_invoice.efris_einvoice_status = "EFRIS Cancelled"
    original_sales_invoice.save()

    original_einvoice.status = "EFRIS Cancelled"
    original_einvoice.save()


def get_credit_note_reason(sale_invoice):
    reason = (
        sale_invoice.efris_creditnote_reasoncode or "102:Cancellation of the purchase"
    )
    reason_code = reason.split(":")[0]
    efris_log_info(f"The Reason Code is :{reason_code}")
    return reason, reason_code


def get_original_invoice_details(einvoice, sale_invoice):
    irn = frappe.get_doc("Sales Invoice", sale_invoice.return_against).efris_irn
    currency = einvoice.currency  # noqa: F841 — kept for symmetry with caller signature.
    original_einvoice = get_einvoice(sale_invoice.return_against)
    if not original_einvoice:
        frappe.throw("No original einvoice found!")
    original_einvoice_id = original_einvoice.invoice_id
    return irn, currency, original_einvoice_id
