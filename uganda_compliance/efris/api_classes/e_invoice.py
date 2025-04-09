import six
import frappe
import json
from frappe import _
from uganda_compliance.efris.api_classes.efris_api import make_post
from uganda_compliance.efris.utils.utils import efris_log_info, safe_load_json, efris_log_error
from uganda_compliance.efris.api_classes.request_utils import get_ug_time_str
from datetime import datetime
from uganda_compliance.efris.utils.utils import get_qr_code
 
from frappe.utils.user import get_users_with_role
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings
from uganda_compliance.efris.doctype.e_invoice_request_log.e_invoice_request_log import log_request_to_efris
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings, get_mode_private_key_path

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
			frappe.db.set_value('Sales Invoice', sales_invoice_name, 'efris_e_invoice', einvoice.name)  # Link E-Invoice to Sales Invoice
		   
		return einvoice
	
	
	@staticmethod
	def generate_credit_note_return_application (sales_invoice):
		efris_log_info(f"generate_credit_note_return called ...")
				
		#EInvoiceAPI.validate_credit_note_return(sales_invoice)
		einvoice = EInvoiceAPI.create_einvoice(sales_invoice.name)

		status, response = EInvoiceAPI.make_credit_note_return_application_request(einvoice, sales_invoice)

		if status:
			EInvoiceAPI.handle_successful_credit_note_return_application(einvoice, response)
			frappe.msgprint(_("Credit Note Return Appliction Generated Successfully."), alert=1)
		else:
			frappe.throw(response, title=_('Credit Note Return Appliction Failed'))
			efris_log_info(f"Credit Note Return Appliction Failed")

		return status   
		

	@staticmethod
	def make_credit_note_return_application_request(einvoice, sale_invoice):
	   	
		reason = sale_invoice.efris_creditnote_reasoncode 
		if not reason:
			reason = "102:Cancellation of the purchase"
			
		reasonCode = reason.split(":")[0]
		irn = frappe.get_doc("Sales Invoice",sale_invoice.return_against).efris_irn 
		currency = einvoice.currency
		original_einvoice = get_einvoice(sale_invoice.return_against)
		if not original_einvoice:
			frappe.throw("No original einvoice found!")

		original_einvoice_id = original_einvoice.invoice_id 

		credit_note = initialize_credit_note(einvoice, irn, original_einvoice_id, reason, reasonCode)
		payment_list = []
		goods_details = get_goods_details(einvoice, original_einvoice)
		credit_note.update({"goodsDetails": goods_details})
		tax_list = []
		tax_list = get_tax_details(einvoice)
		credit_note.update({"taxDetails": tax_list})
		

		credit_note.update({"taxDetails": tax_list})
		summary_details = get_summary_details(einvoice)
		credit_note.update({"summary": summary_details})
		buyer_details = get_buyer_details(einvoice)
		credit_note.update({"buyerDetails": buyer_details})
  
		payment_list = get_payment_details(einvoice)
		credit_note.update({"payWay": payment_list})
		import_seller = get_import_service_seller()
		credit_note.update({"importServicesSeller": import_seller})
		
		basic_information = get_basic_information(einvoice)
		credit_note.update({"basicInformation": basic_information})
		
		company_name = einvoice.company

		status, response = make_post(interfaceCode="T110", content=credit_note, company_name=company_name, reference_doc_type=sale_invoice.doctype, reference_document=sale_invoice.name)
		return status, response

	@staticmethod
	def generate_irn(sales_invoice):
		efris_log_info(f"generate_irn called ...")
		
		sales_invoice = EInvoiceAPI.parse_sales_invoice(sales_invoice)
		efris_log_info(f" after parse done...")
		
		einvoice = EInvoiceAPI.create_einvoice(sales_invoice.name)
		einvoice.fetch_invoice_details() 
		
		einvoice_json = einvoice.get_einvoice_json()
		
		company_name = sales_invoice.company
		status, response = make_post(interfaceCode="T109", content=einvoice_json, company_name=company_name, reference_doc_type= sales_invoice.doctype, reference_document=sales_invoice.name)
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
			efris_qr_code = response["summary"]["qrCode"]
			qrcode = get_qr_code(efris_qr_code)
			invoice_datetime = datetime.strptime(response["basicInformation"]["issuedDate"], '%d/%m/%Y %H:%M:%S')
			data_source = response["basicInformation"]["dataSource"] or "103"

			einvoice.update({
				'irn': irn,
				'invoice_id': invoice_id,
				'antifake_code': antifake_code,
				'status': status,
				'qr_code_data': qrcode,
				'invoice_date': invoice_datetime.date(),
				'issued_time': invoice_datetime.time(),
				'data_source' : data_source,
				'efris_qr_code': efris_qr_code

			})
			einvoice.flags.ignore_permissions = True
			einvoice.submit()
		except KeyError as e:
			frappe.throw(f"Error fetching data from response JSON: Missing key {e}", title="IRN Generation Error")
			

		except Exception as e:
			frappe.throw(f"Unexpected error occurred: {e}", title="IRN Generation Error")


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
	def make_cancel_irn_request(einvoice, reason_code, remark):
		efris_log_info(f"make_cancel_irn_request. reason/remark: {reason_code}/{remark}")
		frappe.throw("Not implemented")
		credit_note = create_credit_note(einvoice, reason_code, remark)
		negate_credit_note_values(credit_note)

		efris_log_info(f"Credit Note JSON before Make_Post: {credit_note}")

		status, response = make_post(
			interfaceCode="T110",
			content=credit_note,
			company_name=einvoice.company,
			reference_doc_type=einvoice.doctype,
			reference_document=einvoice.name
		)

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
		
		status, response = make_post(interfaceCode="T111", content=credit_note_application_query, company_name=company_name, reference_doc_type=einvoice.doctype, reference_document=einvoice.name)
		
		
		if status:
			status, response = EInvoiceAPI.handle_successful_confirm_irn_cancellation(einvoice, response)
		return status, response

	@staticmethod
	def handle_successful_confirm_irn_cancellation(einvoice, response):
		page_count = response["page"]["pageCount"]
		if not page_count:
			return False, "Credit Note Application Reference not found!"

		approve_status = response["records"][0]["approveStatus"]
		efris_log_info(f"response: {response}")

		if approve_status == '102':
			return True, "Pending URA Approval"

		if approve_status == '103':  # Rejected
			return handle_rejected_credit_note(einvoice, response)

		if approve_status == '101':  # Approved
			return handle_approved_credit_note(einvoice, response)

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

