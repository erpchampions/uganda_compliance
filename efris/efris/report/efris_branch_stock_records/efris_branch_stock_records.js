// EFRIS Branch Stock Records — wraps T147. Page/size required; the rest
// are optional URA-side filters scoped to the current branch.

frappe.query_reports["EFRIS Branch Stock Records"] = {
	filters: [
		{
			fieldname: "combine_keywords",
			label: __("Reference No / Supplier Name (Combined Search)"),
			fieldtype: "Data",
		},
		{
			fieldname: "stock_in_type",
			label: __("Stock-In Type"),
			fieldtype: "Select",
			options: [
				"",
				"101 - Import",
				"102 - Local Purchase",
				"103 - Manufacture",
				"104 - Opening Stock",
			].join("\n"),
		},
		{
			fieldname: "start_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "end_date",
			label: __("To Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "supplier_tin",
			label: __("Supplier TIN"),
			fieldtype: "Data",
		},
		{
			fieldname: "supplier_name",
			label: __("Supplier Name"),
			fieldtype: "Data",
		},
		{
			fieldname: "page_no",
			label: __("Page No"),
			fieldtype: "Int",
			default: 1,
			reqd: 1,
		},
		{
			fieldname: "page_size",
			label: __("Page Size"),
			fieldtype: "Int",
			default: 10,
			reqd: 1,
			description: __("Max 100"),
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
	],
};
