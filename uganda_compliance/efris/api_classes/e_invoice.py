import six
import frappe
import json
from frappe import _
from uganda_compliance.efris.api_classes.efris_api import make_post
from uganda_compliance.efris.doctype.e_invoice.e_invoice import validate_company,decode_e_tax_rate
from uganda_compliance.efris.utils.utils import efris_log_info, safe_load_json, efris_log_error
from uganda_compliance.efris.api_classes.request_utils import get_ug_time_str
from json import loads, dumps, JSONDecodeError
from datetime import datetime
from pyqrcode import create as qrcreate
import io
import os
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings
from uganda_compliance.efris.doctype.e_invoice_request_log.e_invoice_request_log import log_request_to_efris

class EInvoiceAPI:
    @staticmethod

    def parse_sales_invoice(sales_invoice):
        if isinstance(sales_invoice, six.string_types):
            sales_invoice = safe_load_json(sales_invoice)
            if not isinstance(sales_invoice, dict):
                frappe.throw(_('Invalid Argument: Sales Invoice')) 
            sales_invoice = frappe._dict(sales_invoice)
            return sales_invoice


    @staticmethod
    def create_einvoice(sales_invoice_name):
        if frappe.db.exists('E Invoice', {'invoice': sales_invoice_name}):
            efris_log_info("found existing e_invoice")
            einvoice = frappe.get_doc('E Invoice', {'invoice': sales_invoice_name})
        else:
            efris_log_info("creating new e_invoice")
            einvoice = frappe.new_doc('E Invoice')
            einvoice.invoice = sales_invoice_name
            einvoice.sync_with_sales_invoice()
            einvoice.flags.ignore_permissions = True
            einvoice.save()
            frappe.db.set_value('Sales Invoice', sales_invoice_name, 'e_invoice', einvoice.name)  # Link E-Invoice to Sales Invoice
           
        return einvoice
    
    
    @staticmethod
    def generate_credit_note_return_application (sales_invoice):
        efris_log_info(f"generate_credit_note_return called ...")
                
        #EInvoiceAPI.validate_credit_note_return(sales_invoice)
        einvoice = EInvoiceAPI.create_einvoice(sales_invoice.name)
        efris_log_info(f"after einvoice creation")

        status, response = EInvoiceAPI.make_credit_note_return_application_request(einvoice, sales_invoice)
       
       
        if status:
            EInvoiceAPI.handle_successful_credit_note_return_application(einvoice, response)
            efris_log_info(f"Credit Note Return Appliction Successfull for einvoice :{einvoice}")
            frappe.msgprint(_("Credit Note Return Appliction Generated Successfully."), alert=1)
        else:
            frappe.throw(response, title=_('Credit Note Return Appliction Failed'))
            efris_log_info(f"Credit Note Return Appliction Failed")

        return status   
    
    
    @staticmethod
    def make_credit_note_return_application_request(einvoice, sale_invoice):
        efris_log_info("make_credit_note_return_application_request called")
        #
        item_list = []
        unique_items = set()
        total_tax = 0.0
        total_discount_tax = 0.0
        orderNumber = 0
        discount_percentage = einvoice.additional_discount_percentage if einvoice.additional_discount_percentage else 0
        initial_tax = einvoice.tax_amount
        item_code  = ""
        goodsCode = ""
        tax_rate = 0.0
        discount_tax = 0.0
        tax_on_discount = 0.0
        discountTaxRate = ""
       	
        remark = sale_invoice.efris_creditnote_remarks
        efris_log_info(f"Credit Note Remark for return Invoice is :{remark}")
        reason = sale_invoice.efris_creditnote_reasoncode 
        efris_log_info(f"The Reason for Passing Credit Not is :{reason}")
        if not reason:
            reason = "102:Cancellation of the purchase"
            
        reasonCode = reason.split(":")[0]
        efris_log_info(f"The Reason Code is :{reasonCode}")

        irn = frappe.get_doc("Sales Invoice",sale_invoice.return_against).irn 
        currency = einvoice.currency
        efris_log_info(f"The Currency is {currency}")
        original_einvoice = get_einvoice(sale_invoice.return_against)
        if not original_einvoice:
            frappe.throw("No original einvoice found!")

        original_einvoice_id = original_einvoice.invoice_id 
        efris_log_info(f"Original IRN, Invoice ID :{irn}, {irn} ")      

        credit_note = {
            "oriInvoiceId": original_einvoice_id,
            "oriInvoiceNo": irn,
            "reasonCode": reasonCode,
            "reason": reason,
            "applicationTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "invoiceApplyCategoryCode": "101",
            "currency": currency, 
            "contactName": "",
            "contactMobileNum": "",
            "contactEmail": "",
            "source": "103",
            "remarks": remark,
            "sellersReferenceNo": einvoice.seller_reference_no
        }
        item_list = []
        discount_percentage = einvoice.additional_discount_percentage
        efris_log_info(f"Additional Discount Percentage :{discount_percentage}")
        
        for item in einvoice.items: 
            qty = item.quantity 
            taxes = item.tax
            taxRate = decode_e_tax_rate(str(item.gst_rate), item.e_tax_category) 
            item_code = item.item_code
            goodsCode = frappe.db.get_value("Item",{"item_code":item_code},"efris_product_code")
            efris_log_info(f"The EFRIS Product code is {goodsCode}")        
            if goodsCode:
                item_code = goodsCode
            if discount_percentage > 0:
                discount_amount = round((item.amount) * (discount_percentage / 100), 9) 
                efris_log_info(f"Taxable Amount :{item.amount}")               
                discountFlag = "1"                        
                discounted_item = item.item_name + " (Discount)"
                efris_log_info(f"tax_rate: {tax_rate}")
                discountTaxRate = taxRate 
                if taxRate == '0.18':
                    tax_rate = float(taxRate) + 1
                    efris_log_info(f"tax_rate after: {tax_rate}")
                    taxes = round((item.amount - (item.amount / tax_rate)), 4)
                    # tax = round((row.amount - (row.amount / tax_rate)), 4)
                    efris_log_info(f"taxes: {taxes}")
                    total_tax += taxes
                if not taxRate or taxRate in ["-", "Exempt"]:
                    # taxRate = "0.00"  # Convert exempt or invalid tax rates to zero
                    discountTaxRate = "0.0"
            item_list.append({
                "item": item.item_name,
                "itemCode": item_code,
                "qty": str(item.quantity),
                "unitOfMeasure": frappe.get_doc("UOM",item.unit).efris_uom_code,
                "unitPrice": str(item.rate),
                "total": str(item.amount),
                "taxRate": str(taxRate),
                "tax": str(taxes),
                "discountTotal": str((-1 * discount_amount)) if discount_percentage > 0 else "",
                "discountTaxRate": str(discountTaxRate),
                "orderNumber": str(orderNumber),
                "discountFlag": discountFlag if discount_percentage > 0 else "2",
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
                "vatApplicableFlag": "1"
            })
            orderNumber += 1
            credit_note.update({"goodsDetails": item_list})
            if discount_percentage > 0:
               
                if taxRate == '0.18':
                    tax_on_discount = round((discount_amount / tax_rate), 4)
                    discount_tax = round((discount_amount - tax_on_discount), 4) * -1
                    total_discount_tax += (discount_tax)
                else:
                    discount_tax = taxes
                    
                discount_item = {
                            "item": discounted_item,
                            "itemCode": item_code,
                            "qty": "",
                            "unitOfMeasure": "",
                            "unitPrice": "",
                            "total": str((-1 * discount_amount)),
                            "taxRate": str(taxRate),
                            "tax": str((discount_tax)),
                            "discountTotal": "",
                            "discountTaxRate": str(discountTaxRate),
                            "orderNumber": str(orderNumber),
                            "discountFlag": "0",
                            "deemedFlag": "2",
                            "exciseFlag": "2",
                            "categoryId": "",
                            "categoryName": "",
                            "goodsCategoryId": item.efris_commodity_code,
                            "goodsCategoryName": "",
                            "vatApplicableFlag": "1",
                        }
                item_list.append(discount_item)
                credit_note.update({"goodsDetails": item_list})
                orderNumber += 1
             # Adjust for tax differences after the loop
                if discount_percentage and discount_percentage > 0 :
                    tax_difference = round(float(initial_tax) - (float(total_tax) + float(total_discount_tax)), 4)
                    if tax_difference != 0.0:
                        efris_log_info(f"Adjusting for tax difference: {tax_difference}")
                        # Ensure the adjustment is made to the last discount item
                        for item in reversed(item_list):
                            if item["discountFlag"] == "0" and taxRate == '0.18':  # Identify the last discount line
                                
                                last_discount_item_tax = round((float(item["tax"]) + round(tax_difference,4)),4)
                                item["tax"] = str(last_discount_item_tax)
                                efris_log_info(f"The Discount Tax for Discount Item has been adjusted to {last_discount_item_tax}")
                                
                            elif item["discountFlag"] == "0" and taxRate != '0.18':
                                    item["tax"] = str(taxes)
                            break

        tax_list = []
        for tax in einvoice.taxes:
            tax_list.append({
                "taxCategoryCode": tax.tax_category_code.split(':')[0],
                "netAmount": tax.net_amount,
                "taxRate": str(tax.tax_rate),
                "taxAmount": str(tax.tax_amount),
                "grossAmount": tax.gross_amount,
                "exciseUnit": tax.excise_unit,
                "exciseCurrency": tax.excise_currency,
                "taxRateName": tax.tax_rate_name
            })

        credit_note.update({"taxDetails": tax_list})
        credit_note.update({"summary": {
            "netAmount": einvoice.net_amount,
            "taxAmount": einvoice.tax_amount,
            "grossAmount": einvoice.gross_amount,
            "itemCount": str(einvoice.item_count),
            "modeCode": "0",
            "qrCode": einvoice.qrcode_path
        }})
        credit_note.update({"buyerDetails": {
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
            "buyerReferenceNo": ""
        }})
        credit_note.update({"payWay": [
            {
                "paymentMode": "101",
                "paymentAmount": einvoice.gross_amount,
                "orderNumber": "a"
            }
        ]})
        credit_note.update({"importServicesSeller": {
            "importBusinessName": "",
            "importEmailAddress": "",
            "importContactNumber": "",
            "importAddress": "",
            "importInvoiceDate": "",
            "importAttachmentName": "",
            "importAttachmentContent": ""
        }})
        credit_note.update({"basicInformation": {
            "operator": einvoice.operator,
            "invoiceKind": "1",
            "invoiceIndustryCode": "102",
            "branchId": ""
        }})

		
        efris_log_info(f"Credit Note JSON before Make_Post: {credit_note}")

        company_name = einvoice.company
        
        status, response = make_post("T110", credit_note, company_name)
        
        return status, response

    @staticmethod
    def generate_irn(sales_invoice):
        efris_log_info(f"generate_irn called ...")

        sales_invoice = EInvoiceAPI.parse_sales_invoice(sales_invoice)
        efris_log_info(f" after parse done...")
        
        einvoice = EInvoiceAPI.create_einvoice(sales_invoice.name)
        einvoice.fetch_invoice_details()  # Ensure details are fetched
        einvoice_json = einvoice.get_einvoice_json()
        
        company_name = sales_invoice.company
        
        status, response = make_post("T109", einvoice_json, company_name)

        if status:
            EInvoiceAPI.handle_successful_irn_generation(einvoice, response)
            efris_log_info(f"EFRIS Generated Successfully. :{einvoice}")
            frappe.msgprint(_("EFRIS Generated Successfully."), alert=1)
        else:
            frappe.throw(response, title=_('EFRIS Generation Failed'))
        
            
        return status,response 

    @staticmethod
    def handle_successful_irn_generation(einvoice, response):
        status = 'EFRIS Generated'
        try:
            irn = response["basicInformation"]["invoiceNo"]
            invoice_id = response["basicInformation"]["invoiceId"]
            antifake_code = response["basicInformation"]["antifakeCode"]
            qrcode = EInvoiceAPI.generate_qrcode(response["summary"]["qrCode"], einvoice)
            invoice_datetime = datetime.strptime(response["basicInformation"]["issuedDate"], '%d/%m/%Y %H:%M:%S')

            einvoice.update({
                'irn': irn,
                'invoice_id': invoice_id,
                'antifake_code': antifake_code,
                'status': status,
                'qrcode_path': qrcode,
                'invoice_date': invoice_datetime.date(),
                'issued_time': invoice_datetime.time(),
            })
            einvoice.flags.ignore_permissions = True
            einvoice.submit()
        except KeyError as e:
            efris_log_error(message=f"Error fetching data from response JSON: Missing key {e}", title="IRN Generation Error")
        except Exception as e:
            efris_log_error(message=f"Unexpected error occurred: {e}", title="IRN Generation Error")

    @staticmethod
    def generate_qrcode(signed_qrcode, einvoice):
        filename = '{} - QRCode.png'.format(einvoice.name).replace(os.path.sep, "__")
        qr_image = io.BytesIO()
        url = qrcreate(signed_qrcode, error='L')
        url.png(qr_image, scale=2, quiet_zone=1)
        _file = frappe.get_doc({
            'doctype': 'File',
            'file_name': filename,
            'attached_to_doctype': einvoice.doctype,
            'attached_to_name': einvoice.name,
            'attached_to_field': 'qrcode_path',
            'is_private': 0,
            'content': qr_image.getvalue()
        })
        _file.save()
        efris_log_info("qr_code is being generated")
        return _file.file_url

    @staticmethod
    def cancel_irn(sales_invoice, reasonCode, remark):
        efris_log_info("cancel_irn called...")
        sales_invoice = EInvoiceAPI.parse_sales_invoice(sales_invoice)

        einvoice = EInvoiceAPI.get_einvoice(sales_invoice.name)
        EInvoiceAPI.validate_irn_cancellation(einvoice)
        success, response = EInvoiceAPI.make_cancel_irn_request(einvoice, reasonCode, remark)
        efris_log_info("make_cancel_irn_request finished...")

        if success:
            frappe.msgprint(_("EFRIS Credit Note Application Submitted Successfully.\nEFRIS will only be cancelled after URA Approval."), alert=1)
        else:
            frappe.throw(response, title=_('EFRIS Cancellation Failed'))

        return success

    @staticmethod
    def make_cancel_irn_request(einvoice, reasonCode, remark):

        efris_log_info ("make_cancel_irn_request. reason/remark" + str(reasonCode) + "/" + str(remark) )
       
        credit_note = {
            "oriInvoiceId": einvoice.invoice_id,
            "oriInvoiceNo": einvoice.irn,
            "reasonCode": reasonCode,
            "reason": "",
            "applicationTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "invoiceApplyCategoryCode": "101",
            "currency": einvoice.currency, 
            "contactName": "",
            "contactMobileNum": "",
            "contactEmail": "",
            "source": "103",
            "remarks": remark,
            "sellersReferenceNo": einvoice.seller_reference_no
        }
        item_list = []
        for item in einvoice.items:
            item_list.append({
                "item": item.item_name,
                "itemCode": item.item_code,
                "qty": str(item.quantity),
                "unitOfMeasure": frappe.get_doc("UOM",item.unit).efris_uom_code,
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
                "vatApplicableFlag": "1"
            })
   
        credit_note.update({"goodsDetails": item_list})

        tax_list = []
        for tax in einvoice.taxes:
            tax_list.append({
                "taxCategoryCode": tax.tax_category_code.split(':')[0],
                "netAmount": tax.net_amount,
                "taxRate": str(tax.tax_rate),
                "taxAmount": tax.tax_amount,
                "grossAmount": tax.gross_amount,
                "exciseUnit": tax.excise_unit,
                "exciseCurrency": tax.excise_currency,
                "taxRateName": tax.tax_rate_name
            })

        credit_note.update({"taxDetails": tax_list})
        credit_note.update({"summary": {
            "netAmount": einvoice.net_amount,
            "taxAmount": einvoice.tax_amount,
            "grossAmount": einvoice.gross_amount,
            "itemCount": str(einvoice.item_count),
            "modeCode": "0",
            "qrCode": einvoice.qrcode_path
        }})
        credit_note.update({"buyerDetails": {
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
            "buyerReferenceNo": ""
        }})
        credit_note.update({"payWay": [
            {
                "paymentMode": "101",
                "paymentAmount": einvoice.gross_amount,
                "orderNumber": "a"
            }
        ]})
        credit_note.update({"importServicesSeller": {
            "importBusinessName": "",
            "importEmailAddress": "",
            "importContactNumber": "",
            "importAddress": "",
            "importInvoiceDate": "",
            "importAttachmentName": "",
            "importAttachmentContent": ""
        }})
        credit_note.update({"basicInformation": {
            "operator": einvoice.operator,
            "invoiceKind": "1",
            "invoiceIndustryCode": "102",
            "branchId": ""
        }})

		
		# Make fields negative
		# GoodsDetails
        for index, item in enumerate(credit_note["goodsDetails"]):
            credit_note["goodsDetails"][index]["qty"] = str(-abs(float(credit_note["goodsDetails"][index]["qty"])))
            # Modify this line to handle both integer and decimal quantities            

            credit_note["goodsDetails"][index]["total"] = str(-abs(float(credit_note["goodsDetails"][index]["total"])))
            credit_note["goodsDetails"][index]["tax"] = str(-abs(float(credit_note["goodsDetails"][index]["tax"])))
            
        # TaxDetails
        for index, tax in enumerate(credit_note["taxDetails"]):
            credit_note["taxDetails"][index]["netAmount"] = str(-abs(float(credit_note["taxDetails"][index]["netAmount"])))
            credit_note["taxDetails"][index]["taxAmount"] = str(-abs(float(credit_note["taxDetails"][index]["taxAmount"])))
            credit_note["taxDetails"][index]["grossAmount"] = str(-abs(float(credit_note["taxDetails"][index]["grossAmount"])))

        # Summary
        credit_note['summary']['netAmount'] = str(-abs(float(credit_note['summary']['netAmount'])))
        credit_note['summary']['taxAmount'] = str(-abs(float(credit_note['summary']['taxAmount'])))
        credit_note['summary']["grossAmount"] = str(-abs(float(credit_note['summary']["grossAmount"])))

        # Payway
        credit_note["payWay"][0]["paymentAmount"] = str(-abs(float(credit_note["payWay"][0]["paymentAmount"])))

        efris_log_info(f"Credit Note JSON before Make_Post: {credit_note}")

        company_name = einvoice.company
   
        status, response = make_post("T110", credit_note, company_name)
            
        if status:
            EInvoiceAPI.handle_successful_irn_cancellation(einvoice, response)
        return status, response

      
    @staticmethod
    def handle_successful_irn_cancellation(einvoice, response):
        credit_note_appl_ref = response["referenceNo"]
        einvoice.update({
            'credit_note_application_ref_no': credit_note_appl_ref,
            'credit_note_approval_status': "102:Submitted",
            'credit_note_application_date': get_ug_time_str(),
            'status': "EFRIS Credit Note Pending"
        })
        einvoice.flags.ignore_permissions = True
        einvoice.save()

    @staticmethod
    def handle_successful_credit_note_return_application(einvoice, response):
        credit_note_appl_ref = response["referenceNo"]
        einvoice.update({
            'credit_note_application_ref_no': credit_note_appl_ref,
            'credit_note_approval_status': "102:Submitted",
            'credit_note_application_date': get_ug_time_str(),
            'status': "EFRIS Credit Note Pending"
        })
        einvoice.flags.ignore_permissions = True
        einvoice.save()

    @staticmethod
    def validate_irn_cancellation(einvoice):
        if not einvoice.irn:
            frappe.throw(_('EFRIS not found. You must generate EFRIS before cancelling.'), title=_('Invalid Request'))
        
        if einvoice.irn_cancelled:
            frappe.throw(_('EFRIS is already cancelled. You cannot cancel e-invoice twice.'), title=_('Invalid Request'))

    @staticmethod
    def get_einvoice(sales_invoice_name):
        if frappe.db.exists('E Invoice', {'invoice': sales_invoice_name}):
            efris_log_info("found existing e_invoice")
            return frappe.get_doc("E Invoice", {"invoice": sales_invoice_name})
        else: return None

    @staticmethod
    def confirm_irn_cancellation(sales_invoice):
        efris_log_info(f"confirm_irn_cancellation called ...")
        sales_invoice = EInvoiceAPI.parse_sales_invoice(sales_invoice)
        einvoice = EInvoiceAPI.get_einvoice(sales_invoice.name)
        
        status, response = EInvoiceAPI.make_confirm_irn_cancellation_request(einvoice)
        if status:
            frappe.msgprint(_("Credit Note Status: " + str(response)), alert=1)
        else:
            frappe.throw(response, title=_('Error Confirming EFRIS Cancellation'))

        return status

    @staticmethod
    def make_confirm_irn_cancellation_request(einvoice):
        credit_note_application_query = {
            "referenceNo": einvoice.credit_note_application_ref_no,
            "queryType": "1",
            "pageNo": "1",
            "pageSize": "10"
        }
        
        company_name = einvoice.company
        
        status, response = make_post("T111", credit_note_application_query, company_name)
        #status, response = make_post("T111", credit_note_application_query)
        if status:
            status, response = EInvoiceAPI.handle_successful_confirm_irn_cancellation(einvoice, response)
        return status, response

    @staticmethod
    def handle_successful_confirm_irn_cancellation(einvoice, response):
        page_count = response["page"]["pageCount"]
        if not page_count:
            return False, "Credit Note Application Reference not found!"
        
        approve_status = response["records"][0]["approveStatus"]
        
        efris_log_info(f"response:{response}")

        if approve_status == '102':
            return True, "Pending URA Approval"
        
        approve_status = response["records"][0]["approveStatus"]

        if approve_status == '103':  # Rejected
            efris_log_info(f"The Approval status is {approve_status}")     

            # Log and cancel the rejected e-invoice (Sales Invoice Return)
            efris_log_info(f"Draft e-invoice {einvoice.name} submitted successfully")
            einvoice.flags.ignore_permissions = True            
            einvoice.status = 'Credit Note Rejected'
            einvoice.credit_note_approval_status = '103:Rejected'
            einvoice.docstatus = '2'
            # einvoice.cancel()
            #TODO: Bug in rejection process. Perhaps a notification/report is needed so that credit note can be handled manually
            # Creditnote rejection not officailly tested by URA

            # Load the Sales Invoice and mark it as cancelled
            sales_invoice_return = frappe.get_doc("Sales Invoice", einvoice.name)
            efris_log_info(f"Sales Invoice Return called: {sales_invoice_return.name}")

            # Update status and mark it as cancelled (docstatus = 2)
            sales_invoice_return.einvoice_status = "Credit Note Rejected"
            efris_log_info(f"Sales Invoice Return status changed to {sales_invoice_return.einvoice_status}")
            sales_invoice_return.flags.ignore_permissions = True
            efris_log_info(f"Submitted e-invoice {sales_invoice_return.name} cancelled successfully")
            sales_invoice_return.docstatus = 'Return Cancelled'
            # Save the cancellation (without making external EFRIS calls)
            sales_invoice_return.save()

            # Now handle the original invoice associated with the return
            original_einvoice = get_einvoice(sales_invoice_return.return_against)
            efris_log_info(f"Original e-invoice: {original_einvoice}")

            # Load the original sales invoice and update status
            original_sales_invoice = frappe.get_doc("Sales Invoice", original_einvoice)
            original_sales_invoice.einvoice_status = "EFRIS Generated"  # No longer marked as cancelled
            efris_log_info(f"The sales Invoice Return Status is {original_sales_invoice.docstatus}")
            
            # Update status to reflect the cancellation of the return
            original_sales_invoice.status = 'Return Cancelled'
            
            # Save and submit the original Sales Invoice to finalize the process
            original_sales_invoice.save()
            # original_sales_invoice.submit()

            # Update the original e-invoice status as well
            original_einvoice.status = "EFRIS Generated"
            original_einvoice.save()

            return True, "Credit Note Cancelled Successfully"
  
               
        if approve_status == '101':
            #TODO Get FDN details here, update them on einvoice and submit both sales invoice and einvoice
            credit_invoice_no = response["records"][0]["invoiceNo"]
            oriInvoiceNo = response["records"][0]["oriInvoiceNo"]
            
            #credit_invoice_no = "324013257658"

            credit_note_no_query = { "invoiceNo": credit_invoice_no }
            efris_log_info("query: {credit_note_no_query}" )

            # call T108 with credit_invoice_no - this returns the fdn_invoice_details
            company_name = einvoice.company        
            status, response = make_post("T108", credit_note_no_query, company_name)
            
            if not status:
                frappe.throw(f"Failed to get credit note invoice details, status:{status}")
            
            invoice_id = response["basicInformation"]["invoiceId"]
            efris_creditnote_reasoncode = response["extend"]["reason"]
            antifake_code = response["basicInformation"]["antifakeCode"]
            qrcode = EInvoiceAPI.generate_qrcode(response["summary"]["qrCode"], einvoice)
            invoice_datetime = datetime.strptime(response["basicInformation"]["issuedDate"], '%d/%m/%Y %H:%M:%S')


            einvoice.update({
                
                'irn': credit_invoice_no,
                'credit_note_approval_status': "101:Approved",
                'antifake_code':antifake_code,
                'invoice_id':invoice_id,
                'qrcode_path':qrcode,
                'invoice_date': invoice_datetime.date(),
                'issued_time': invoice_datetime.time(),
                'status': "EFRIS Generated",
                'original_fdn':oriInvoiceNo,
                'efris_creditnote_reasoncode':efris_creditnote_reasoncode,
                'is_return':1

            })
            einvoice.flags.ignore_permissions = True
            einvoice.save()
            einvoice.submit()

            
            sales_invoice_return = frappe.get_doc("Sales Invoice", einvoice.name )
            sales_invoice_return.einvoice_status = "EFRIS Generated"
            sales_invoice_return.submit()

            original_einvoice = get_einvoice(sales_invoice_return.return_against)
            original_sales_invoice = frappe.get_doc("Sales Invoice", original_einvoice )
            original_sales_invoice.einvoice_status = "EFRIS Cancelled"
            original_sales_invoice.save()

            original_einvoice.status = "EFRIS Cancelled"
            original_einvoice.save()

            return True, "Credit Note Approved! New Credit Note Invoice No: " + str(einvoice.credit_note_invoice_no)
        return True, ""
        

    @staticmethod
    def synchronize_e_invoice(doc):        
        if doc.get('einvoice_status') == 'EFRIS Generated':
            efris_log_info('synchronize skipped for EFRIS Generated invoice ')
            return
        if frappe.db.exists('E Invoice', doc.name):
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

