frappe.listview_settings["POS Invoice"] = frappe.listview_settings["POS Invoice"] || {};
const _pos_onload = frappe.listview_settings["POS Invoice"].onload;
frappe.listview_settings["POS Invoice"].onload = function (listview) {
	if (_pos_onload) _pos_onload(listview);
	efris.batch_invoice.add_action(listview, "POS Invoice");
};
