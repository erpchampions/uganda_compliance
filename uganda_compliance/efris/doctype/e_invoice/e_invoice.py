# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe

import json
from collections import defaultdict
from frappe import _
from json import JSONEncoder
from frappe.model.document import Document
from datetime import datetime
from uganda_compliance.efris.utils.utils import efris_log_info
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings
from uganda_compliance.efris.api_classes.e_invoice import EInvoiceAPI, decode_e_tax_rate, validate_company

CONST_EFRIS_PAYMENT_MODE_CREDIT = "Credit"
CONST_EFRIS_PAYMENT_MODE_CREDIT_CODE = "101"


class DateTimeEncoder(JSONEncoder):
	def default(self, obj):
		if isinstance(obj, datetime):
			return obj.isoformat()
		return super(DateTimeEncoder, self).default(obj)

class EInvoice(Document):
	def validate(self):
		efris_log_info("Validating EInvoice")
		self.validate_uom()
		self.validate_items()

	def before_submit(self):
		original_invoice = frappe.get_doc('Sales Invoice',{'name':self.name})
		efris_log_info(f"Sales Invoice IRN :{original_invoice}")
		fdn = original_invoice.efris_irn
		if fdn:
			self.irn = fdn
		
		if not self.irn :
			msg = _("Cannot submit e-invoice without EFRIS.") + ' '
			msg += _("You must generate EFRIS for the sales invoice to submit this e-invoice.")
			frappe.throw(msg, title=_("Missing EFRIS"))
					
	def on_update(self):
		self.update_sales_invoice()

	def on_update_after_submit(self):
		efris_log_info("On update after submit EInvoice")
		self.update_sales_invoice()

	def update_sales_invoice(self):
		dataSource = self.data_source
		data_source_map = {"101":"EFD",
							"102":"Windows Client APP",
							"103":"WebService API",
							"104":"Mis",
							"105":"Webportal",
							"106":"Offline Mode Enabler"
							}
		data_source = data_source_map.get(dataSource,"")
		# Update main fields of Sales Invoice
		frappe.db.set_value("Sales Invoice", self.invoice, {
			'efris_einvoice_status': self.status,
			'efris_qrcode_image': self.qrcode_path,
			'efris_irn_cancel_date': self.irn_cancel_date,
			'efris_irn': self.irn,
			'efris_data_source':f"{dataSource}:{data_source}"
		})          
	

	def on_cancel(self):
		frappe.db.set_value('Sales Invoice', self.invoice, 'efris_e_invoice', self.name, update_modified=False)

	@frappe.whitelist()
	def fetch_invoice_details(self):
		self.set_sales_invoice()
		
		self.set_invoice_type()	
	
		self.set_basic_information()
  
		self.set_seller_details()

		self.set_buyer_details()

		self.set_item_details()
		
		self.set_tax_details()

		self.set_payment_details()
		
		self.set_summary_details()

		self.set_additional_discounts()

	def sync_with_sales_invoice(self):
		self._action = 'save'
		self._validate_links()
		self.fetch_invoice_details()

	def validate_uom(self):
		for item in self.items:
			inv_uom = frappe.get_doc("UOM", item.unit)
			if not inv_uom:
				frappe.log_error(f"Cannot find in UOM List. Unit: {item.unit}")
				frappe.throw("Cannot find in UOM List. Unit:" + item.unit)
			efris_uom_code = inv_uom.efris_uom_code			

			if not efris_uom_code:
				msg = _('Row #{}: {} has invalid UOM set.').format(item.idx, item.item_name) + ' '
				msg += _('Please set EFRIS UOM Code on UOM.')
				frappe.throw(msg, title=_('Invalid Item UOM'))

	def validate_items(self):
		efris_log_info("Validating items")
		error_list = []
		return # TODO validating Items

	def set_basic_information(self):
		efris_log_info("Setting basic information")
		self.invoiceNo = ""
		self.antifakeCode = ""

		self.device_no = get_e_company_settings(self.company).device_no
		
		self.issuedDate = self.sales_invoice.creation
		self.operator = self.sales_invoice.modified_by
		self.currency = self.sales_invoice.currency
		self.oriInvoiceId = ""
		self.invoiceType = self.set_invoice_type()
		self.invoiceKind = 1 
		self.dataSource = 103 
		self.invoiceIndustryCode = 101 
		self.isBatch = 0 
		self.is_return = self.sales_invoice.is_return

	def set_summary_details(self):
		self.net_amount = 0
		self.tax_amount = 0
		for e_tax_item in self.taxes:
			self.tax_amount += e_tax_item.tax_amount
			self.net_amount += e_tax_item.net_amount

		self.net_amount = round(self.net_amount, 2)
		self.gross_amount = round((self.net_amount + self.tax_amount ),2)
		self.item_count = len(self.sales_invoice.items)
		self.mode_code = 1 
		self.remarks = ""
		self.qr_code = ""
	

	def set_sales_invoice(self):
		self.sales_invoice = frappe.get_doc('Sales Invoice', self.invoice)

	def set_invoice_type(self):
		return 1 
	
	def set_supply_type(self):
		efris_customer_type = self.sales_invoice.efris_customer_type
		if efris_customer_type == 'B2B': 
			self.supply_type = 0
		elif efris_customer_type == 'B2C': 
			self.supply_type = 1
		elif efris_customer_type == 'Foreigner': 
			self.supply_type = 2
		elif efris_customer_type == 'B2G': 
			self.supply_type = 3

	def set_tax_details(self):
		efris_log_info("Setting tax details")
		self.taxes = []
		output_vat_account = get_e_company_settings(self.company).output_vat_account

		for tax_item in self.sales_invoice.taxes:
			accnt_id = tax_item.account_head
			accnt = frappe.get_doc('Account', accnt_id)
			if tax_item.charge_type == "On Net Total" and (accnt_id == output_vat_account or accnt.account_type == "Tax"):
				e_taxes_table = {}
				for e_invoice_item in self.items:
					e_tax_category = e_invoice_item.e_tax_category
					tax_amount = e_invoice_item.tax
					# Calculate the discount amount if any, based on the additional_discount_percentage
					discount_amount = 0
					net_amount = 0.0
					gross_amount = 0.0
					if self.sales_invoice.additional_discount_percentage:
						discount_amount = e_invoice_item.amount * (self.sales_invoice.additional_discount_percentage / 100)
						# Adjust gross amount by subtracting the discount amount
						gross_amount = round((e_invoice_item.amount - discount_amount),2)
					else:
						gross_amount = round(e_invoice_item.amount,2)
					# Calculate net amount using the discounted gross amount
									
					net_amount = gross_amount - tax_amount
					tax_rate = decode_e_tax_rate(e_invoice_item.gst_rate, e_tax_category)
					if e_tax_category in e_taxes_table:
						e_taxes_table[e_tax_category]["gross_amount"] += gross_amount
						e_taxes_table[e_tax_category]["net_amount"] += net_amount
						e_taxes_table[e_tax_category]["tax_amount"] += tax_amount
						e_taxes_table[e_tax_category]["nr_items"] += 1
					else:
						e_taxes_table[e_tax_category] = {
							'net_amount': net_amount,
							'tax_rate': tax_rate,
							'tax_amount': tax_amount,
							'gross_amount': round(gross_amount,2),
							'nr_items': 1
						}
				sorted_e_taxes_table_keys = sorted(e_taxes_table.keys())
				for e_tax_category in sorted_e_taxes_table_keys:
					data = e_taxes_table[e_tax_category]
					taxes = frappe._dict({
						"tax_category_code": e_tax_category,
						"net_amount": round(data['net_amount'], 2),  
						"tax_rate": data['tax_rate'],
						"tax_amount": round(data['tax_amount'], 2),
						"gross_amount": round(data['gross_amount'], 2),
						"excise_unit": "",
						"excise_currency": "",
						"tax_rate_name": ""
					})
					self.append("taxes", taxes)

	def set_payment_details(self):
		paid_amount = 0.0
		payment_mode = ""
		self.e_payments = [] 
		credit = ""  
		total_payment = ""   
		payments = ""    
		if self.sales_invoice.is_return:
			orignal_einvoice = EInvoiceAPI.get_einvoice(self.sales_invoice.return_against)
			credit = orignal_einvoice.credit_amount
		else:
			total_payment = self.sales_invoice.paid_amount or 0.0
			
			if total_payment != 0.0:
				credit = self.sales_invoice.outstanding_amount or 0.0

			else:
				credit = self.sales_invoice.grand_total or 0.0
		
		payments = self.sales_invoice.payments
		if not payments:
			payment_mode = self.sales_invoice.efris_payment_mode 
		for pay_amount in self.sales_invoice.payments:
			paid_amount = pay_amount.amount                
			payment_mode = pay_amount.mode_of_payment
			e_payments =frappe._dict(
				{
					 "amount":paid_amount,
					"mode_of_payment":payment_mode
			}
			) 
			self.append('e_payments', e_payments)
			self.paid_amount = total_payment
		self.credit_amount = credit
		# Add "Credit" line if credit amount exists
		if abs(credit) > 0:
			if not self.sales_invoice.efris_payment_mode:
				payment_mode = CONST_EFRIS_PAYMENT_MODE_CREDIT
			credit_payment = frappe._dict({
				"amount": credit,
				"mode_of_payment": payment_mode,
			})
			self.append('e_payments', credit_payment)
		self.credit_amount = credit

				

	def set_seller_details(self):
		company_address = self.sales_invoice.company_address
	   
		self.seller_email = self.sales_invoice.efris_seller_email
		if company_address:
			seller_address = frappe.get_all('Address', {'name': company_address}, ['*'])[0]
			self.seller_phone = seller_address.phone           
			self.seller_address = ' '.join(filter(None, [
														seller_address.address_line2,
														seller_address.address_line1,
														seller_address.county,
														seller_address.city,
														seller_address.country,
														self.seller_email
													]))[:140]

			if not self.seller_address:
				frappe.throw(f"Seller Address is not set")
			
		self.seller_legal_name = self.company
		company = frappe.get_doc('Company', {'name': self.seller_legal_name})
		self.seller_nin_or_brn  = company.efris_nin_or_brn

		self.seller_gstin = self.sales_invoice.company_tax_id       

		self.seller_reference_no = self.sales_invoice.efris_seller_reference_no
		if not self.seller_reference_no:
			self.seller_reference_no = self.sales_invoice.name
		self.seller_trade_name = self.company

	def set_buyer_details(self):
		customer_name = self.sales_invoice.customer
		if not customer_name:
			frappe.throw(_('Customer must be set to be able to generate e-invoice.'))
		customer = frappe.get_doc('Customer', customer_name)

		self.buyer_gstin = customer.tax_id
		efris_customer_type = customer.efris_customer_type 
		
		if not efris_customer_type:
			frappe.throw(_('EFRIS Customer Type must be set on on the Customer Details page.'))
		
		if efris_customer_type == 'B2B' and not self.buyer_gstin:
			frappe.log_error(_('TaxID/TIN must be set for B2B Customer (GST Category). See Tax tab on Customer profile.'))
			frappe.throw(_('TaxID/TIN must be set for B2B Customer (GST Category). See Tax tab on Customer profile.'))
		self.sales_invoice.efris_customer_type = efris_customer_type
		self.set_supply_type()

		self.buyer_legal_name = customer.customer_name
		self.buyer_nin_or_brn = customer.efris_nin_or_brn         
		self.buyer_citizenship = ""
		self.buyer_sector = ""
		self.buyer_reference_no = ""
		self.non_resident_flag = 0 

	def set_item_details(self):
		self.update_items_from_invoice()

	def set_additional_discounts(self):
		self.applied_discount_on = self.sales_invoice.apply_discount_on
		self.additional_discount_percentage = self.sales_invoice.additional_discount_percentage
		self.discount_amount = self.sales_invoice.discount_amount

	def fetch_items_from_invoice(self):	   
		if not self.sales_invoice.taxes:
			frappe.throw("taxes table can't be empty")
		item_taxes = json.loads(self.sales_invoice.taxes[0].item_wise_tax_detail)
		conversion_rate = self.sales_invoice.conversion_rate
		
		for i, item in enumerate(self.sales_invoice.items):
			if not item.efris_commodity_code:
				frappe.throw(_('Row #{}: Item {} must have EFRIS Commodity code set to be able to generate e-invoice.').format(item.idx, item.item_code))
			is_service_item = item.efris_commodity_code[:2] == "99"
			item_doc = frappe.get_doc("Item", item.item_code)
			if item_doc.taxes:
				tax_template = frappe.get_doc("Item Tax Template", item_doc.taxes[0].item_tax_template)
			else:
				frappe.throw(_('Row #{}: Item {} must have Tax Template set under Tax tab').format(item.idx, item.item_code))
			efris_tax_category = tax_template.taxes[0].efris_e_tax_category
			if not efris_tax_category:
				frappe.throw(_("Missing EFRIS Tax Category on Row #{}: Item {}. Ensure all Items have E Tax Category set under Item Tax Template Detail").format(item.idx, item.item_code))
			
			item_tax_amount = item_taxes[item.item_code][1]
			if not conversion_rate == 1:
				item_tax_amount = item_tax_amount / conversion_rate

			item_tax_amount = round(item_tax_amount,2)
			
			
			einvoice_item = frappe._dict({
				'si_item_ref': item.item_code,
				'item_code': item.item_code,
				'item_name': item.item_name,
				'is_service_item': is_service_item,
				'efris_commodity_code': item.efris_commodity_code,
				'quantity': item.qty,
				'unit': item.uom, 
				'rate': round(item.rate, 2),
				'tax': item_tax_amount,
				'gst_rate':  decode_e_tax_rate(round(item_taxes[item.item_code][0]/100, 2), efris_tax_category),
				'amount': round(item.amount, 2),
				'order_number': i,
				'e_tax_category': efris_tax_category,
				'efris_dsct_discount_total':round(item.efris_dsct_discount_total,4),
				'efris_dsct_discount_tax' : round(item.efris_dsct_discount_tax,4),
				'efris_dsct_discount_tax_rate' : item.efris_dsct_discount_tax_rate,
				'efris_dsct_item_tax' : item.efris_dsct_item_tax,
				'efris_dsct_taxable_amount' : round(item.efris_dsct_taxable_amount,4),
				'efris_dsct_item_discount' : item.efris_dsct_item_discount,
				'commodity_code_description': frappe.get_doc("EFRIS Commodity Code", item.efris_commodity_code).commodity_name
			})
			self.append('items', einvoice_item)


	def update_items_from_invoice(self):
		if self.items:
			self.get("items").clear()
		self.fetch_items_from_invoice()

	def get_einvoice_json(self):
		einvoice_json = {
			"extend": {},
			"importServicesSeller": {},
			"airlineGoodsDetails": [{}],
			"edcDetails": {},
			"agentEntity": {}
		}
		einvoice_json.update(self.get_seller_details_json())
		einvoice_json.update(self.get_basic_information_json())
		einvoice_json.update(self.get_buyer_details_json())
		einvoice_json.update(self.get_buyer_extend())
		einvoice_json.update(self.get_good_details())
		einvoice_json.update(self.get_tax_details())
		einvoice_json.update(self.get_summary())
		einvoice_json.update(self.get_payment_details())
		return einvoice_json

	def get_seller_details_json(self):
		try:
			
			seller_details = {
				"sellerDetails": {
					"tin": self.seller_gstin if self.seller_gstin is not None else "",
					"ninBrn": self.seller_nin_or_brn if self.seller_nin_or_brn else "",
					"legalName": self.seller_legal_name if self.seller_legal_name is not None else "",
					"businessName": self.seller_trade_name if self.seller_trade_name is not None else "",
					"mobilePhone": self.seller_phone if self.seller_phone is not None else "",
					"linePhone": "",
					"emailAddress": self.seller_email if self.seller_email is not None else "",
					"referenceNo": self.seller_reference_no if self.seller_reference_no is not None else "",
					"branchId": "",
					"isCheckReferenceNo": "0",
					"branchName": "Test",
					"branchCode": ""
				}
			}
			
			return seller_details
		except Exception as e:
			frappe.log_error(f"Error getting seller details JSON: {e}")
			raise


	def get_basic_information_json(self):
		return {
			"basicInformation": {
				"invoiceNo": "",
				"antifakeCode": "",
				"deviceNo": self.device_no,
				"issuedDate": str(self.issuedDate),
				"operator": self.operator,
				"currency": self.currency,
				"oriInvoiceId": "",
				"invoiceType": str(self.invoiceType),
				"invoiceKind": str(self.invoiceKind),
				"dataSource": str(self.dataSource),
				"invoiceIndustryCode": str(self.invoiceIndustryCode),
				"isBatch": str(self.isBatch)
			}
		}
	
	def get_buyer_details_json(self):
		return {
			"buyerDetails": {
				"buyerTin": self.buyer_gstin if self.buyer_gstin is not None else "",
				"buyerNinBrn": self.buyer_nin_or_brn,
				"buyerPassportNum": "",
				"buyerLegalName": self.buyer_legal_name,
				"buyerBusinessName": self.buyer_legal_name,
				"buyerType": self.supply_type,
				"buyerCitizenship": self.buyer_citizenship,
				"buyerSector": self.buyer_sector,
				"buyerReferenceNo": self.buyer_reference_no,
				"nonResidentFlag": self.non_resident_flag
			}
		}

	def get_buyer_extend(self):
		return {
			"buyerExtend": {
				"propertyType": "",
				"district": "",
				"municipalityCounty": "",
				"divisionSubcounty": "",
				"town": "",
				"cellVillage": "",
				"effectiveRegistrationDate": "",
				"meterStatus": ""
			}
		}

	def get_good_details(self):
		item_list = []
		unique_items = set()    
		
		orderNumber = 0
		discount_percentage = self.additional_discount_percentage if self.additional_discount_percentage else 0
		
		item_code  = ""
		goodsCode = ""      
		discount_tax = 0.0    
		discountTaxRate = ""
		for row in self.items:
			taxRate = decode_e_tax_rate(str(row.gst_rate), row.e_tax_category)
			item_code = row.item_code
			goodsCode = frappe.db.get_value("Item",{"item_code":item_code},"efris_product_code")
			if goodsCode:
				item_code = goodsCode
			# Create a unique identifier for the item
			if self._is_duplicate_item(row, unique_items):
				continue

			inv_uom = frappe.get_doc("UOM", row.unit)
			efris_uom_code = inv_uom.efris_uom_code

			# Calculate the discount amount if applicable
			discount_amount = 0.0
			discountFlag = "0"
			tax = row.tax
			discounted_item = row.item_name            

			if discount_percentage > 0:
				discount_amount, discountFlag, discounted_item, discountTaxRate = self.calculate_discounts(row, discount_percentage, taxRate)

			item, discount_item = self._prepare_item_details(row, item_code, taxRate, efris_uom_code, discount_percentage, orderNumber, discount_amount, discountFlag, discounted_item, discountTaxRate)
			item_list.append(item)
			orderNumber += 1
   
			if discount_item:
				item_list.append(discount_item)
				orderNumber += 1

		return {"goodsDetails": item_list}

	def calculate_discounts(self, row, discount_percentage, taxRate):
		discount_amount = row.efris_dsct_discount_total
		discountFlag = "1"
		discounted_item = row.item_name + " (Discount)"
		discountTaxRate = taxRate 
		efris_log_info(f"Taxable Amount :{row.amount}")
		
		if taxRate == '0.18':
			tax = row.efris_dsct_item_tax                   
		if not taxRate or taxRate in ["-", "Exempt"]:
			discountTaxRate = "0.0"
		return discount_amount, discountFlag, discounted_item, discountTaxRate
     
	def _is_duplicate_item(self, row, unique_items):
		unique_identifier = f"{row.item_code}_{row.unit}_{row.rate}"
		if unique_identifier in unique_items:
			return True
		unique_items.add(unique_identifier)
		return False
	
	def _prepare_item_details(self, row, item_code, tax_rate, efris_uom_code, discount_percentage, order_number, discount_amount, discount_flag, discounted_item, discount_tax_rate):
		tax = row.efris_dsct_item_tax if tax_rate == '0.18' and discount_percentage > 0 else row.tax

		item = {
			"item": row.item_name,
			"itemCode": item_code,
			"qty": str(row.quantity),
			"unitOfMeasure": efris_uom_code,
			"unitPrice": str(row.rate),
			"total": str(row.amount),
			"taxRate": str(tax_rate),
			"tax": str(tax),
			"discountTotal": str(discount_amount) if discount_percentage > 0 else "",
			"discountTaxRate": str(discount_tax_rate),
			"orderNumber": str(order_number),
			"discountFlag": discount_flag if discount_percentage > 0 else "2",
			"deemedFlag": "2",
			"exciseFlag": "2",
			"categoryId": "",
			"categoryName": "",
			"goodsCategoryId": row.efris_commodity_code,
			"goodsCategoryName": row.commodity_code_description,
			"vatApplicableFlag": "1",
		}

		discount_item = None
		if discount_percentage > 0:
			discount_tax = row.efris_dsct_discount_tax if tax_rate == '0.18' else tax
			discount_item = {
				"item": discounted_item,
				"itemCode": item_code,
				"qty": "",
				"unitOfMeasure": "",
				"unitPrice": "",
				"total": str(discount_amount),
				"taxRate": str(tax_rate),
				"tax": str(discount_tax),
				"discountTotal": "",
				"discountTaxRate": str(discount_tax_rate),
				"orderNumber": str(order_number + 1),
				"discountFlag": "0",
				"deemedFlag": "2",
				"exciseFlag": "2",
				"categoryId": "",
				"categoryName": "",
				"goodsCategoryId": row.efris_commodity_code,
				"goodsCategoryName": "",
				"vatApplicableFlag": "1",
			}

		return item, discount_item


 
	def get_tax_details(self):
		efris_log_info("Getting tax details JSON")
		tax_details_list = []
		
		tax_per_category = calculate_tax_by_category(self.invoice)
		trimmed_response = {}
		for key, value in tax_per_category.items():
			# Extract the part inside the parentheses
			tax_category = key.split('(')[1].split(')')[0]
			tax_category = tax_category.replace('%', '')
			trimmed_response[tax_category] = value
		
		for row in self.taxes:
			tax_rate_key='0'
			if row.tax_rate=='0.18':
				tax_rate = float(row.tax_rate)
				tax_rate_key = str(int(tax_rate * 100))
			else:
				tax_rate_key = row.tax_rate
			tax_category = row.tax_category_code.split(':')[0]
   			
			if tax_rate_key in trimmed_response:
				calculated_tax = round(trimmed_response[tax_rate_key],2)
				# Take care of when we have mismatch of decimal points summary and taxDetails values
			if calculated_tax > 0 and calculated_tax != calculate_additional_discounts(self.invoice):
				calculated_tax = calculate_additional_discounts(self.invoice)
			tax_details = {
				"taxCategoryCode": tax_category,
				"netAmount": str(row.net_amount),
				"taxRate": str(row.tax_rate),
				"taxAmount": str(round(calculated_tax, 2)),
				"grossAmount": round(calculated_tax + row.net_amount, 2),
				"exciseUnit": "",
				"exciseCurrency": "",
				"taxRateName": ""
			}
			tax_details_list.append(tax_details)
		
		return {"taxDetails": tax_details_list}
	
	def get_payment_details(self):
		efris_log_info("Getting Payment details JSON")
		payment_list = []      
		payment_code = ""
	   
		for row in self.e_payments:
			 # Map mode_of_payment to the corresponding EFRIS code
			mode_of_payment = row.mode_of_payment
			if mode_of_payment and mode_of_payment != CONST_EFRIS_PAYMENT_MODE_CREDIT:
				efris_payment_mode  = frappe.db.get_value('Mode of Payment',{'name':mode_of_payment},'efris_payment_mode') 
				if not efris_payment_mode:
					frappe.throw(f"EFRIS Mode of Payment must be configured on Payment Mode: {mode_of_payment}")

				payment_code = efris_payment_mode.split(':')[0] 
			elif mode_of_payment == CONST_EFRIS_PAYMENT_MODE_CREDIT:
				payment_code = CONST_EFRIS_PAYMENT_MODE_CREDIT_CODE    
			
			payments = {
				"paymentMode": str(payment_code),
				"paymentAmount": str(round(row.amount,2)),
				"orderNumber": "a"
			}
			payment_list.append(payments)
		return {"payWay": payment_list}

	def get_summary(self):
		efris_log_info("Getting summary JSON")
		return {
			"summary": {
				"netAmount": str(self.net_amount),
				"taxAmount": calculate_additional_discounts(self.invoice),
				"grossAmount": round(calculate_additional_discounts(self.invoice) + self.net_amount,2),
				"itemCount": str(self.item_count),
				"modeCode": str(self.mode_code),
				"remarks": self.remarks,
				"qrCode": self.qr_code
			}
		}
	def get_additional_discount(self):
		return {"additional_discount_percentage":self.additional_discount_percentage}
	

