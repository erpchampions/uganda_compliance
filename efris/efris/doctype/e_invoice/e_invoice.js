// E-Invoice — manual T109 upload + QR code preview.

frappe.ui.form.on("E-Invoice", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.upload_status !== "Uploaded") {
			frm.add_custom_button(
				__("Upload to EFRIS (T109)"),
				() => upload_e_invoice(frm),
				__("EFRIS"),
			);
		}

		if (frm.doc.efris_qr_code) {
			frm.add_custom_button(
				__("Show QR Code"),
				() => show_qr(frm),
				__("EFRIS"),
			);
		}

		if (frm.doc.e_invoice_type === "Credit Note" && frm.doc.original_e_invoice) {
			frm.add_custom_button(
				__("Open Original E-Invoice"),
				() =>
					frappe.set_route("Form", "E-Invoice", frm.doc.original_e_invoice),
				__("EFRIS"),
			);
		}
	},
});

function upload_e_invoice(frm) {
	frappe.dom.freeze(__("Uploading invoice to EFRIS…"));
	frm
		.call("upload")
		.then(() => frm.reload_doc())
		.always(() => frappe.dom.unfreeze());
}

function show_qr(frm) {
	const payload = frm.doc.efris_qr_code || "";
	const src = `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(payload)}`;
	frappe.msgprint({
		title: __("EFRIS QR Code"),
		indicator: "green",
		message: `<div style="text-align:center"><img src="${src}" alt="QR"/><br/><pre style="white-space:pre-wrap">${frappe.utils.escape_html(payload)}</pre></div>`,
	});
}