###cancel rn#####
def create_credit_note(einvoice, reason_code, remark):
	credit_note = {
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
		"goodsDetails": create_goods_details(einvoice.items),
		"taxDetails": create_tax_details(einvoice.taxes),
		"summary": create_summary(einvoice),
		"buyerDetails": create_buyer_details(einvoice),
		"payWay": create_payment_details(einvoice),
		"importServicesSeller": {
			"importBusinessName": "",
			"importEmailAddress": "",
			"importContactNumber": "",
			"importAddress": "",
			"importInvoiceDate": "",
			"importAttachmentName": "",
			"importAttachmentContent": ""
		},
		"basicInformation": {
			"operator": einvoice.operator,
			"invoiceKind": "1",
			"invoiceIndustryCode": "102",
			"branchId": ""
		}
	}
	return credit_note

def create_goods_details(items):
	return [{
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
		"vatApplicableFlag": "1"
	} for item in items]

def create_tax_details(taxes):
	return [{
		"taxCategoryCode": tax.tax_category_code.split(':')[0],
		"netAmount": tax.net_amount,
		"taxRate": str(tax.tax_rate),
		"taxAmount": tax.tax_amount,
		"grossAmount": tax.gross_amount,
		"exciseUnit": tax.excise_unit,
		"exciseCurrency": tax.excise_currency,
		"taxRateName": tax.tax_rate_name
	} for tax in taxes]

def create_summary(einvoice):
	return {
		"netAmount": einvoice.net_amount,
		"taxAmount": einvoice.tax_amount,
		"grossAmount": einvoice.gross_amount,
		"itemCount": str(einvoice.item_count),
		"modeCode": "0",
		"qrCode": einvoice.efris_qr_code
	}

