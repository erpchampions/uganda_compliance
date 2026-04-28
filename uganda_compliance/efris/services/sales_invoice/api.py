"""`EInvoiceAPI` — central façade for the URA invoice lifecycle.

T109 (submit) → T110 (cancel application / return application) → T111
(confirm cancellation). Each method is a thin orchestrator over the
transport (`dispatch_legacy`) and the build/credit-note helpers.

Kept as a class-with-staticmethods because every existing import in the
codebase reaches it via `EInvoiceAPI.foo(...)`. Converting to plain
functions would be cleaner but ripples to every call site.
"""
from datetime import datetime

import frappe
import six
from frappe import _
from frappe.integrations.utils import create_request_log

from uganda_compliance.efris.client.dispatch import dispatch_legacy
from uganda_compliance.efris.client.envelope import get_ug_time_str
from uganda_compliance.efris.utils.utils import (
    efris_log_error,
    efris_log_info,
    get_qr_code,
    safe_load_json,
    update_integration_request_log,
)

from .build import (
    get_basic_information,
    get_buyer_details,
    get_einvoice,
    get_goods_details,
    get_import_service_seller,
    get_payment_details,
    get_summary_details,
    get_tax_details,
)
from .credit_note import (
    create_credit_note,
    handle_approved_credit_note,
    handle_rejected_credit_note,
    initialize_credit_note,
    negate_credit_note_values,
)


