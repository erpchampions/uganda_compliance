// EFRIS Goods Stock Records — filters wrap T145 (page + at least one
// identifier required). URA expects productionBatchNo / invoiceNo /
// referenceNo to be passed through verbatim.

frappe.query_reports["EFRIS Goods Stock Records"] = {
	filters: [
		{
			fieldname: "production_batch_no",
			label: __("Production Batch No"),
			fieldtype: "Data",
		},
		{
			fieldname: "invoice_no",
			label: __("Invoice No"),
			fieldtype: "Data",
		},
		{
			fieldname: "reference_no",
			label: __("Reference No"),
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
