// Copyright (c) 2021, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on('E Invoice', {
	refresh(frm) {
		// Allow sending a reviewed E-Invoice draft to EFRIS.
		if (!frm.is_new() && !frm.doc.irn && frm.doc.status === "EFRIS Pending") {
			frm.add_custom_button(__("Send to EFRIS"), function () {
				frappe.confirm(
					__("Send this E-Invoice to EFRIS and generate the IRN?"),
					async function () {
						try {
							const response = await frappe.call({
								method:
									"uganda_compliance.efris.api_classes.e_invoice.send_einvoice_to_efris",
								args: { e_invoice: frm.doc.name },
								freeze: true,
								freeze_message: __("Submitting to EFRIS..."),
							});

							if (response.message) {
								frappe.msgprint(
									__("E-Invoice sent to EFRIS successfully.")
								);
								frm.reload_doc();
							}
						} catch (error) {
							console.error("Error sending E-Invoice to EFRIS:", error);
							frappe.msgprint(
								__("An error occurred while sending to EFRIS.")
							);
						}
					}
				);
			});
		}
	},

	invoice(frm) {
		frm.call({
			'doc': frm.doc,
			'method': 'fetch_invoice_details'
		})
	}
});