def calculate_additional_discounts(invoice):
    """
    Calculate additional discounts and adjust tax values on Sales Invoice items for EFRIS compliance.
    """
    doc = _get_valid_document(invoice)

    discount_percentage = doc.get('additional_discount_percentage', 0) or 0.0
    if not doc.taxes:
        return

    item_taxes = json.loads(doc.taxes[0].item_wise_tax_detail)
    total_item_tax, total_discount_tax = _calculate_taxes_and_discounts(doc, item_taxes, discount_percentage)

    calculated_total_tax = round(total_item_tax + total_discount_tax, 2)
    return calculated_total_tax


def _get_valid_document(invoice):
    """
    Fetch and validate the Sales Invoice document.
    """
    try:
        doc = frappe.get_doc('Sales Invoice', invoice)
        if isinstance(doc, str):
            doc = json.loads(doc)
        return doc
    except (json.JSONDecodeError, Exception) as e:
        frappe.log_error(f"Failed to process document: {e}", "calculate_additional_discounts Error")
        return None


def _calculate_taxes_and_discounts(doc, item_taxes, discount_percentage):
    """
    Calculate taxes and discounts for each item in the document.
    """
    total_item_tax = 0.0
    total_discount_tax = 0.0

    for row in doc.get('items', []):
        item_code = row.get('item_code', '')
        discount_amount = round(-row.amount * (discount_percentage / 100), 4)
        tax_rate = float(item_taxes.get(item_code, [0, 0])[0]) or 0.0

        discount_tax, item_tax = _calculate_tax_adjustments(discount_amount, tax_rate, row.amount)
        total_item_tax += item_tax
        total_discount_tax += discount_tax

        _update_row_with_discount_details(row, discount_amount, discount_tax, tax_rate, item_tax)

    return total_item_tax, total_discount_tax


