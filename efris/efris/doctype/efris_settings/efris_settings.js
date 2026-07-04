// Copyright (c) 2026, Ignite Digital and contributors
// For license information, please see license.txt

frappe.ui.form.on("EFRIS Settings", {
	setup(frm) {
		// Filter the Tax Type → Account picker to the parent settings' company.
		frm.set_query("account", "tax_types", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				account_type: "Tax",
				root_type: "Liability",
			},
		}));
		// Combined Invoice Item must already be uploaded to EFRIS — URA
		// rejects T109 lines with goodsCodes it doesn't know about.
		frm.set_query("combined_invoice_item", () => ({
			filters: { efris_uploaded: 1, disabled: 0 },
		}));
	},
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		// T101 (get server time) doubles as a connectivity / credentials check.
		frm.add_custom_button(
			__("Test Connection (T101)"),
			() => test_connection(frm),
			__("EFRIS"),
		);
		// T103 — login: fetch taxpayer / device / branch details.
		frm.add_custom_button(
			__("Fetch Taxpayer Details (T103)"),
			() => fetch_taxpayer_details(frm),
			__("EFRIS"),
		);
		// T115 — refresh local copy of EFRIS reference data.
		frm.add_custom_button(
			__("Sync Dictionary (T115)"),
			() => sync_dictionary(frm),
			__("EFRIS"),
		);
		// T125 — refresh local copy of the excise duty catalogue.
		frm.add_custom_button(
			__("Sync Excise Duty (T125)"),
			() => sync_excise_duty(frm),
			__("EFRIS"),
		);
		// T124 — refresh local copy of the commodity category catalogue.
		frm.add_custom_button(
			__("Sync Commodity Categories (T124)"),
			() => sync_commodity_categories(frm),
			__("EFRIS"),
		);
		// T136 — upload a public-key certificate (.crt / .cer).
		frm.add_custom_button(
			__("Upload Certificate (T136)"),
			() => upload_certificate(frm),
			__("EFRIS"),
		);
		// T138 — fetch all taxpayer branches.
		frm.add_custom_button(
			__("Fetch Branches (T138)"),
			() => fetch_branches(frm),
			__("EFRIS"),
		);
		// One-shot mapper: default Mode of Payment → EFRIS payWay dictionary.
		frm.add_custom_button(
			__("Map Modes of Payment"),
			() => map_modes_of_payment(frm),
			__("EFRIS"),
		);
	},

	company(frm) {
		if (!frm.doc.company) {
			return;
		}
		populate_company_details(frm);
	},
});

function sync_dictionary(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the form before syncing the dictionary."));
		return;
	}
	frappe.dom.freeze(__("Syncing EFRIS dictionary…"));
	frm
		.call("sync_dictionary")
		.always(() => frappe.dom.unfreeze());
}

function sync_commodity_categories(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the form before syncing commodity categories."));
		return;
	}
	frappe.dom.freeze(__("Syncing EFRIS commodity categories…"));
	frm
		.call("sync_commodity_categories")
		.always(() => frappe.dom.unfreeze());
}

function sync_excise_duty(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the form before syncing excise duty."));
		return;
	}
	frappe.dom.freeze(__("Syncing EFRIS excise duty…"));
	frm
		.call("sync_excise_duty")
		.always(() => frappe.dom.unfreeze());
}

function fetch_taxpayer_details(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the form before fetching taxpayer details."));
		return;
	}
	frappe.dom.freeze(__("Fetching taxpayer details from EFRIS…"));
	frm
		.call("fetch_taxpayer_details")
		.then((r) => {
			if (r && r.message) {
				frm.reload_doc();
			}
		})
		.always(() => frappe.dom.unfreeze());
}

function map_modes_of_payment(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the form before mapping Modes of Payment."));
		return;
	}
	frappe.dom.freeze(__("Mapping Modes of Payment to EFRIS payWay…"));
	frm
		.call("map_modes_of_payment")
		.always(() => frappe.dom.unfreeze());
}

function fetch_branches(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the form before fetching branches."));
		return;
	}
	frappe.dom.freeze(__("Fetching branches from EFRIS…"));
	frm
		.call("fetch_branches")
		.then(() => frm.reload_doc())
		.always(() => frappe.dom.unfreeze());
}

function upload_certificate(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the form before uploading a certificate."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Upload Certificate to EFRIS (T136)"),
		fields: [
			{
				fieldname: "certificate_file",
				fieldtype: "Attach",
				label: __("Certificate File"),
				reqd: 1,
				description: __("Must be a .crt or .cer file."),
				options: { restrictions: { allowed_file_types: [".crt", ".cer"] } },
			},
		],
		primary_action_label: __("Upload"),
		primary_action(values) {
			dialog.hide();
			frappe.dom.freeze(__("Uploading certificate to EFRIS…"));
			frm
				.call("upload_certificate", { file_url: values.certificate_file })
				.always(() => frappe.dom.unfreeze());
		},
	});
	dialog.show();
}

function test_connection(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Please save the form before testing the connection."));
		return;
	}
	frappe.dom.freeze(__("Contacting EFRIS…"));
	frm
		.call("test_connection")
		.then((r) => {
			if (r && r.message) {
				frappe.msgprint({
					title: __("EFRIS Server Time (T101)"),
					indicator: "green",
					message: `<pre>${frappe.utils.escape_html(
						JSON.stringify(r.message, null, 2),
					)}</pre>`,
				});
			}
		})
		.always(() => frappe.dom.unfreeze());
}

function populate_company_details(frm) {
	// Pull the seller/taxpayer details straight off the ERPNext Company record
	// so the user does not have to retype them.
	frappe.db
		.get_value("Company", frm.doc.company, [
			"tax_id",
			"company_name",
			"email",
			"phone_no",
			"default_currency",
		])
		.then((r) => {
			const company = r.message;
			if (!company) {
				return;
			}
			if (company.tax_id) {
				frm.set_value("tin", company.tax_id);
			}
			frm.set_value("company_legal_name", company.company_name);
			if (company.email) {
				frm.set_value("email_address", company.email);
			}
			if (company.phone_no) {
				frm.set_value("mobile_phone", company.phone_no);
				frm.set_value("line_phone", company.phone_no);
			}
		});

	// Company primary address (if one is set) → seller address.
	frappe.call({
		method: "frappe.contacts.doctype.address.address.get_default_address",
		args: { doctype: "Company", name: frm.doc.company },
		callback: (r) => {
			if (!r.message) {
				return;
			}
			frappe.db.get_value("Address", r.message, "city").then((res) => {
				const city = res.message ? res.message.city : "";
				frappe.call({
					method: "frappe.contacts.doctype.address.address.get_address_display",
					args: { address_dict: r.message },
					callback: (disp) => {
						if (disp.message) {
							frm.set_value(
								"company_address",
								$("<div>").html(disp.message).text().trim(),
							);
						}
						if (city && !frm.doc.place_of_business) {
							frm.set_value("place_of_business", city);
						}
					},
				});
			});
		},
	});
}
