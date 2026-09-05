frappe.listview_settings["EFRIS Commodity Code"] = {
	onload: function (listview) {
		listview.page.add_inner_button(__("Fetch from URA"), function () {
			frappe.confirm(
				__("Pull URA's commodity categories (T124) with their tax rates? Manual tax-category mappings are kept. This runs in the background."),
				function () {
					frappe.call({
						method: "uganda_compliance.efris.doctype.efris_commodity_code.efris_commodity_code.fetch_from_ura",
						callback: function (r) {
							if (r.message && r.message.queued) {
								frappe.msgprint(__("Sync queued for {0}. Refresh the list in a few minutes.", [r.message.company]));
							} else if (r.message) {
								frappe.msgprint(__("Synced: {0}", [JSON.stringify(r.message)]));
								listview.refresh();
							}
						},
					});
				}
			);
		});
	},
};
