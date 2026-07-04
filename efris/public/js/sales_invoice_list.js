frappe.listview_settings["Sales Invoice"] = frappe.listview_settings["Sales Invoice"] || {};
const _efris_si_list_onload = frappe.listview_settings["Sales Invoice"].onload;
frappe.listview_settings["Sales Invoice"].onload = function (listview) {
	if (_efris_si_list_onload) _efris_si_list_onload(listview);
	efris.batch_invoice.add_action(listview, "Sales Invoice");
};
