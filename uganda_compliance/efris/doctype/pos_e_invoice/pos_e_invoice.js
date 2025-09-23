// Copyright (c) 2021, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('POS E Invoice', {
	refresh(frm) {
	},

	invoice(frm) {
		frm.call({
			'doc': frm.doc,
			'method': 'fetch_invoice_details'
		})
	}
});
