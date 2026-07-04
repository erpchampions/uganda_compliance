// Auto-filter the EFRIS Dictionary picker on standard doctypes that we
// extend with an `efris_dictionary` Link field. Loaded globally via
// app_include_js so the filters apply wherever the form is opened.

frappe.ui.form.on("UOM", {
	setup(frm) {
		efris.dictionary.set_link_query(frm, "efris_dictionary", "rateUnit");
	},
});

frappe.ui.form.on("Currency", {
	setup(frm) {
		efris.dictionary.set_link_query(frm, "efris_dictionary", "currencyType");
	},
});

frappe.ui.form.on("Mode of Payment", {
	setup(frm) {
		efris.dictionary.set_link_query(frm, "efris_dictionary", "payWay");
	},
});
