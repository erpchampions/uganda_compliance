// EFRIS Goods Inquiry — filters: Company (drives the TIN via EFRIS
// Settings) and a multi-select of EFRIS-uploaded Items.

frappe.query_reports["EFRIS Goods Inquiry"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "items",
			label: __("Items"),
			fieldtype: "MultiSelectList",
			reqd: 1,
			get_data(txt) {
				return frappe.db.get_link_options("Item", txt, {
					efris_uploaded: 1,
				});
			},
		},
	],
};
