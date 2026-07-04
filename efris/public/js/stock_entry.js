// Defaults the EFRIS Stock-In Type from the Stock Entry purpose so users
// don't have to set it manually for the common cases.
const EFRIS_STOCK_IN_TYPE_BY_PURPOSE = {
	"Material Receipt": "104 - Opening Stock",
	"Manufacture": "103 - Manufacture",
	"Repack": "103 - Manufacture",
};

frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		default_stock_in_type(frm);

		if (frm.doc.docstatus !== 1) return;
		frm.add_custom_button(
			__("Upload Stock to EFRIS (T131)"),
			() => {
				frappe.dom.freeze(__("Uploading to EFRIS…"));
				frappe
					.call({
						method: "efris.efris.api.stock.upload_stock_entry",
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

	stock_entry_type(frm) {
		default_stock_in_type(frm);
	},
});

function default_stock_in_type(frm) {
	const purpose = frm.doc.stock_entry_type;
	const suggested = EFRIS_STOCK_IN_TYPE_BY_PURPOSE[purpose];
	if (suggested && !frm.doc.efris_stock_in_type) {
		frm.set_value("efris_stock_in_type", suggested);
	}
}