def create_buyer_details(einvoice):
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
		"buyerReferenceNo": ""
	}

def create_payment_details(einvoice):
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
		"Swift transfer": "110"
	}

	if not einvoice.e_payments:
		return [{
			"paymentMode": "102",
			"paymentAmount": einvoice.credit,
			"orderNumber": "a"
		}]

	payments = []
	for payment in einvoice.e_payments:
		mode_of_payment = payment_code_map.get(payment.mode_of_payment, "Unknown")
		if mode_of_payment == "Unknown":
			efris_log_info(f"Unsupported Payment Method")
			continue
		payments.append({
			"paymentMode": mode_of_payment,
			"paymentAmount": round(payment.amount, 2),
			"orderNumber": "a"
		})
	return payments

def negate_credit_note_values(credit_note):
	# Negate GoodsDetails
	for item in credit_note["goodsDetails"]:
		item["qty"] = str(-abs(float(item["qty"])))
		item["total"] = str(-abs(float(item["total"])))
		item["tax"] = str(-abs(float(item["tax"])))

	# Negate TaxDetails
	for tax in credit_note["taxDetails"]:
		tax["netAmount"] = str(-abs(float(tax["netAmount"])))
		tax["taxAmount"] = str(-abs(float(tax["taxAmount"])))
		tax["grossAmount"] = str(-abs(float(tax["grossAmount"])))

	# Negate Summary
	credit_note['summary']['netAmount'] = str(-abs(float(credit_note['summary']['netAmount'])))
	credit_note['summary']['taxAmount'] = str(-abs(float(credit_note['summary']['taxAmount'])))
	credit_note['summary']["grossAmount"] = str(-abs(float(credit_note['summary']["grossAmount"])))

	# Negate PayWay
	credit_note["payWay"][0]["paymentAmount"] = str(-abs(float(credit_note["payWay"][0]["paymentAmount"])))


##Handle credit note cancelation
def handle_rejected_credit_note(einvoice, response):
	efris_log_info(f"The Approval status is {response['records'][0]['approveStatus']}")

	einvoice.flags.ignore_permissions = True
	einvoice.status = 'Credit Note Rejected'
	einvoice.credit_note_approval_status = '103:Rejected'
	einvoice.docstatus = '2'
	einvoice.save()

	sales_invoice_return = frappe.get_doc("Sales Invoice", einvoice.name)
	sales_invoice_return.efris_einvoice_status = "Credit Note Rejected"
	sales_invoice_return.flags.ignore_permissions = True
	sales_invoice_return.docstatus = 'Return Cancelled'
	sales_invoice_return.save()
	notify_system_managers(sales_invoice_return)

	original_einvoice = get_einvoice(sales_invoice_return.return_against)
	original_sales_invoice = frappe.get_doc("Sales Invoice", original_einvoice)
	original_sales_invoice.efris_einvoice_status = "EFRIS Generated"
	original_sales_invoice.status = 'Return Cancelled'
	original_sales_invoice.save()

	original_einvoice.status = "EFRIS Generated"
	original_einvoice.save()

	return True, "Credit Note Cancelled Successfully"

def notify_system_managers(credit_note_name):
	"""
	Fetch users with the 'System Manager' role and send them an email notification
	about the rejected credit note.
	"""
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
		frappe.sendmail(
			recipients=[user.email],
			subject=subject,
			message=message
		)
		efris_log_info(f"Email sent to {user.email} about rejected credit note {credit_note_name}.")
		
def handle_approved_credit_note(einvoice, response):
	credit_invoice_no = response["records"][0]["invoiceNo"]
	oriInvoiceNo = response["records"][0]["oriInvoiceNo"]

	fdn_response = fetch_fdn_details(einvoice, credit_invoice_no)
	if not fdn_response:
		frappe.throw("Failed to get credit note invoice details.")

	update_einvoice_with_fdn_details(einvoice, fdn_response, credit_invoice_no, oriInvoiceNo)

	update_sales_invoice_return_status(einvoice)

	update_original_invoice_status(einvoice)

	return True, f"Credit Note Approved! New Credit Note Invoice No: {credit_invoice_no}"