def _calculate_tax_adjustments(discount_amount, tax_rate, item_amount):
    """
    Calculate tax adjustments for a given discount amount and tax rate.
    """
    if tax_rate > 0:
        tax_on_discount = round(discount_amount / (1 + (tax_rate / 100)), 4)
        discount_tax = round(discount_amount - tax_on_discount, 2)
        item_tax = round(item_amount * (tax_rate / (100 + tax_rate)), 2)
    else:
        discount_tax = 0.0
        item_tax = 0.0

    return discount_tax, item_tax


def _update_row_with_discount_details(row, discount_amount, discount_tax, tax_rate, item_tax):
    """
    Update the row with calculated discount and tax details.
    """
    row.efris_dsct_discount_total = discount_amount
    row.efris_dsct_discount_tax = discount_tax
    row.efris_dsct_discount_tax_rate = f"{tax_rate / 100:.2f}" if tax_rate > 0 else "0.0"
    row.efris_dsct_item_tax = item_tax
    row.efris_dsct_taxable_amount = row.amount
    row.efris_dsct_item_discount = f"{row.get('item_name', '')} (Discount)"
	
 
def calculate_tax_by_category(invoice):
	"""
	Calculate total tax per tax category for Sales Invoice items.
	"""
	
	doc = frappe.get_doc('Sales Invoice', invoice)

	doc = _get_valid_document(invoice)

	if not doc.taxes:
		return

	item_taxes = json.loads(doc.taxes[0].item_wise_tax_detail)

	tax_category_totals = defaultdict(float)

	for row in doc.get('items', []):
		item_code = row.get('item_code', '')
		item_tax_template = row.get('item_tax_template', '')

		if not item_tax_template:
			continue

		tax_rate = float(item_taxes.get(item_code, [0, 0])[0]) or 0.0

		if tax_rate > 0:
			item_tax = round(row.amount * (tax_rate / (100 + tax_rate)), 2) 
			if doc.additional_discount_percentage >0.0:
				item_tax = item_tax + row.efris_dsct_discount_tax
			tax_category_totals[item_tax_template] += item_tax
		else:
			item_tax=0.0
			tax_category_totals[item_tax_template] += item_tax

	tax_category_totals = dict(tax_category_totals)

	return tax_category_totals