frappe.setup.on("before_load", function () {
	if (frappe.boot.setup_wizard_completed_apps?.includes("erpnext")) return;

	frappe.setup.add_slide({
		name: "efris",
		title: __("EFRIS (Uganda)"),
		icon: "fa fa-file-text",
		fields: [
			{
				fieldname: "efris_setup",
				label: __("Set up EFRIS now"),
				fieldtype: "Check",
				default: 1,
				description: __("You can also do this later in E Invoicing Settings."),
			},
			{ fieldtype: "Section Break", depends_on: "eval:doc.efris_setup" },
			{ fieldname: "efris_tin", label: __("TIN"), fieldtype: "Data" },
			{
				fieldname: "efris_connection_mode",
				label: __("Connection"),
				fieldtype: "Select",
				options: ["Online (URA)", "Offline Enabler"],
				default: "Online (URA)",
			},
			{
				fieldname: "efris_device_no",
				label: __("Device No"),
				fieldtype: "Data",
				description: __("From the URA portal, or the enabler's TCS number."),
			},
			{
				fieldname: "efris_enabler_url",
				label: __("Enabler URL"),
				fieldtype: "Data",
				default: "http://127.0.0.1:9880/efristcs/ws/tcsapp/getInformation",
				depends_on: "eval:doc.efris_connection_mode=='Offline Enabler'",
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "efris_seller_email",
				label: __("Seller Email"),
				fieldtype: "Data",
				options: "Email",
				description: __("URA refuses invoices without it."),
			},
			{ fieldname: "efris_seller_phone", label: __("Seller Phone"), fieldtype: "Data" },
			{
				fieldname: "efris_sandbox",
				label: __("Use URA's test environment"),
				fieldtype: "Check",
				default: 1,
			},
		],
		before_show: function () {
			if (!this.form.get_value("efris_seller_email") && frappe.wizard.values.email) {
				this.form.set_value("efris_seller_email", frappe.wizard.values.email);
			}
		},
		// UX only: the server repeats these checks (efris/setup_wizard.py)
		validate: function () {
			const v = this.values;
			if (!v.efris_setup) return true;
			if (!/^\d{10}$/.test(v.efris_tin || "")) {
				frappe.msgprint(__("EFRIS TIN must be 10 digits"));
				return false;
			}
			if (!v.efris_seller_email) {
				frappe.msgprint(__("EFRIS needs the seller's email"));
				return false;
			}
			if (
				v.efris_connection_mode === "Offline Enabler" &&
				!(v.efris_device_no && v.efris_enabler_url)
			) {
				frappe.msgprint(__("Offline Enabler mode needs the Device No and the Enabler URL"));
				return false;
			}
			return true;
		},
	});
});