def fetch_fdn_details(einvoice, credit_invoice_no):
	"""
	Fetch FDN details using the T108 interface.
	"""
	credit_note_no_query = {"invoiceNo": credit_invoice_no}
	status, fdn_response = make_post(
		interfaceCode="T108",
		content=credit_note_no_query,
		company_name=einvoice.company,
		reference_doc_type=einvoice.doctype,
		reference_document=einvoice.name
	)
	return fdn_response if status else None

def update_einvoice_with_fdn_details(einvoice, fdn_response, credit_invoice_no, oriInvoiceNo):
	"""
	Update the e-invoice with FDN details.
	"""
	invoice_id = fdn_response["basicInformation"]["invoiceId"]
	efris_creditnote_reasoncode = fdn_response["extend"]["reason"]
	antifake_code = fdn_response["basicInformation"]["antifakeCode"]
	efris_qr_code = fdn_response["summary"]["qrCode"]
	# qrcode = EInvoiceAPI.generate_qrcode(fdn_response["summary"]["qrCode"], einvoice)
	qrcode = get_qr_code(efris_qr_code)
	invoice_datetime = datetime.strptime(fdn_response["basicInformation"]["issuedDate"], '%d/%m/%Y %H:%M:%S')

	einvoice.update({
		'irn': credit_invoice_no,
		'credit_note_approval_status': "101:Approved",
		'antifake_code': antifake_code,
		'invoice_id': invoice_id,
		# 'qrcode_path': qrcode,
		'qr_code_data':qrcode,
		'invoice_date': invoice_datetime.date(),
		'issued_time': invoice_datetime.time(),
		'status': "EFRIS Generated",
		'original_fdn': oriInvoiceNo,
		'efris_creditnote_reasoncode': efris_creditnote_reasoncode,
		'is_return': 1,
		'efris_qr_code': efris_qr_code
	})
	einvoice.flags.ignore_permissions = True
	einvoice.save()
	einvoice.submit()

def update_sales_invoice_return_status(einvoice):
	"""
	Update the Sales Invoice Return status to "EFRIS Generated".
	"""
	sales_invoice_return = frappe.get_doc("Sales Invoice", einvoice.name)
	sales_invoice_return.efris_einvoice_status = "EFRIS Generated"
	sales_invoice_return.submit()

def update_original_invoice_status(einvoice):
	"""
	Update the original Sales Invoice and e-invoice status to "EFRIS Cancelled".
	"""
	original_einvoice = get_einvoice(einvoice.return_against)
	original_sales_invoice = frappe.get_doc("Sales Invoice", original_einvoice)
	original_sales_invoice.efris_einvoice_status = "EFRIS Cancelled"
	original_sales_invoice.save()

	original_einvoice.status = "EFRIS Cancelled"
	original_einvoice.save()
#####End of credit note status update

def get_credit_note_reason(sale_invoice):
	reason = sale_invoice.efris_creditnote_reasoncode or "102:Cancellation of the purchase"
	reason_code = reason.split(":")[0]
	efris_log_info(f"The Reason Code is :{reason_code}")
	return reason, reason_code

def get_original_invoice_details(einvoice, sale_invoice):
	irn = frappe.get_doc("Sales Invoice", sale_invoice.return_against).efris_irn 
	currency = einvoice.currency
	original_einvoice = get_einvoice(sale_invoice.return_against)
	if not original_einvoice:
		frappe.throw("No original einvoice found!")
	original_einvoice_id = original_einvoice.invoice_id 
	return irn, currency, original_einvoice_id

def initialize_credit_note(einvoice, irn, original_einvoice_id, reason, reason_code):
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
		"sellersReferenceNo": einvoice.seller_reference_no
	}


def get_tax_details(einvoice):
	return [{
		"taxCategoryCode": tax.tax_category_code.split(':')[0],
		"netAmount": tax.net_amount,
		"taxRate": str(tax.tax_rate),
		"taxAmount": str(tax.tax_amount),
		"grossAmount": tax.gross_amount,
		"exciseUnit": tax.excise_unit,
		"exciseCurrency": tax.excise_currency,
		"taxRateName": tax.tax_rate_name
	} for tax in einvoice.taxes]

