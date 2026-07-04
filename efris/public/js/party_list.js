// "Create by TIN (EFRIS)" action on Customer and Supplier list views.
//
// Wired via doctype_list_js in hooks.py for both doctypes. The shared
// implementation prompts for a TIN, calls T119, creates the party, then
// routes to its form.

(function () {
	function prompt_and_create(listview) {
		const doctype = listview.doctype;
		frappe.prompt(
			[
				{
					fieldname: "tin",
					label: __("TIN"),
					fieldtype: "Data",
					reqd: 1,
					description: __("EFRIS will look up the taxpayer and pre-fill the new {0}.", [doctype]),
				},
			],
			(values) => {
				frappe.dom.freeze(__("Fetching from EFRIS…"));
				frappe
					.call({
						method: "efris.efris.api.taxpayer.create_party_from_tin",
						args: { doctype, tin: (values.tin || "").trim() },
					})
					.then((r) => {
						if (r && r.message) {
							frappe.set_route("Form", doctype, r.message);
						}
					})
					.always(() => frappe.dom.unfreeze());
			},
			__("Create {0} from TIN", [doctype]),
			__("Create"),
		);
	}

	function add_button(listview) {
		listview.page.add_inner_button(
			__("Create by TIN (EFRIS)"),
			() => prompt_and_create(listview),
		);
	}

	// Register on both doctypes; only the currently-loaded list view's
	// onload actually fires.
	for (const doctype of ["Customer", "Supplier"]) {
		frappe.listview_settings[doctype] = frappe.listview_settings[doctype] || {};
		const existing = frappe.listview_settings[doctype].onload;
		frappe.listview_settings[doctype].onload = function (listview) {
			if (existing) existing(listview);
			add_button(listview);
		};
	}
})();
