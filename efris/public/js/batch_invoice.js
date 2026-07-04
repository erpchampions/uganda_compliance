frappe.provide("efris.batch_invoice");

efris.batch_invoice.add_action = function (listview, source_doctype) {
	listview.page.add_actions_menu_item(
		__("Batch Upload to EFRIS (T129)"),
		() => efris.batch_invoice.start(listview, source_doctype),
		true,
	);
};

efris.batch_invoice.start = function (listview, source_doctype) {
	const selected = (listview.get_checked_items() || []).map((d) => d.name);
	if (!selected.length) {
		frappe.show_alert({ message: __("Select one or more invoices first."), indicator: "orange" });
		return;
	}
	frappe.dom.freeze(__("Preparing batch…"));
	frappe
		.call({
			method: "efris.efris.api.batch_invoice.prepare_batch",
			args: { source_doctype, names: JSON.stringify(selected) },
		})
		.then((r) => {
			if (!r || !r.message) return;
			efris.batch_invoice.confirm(source_doctype, r.message);
		})
		.always(() => frappe.dom.unfreeze());
};

efris.batch_invoice.confirm = function (source_doctype, result) {
	const eligible = result.eligible || [];
	const skipped = result.skipped || [];
	const esc = frappe.utils.escape_html;

	const skipped_table = skipped.length
		? `<p style="margin-top:10px"><strong>${__("Skipped")} (${skipped.length})</strong></p>
			<table class="table table-bordered table-sm"><thead><tr>
				<th>${__("Invoice")}</th><th>${__("Reason")}</th></tr></thead>
			<tbody>${skipped
				.map((s) => `<tr><td>${esc(s.name)}</td><td>${esc(s.reason)}</td></tr>`)
				.join("")}</tbody></table>`
		: "";

	if (!eligible.length) {
		frappe.msgprint({
			title: __("Nothing to Upload"),
			indicator: "orange",
			message: `<p>${__("None of the selected invoices are eligible for T129 batch upload.")}</p>${skipped_table}`,
		});
		return;
	}

	const eligible_html = eligible.map((e) => `<li>${esc(e.name)}</li>`).join("");
	const html = `
		<p><strong>${__("Eligible for upload")} (${eligible.length})</strong></p>
		<ul style="max-height:240px;overflow:auto">${eligible_html}</ul>
		${skipped_table}
		<p style="margin-top:12px">${__("This will report the invoices to URA via T129 and cannot be undone. Continue?")}</p>
	`;

	const dlg = new frappe.ui.Dialog({
		title: __("Confirm EFRIS Batch Upload (T129)"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
		primary_action_label: __("Upload {0} Invoice(s)", [eligible.length]),
		primary_action() {
			dlg.hide();
			efris.batch_invoice.send(
				source_doctype,
				eligible.map((e) => e.name),
			);
		},
	});
	dlg.fields_dict.body.$wrapper.html(html);
	dlg.show();
};

efris.batch_invoice.send = function (source_doctype, names) {
	frappe.dom.freeze(__("Uploading batch to EFRIS…"));
	frappe
		.call({
			method: "efris.efris.api.batch_invoice.upload_batch",
			args: { source_doctype, names: JSON.stringify(names) },
		})
		.then((r) => {
			if (!r || !r.message) return;
			const res = r.message;
			const indicator =
				res.status === "Success"
					? "green"
					: res.status === "Partial"
						? "orange"
						: "red";
			frappe.show_alert(
				{
					message: __("EFRIS batch {0}: {1} ok, {2} failed, {3} skipped.", [
						res.status,
						res.success,
						res.failed,
						res.skipped,
					]),
					indicator,
				},
				8,
			);
			frappe.set_route("Form", "EFRIS Batch Invoice Upload", res.batch);
		})
		.always(() => frappe.dom.unfreeze());
};