def get_summary_details(einvoice):
	return {
		"netAmount": einvoice.net_amount, 
		"taxAmount": einvoice.tax_amount,
		"grossAmount": einvoice.gross_amount,
		"itemCount": str(einvoice.item_count),
		"modeCode": "0",
		"qrCode": einvoice.efris_qr_code
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
			"buyerReferenceNo": ""
	}

def get_payment_details(einvoice):
	payment_code_map = {
		"Credit": "101", "Cash": "102", "Cheque": "103", "Demand draft": "104",
		"Mobile money": "105", "Visa/Master card": "106", "EFT": "107",
		"POS": "108", "RTGS": "109", "Swift transfer": "110"
	}
	
	if not einvoice.e_payments:
		return [{"paymentMode": "101", "paymentAmount": einvoice.gross_amount, "orderNumber": "a"}]
	
	return [{
		"paymentMode": payment_code_map.get(payment.mode_of_payment, "Unknown"),
		"paymentAmount": round(payment.amount, 2),
		"orderNumber": "a"
	} for payment in einvoice.e_payments if payment.mode_of_payment in payment_code_map]

def get_import_service_seller():
	return {
		"importBusinessName": "",
		"importEmailAddress": "",
		"importContactNumber": "",
		"importAddress": "",
		"importInvoiceDate": "",
		"importAttachmentName": "",
		"importAttachmentContent": ""
	}

def get_basic_information(einvoice):
	return {
		"operator": einvoice.operator,
		"invoiceKind": "1",
		"invoiceIndustryCode": "102",
		"branchId": ""
	}


def get_basic_information(einvoice):
	return {
		"operator": einvoice.operator,
		"invoiceKind": "1",
		"invoiceIndustryCode": "102"
	}


