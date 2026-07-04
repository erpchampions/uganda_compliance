"""App-install / app-migrate setup hooks.

Wires the EFRIS-specific custom fields onto Customer and Supplier records so
T119 validation has somewhere to write its results.
"""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


_PARTY_FIELDS = [
	{
		"fieldname": "efris_section",
		"fieldtype": "Section Break",
		"label": "EFRIS",
		"insert_after": "tax_id",
		"collapsible": 1,
	},
	{
		"fieldname": "efris_legal_name",
		"fieldtype": "Data",
		"label": "Legal Name",
		"insert_after": "efris_section",
		"read_only": 1,
		"description": "Confirmed by EFRIS T119 against the Tax ID.",
	},
	{
		"fieldname": "efris_business_name",
		"fieldtype": "Data",
		"label": "Business Name",
		"insert_after": "efris_legal_name",
		"read_only": 1,
	},
	{
		"fieldname": "efris_column_break",
		"fieldtype": "Column Break",
		"insert_after": "efris_business_name",
	},
	{
		"fieldname": "efris_taxpayer_status",
		"fieldtype": "Data",
		"label": "Taxpayer Status",
		"insert_after": "efris_column_break",
		"read_only": 1,
	},
	{
		"fieldname": "efris_taxpayer_type",
		"fieldtype": "Data",
		"label": "Taxpayer Type",
		"insert_after": "efris_taxpayer_status",
		"read_only": 1,
	},
	{
		"fieldname": "efris_last_validated_on",
		"fieldtype": "Datetime",
		"label": "Last Validated by EFRIS",
		"insert_after": "efris_taxpayer_type",
		"read_only": 1,
	},
]


_CUSTOMER_EXTRA_FIELDS = [
	{
		"fieldname": "efris_upload_trigger",
		"fieldtype": "Select",
		"label": "EFRIS Upload Trigger",
		"insert_after": "efris_last_validated_on",
		"options": "\nManual\nOn Submit\nOn Payment",
		"description": (
			"Overrides the default EFRIS upload trigger from EFRIS Settings for "
			"this customer. Leave blank to inherit. "
			"'On Submit' uploads when the Sales Invoice is submitted; "
			"'On Payment' uploads when a Payment Entry is submitted against it; "
			"'Manual' requires the user to click the EFRIS button."
		),
	},
]


PARTY_CUSTOM_FIELDS = {
	"Customer": _PARTY_FIELDS + _CUSTOMER_EXTRA_FIELDS,
	"Supplier": _PARTY_FIELDS,
}


# Single Link → EFRIS Dictionary, category-filtered to the right T115 table.
# Lives on UOM / Currency so each Item picks up its EFRIS code automatically
# from `stock_uom` and the Company currency — no per-Item duplication.
UOM_CUSTOM_FIELDS = {
	"UOM": [
		{
			"fieldname": "efris_dictionary",
			"fieldtype": "Link",
			"options": "EFRIS Dictionary",
			"label": "EFRIS Rate Unit",
			"insert_after": "enabled",
			"description": "EFRIS Dictionary entry in category `rateUnit`. Used as T130 measureUnit.",
		},
	],
	# Per-Item overrides for EFRIS "other unit" rows. The UOM itself supplies
	# the EFRIS Dictionary mapping; here we store the per-Item price and
	# package_scaled values that EFRIS T130 wants for each non-stock UOM.
	"UOM Conversion Detail": [
		{
			"fieldname": "efris_unit_price",
			"fieldtype": "Currency",
			"label": "EFRIS Unit Price",
			"insert_after": "conversion_factor",
			"in_list_view": 1,
			"columns": 2,
			"description": "Price sent as T130 otherPrice. Only used for non-stock rows.",
		},
		{
			"fieldname": "efris_package_scaled",
			"fieldtype": "Float",
			"label": "EFRIS Package Scaled",
			"insert_after": "efris_unit_price",
			"default": "1",
			"in_list_view": 1,
			"columns": 2,
			"description": "Sent as T130 packageScaled. Only used for non-stock rows.",
		},
	],
}

CURRENCY_CUSTOM_FIELDS = {
	"Currency": [
		{
			"fieldname": "efris_dictionary",
			"fieldtype": "Link",
			"options": "EFRIS Dictionary",
			"label": "EFRIS Currency",
			"insert_after": "enabled",
			"description": "EFRIS Dictionary entry in category `currencyType`. Used as T130 currency.",
		},
	]
}


