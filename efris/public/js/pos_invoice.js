frappe.ui.form.on("POS Invoice", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) return;

		if (!frm.doc.efris_uploaded) {
			frm.add_custom_button(
				__("Upload to EFRIS (T109)"),
				() => {
					frappe.dom.freeze(__("Uploading invoice to EFRIS…"));
					frappe
						.call({
							method: "efris.efris.api.invoice.upload_source",
							args: { source_doctype: frm.doctype, source_name: frm.docname },
						})
						.always(() => {
							frappe.dom.unfreeze();
							frm.reload_doc();
						});
				},
				__("EFRIS"),
			);
		}

		if (frm.doc.efris_e_invoice) {
			frm.add_custom_button(
				__("Open E-Invoice"),
				() => frappe.set_route("Form", "E-Invoice", frm.doc.efris_e_invoice),
				__("EFRIS"),
			);
		}
	},
});