def get_goods_details(einvoice, original_einvoice, discount_percentage=0):
	"""
	Process items in the einvoice and return a list of goods details for the credit note.
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
		goodsCode = frappe.db.get_value("Item", {"item_code": item_code}, "efris_product_code")
		efris_log_info(f"The EFRIS Product code is {goodsCode}")

		if goodsCode:
			item_code = goodsCode

		if discount_percentage > 0:
			discount_amount = item.efris_dsct_discount_total
			efris_log_info(f"Discount Amount: {discount_amount}")
			taxable_amount = -1 * item.efris_dsct_taxable_amount
			discountFlag = "1"
			discounted_item = item.efris_dsct_item_discount
			discountTaxRate = item.efris_dsct_discount_tax_rate
			efris_log_info(f"Tax Rate: {discountTaxRate}")

			if taxRate == '0.18':
				taxes = -1 * item.efris_dsct_item_tax
				efris_log_info(f"Item Taxes: {taxes}")

			if not taxRate or taxRate in ["-", "Exempt"]:
				discountTaxRate = "0.0"

		item_list.append({
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
			"vatApplicableFlag": "1"
		})

	return item_list

def get_einvoice(sales_invoice):
		if frappe.db.exists('E Invoice', {'invoice': sales_invoice}):
			efris_log_info("found existing e_invoice")
			return frappe.get_doc("E Invoice", {"invoice": sales_invoice})
		else: return None

#######################################################
# 
# in sales_invoice.py
def validate_payment(doc):
	if doc.get("efris_payment_mode") and doc.get("payments"):
		for payment in doc.get("payments"):
			if payment.get("amount") == 0.0:
				payment["amount"] = doc.get("grand_total")


def after_save_sales_invoice(doc, method):
	doc = frappe.as_json(doc)
	sales_invoice = EInvoiceAPI.parse_sales_invoice(doc)
	is_return = sales_invoice.is_return
	if is_return:
		return
	
def on_submit_sales_invoice(doc, method):
	
	
	"""
	Handle EFRIS-related logic when a Sales Invoice is submitted.
	"""
	sales_invoice = EInvoiceAPI.parse_sales_invoice(frappe.as_json(doc))
	validate_payment(sales_invoice)
	if not sales_invoice.efris_invoice or sales_invoice.is_consolidated:
		return

	if not validate_company(sales_invoice):
		return
	_handle_efris_logic(sales_invoice, doc)
	
def _handle_efris_logic(sales_invoice, doc):
	"""
	Handle EFRIS-specific logic for Sales Invoices and Returns.
	"""
	if sales_invoice.is_return:
		_handle_sales_return(sales_invoice)
	else:
		_handle_sales_invoice(sales_invoice, doc)

	efris_log_info("Finished on_submit_sales_invoice")
	
def _handle_sales_return(sales_invoice):
	"""
	Handle EFRIS logic for Sales Returns.
	"""
	
	original_e_invoice = get_einvoice(sales_invoice.return_against)
	credit_note_status = ""

	if frappe.db.exists('E Invoice', sales_invoice.name):
		creditnote_einvoice = get_einvoice(sales_invoice.name)
		credit_note_status = creditnote_einvoice.status or ""
	else:
		frappe.log_error("Sales return name not set, assumption is it is new")

	if original_e_invoice.status == "EFRIS Generated" and not credit_note_status in ["EFRIS Credit Note Pending", "EFRIS Generated"]:
		EInvoiceAPI.generate_credit_note_return_application(sales_invoice)
		
def _handle_sales_invoice(sales_invoice, doc):
	"""
	Handle EFRIS logic for regular Sales Invoices.
	"""
	doc = frappe.as_json(doc)
	EInvoiceAPI.synchronize_e_invoice(sales_invoice)

	if sales_invoice.efris_irn:
		return

	einvoice_status = sales_invoice.get('efris_einvoice_status')
	if not einvoice_status or einvoice_status == 'EFRIS Pending':
		status, response = EInvoiceAPI.generate_irn(doc)
	else:
		efris_log_info("einvoice generation skipped...")
		
  
def on_update_sales_invoice(doc, method):
	efris_log_info("on_update_sales_invoice called...")
	doc = frappe.as_json(doc)
	sales_invoice = EInvoiceAPI.parse_sales_invoice(doc)
	
	# Validate if the company is set up for EFRIS
	if not validate_company(sales_invoice):
		efris_log_info(f"The company does not have E Invoicing settings! Skipping EFRIS posting.")
		return  
	

def on_cancel_sales_invoice(doc, method):
	is_efris = doc.get('efris_invoice')
	efris_log_info("On Cancel Test Is EFRIS {is_efris}")
	if not is_efris:
		return
	EInvoiceAPI.on_cancel_sales_invoice(doc)
 
 
def validate_sales_invoice(doc, method):
	"""
	Validate the Sales Invoice to ensure EFRIS and non-EFRIS items are not mixed.
	Set the Sales Taxes and Charges Template for EFRIS items.
	"""
	items = doc.get('items', [])
	company = doc.get('company')

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
	"""
	Set the Sales Taxes and Charges Template for EFRIS items.
	"""
	template_name = get_e_company_settings(company).sales_taxes_and_charges_template

	if template_name:
		doc.taxes_and_charges = template_name
	else:
		frappe.throw("No Sales Taxes and Charges Template found!")


#ToDo: 
def check_credit_note_approval_status():
	
	sales_invoices = frappe.get_all("Sales Invoice", filters={
		'efris_einvoice_status': 'EFRIS Credit Note Pending'
	})

	if not sales_invoices:
		efris_log_info("No Sales Invoices found with 'EFRIS Credit Note Pending'.")
		return
	
	for sales_invoice in sales_invoices:
		try:
			sales_invoice_doc = frappe.get_doc("Sales Invoice", sales_invoice.name)
			efris_log_info(f"Checking approval status for Sales Invoice: {sales_invoice.name}")
			
			status, response = EInvoiceAPI.confirm_irn_cancellation(sales_invoice_doc)

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
   is_efris_flag = bool(is_return and frappe.db.exists('E Invoice', return_against)) or False
   efris_log_info(f"Returned value is {is_efris_flag}")
   return is_efris_flag

@frappe.whitelist()
def Sales_invoice_is_efris_validation(doc, method):
	"""Validate EFRIS compliance for Sales Invoice."""
	efris_log_info("Before Save is called ...")
	try:
		doc = _parse_doc(doc)
		
		is_efris = doc.get('efris_invoice')
		items = doc.get('items', [])
		
		if is_efris:
			validate_efris_warehouse(doc)        
		else:
			set_efris_based_on_items(doc, items)
	
	except Exception as e:
		frappe.throw(f"Sales Invoice EFRIS Validation Failed: {str(e)}")


def validate_efris_warehouse(doc):
	"""Validate EFRIS warehouse settings."""
	set_warehouse = doc.get("set_warehouse")
	target_warehouse = set_warehouse or next(
		(item.get('warehouse') for item in doc.get('items', []) if item.get('warehouse')),
		None
	)
	
	if target_warehouse:
		is_efris_warehouse = frappe.db.get_value(
			"Warehouse", {"name": target_warehouse}, "efris_warehouse"
		)
		efris_log_info(f"The EFRIS Warehouse Flag for {target_warehouse} is {is_efris_warehouse}")
		
		if not is_efris_warehouse:
			frappe.throw(f"Warehouse {target_warehouse} must be an EFRIS Warehouse")


def set_efris_based_on_items(doc, items):
	"""Set EFRIS flag and customer type based on items."""
	for item in items:
		item_code = item.get('item_code')
		if frappe.db.get_value('Item', {'item_code': item_code}, 'efris_item'):
			doc.efris_invoice = 1
			target_warehouse = item.get('warehouse')
			
			is_efris_warehouse = frappe.db.get_value(
				"Warehouse", {"name": target_warehouse}, "efris_warehouse"
			)
			if not is_efris_warehouse:
				frappe.throw(f"Target Warehouse {target_warehouse} must be an EFRIS Warehouse")
			
			customer = doc.get('customer')
			efris_customer_type = frappe.db.get_value(
				'Customer', {'customer_name': customer}, 'efris_customer_type'
			)
			doc.efris_customer_type = efris_customer_type
			doc.flags.ignore_validate_update_after_submit = True
			efris_log_info(f"Updated Sales Invoice for EFRIS compliance.")
			break  

@frappe.whitelist()
def sales_uom_validation(doc, method):
	"""
	Validate that the Sales UOM for each item in the document exists in the Item's UOMs list.
	"""
	doc = _parse_doc(doc)
	
	if doc.get('is_return') or not doc.get('efris_invoice'):
		return

	for item in doc.get('items', []):
		_validate_item_uom(item)
		
def _validate_item_uom(item):
	"""
	Validate that the Sales UOM for the item exists in the Item's UOMs list.
	"""
	item_code = item.get('item_code')
	sales_uom = item.get('uom')

	if not sales_uom:
		return

	item_doc = frappe.get_doc('Item', {'item_code': item_code})
	uoms_detail = item_doc.get('uoms', [])

	if not any(row.uom == sales_uom for row in uoms_detail):
		frappe.throw(f"The Sales UOM ({sales_uom}) must be in the Item's UOMs list for item {item_code}.")
		
def calculate_additional_discounts(doc, method):
	"""
	Calculate additional discounts and adjust tax values on Sales Invoice items for EFRIS compliance.
	"""
	doc = _parse_doc(doc)

	efris_log_info(f"Calculate Additional Discounts called: {doc}")

	discount_percentage = doc.get('additional_discount_percentage', 0) or 0.0
	efris_log_info(f"Issued Discount: {discount_percentage}%")

	if not discount_percentage or not doc.taxes:
		return

	# Load item tax details
	item_taxes = json.loads(doc.taxes[0].item_wise_tax_detail)
	initial_tax = doc.total_taxes_and_charges
	efris_log_info(f"Initial Tax: {initial_tax}")

	total_item_tax, total_discount_tax = _process_items(doc, item_taxes, discount_percentage)
	
def _parse_doc(doc):
	"""
	Parse the `doc` if it's a JSON string.
	"""
	if isinstance(doc, str):
		try:
			return json.loads(doc)
		except json.JSONDecodeError:
			frappe.log_error("Failed to decode `doc` JSON string", "sales_uom_validation Error")
			return None
	return doc
	
def _process_items(doc, item_taxes, discount_percentage):
	"""
	Process each item in the document to calculate discounts and taxes.
	"""
	total_item_tax = 0.0
	total_discount_tax = 0.0

	for row in doc.get('items', []):
		item_code = row.get('item_code', '')
		discount_amount = round(-row.amount * (discount_percentage / 100), 4)
		discounted_item = f"{row.get('item_name', '')} (Discount)"
		tax_rate = float(item_taxes.get(item_code, [0, 0])[0]) or 0.0

		if tax_rate > 0:
			tax_on_discount, discount_tax, item_tax = _calculate_tax_adjustments(discount_amount, tax_rate, row.amount)
			total_item_tax += item_tax
			total_discount_tax += discount_tax
		   
		else:
			
			discount_tax = 0.0
			item_tax = 0.0

		_update_row_values(row, discount_amount, discount_tax, tax_rate, item_tax, discounted_item, doc.get('is_return', False))

	return total_item_tax, total_discount_tax

def _calculate_tax_adjustments(discount_amount, tax_rate, item_amount):
	"""
	Calculate tax adjustments for taxable items.
	"""
	tax_on_discount = round(discount_amount / (1 + (tax_rate / 100)), 4)
	discount_tax = round(discount_amount - tax_on_discount, 4)
	item_tax = round(item_amount * (tax_rate / (100 + tax_rate)), 4)
	return tax_on_discount, discount_tax, item_tax

def _update_row_values(row, discount_amount, discount_tax, tax_rate, item_tax, discounted_item, is_return):
	"""
	Update row values with calculated discounts and taxes.
	"""
	row.efris_dsct_discount_total = -discount_amount if is_return else discount_amount
	row.efris_dsct_discount_tax = -discount_tax if is_return else discount_tax
	row.efris_dsct_discount_tax_rate = f"{tax_rate / 100:.2f}" if tax_rate > 0 else "0.0"
	row.efris_dsct_item_tax = -item_tax if is_return else item_tax
	row.efris_dsct_taxable_amount = -row.amount if is_return else row.amount
	row.efris_dsct_item_discount = discounted_item


def decode_e_tax_rate(tax_rate, e_tax_category):
	e_tax_code = e_tax_category.split(':')[0]
	if e_tax_code == '01':
		return '0.18' 
	if e_tax_code == '02':
		return '0'
	if e_tax_code == '03':
		return '-'
	return str(tax_rate)


#Ref: Directly return False or True where appropriate. Simplify logic to return conditions when met early
def validate_company(doc):
	company_name = doc.get('company', '')

	if not company_name:
		return valid

	try:        
		
		einvoicing_settings = frappe.get_all(
			"E Invoicing Settings",
			fields=["*"], 
			filters={"company": company_name}
		)
	
		if not einvoicing_settings:
			efris_log_error(f"No E Invoicing Settings found for company: {company_name}")
			return False
			
		return True

	
	except Exception as e:
		efris_log_error(f"Unexpected error while validating company '{company_name}': {e}")
		valid = False

def new_credit_note_rate(sales_invoice):
	doc = frappe.get_doc("Sales Invoice", sales_invoice)
	
	if doc.additional_discount_percentage > 0.0:
		return doc.additional_discount_percentage
	
	return None

def before_save(doc, method):
	if doc.is_new() and doc.is_return and doc.return_against:
		sales_invoice = doc.return_against
		
		discount = new_credit_note_rate(sales_invoice)
		
		if discount is None:
			return
		
		for item in doc.items:
			item.rate = item.rate - (discount * item.rate) / 100
			item.amount = item.rate * item.qty

def get_order_no(invoice, item_code, item_name):
	doc_list = frappe.get_all(
		"E Invoice Request Log",
		filters={"reference_doc_type":"Sales Invoice", "reference_document": invoice.name},
		fields=["name"],
		order_by="creation DESC",  
		limit_page_length=1  
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

def get_efris_product_code(item_code):
	product_code = frappe.db.get_value("Item", item_code, "efris_product_code")
	if not product_code:
		frappe.throw(f"No EFRIS Product Code found for item: {item_code}")
	return product_code