MODE_OF_PAYMENT_CUSTOM_FIELDS = {
	"Mode of Payment": [
		{
			"fieldname": "efris_dictionary",
			"fieldtype": "Link",
			"options": "EFRIS Dictionary",
			"label": "EFRIS Pay Way",
			"insert_after": "type",
			"description": "EFRIS Dictionary entry in category `payWay`. Sent as T109 payWay.paymentMode.",
		},
	]
}


ITEM_CUSTOM_FIELDS = {
	"Item": [
		{
			"fieldname": "efris_section",
			"fieldtype": "Section Break",
			"label": "EFRIS",
			"insert_after": "item_group",
			"collapsible": 1,
		},
		{
			"fieldname": "efris_goods_code",
			"fieldtype": "Data",
			"label": "Goods Code",
			"insert_after": "efris_section",
			"description": "Code sent to EFRIS as goodsCode. Defaults to the Item Code if left blank.",
		},
		{
			"fieldname": "efris_commodity_category",
			"fieldtype": "Link",
			"options": "EFRIS Commodity Category",
			"label": "Commodity Category",
			"insert_after": "efris_goods_code",
			"description": "URA commodityCategoryId for this item. Tree-picker — drill down to a leaf node.",
		},
		{
			"fieldname": "efris_goods_type",
			"fieldtype": "Select",
			"label": "Goods Type",
			"insert_after": "efris_commodity_category",
			"options": "101 - Goods\n102 - Fuel",
			"default": "101 - Goods",
		},
		{
			"fieldname": "efris_stock_prewarning",
			"fieldtype": "Float",
			"label": "Stock Prewarning",
			"insert_after": "efris_goods_type",
			"default": "0",
			"description": "Send 0 for service items.",
		},
		{
			"fieldname": "efris_column_break_1",
			"fieldtype": "Column Break",
			"insert_after": "efris_stock_prewarning",
		},
		{
			"fieldname": "efris_have_excise_tax",
			"fieldtype": "Check",
			"label": "Has Excise Tax",
			"insert_after": "efris_column_break_1",
			"default": "0",
		},
		{
			"fieldname": "efris_excise_duty_code",
			"fieldtype": "Link",
			"options": "EFRIS Excise Duty",
			"label": "Excise Duty Code",
			"insert_after": "efris_have_excise_tax",
			"depends_on": "eval:doc.efris_have_excise_tax",
			"mandatory_depends_on": "eval:doc.efris_have_excise_tax",
		},
		{
			"fieldname": "efris_have_piece_unit",
			"fieldtype": "Check",
			"label": "Has Piece Unit",
			"insert_after": "efris_excise_duty_code",
			"default": "0",
		},
		{
			"fieldname": "efris_piece_measure_unit",
			"fieldtype": "Link",
			"label": "Piece Measure Unit",
			"options": "EFRIS Dictionary",
			"insert_after": "efris_have_piece_unit",
			"depends_on": "eval:doc.efris_have_piece_unit",
			"mandatory_depends_on": "eval:doc.efris_have_piece_unit",
		},
		{
			"fieldname": "efris_piece_unit_price",
			"fieldtype": "Currency",
			"label": "Piece Unit Price",
			"insert_after": "efris_piece_measure_unit",
			"depends_on": "eval:doc.efris_have_piece_unit",
		},
		{
			"fieldname": "efris_package_scaled_value",
			"fieldtype": "Float",
			"label": "Package Scaled Value",
			"insert_after": "efris_piece_unit_price",
			"depends_on": "eval:doc.efris_have_piece_unit",
			"default": "1",
		},
		{
			"fieldname": "efris_piece_scaled_value",
			"fieldtype": "Float",
			"label": "Piece Scaled Value",
			"insert_after": "efris_package_scaled_value",
			"depends_on": "eval:doc.efris_have_piece_unit",
			"default": "1",
		},
		{
			"fieldname": "efris_have_customs_unit",
			"fieldtype": "Check",
			"label": "Has Customs Unit",
			"insert_after": "efris_piece_scaled_value",
			"default": "0",
		},
		{
			"fieldname": "efris_customs_units",
			"fieldtype": "Table",
			"label": "Customs Units",
			"options": "EFRIS Customs Unit",
			"insert_after": "efris_have_customs_unit",
			"depends_on": "eval:doc.efris_have_customs_unit",
		},
		{
			"fieldname": "efris_status_section",
			"fieldtype": "Section Break",
			"label": "EFRIS Upload Status",
			"insert_after": "efris_customs_units",
			"collapsible": 1,
		},
		{
			"fieldname": "efris_uploaded",
			"fieldtype": "Check",
			"label": "Uploaded to EFRIS",
			"insert_after": "efris_status_section",
			"read_only": 1,
		},
		{
			"fieldname": "efris_operation_type",
			"fieldtype": "Data",
			"label": "Last Operation Type",
			"insert_after": "efris_uploaded",
			"read_only": 1,
		},
		{
			"fieldname": "efris_status_column_break",
			"fieldtype": "Column Break",
			"insert_after": "efris_operation_type",
		},
		{
			"fieldname": "efris_last_uploaded_on",
			"fieldtype": "Datetime",
			"label": "Last Uploaded On",
			"insert_after": "efris_status_column_break",
			"read_only": 1,
		},
		{
			"fieldname": "efris_upload_error",
			"fieldtype": "Small Text",
			"label": "Last Upload Error",
			"insert_after": "efris_last_uploaded_on",
			"read_only": 1,
		},
	]
}