def get_einvoice(sales_invoice):
        if frappe.db.exists('E Invoice', {'invoice': sales_invoice}):
            efris_log_info("found existing e_invoice")
            return frappe.get_doc("E Invoice", {"invoice": sales_invoice})
        else: return None

#######################################################
# 



def after_save_sales_invoice(doc, method):
    doc = frappe.as_json(doc)
    sales_invoice = EInvoiceAPI.parse_sales_invoice(doc)
    is_return = sales_invoice.is_return
    if is_return:
        return

def on_submit_sales_invoice(doc, method):

    
    efris_log_info(f"on_submit_sales_invoice called") 
    is_efris = doc.is_efris
    efris_log_info(f"Is Efris is set to :{is_efris}") 
    if not is_efris:
        return   
    
    doc = frappe.as_json(doc)
    sales_invoice = EInvoiceAPI.parse_sales_invoice(doc)
    if sales_invoice.is_consolidated:
        efris_log_info(f"The Pos Sales Invoice is a Consolidated Invoice")
        return

    if not validate_company(sales_invoice):
        return

    is_return = sales_invoice.is_return
    efris_log_info(f"The Selected Invoice a return Sales :is_return {is_return}")


    efris_log_info(f"sales_invoice.'einvoice_status:{sales_invoice.get('einvoice_status')}")

    
    if sales_invoice.is_return:
        original_e_invoice = get_einvoice(sales_invoice.return_against)
        if frappe.db.exists('E Invoice', sales_invoice.name):
            creditnote_einvoice = get_einvoice(sales_invoice.name)
            credit_note_status = creditnote_einvoice.status or ""
        else:
            efris_log_info("Sales return name not set, assumption is it is new")
            credit_note_status = ""

        if original_e_invoice.status == "EFRIS Generated" and not credit_note_status in ["EFRIS Credit Note Pending", "EFRIS Generated"]:
            EInvoiceAPI.generate_credit_note_return_application(sales_invoice)
    else:
        # Synchronize the E Invoice with Sales Invoice
        EInvoiceAPI.synchronize_e_invoice(sales_invoice)
        
        if (not sales_invoice.get('einvoice_status') or sales_invoice.get('einvoice_status') == 'EFRIS Pending') and not sales_invoice.get('irn'):
            efris_log_info(f"einvoice_status is NULL or EFRIS Pending")
            status, response = EInvoiceAPI.generate_irn(doc)        
                        
        else:
            efris_log_info("einvoice generation skipped...")

    efris_log_info(f"finished on_submit_sales_invoice")

  
