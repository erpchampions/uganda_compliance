// Shared "Validate TIN with EFRIS" button for Customer and Supplier forms.
// Wired via doctype_js in hooks.py so it applies to both without duplicating
// the implementation.

(function () {
	function validate_efris_tin(frm) {
		if (!frm.doc.tax_id) {
			frappe.msgprint(__("Set Tax ID on this {0} before validating with EFRIS.", [frm.doctype]));
			return;
		}
		frappe.dom.freeze(__("Validating TIN with EFRIS…"));
		frappe
			.call({
				method: "efris.efris.api.taxpayer.validate_party_tin",
				args: { doctype: frm.doctype, name: frm.docname },
			})
			.always(() => {
				frappe.dom.unfreeze();
				frm.reload_doc();
			});
	}

	function add_button(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(
			__("Validate TIN (T119)"),
			() => validate_efris_tin(frm),
			__("EFRIS"),
		);
	}

	frappe.ui.form.on("Customer", { refresh: add_button });
	frappe.ui.form.on("Supplier", { refresh: add_button });
})();