def _stock_status_fields(insert_after: str) -> list[dict]:
	"""Reusable EFRIS upload status block for stock-movement doctypes."""
	return [
		{
			"fieldname": "efris_status_section",
			"fieldtype": "Section Break",
			"label": "EFRIS Upload Status",
			"insert_after": insert_after,
			"collapsible": 1,
		},
		{
			"fieldname": "efris_uploaded",
			"fieldtype": "Check",
			"label": "Uploaded to EFRIS",
			"insert_after": "efris_status_section",
			"read_only": 1,
		},
		{
			"fieldname": "efris_operation_type",
			"fieldtype": "Data",
			"label": "Last Operation Type",
			"insert_after": "efris_uploaded",
			"read_only": 1,
		},
		{
			"fieldname": "efris_status_column_break",
			"fieldtype": "Column Break",
			"insert_after": "efris_operation_type",
		},
		{
			"fieldname": "efris_last_uploaded_on",
			"fieldtype": "Datetime",
			"label": "Last Uploaded On",
			"insert_after": "efris_status_column_break",
			"read_only": 1,
		},
		{
			"fieldname": "efris_upload_error",
			"fieldtype": "Small Text",
			"label": "Last Upload Error",
			"insert_after": "efris_last_uploaded_on",
			"read_only": 1,
		},
	]


STOCK_ENTRY_CUSTOM_FIELDS = {
	"Stock Entry": [
		{
			"fieldname": "efris_section",
			"fieldtype": "Section Break",
			"label": "EFRIS",
			"insert_after": "remarks",
			"collapsible": 1,
		},
		{
			"fieldname": "efris_stock_in_type",
			"fieldtype": "Select",
			"label": "EFRIS Stock-In Type",
			"insert_after": "efris_section",
			"options": "\n101 - Import\n102 - Local Purchase\n103 - Manufacture\n104 - Opening Stock",
			"depends_on": "eval:doc.stock_entry_type=='Material Receipt'",
			"mandatory_depends_on": "eval:doc.stock_entry_type=='Material Receipt'",
			"description": "Required for Material Receipt entries — sent as T131 stockInType.",
		},
		{
			"fieldname": "efris_adjust_type",
			"fieldtype": "Data",
			"label": "EFRIS Adjust Type",
			"insert_after": "efris_stock_in_type",
			"depends_on": "eval:['Material Issue','Manufacture','Repack'].includes(doc.stock_entry_type)",
			"description": "EFRIS adjustType code(s). 101=Expired, 102=Damaged, 103=Personal, 104=Other, 105=Raw Material. Comma-separate for multiples.",
		},
		{
			"fieldname": "efris_adjust_remarks",
			"fieldtype": "Small Text",
			"label": "EFRIS Adjust Remarks",
			"insert_after": "efris_adjust_type",
			"depends_on": "eval:(doc.efris_adjust_type||'').indexOf('104')!==-1",
			"mandatory_depends_on": "eval:(doc.efris_adjust_type||'').indexOf('104')!==-1",
		},
		{
			"fieldname": "efris_transfer_type",
			"fieldtype": "Data",
			"label": "EFRIS Transfer Type",
			"insert_after": "efris_adjust_remarks",
			"depends_on": "eval:doc.stock_entry_type=='Material Transfer'",
			"mandatory_depends_on": "eval:doc.stock_entry_type=='Material Transfer'",
			"description": "T139 transferTypeCode. 101=Out of Stock Adjust, 102=Error Adjust, 103=Others. Comma-separate for multiples.",
		},
		{
			"fieldname": "efris_transfer_remarks",
			"fieldtype": "Small Text",
			"label": "EFRIS Transfer Remarks",
			"insert_after": "efris_transfer_type",
			"depends_on": "eval:doc.stock_entry_type=='Material Transfer'",
			"mandatory_depends_on": "eval:doc.stock_entry_type=='Material Transfer' && (doc.efris_transfer_type||'').indexOf('103')!==-1",
		},
		{
			"fieldname": "efris_vehicle_no",
			"fieldtype": "Data",
			"label": "EFRIS Vehicle No",
			"insert_after": "efris_transfer_remarks",
			"depends_on": "eval:doc.stock_entry_type=='Material Transfer'",
			"length": 200,
		},
		*_stock_status_fields("efris_vehicle_no"),
	]
}


