frappe.ui.form.on("Subscription", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(
			__("Batch Upload Invoices to EFRIS (T129)"),
			() => efris_batch_upload_subscription_invoices(frm),
			__("EFRIS"),
		);
	},
});

function efris_batch_upload_subscription_invoices(frm) {
	frappe.dom.freeze(__("Fetching submitted invoices for this subscription…"));
	frappe.db
		.get_list("Sales Invoice", {
			filters: { subscription: frm.docname, docstatus: 1 },
			fields: ["name"],
			limit: 0,
		})
		.then((rows) => {
			if (!rows || !rows.length) {
				frappe.msgprint({
					title: __("No Invoices"),
					indicator: "orange",
					message: __("No submitted Sales Invoices are linked to this subscription."),
				});
				return;
			}
			const names = rows.map((r) => r.name);
			return frappe
				.call({
					method: "efris.efris.api.batch_invoice.prepare_batch",
					args: { source_doctype: "Sales Invoice", names: JSON.stringify(names) },
				})
				.then((r) => {
					if (!r || !r.message) return;
					efris.batch_invoice.confirm("Sales Invoice", r.message);
				});
		})
		.always(() => frappe.dom.unfreeze());
}