class EInvoiceAPI:
    @staticmethod
    def parse_sales_invoice(sales_invoice):
        if isinstance(sales_invoice, six.string_types):
            sales_invoice = safe_load_json(sales_invoice)
            if not isinstance(sales_invoice, dict):
                frappe.throw(_("Invalid Argument: Sales Invoice"))
            sales_invoice = frappe._dict(sales_invoice)
            return sales_invoice

    @staticmethod
    def create_einvoice(sales_invoice_name):
        if frappe.db.exists("E Invoice", {"invoice": sales_invoice_name}):
            efris_log_info("found existing e_invoice")
            einvoice = frappe.get_doc("E Invoice", {"invoice": sales_invoice_name})
        else:
            efris_log_info("creating new e_invoice")
            einvoice = frappe.new_doc("E Invoice")
            einvoice.invoice = sales_invoice_name
            einvoice.sync_with_sales_invoice()
            einvoice.flags.ignore_permissions = True
            einvoice.save()
            frappe.db.set_value(
                "Sales Invoice", sales_invoice_name, "efris_e_invoice", einvoice.name
            )
        return einvoice

    @staticmethod
    def generate_credit_note_return_application(sales_invoice):
        efris_log_info("generate_credit_note_return called ...")
        einvoice = EInvoiceAPI.create_einvoice(sales_invoice.name)
        status, response = EInvoiceAPI.make_credit_note_return_application_request(
            einvoice, sales_invoice
        )
        if status:
            EInvoiceAPI.handle_successful_credit_note_return_application(
                einvoice, response
            )
            frappe.msgprint(
                _("Credit Note Return Appliction Generated Successfully."), alert=1
            )
        else:
            frappe.throw(response, title=_("Credit Note Return Appliction Failed"))
            efris_log_info("Credit Note Return Appliction Failed")
        return status

    @staticmethod
    def make_credit_note_return_application_request(einvoice, sale_invoice):
        reason = sale_invoice.efris_creditnote_reasoncode or "102:Cancellation of the purchase"
        reasonCode = reason.split(":")[0]
        irn = frappe.get_doc("Sales Invoice", sale_invoice.return_against).efris_irn
        original_einvoice = get_einvoice(sale_invoice.return_against)
        if not original_einvoice:
            frappe.throw("No original einvoice found!")

        original_einvoice_id = original_einvoice.invoice_id

        credit_note = initialize_credit_note(
            einvoice, irn, original_einvoice_id, reason, reasonCode
        )
        credit_note.update({"goodsDetails": get_goods_details(einvoice, original_einvoice)})
        credit_note.update({"taxDetails": get_tax_details(einvoice)})
        credit_note.update({"summary": get_summary_details(einvoice)})
        credit_note.update({"buyerDetails": get_buyer_details(einvoice)})
        credit_note.update({"payWay": get_payment_details(einvoice)})
        credit_note.update({"importServicesSeller": get_import_service_seller()})
        credit_note.update({"basicInformation": get_basic_information(einvoice)})

        return dispatch_legacy(
            company=einvoice.company,
            interface_code="T110",
            payload=credit_note,
            doc=sale_invoice,
            force_sync=True,
        )

    @staticmethod
    def generate_irn(sales_invoice):
        efris_log_info("generate_irn called ...")

        sales_invoice = EInvoiceAPI.parse_sales_invoice(sales_invoice)
        einvoice = EInvoiceAPI.create_einvoice(sales_invoice.name)
        einvoice.fetch_invoice_details()
        einvoice_json = einvoice.get_einvoice_json()

        company_name = sales_invoice.company

        integration_request_log = create_request_log(
            data=einvoice_json,
            is_remote_request=1,
            service_name="EFRIS Generate IRN",
            reference_doctype=sales_invoice.doctype,
            reference_document=sales_invoice.name,
        )

        try:
            status, response = dispatch_legacy(
                company=company_name,
                interface_code="T109",
                payload=einvoice_json,
                doc=sales_invoice,
                force_sync=True,
            )

            if status:
                EInvoiceAPI.handle_successful_irn_generation(einvoice, response)
                efris_log_info(f"EFRIS Generated Successfully. :{einvoice}")
                frappe.msgprint(_("EFRIS Generated Successfully."), alert=1)
                update_integration_request_log(
                    integration_request_log,
                    status="Completed",
                    response=response,
                    error=None,
                )
            else:
                update_integration_request_log(
                    integration_request_log,
                    status="Failed",
                    response=response,
                    error=response,
                )
                frappe.log_error(title=response, message=frappe.get_traceback())
                frappe.throw(response, title=_("EFRIS Generation Failed"))
        except Exception as e:
            update_integration_request_log(
                integration_request_log,
                status="Failed",
                response=response,
                error=str(e),
            )
            efris_log_error(f"Error generating IRN: {str(e)}")
            frappe.throw(str(e), title=_("EFRIS Generation Failed"))

        return status, response

    @staticmethod
    def handle_successful_irn_generation(einvoice, response):
        status = "EFRIS Generated"
        try:
            irn = response["basicInformation"]["invoiceNo"]
            invoice_id = response["basicInformation"]["invoiceId"]
            antifake_code = response["basicInformation"]["antifakeCode"]
            efris_qr_code = response["summary"]["qrCode"]
            qrcode = get_qr_code(efris_qr_code)
            invoice_datetime = datetime.strptime(
                response["basicInformation"]["issuedDate"], "%d/%m/%Y %H:%M:%S"
            )
            data_source = response["basicInformation"]["dataSource"] or "103"

            einvoice.update(
                {
                    "irn": irn,
                    "invoice_id": invoice_id,
                    "antifake_code": antifake_code,
                    "status": status,
                    "qr_code_data": qrcode,
                    "invoice_date": invoice_datetime.date(),
                    "issued_time": invoice_datetime.time(),
                    "data_source": data_source,
                    "efris_qr_code": efris_qr_code,
                }
            )
            einvoice.flags.ignore_permissions = True
            einvoice.submit()
        except KeyError as e:
            frappe.throw(
                f"Error fetching data from response JSON: Missing key {e}",
                title="IRN Generation Error",
            )
        except Exception as e:
            frappe.throw(
                f"Unexpected error occurred: {e}", title="IRN Generation Error"
            )

    @staticmethod
    def cancel_irn(sales_invoice, reasonCode, remark):
        efris_log_info("cancel_irn called...")
        sales_invoice = EInvoiceAPI.parse_sales_invoice(sales_invoice)

        einvoice = EInvoiceAPI.get_einvoice(sales_invoice.name)
        EInvoiceAPI.validate_irn_cancellation(einvoice)
        success, response = EInvoiceAPI.make_cancel_irn_request(
            einvoice, reasonCode, remark
        )
        efris_log_info("make_cancel_irn_request finished...")

        if success:
            frappe.msgprint(
                _(
                    "EFRIS Credit Note Application Submitted Successfully.\n"
                    "EFRIS will only be cancelled after URA Approval."
                ),
                alert=1,
            )
        else:
            frappe.throw(response, title=_("EFRIS Cancellation Failed"))
        return success

    @staticmethod
    def make_cancel_irn_request(einvoice, reason_code, remark):
        efris_log_info(
            f"make_cancel_irn_request. reason/remark: {reason_code}/{remark}"
        )
        frappe.throw("Not implemented")
        credit_note = create_credit_note(einvoice, reason_code, remark)
        negate_credit_note_values(credit_note)

        efris_log_info(f"Credit Note JSON before Make_Post: {credit_note}")

        status, response = dispatch_legacy(
            company=einvoice.company,
            interface_code="T110",
            payload=credit_note,
            doc=einvoice,
            force_sync=True,
        )

        if status:
            EInvoiceAPI.handle_successful_irn_cancellation(einvoice, response)
        return status, response

    @staticmethod
    def handle_successful_irn_cancellation(einvoice, response):
        credit_note_appl_ref = response["referenceNo"]
        einvoice.update(
            {
                "credit_note_application_ref_no": credit_note_appl_ref,
                "credit_note_approval_status": "102:Submitted",
                "credit_note_application_date": get_ug_time_str(),
                "status": "EFRIS Credit Note Pending",
            }
        )
        einvoice.flags.ignore_permissions = True
        einvoice.save()

    @staticmethod
    def handle_successful_credit_note_return_application(einvoice, response):
        credit_note_appl_ref = response["referenceNo"]
        einvoice.update(
            {
                "credit_note_application_ref_no": credit_note_appl_ref,
                "credit_note_approval_status": "102:Submitted",
                "credit_note_application_date": get_ug_time_str(),
                "status": "EFRIS Credit Note Pending",
            }
        )
        einvoice.flags.ignore_permissions = True
        einvoice.save()

    @staticmethod
    def validate_irn_cancellation(einvoice):
        if not einvoice.irn:
            frappe.throw(
                _("EFRIS not found. You must generate EFRIS before cancelling."),
                title=_("Invalid Request"),
            )
        if einvoice.irn_cancelled:
            frappe.throw(
                _("EFRIS is already cancelled. You cannot cancel e-invoice twice."),
                title=_("Invalid Request"),
            )

    @staticmethod
    def get_einvoice(sales_invoice_name):
        if frappe.db.exists("E Invoice", {"invoice": sales_invoice_name}):
            efris_log_info("found existing e_invoice")
            return frappe.get_doc("E Invoice", {"invoice": sales_invoice_name})
        return None

    @staticmethod
    def confirm_irn_cancellation(sales_invoice):
        efris_log_info("confirm_irn_cancellation called ...")
        sales_invoice = EInvoiceAPI.parse_sales_invoice(sales_invoice)
        einvoice = EInvoiceAPI.get_einvoice(sales_invoice.name)
        status, response = EInvoiceAPI.make_confirm_irn_cancellation_request(einvoice)
        if status:
            frappe.msgprint(_("Credit Note Status: " + str(response)), alert=1)
        else:
            frappe.throw(response, title=_("Error Confirming EFRIS Cancellation"))
        return status

    @staticmethod
    def make_confirm_irn_cancellation_request(einvoice):
        credit_note_application_query = {
            "referenceNo": einvoice.credit_note_application_ref_no,
            "queryType": "1",
            "pageNo": "1",
            "pageSize": "10",
        }

        status, response = dispatch_legacy(
            company=einvoice.company,
            interface_code="T111",
            payload=credit_note_application_query,
            doc=einvoice,
            force_sync=True,
        )

        if status:
            status, response = EInvoiceAPI.handle_successful_confirm_irn_cancellation(
                einvoice, response
            )
        return status, response

    @staticmethod
    def handle_successful_confirm_irn_cancellation(einvoice, response):
        page_count = response["page"]["pageCount"]
        if not page_count:
            return False, "Credit Note Application Reference not found!"

        approve_status = response["records"][0]["approveStatus"]
        efris_log_info(f"response: {response}")

        if approve_status == "102":
            return True, "Pending URA Approval"
        if approve_status == "103":  # Rejected
            return handle_rejected_credit_note(einvoice, response)
        if approve_status == "101":  # Approved
            return handle_approved_credit_note(einvoice, response)
        return True, ""

    @staticmethod
    def synchronize_e_invoice(doc):
        if doc.get("einvoice_status") == "EFRIS Generated":
            efris_log_info("synchronize skipped for EFRIS Generated invoice ")
            return
        if frappe.db.exists("E Invoice", doc.name):
            efris_log_info("found einvoice..")
            einvoice = EInvoiceAPI.get_einvoice(doc.name)
            efris_log_info("before sync ...")
            einvoice.sync_with_sales_invoice()
            einvoice.flags.ignore_permissions = True
            efris_log_info("sync_with_sales_invoice done ..")
            einvoice.save()
            efris_log_info("after save...")

    @staticmethod
    def on_cancel_sales_invoice(doc):
        einvoice = EInvoiceAPI.get_einvoice(doc.name)
        if einvoice:
            einvoice.cancel()
            einvoice.save()