PURCHASE_RECEIPT_CUSTOM_FIELDS = {
	"Purchase Receipt": _stock_status_fields("remarks"),
}


WAREHOUSE_CUSTOM_FIELDS = {
	"Warehouse": [
		{
			"fieldname": "efris_branch",
			"fieldtype": "Link",
			"options": "Branch",
			"label": "EFRIS Branch",
			"insert_after": "warehouse_name",
			"description": "ERPNext Branch this warehouse belongs to. T139 uses its EFRIS Branch ID for stock transfers.",
		},
	]
}


BRANCH_CUSTOM_FIELDS = {
	"Branch": [
		{
			"fieldname": "efris_branch_id",
			"fieldtype": "Data",
			"label": "EFRIS Branch ID",
			"insert_after": "branch",
			"length": 18,
			"description": "URA-issued branch identifier (T138 branchId). Mapped from the EFRIS Settings Branches table.",
		},
	]
}


def _e_invoice_status_fields(insert_after: str) -> list[dict]:
	"""Reusable EFRIS T109 upload-status block for Sales Invoice / POS Invoice.

	All status fields are ``no_copy = 1`` so an ERPNext return doesn't inherit
	the original document's upload state (which would hide the EFRIS button).
	"""
	return [
		{
			"fieldname": "efris_section",
			"fieldtype": "Section Break",
			"label": "EFRIS",
			"insert_after": insert_after,
			"collapsible": 1,
		},
		{
			"fieldname": "efris_e_invoice",
			"fieldtype": "Link",
			"options": "E-Invoice",
			"label": "E-Invoice",
			"insert_after": "efris_section",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "efris_uploaded",
			"fieldtype": "Check",
			"label": "Uploaded to EFRIS",
			"insert_after": "efris_e_invoice",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "efris_invoice_id",
			"fieldtype": "Data",
			"label": "EFRIS Invoice ID",
			"insert_after": "efris_uploaded",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "efris_antifake_code",
			"fieldtype": "Data",
			"label": "EFRIS Antifake Code",
			"insert_after": "efris_invoice_id",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "efris_status_column_break",
			"fieldtype": "Column Break",
			"insert_after": "efris_antifake_code",
		},
		{
			"fieldname": "efris_last_uploaded_on",
			"fieldtype": "Datetime",
			"label": "Last Uploaded On",
			"insert_after": "efris_status_column_break",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "efris_upload_error",
			"fieldtype": "Small Text",
			"label": "Last Upload Error",
			"insert_after": "efris_last_uploaded_on",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "efris_qr_code",
			"fieldtype": "Small Text",
			"label": "EFRIS QR Code",
			"insert_after": "efris_upload_error",
			"read_only": 1,
			"no_copy": 1,
		},
	]


SALES_INVOICE_CUSTOM_FIELDS = {
	"Sales Invoice": [
		{
			"fieldname": "efris_reason_code",
			"fieldtype": "Select",
			"label": "EFRIS Credit Note Reason",
			"insert_after": "is_return",
			"options": "\n101 - Return of products due to expiry or damage\n102 - Cancellation of the purchase\n103 - Invoice amount wrongly stated\n104 - Partial or complete waive off\n105 - Others (Please specify)",
			"default": "102 - Cancellation of the purchase",
			"depends_on": "eval:doc.is_return",
			"mandatory_depends_on": "eval:doc.is_return",
			"description": "Sent as T110 reasonCode when the credit note is uploaded to EFRIS.",
		},
		{
			"fieldname": "efris_reason",
			"fieldtype": "Small Text",
			"label": "EFRIS Credit Note Reason (Other)",
			"insert_after": "efris_reason_code",
			"depends_on": "eval:doc.is_return && (doc.efris_reason_code||'').indexOf('105')!==-1",
			"mandatory_depends_on": "eval:doc.is_return && (doc.efris_reason_code||'').indexOf('105')!==-1",
		},
		*_e_invoice_status_fields("remarks"),
		{
			"fieldname": "efris_upload_trigger_resolved",
			"fieldtype": "Data",
			"label": "EFRIS Upload Trigger (Resolved)",
			"insert_after": "efris_qr_code",
			"read_only": 1,
			"no_copy": 1,
			"hidden": 1,
			"description": "Computed on save: Manual / On Submit / On Payment. Used by the EFRIS button on Sales Invoice.",
		},
		{
			"fieldname": "efris_credit_note_status",
			"fieldtype": "Select",
			"label": "EFRIS Credit Note Status",
			"options": "\n101 - Approved\n102 - Pending\n103 - Rejected\n104 - Voided",
			"insert_after": "efris_upload_trigger_resolved",
			"read_only": 1,
			"no_copy": 1,
			"depends_on": "eval:doc.is_return",
			"description": "EFRIS approval status of the credit note application (T112).",
		},
		{
			"fieldname": "efris_credit_note_application_id",
			"fieldtype": "Data",
			"label": "EFRIS Credit Note Application ID",
			"insert_after": "efris_credit_note_status",
			"read_only": 1,
			"no_copy": 1,
			"depends_on": "eval:doc.is_return",
		},
	],
}


