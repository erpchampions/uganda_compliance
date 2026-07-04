frappe.ui.form.on("Payment Entry", {
	onload(frm) {
		apply_efris_default(frm);
	},

	company(frm) {
		apply_efris_default(frm);
	},

	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 1) return;
		if ((frm.doc.payment_type || "") !== "Receive") return;

		const has_si_refs = (frm.doc.references || []).some(
			(r) => r.reference_doctype === "Sales Invoice",
		);
		if (!has_si_refs) return;

		frm.add_custom_button(
			__("Upload Linked Invoices to EFRIS"),
			() => upload_linked_invoices(frm),
			__("EFRIS"),
		);

		if (frm.doc.efris_upload_error) {
			frm.dashboard.set_headline_alert(
				__("EFRIS: last upload attempt had errors. See 'EFRIS Last Upload Error' field."),
				"orange",
			);
		}
	},
});

function apply_efris_default(frm) {
	if (!frm.is_new()) return;
	if (!frm.doc.company) return;
	if (frm.doc.efris_auto_upload_invoices) return;

	frappe.db
		.get_value("EFRIS Settings", frm.doc.company, "efris_default_payment_auto_upload")
		.then((r) => {
			const v = r && r.message && r.message.efris_default_payment_auto_upload;
			if (v && !frm.doc.efris_auto_upload_invoices) {
				frm.set_value("efris_auto_upload_invoices", 1);
			}
		})
		.catch(() => {});
}

function upload_linked_invoices(frm) {
	frappe.dom.freeze(__("Uploading linked invoices to EFRIS…"));
	frappe
		.call({
			method: "efris.efris.api.payment.upload_invoices_for_payment",
			args: { payment_entry: frm.docname },
		})
		.then((r) => {
			if (!r || !r.message) return;
			const res = r.message;
			const parts = [];
			if (res.uploaded && res.uploaded.length) {
				parts.push(__("Uploaded: {0}", [res.uploaded.join(", ")]));
			}
			if (res.skipped && res.skipped.length) {
				parts.push(__("Skipped: {0}", [res.skipped.join(", ")]));
			}
			if (res.errors && res.errors.length) {
				parts.push(__("Errors: {0}", [res.errors.join("; ")]));
			}
			frappe.show_alert(
				{
					message: parts.join(" | ") || __("Nothing to upload."),
					indicator: res.errors && res.errors.length ? "orange" : "green",
				},
				8,
			);
		})
		.always(() => {
			frappe.dom.unfreeze();
			frm.reload_doc();
		});
}
