// EFRIS Credit Note Applications — wraps T111. pageNo/pageSize/queryType are
// required; everything else is an optional URA-side filter.

frappe.query_reports["EFRIS Credit Note Applications"] = {
	filters: [
		{
			fieldname: "query_type",
			label: __("Query Type"),
			fieldtype: "Select",
			options: [
				"1 - My Applications",
				"2 - To Approve (To-Do)",
				"3 - Approved By Me",
			].join("\n"),
			default: "1 - My Applications",
			reqd: 1,
		},
		{
			fieldname: "approve_status",
			label: __("Approval Status"),
			fieldtype: "Select",
			options: [
				"",
				"101 - Approved",
				"102 - Submitted",
				"103 - Rejected",
				"104 - Voided",
			].join("\n"),
		},
		{
			fieldname: "invoice_apply_category_code",
			label: __("Category"),
			fieldtype: "Select",
			options: [
				"",
				"101 - Credit Note",
				"103 - Cancel of Debit Note",
			].join("\n"),
		},
		{
			fieldname: "credit_note_type",
			label: __("Credit Note Type"),
			fieldtype: "Select",
			options: [
				"1 - Credit Note",
				"2 - Credit Note Without FDN",
			].join("\n"),
			default: "1 - Credit Note",
		},
		{
			fieldname: "reference_no",
			label: __("Reference No"),
			fieldtype: "Data",
		},
		{
			fieldname: "ori_invoice_no",
			label: __("Original Invoice No"),
			fieldtype: "Data",
		},
		{
			fieldname: "invoice_no",
			label: __("Invoice No"),
			fieldtype: "Data",
		},
		{
			fieldname: "combine_keywords",
			label: __("Reference / Invoice (Combined Search)"),
			fieldtype: "Data",
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

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "status" && value) {
			const colors = {
				[__("Approved")]: "green",
				[__("Submitted")]: "orange",
				[__("Rejected")]: "red",
				[__("Voided")]: "grey",
			};
			const color = colors[value] || "grey";
			return `<span class="indicator-pill ${color}">${frappe.utils.escape_html(value)}</span>`;
		}
		return default_formatter(value, row, column, data);
	},
};