def on_update_sales_invoice(doc, method):
    efris_log_info("on_update_sales_invoice called...")
    doc = frappe.as_json(doc)
    sales_invoice = EInvoiceAPI.parse_sales_invoice(doc)
    
    # Validate if the company is set up for EFRIS
    if not validate_company(sales_invoice):
        efris_log_info(f"The company does not have E Invoicing settings! Skipping EFRIS posting.")
        return  # Skip EFRIS posting, continue with the submission process

    

def on_cancel_sales_invoice(doc, method):
    efris_log_info(f"On Cancel is called ...")
    is_efris = doc.get('is_efris')
    efris_log_info("On Cancel Test Is Efris {is_efris}")
    if not is_efris:
        return
    EInvoiceAPI.on_cancel_sales_invoice(doc)



def validate_sales_invoice(doc,method):

    items = doc.get('items',[])
    company = doc.get('company')
    if items:
        found_efris_item, found_non_efris_item = 0, 0
        for row in items:
            item_code = row.efris_commodity_code
            efris_log_info(f"the EFRIS Goods & Services Code is:{item_code}")
            if item_code:
               found_efris_item = 1
            else:
                found_non_efris_item = 1

        # cannot have both on same invoice
        if found_efris_item and found_non_efris_item:
            frappe.throw("Cannot sell non-Efris and Efris items on the same Sales Invoice")
        
        if found_efris_item:
            # default the sales taxes and charges template
            template_name = get_e_company_settings(company).sales_taxes_and_charges_template
            efris_log_info(f"The Sales Tax Template Title is: {template_name}")
            
            if template_name:
                doc.taxes_and_charges = template_name
                
            else:
                efris_log_error("No Sales Taxes and Charges Template found.")
                frappe.throw("No Sales Taxes and Charges Template found!")


