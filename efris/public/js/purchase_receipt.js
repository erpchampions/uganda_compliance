frappe.ui.form.on("Purchase Receipt", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(
			__("Upload Stock to EFRIS (T131)"),
			() => {
				frappe.dom.freeze(__("Uploading to EFRIS…"));
				frappe
					.call({
						method: "efris.efris.api.stock.upload_purchase_receipt",
						args: { name: frm.docname },
					})
					.always(() => {
						frappe.dom.unfreeze();
						frm.reload_doc();
					});
			},
			__("EFRIS"),
		);
	},
});