POS_INVOICE_CUSTOM_FIELDS = {
	"POS Invoice": _e_invoice_status_fields("remarks"),
}


PURCHASE_INVOICE_CUSTOM_FIELDS = {
	"Purchase Invoice": [
		{
			"fieldname": "supplier_invoice_fdn",
			"fieldtype": "Data",
			"label": "Supplier Invoice FDN",
			"insert_after": "bill_no",
			"length": 20,
			"description": "EFRIS FDN of the supplier's invoice. Sent as T131 invoiceNo when set; falls back to Bill No.",
		},
		*_stock_status_fields("remarks"),
	],
}


PAYMENT_ENTRY_CUSTOM_FIELDS = {
	"Payment Entry": [
		{
			"fieldname": "efris_section",
			"fieldtype": "Section Break",
			"label": "EFRIS",
			"insert_after": "remarks",
			"collapsible": 1,
		},
		{
			"fieldname": "efris_auto_upload_invoices",
			"fieldtype": "Check",
			"label": "Auto-upload Linked Sales Invoices to EFRIS",
			"insert_after": "efris_section",
			"default": "0",
			"description": (
				"When set, submitting this Payment Entry will upload any linked "
				"Sales Invoice whose EFRIS upload trigger is 'On Payment' and "
				"which is not yet uploaded. Default is sourced from EFRIS Settings."
			),
		},
		{
			"fieldname": "efris_upload_status_column",
			"fieldtype": "Column Break",
			"insert_after": "efris_auto_upload_invoices",
		},
		{
			"fieldname": "efris_last_uploaded_on",
			"fieldtype": "Datetime",
			"label": "EFRIS Last Upload Attempt",
			"insert_after": "efris_upload_status_column",
			"read_only": 1,
			"no_copy": 1,
		},
		{
			"fieldname": "efris_upload_error",
			"fieldtype": "Small Text",
			"label": "EFRIS Last Upload Error",
			"insert_after": "efris_last_uploaded_on",
			"read_only": 1,
			"no_copy": 1,
		},
	],
}


CUSTOMER_TYPE_OPTIONS = "\nIndividual\nCompany\nGovernment\nForeigner\nPartnership"


def _install_property_setters() -> None:
	"""Override core doctype field properties for EFRIS."""
	make_property_setter(
		"Customer",
		"customer_type",
		"options",
		CUSTOMER_TYPE_OPTIONS,
		"Select",
		validate_fields_for_doctype=False,
	)


def install_custom_fields() -> None:
	"""Idempotent — safe to call from after_install *and* after_migrate."""
	create_custom_fields(PARTY_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(UOM_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(CURRENCY_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(MODE_OF_PAYMENT_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(ITEM_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(STOCK_ENTRY_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(PURCHASE_RECEIPT_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(PURCHASE_INVOICE_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(BRANCH_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(WAREHOUSE_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(SALES_INVOICE_CUSTOM_FIELDS, ignore_validate=True)
	create_custom_fields(PAYMENT_ENTRY_CUSTOM_FIELDS, ignore_validate=True)
	_install_property_setters()
	try:
		import frappe as _frappe

		if _frappe.db.exists("DocType", "POS Invoice"):
			create_custom_fields(POS_INVOICE_CUSTOM_FIELDS, ignore_validate=True)
	except Exception:
		# POS Invoice ships with ERPNext POS; skip silently when absent.
		pass