def check_credit_note_approval_status():
    # Log the start of the process
    frappe.throw("Test error")
    efris_log_info("Starting daily check for EFRIS credit note approval status.")
    
    # Fetch all sales invoices that are pending credit note approval in EFRIS
    sales_invoices = frappe.get_all("Sales Invoice", filters={
        'einvoice_status': 'EFRIS Credit Note Pending'
    })

    if not sales_invoices:
        efris_log_info("No Sales Invoices found with 'EFRIS Credit Note Pending'.")
        return
    
    # Loop through each sales invoice and check the approval status
    for sales_invoice in sales_invoices:
        try:
            sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice.name)
            efris_log_info(f"Checking approval status for Sales Invoice: {sales_invoice.name}")
            
            # Call the method to check the EFRIS status
            status, response = EInvoiceAPI.confirm_irn_cancellation(sales_invoice_doc)

            # Log the response
            if status:
                efris_log_info(f"Credit note approval successful for Sales Invoice: {sales_invoice.name}.")
            else:
                frappe.logger().error(f"Failed to check approval for Sales Invoice: {sales_invoice.name}. Response: {response}")
        
        except Exception as e:
            frappe.log_error(f"Error checking EFRIS status for Sales Invoice {sales_invoice.name}: {e}", "EFRIS Credit Note Approval Check")

    efris_log_info("Completed daily check for EFRIS credit note approval status.")


