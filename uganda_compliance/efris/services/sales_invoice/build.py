"""URA T109 / T110 payload builders for *new* invoice and credit-note flows.

Per-section helpers (`get_*_details`) construct one block of the payload each.
The credit-note rebuild path (`credit_note.create_credit_note`) uses similar
but slightly different shapes — kept separate to avoid one builder serving two
masters.
"""
import frappe

from uganda_compliance.efris.utils.utils import efris_log_info

from .utils import decode_e_tax_rate, get_order_no


def validate_payment(doc):
    """Default zero-amount payment rows to `grand_total` when efris_payment_mode is set."""
    if doc.get("efris_payment_mode") and doc.get("payments"):
        for payment in doc.get("payments"):
            if payment.get("amount") == 0.0:
                payment["amount"] = doc.get("grand_total")


def get_einvoice(sales_invoice):
    if frappe.db.exists("E Invoice", {"invoice": sales_invoice}):
        efris_log_info("found existing e_invoice")
        return frappe.get_doc("E Invoice", {"invoice": sales_invoice})
    return None


def get_tax_details(einvoice):
    return [
        {
            "taxCategoryCode": tax.tax_category_code.split(":")[0],
            "netAmount": tax.net_amount,
            "taxRate": str(tax.tax_rate),
            "taxAmount": str(tax.tax_amount),
            "grossAmount": tax.gross_amount,
            "exciseUnit": tax.excise_unit,
            "exciseCurrency": tax.excise_currency,
            "taxRateName": tax.tax_rate_name,
        }
        for tax in einvoice.taxes
    ]


def get_summary_details(einvoice):
    return {
        "netAmount": einvoice.net_amount,
        "taxAmount": einvoice.tax_amount,
        "grossAmount": einvoice.gross_amount,
        "itemCount": str(einvoice.item_count),
        "modeCode": "0",
        "qrCode": einvoice.efris_qr_code,
    }


def get_buyer_details(einvoice):
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


def get_payment_details(einvoice):
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
            {
                "paymentMode": "101",
                "paymentAmount": einvoice.gross_amount,
                "orderNumber": "a",
            }
        ]

    return [
        {
            "paymentMode": payment_code_map.get(payment.mode_of_payment, "Unknown"),
            "paymentAmount": round(payment.amount, 2),
            "orderNumber": "a",
        }
        for payment in einvoice.e_payments
        if payment.mode_of_payment in payment_code_map
    ]


def get_import_service_seller():
    return {
        "importBusinessName": "",
        "importEmailAddress": "",
        "importContactNumber": "",
        "importAddress": "",
        "importInvoiceDate": "",
        "importAttachmentName": "",
        "importAttachmentContent": "",
    }


def get_basic_information(einvoice):
    # Legacy file had two definitions of this function; the second one wins
    # in Python module evaluation, so we preserve only that variant. The first
    # included `branchId: ""` which was always overwritten and unused.
    return {
        "operator": einvoice.operator,
        "invoiceKind": "1",
        "invoiceIndustryCode": "102",
    }


def get_goods_details(einvoice, original_einvoice, discount_percentage=0):
    """Build the credit-note `goodsDetails` array.

    For each item: look up the EFRIS product code, derive the URA tax rate
    from the e_tax_category, and resolve the `orderNumber` URA originally
    assigned via the cached request log (`get_order_no`). When the original
    invoice carried an additional discount, the goods rows are emitted with
    `discountFlag=1` and negated taxable amounts so URA matches them to the
    discount line on the original invoice.
    """
    item_list = []
    discountFlag = "2"

    for item in einvoice.items:
        qty = item.quantity
        taxes = item.tax
        taxRate = decode_e_tax_rate(str(item.gst_rate), item.e_tax_category)
        item_code = item.item_code
        taxable_amount = item.amount
        orderNumber = get_order_no(original_einvoice, item.item_code, item.item_name)
        goodsCode = frappe.db.get_value(
            "Item", {"item_code": item_code}, "efris_product_code"
        )
        efris_log_info(f"The EFRIS Product code is {goodsCode}")

        if goodsCode:
            item_code = goodsCode

        if discount_percentage > 0:
            discount_amount = item.efris_dsct_discount_total
            efris_log_info(f"Discount Amount: {discount_amount}")
            taxable_amount = -1 * item.efris_dsct_taxable_amount
            discountFlag = "1"
            discounted_item = item.efris_dsct_item_discount  # noqa: F841
            discountTaxRate = item.efris_dsct_discount_tax_rate
            efris_log_info(f"Tax Rate: {discountTaxRate}")

            if taxRate == "0.18":
                taxes = -1 * item.efris_dsct_item_tax
                efris_log_info(f"Item Taxes: {taxes}")

            if not taxRate or taxRate in ["-", "Exempt"]:
                discountTaxRate = "0.0"  # noqa: F841

        item_list.append(
            {
                "item": item.item_name,
                "itemCode": item_code,
                "qty": str(qty),
                "unitOfMeasure": frappe.get_doc("UOM", item.unit).efris_uom_code,
                "unitPrice": str(item.rate),
                "total": str(taxable_amount),
                "taxRate": str(taxRate),
                "tax": str(taxes),
                "orderNumber": str(orderNumber),
                "discountFlag": discountFlag,
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
        )

    return item_list
