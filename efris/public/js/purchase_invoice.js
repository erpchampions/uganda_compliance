frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		efris.exchange_rate.add_button(frm, { date_field: "bill_date" });
		if (frm.doc.docstatus !== 1 || !frm.doc.update_stock) return;
		frm.add_custom_button(
			__("Upload Stock to EFRIS (T131)"),
			() =>
				efris_upload(frm, "efris.efris.api.stock.upload_purchase_invoice"),
			__("EFRIS"),
		);
	},
});

function efris_upload(frm, method) {
	frappe.dom.freeze(__("Uploading to EFRIS…"));
	frappe
		.call({ method, args: { name: frm.docname } })
		.always(() => {
			frappe.dom.unfreeze();
			frm.reload_doc();
		});
}