@frappe.whitelist()
def generate_irn(sales_invoice_doc):
    efris_log_info(f"generate_irn for doc: {sales_invoice_doc}")
    return EInvoiceAPI.generate_irn(sales_invoice_doc)

            
# Similarly, add bridge methods for other required functionalities
@frappe.whitelist()
def confirm_irn_cancellation(sales_invoice):
    efris_log_info(f"confirm_irn_cancellation called ...")
    return EInvoiceAPI.confirm_irn_cancellation(sales_invoice)

@frappe.whitelist()
def cancel_irn(sales_invoice, reasonCode, remark):
    return EInvoiceAPI.cancel_irn(sales_invoice, reasonCode, remark)

@frappe.whitelist()
def check_efris_flag_for_sales_invoice(is_return,return_against):
   
   efris_log_info(f"Parsed variables: {is_return}, {return_against}")
   is_efris_flag = bool(is_return and frappe.db.exists('E Invoice', return_against)) or False
   efris_log_info(f"Returned value is {is_efris_flag}")
   return is_efris_flag

@frappe.whitelist()
def Sales_invoice_is_efris_validation(doc,method):
    efris_log_info(f"Before Save is called ...")
    try:
        if isinstance(doc, str):
            doc = json.loads(doc)
        
        is_efris = doc.get('is_efris')
        
        if  not is_efris:
            for item in doc.get('items',[]):
                item_code = item.get('item_code')
                is_efris_item = frappe.db.get_value('Item', {'item_code':item_code}, 'is_efris_item')
                if is_efris_item:
                    doc.is_efris = 1
                    
                    customer = doc.get('customer')
                    efris_log_info(f"The Customer is {customer}")                
                    efris_customer_type = frappe.db.get_value('Customer',{'customer_name':customer},'efris_customer_type')
                    efris_log_info(f"The Efris Customer Type for Customer:{customer} is {efris_customer_type}")
                    if not doc.efris_customer_type:
                        doc.efris_customer_type = efris_customer_type
                        doc.flags.ignore_validate_update_after_submit = True
                    # doc.save()
                    efris_log_info(f"Updated Sales Invoice for EFRIS compliance.")
                    break  # No need to check further items once is_efris is set
                        
    
    except Exception as e:
        frappe.throw(f"Sales Invoice Is Efris Validation Failed ...: {str(e)}")


@frappe.whitelist()
def sales_uom_validation(doc,mehtod):
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except json.JSONDecodeError:
            frappe.log_error("Failed to decode `doc` JSON string", "purchase_uom_validation Error")
            return {"error": "Failed to decode `doc` JSON string"}
    efris_log_info(f"sales_uom_validation called with doc: {doc}")
    
    item = doc.get('items',[])
    for data in item:
        item_code = data.item_code
        efris_log_info(f"Item Code :{item_code}")
        sales_uom = data.uom
        efris_log_info(f"Sales UOM on Items Child Table {sales_uom}")
        if sales_uom:
            items = frappe.get_doc('Item',{'item_code':item_code})
            uoms_detail = items.get('uoms',[])
            efris_log_info(f"Item UOm is {uoms_detail}")
            # Check if purchase_uom exists in uoms_detail
            uom_exists = any(row.uom == sales_uom for row in uoms_detail)
            
            if not uom_exists:
                frappe.throw(f"The Sales UOM ({sales_uom}) must be in the Item's UOMs list for item {item_code}.")
