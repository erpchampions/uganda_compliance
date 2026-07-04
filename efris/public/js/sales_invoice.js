frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		efris.exchange_rate.add_button(frm);
		efris_invoice_buttons(frm);
	},
});

function efris_invoice_buttons(frm) {
	if (frm.is_new() || frm.doc.docstatus !== 1) return;

	if (!frm.doc.efris_uploaded) {
		const trigger = frm.doc.efris_upload_trigger_resolved || "Manual";
		const has_error = !!frm.doc.efris_upload_error;
		const is_credit_note = !!frm.doc.is_return;

		// On Submit: button only as a retry affordance after a failure.
		// Manual / On Payment: button always available.
		const show_button = trigger !== "On Submit" || has_error;

		if (show_button) {
			let label;
			if (is_credit_note) {
				label = has_error
					? __("Retry Credit Note Upload to EFRIS (T110)")
					: __("Upload Credit Note to EFRIS (T110)");
			} else {
				label = has_error
					? __("Retry Upload to EFRIS (T109)")
					: __("Upload to EFRIS (T109)");
			}
			frm.add_custom_button(
				label,
				() => confirm_upload_invoice_to_efris(frm, is_credit_note),
				__("EFRIS"),
			);
		}

		if (trigger === "On Payment" && !has_error) {
			frm.dashboard.add_comment(
				__("EFRIS upload will run automatically when a Payment Entry is submitted against this invoice."),
				"blue",
				true,
			);
		}
	}

	// Already uploaded: allow issuing an *additional* EFRIS invoice for this SI
	// (gated by a warn/summary precheck). Not applicable to credit notes.
	if (frm.doc.efris_uploaded && !frm.doc.is_return) {
		frm.add_custom_button(
			__("Upload Additional Invoice to EFRIS"),
			() => additional_invoice_to_efris(frm),
			__("EFRIS"),
		);
	}

	if (frm.doc.efris_e_invoice) {
		frm.add_custom_button(
			__("Open E-Invoice"),
			() => frappe.set_route("Form", "E-Invoice", frm.doc.efris_e_invoice),
			__("EFRIS"),
		);
		frm.add_custom_button(
			__("View All E-Invoices"),
			() =>
				frappe.set_route("List", "E-Invoice", {
					source_doctype: frm.doctype,
					source_name: frm.docname,
				}),
			__("EFRIS"),
		);
	}

	if (frm.doc.efris_qr_code) {
		frm.add_custom_button(
			__("Show EFRIS QR"),
			() => show_efris_qr(frm.doc.efris_qr_code),
			__("EFRIS"),
		);
	}

	if (frm.doc.is_return && frm.doc.efris_uploaded && frm.doc.efris_e_invoice) {
		frm.add_custom_button(
			__("Check Credit Note Status (T112)"),
			() => check_credit_note_status(frm),
			__("EFRIS"),
		);
		frm.add_custom_button(
			__("View Application Details (T118)"),
			() => view_credit_note_application(frm),
			__("EFRIS"),
		);
		frm.add_custom_button(
			__("Cancel Application (T114)"),
			() => cancel_credit_note_dialog(frm),
			__("EFRIS"),
		);
		frm.add_custom_button(
			__("Void Application (T120)"),
			() => void_credit_note_action(frm),
			__("EFRIS"),
		);
		// Sandbox-only: seller self-approval (T113). URA blocks it on Production.
		frappe
			.call({
				method: "efris.efris.api.credit_note_status.get_sandbox_environment",
				args: { company: frm.doc.company },
			})
			.then((r) => {
				if (r && r.message && r.message.is_sandbox) {
					frm.add_custom_button(
						__("Approve/Reject (T113 — Sandbox)"),
						() => approve_credit_note_dialog(frm),
						__("EFRIS"),
					);
				}
			});
	}
}

function check_credit_note_status(frm) {
	frappe.dom.freeze(__("Querying EFRIS credit note status…"));
	frappe
		.call({
			method: "efris.efris.api.credit_note_status.check_credit_note_status",
			args: { sales_invoice: frm.docname },
		})
		.then((r) => {
			if (!r || !r.message) return;
			const res = r.message;
			show_credit_note_status(res);
			if (res.status_changed) {
				frappe.show_alert(
					{
						message: __("EFRIS status updated to {0}.", [res.status_label]),
						indicator: "green",
					},
					6,
				);
				frm.reload_doc();
			}
		})
		.always(() => frappe.dom.unfreeze());
}

function show_credit_note_status(res) {
	const d = res.details || {};
	const esc = frappe.utils.escape_html;
	const row = (label, value) =>
		value !== undefined && value !== null && value !== ""
			? `<tr><th style="text-align:left;padding:4px 8px;white-space:nowrap">${esc(label)}</th><td style="padding:4px 8px">${esc(String(value))}</td></tr>`
			: "";

	const changed_banner = res.status_changed
		? `<div class="alert alert-success" style="margin-bottom:10px">${__(
				"Status changed: {0} → {1}",
				[res.previous_status || __("(unknown)"), res.status_label],
			)}</div>`
		: `<div class="alert alert-info" style="margin-bottom:10px">${__(
				"Status unchanged: {0}",
				[res.status_label || __("(unknown)")],
			)}</div>`;

	const html = `
		${changed_banner}
		<table class="table table-bordered">
			${row(__("Application ID"), res.application_id)}
			${row(__("Status"), res.status_label || d.approveStatusCode)}
			${row(__("Application Time"), d.applicationTime)}
			${row(__("Updated Time"), d.updateTime)}
			${row(__("Original Invoice No"), d.oriInvoiceNo)}
			${row(__("Credit Invoice No"), d.refundInvoiceNo)}
			${row(__("Reference No"), d.referenceNo)}
			${row(__("Reason"), d.reason)}
			${row(__("Approve Remarks"), d.approveRemarks)}
			${row(__("Gross Amount"), d.grossAmount)}
			${row(__("Credit Total"), d.totalAmount)}
			${row(__("Currency"), d.currency)}
			${row(__("Issued Date"), d.issuedDate)}
			${row(__("Credit Issued Date"), d.refundIssuedDate)}
			${row(__("Buyer"), d.buyerLegalName || d.buyerBusinessName)}
			${row(__("Buyer TIN"), d.buyerTin)}
		</table>
	`;
	frappe.msgprint({
		title: __("EFRIS Credit Note Status"),
		indicator: res.status_changed ? "green" : "blue",
		message: html,
	});
}

function confirm_upload_invoice_to_efris(frm, is_credit_note) {
	const message = is_credit_note
		? __(
				"Upload credit note {0} to EFRIS (T110)? This is reported to URA and cannot be undone.",
				[frm.docname],
			)
		: __(
				"Upload invoice {0} to EFRIS (T109)? This is reported to URA and cannot be undone.",
				[frm.docname],
			);
	frappe.confirm(message, () => upload_invoice_to_efris(frm));
}

function upload_invoice_to_efris(frm, confirm_combined = false, force_new = false) {
	frappe.dom.freeze(__("Uploading invoice to EFRIS…"));
	frappe
		.call({
			method: "efris.efris.api.invoice.upload_source",
			args: {
				source_doctype: frm.doctype,
				source_name: frm.docname,
				confirm_combined: confirm_combined ? 1 : 0,
				force_new: force_new ? 1 : 0,
			},
		})
		.then((r) => {
			const res = r && r.message;
			if (res && res.needs_confirm) {
				// Re-prompt for the combined-item fallback and recurse on confirm.
				frappe.confirm(res.message, () =>
					upload_invoice_to_efris(frm, true, force_new),
				);
				return;
			}
			frm.reload_doc();
		})
		.always(() => frappe.dom.unfreeze());
}

// Issuing a 2nd+ EFRIS invoice for one Sales Invoice: precheck prior invoices,
// warn on credit (double-report risk) or show summary + payments, then confirm.
function additional_invoice_to_efris(frm) {
	frappe.dom.freeze(__("Checking existing EFRIS invoices…"));
	frappe
		.call({
			method: "efris.efris.api.invoice.precheck_additional_invoice",
			args: { source_doctype: frm.doctype, source_name: frm.docname },
		})
		.then((r) => {
			const res = (r && r.message) || {};
			if (!res.exists) {
				// No prior uploaded invoice (link cleared?) — upload directly.
				upload_invoice_to_efris(frm, false, true);
				return;
			}
			show_additional_invoice_dialog(frm, res);
		})
		.always(() => frappe.dom.unfreeze());
}

function show_additional_invoice_dialog(frm, res) {
	const esc = frappe.utils.escape_html;
	const num = (v) => esc(format_number(Number(v || 0), null, 2));
	const t = res.totals || {};

	const inv_rows = (res.existing || [])
		.map((e) => {
			const modes =
				(e.pay_ways || [])
					.map((p) => `${esc(p.mode)}: ${num(p.amount)}`)
					.join("<br>") || `<span class="text-muted">${__("—")}</span>`;
			return `<tr>
				<td>${esc(e.efris_invoice_id || e.name)}</td>
				<td class="text-center">${e.invoice_kind === "2" ? __("Receipt") : __("Invoice")}</td>
				<td class="text-right">${num(e.gross_amount)}</td>
				<td>${modes}</td>
			</tr>`;
		})
		.join("");

	const summary_html = `
		<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${__("EFRIS Invoice (FDN)")}</th>
				<th class="text-center">${__("Kind")}</th>
				<th class="text-right">${__("Gross")}</th>
				<th>${__("Pay Way")}</th>
			</tr></thead>
			<tbody>${inv_rows}</tbody>
			<tfoot>
				<tr>
					<th>${__("EFRIS Total")} (${esc(String(t.invoice_count || 0))})</th>
					<th></th>
					<th class="text-right">${num(t.efris_gross_total)}</th>
					<th>${__("Payments")}: ${num(t.payment_total)}</th>
				</tr>
				<tr>
					<th colspan="2">${__("Sales Invoice Total")}</th>
					<th class="text-right">${num(t.si_grand_total)}</th>
					<th>${__("Outstanding")}: ${num(t.si_outstanding)}</th>
				</tr>
			</tfoot>
		</table>`;

	const banner = res.has_credit
		? `<div class="alert alert-warning">${__(
				"An existing EFRIS invoice for {0} was issued on <b>Credit</b>. Issuing another invoice reports an additional sale to URA and may double-count this transaction. Proceed only if this is genuinely a separate invoice.",
				[frm.docname],
			)}</div>`
		: `<div class="alert alert-info">${__(
				"This Sales Invoice already has {0} EFRIS invoice(s). Review the summary and payments below before issuing another.",
				[esc(String(t.invoice_count || 0))],
			)}</div>`;

	const dlg = new frappe.ui.Dialog({
		title: __("Issue Additional EFRIS Invoice?"),
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
		primary_action_label: res.has_credit
			? __("Proceed Anyway")
			: __("Issue Another Invoice"),
		primary_action() {
			dlg.hide();
			upload_invoice_to_efris(frm, false, true);
		},
	});
	dlg.fields_dict.body.$wrapper.html(banner + summary_html);
	dlg.show();
}

function void_credit_note_action(frm) {
	frappe.confirm(
		__(
			"Void the EFRIS credit note application for {0}? URA will mark the application as Voided.",
			[frm.docname],
		),
		() => {
			frappe.dom.freeze(__("Voiding credit note application…"));
			frappe
				.call({
					method: "efris.efris.api.credit_note_status.void_credit_note",
					args: { sales_invoice: frm.docname },
				})
				.then((r) => {
					if (r && r.message) {
						frappe.show_alert(
							{
								message: __("EFRIS marked the application as {0}.", [
									r.message.status_label,
								]),
								indicator: "orange",
							},
							6,
						);
						frm.reload_doc();
					}
				})
				.always(() => frappe.dom.unfreeze());
		},
	);
}

function cancel_credit_note_dialog(frm) {
	const dlg = new frappe.ui.Dialog({
		title: __("Cancel Credit Note Application (T114)"),
		fields: [
			{
				fieldtype: "Select",
				fieldname: "reason_code",
				label: __("Reason Code"),
				options: [
					"101 - Buyer refused due to incorrect invoice/receipt",
					"102 - Not delivered due to incorrect invoice/receipt",
					"103 - Other reasons",
				].join("\n"),
				default: "103 - Other reasons",
				reqd: 1,
			},
			{
				fieldtype: "Small Text",
				fieldname: "reason",
				label: __("Reason"),
				mandatory_depends_on: "eval:(doc.reason_code||'').indexOf('103')!==-1",
				description: __("Required when Reason Code = 103 (Other reasons)."),
			},
			{
				fieldtype: "Select",
				fieldname: "invoice_apply_category_code",
				label: __("Cancel Category"),
				options: [
					"104 - Cancel of Credit Note",
					"103 - Cancel of Debit Note",
					"105 - Cancel of Credit Memo",
				].join("\n"),
				default: "104 - Cancel of Credit Note",
				reqd: 1,
			},
		],
		primary_action_label: __("Cancel Application"),
		primary_action(values) {
			const reason_code = (values.reason_code || "").split(" ")[0];
			const category = (values.invoice_apply_category_code || "").split(" ")[0];
			frappe.confirm(
				__(
					"Cancel the EFRIS credit note application for {0}? This is reported to URA and cannot be undone.",
					[frm.docname],
				),
				() => {
					dlg.hide();
					frappe.dom.freeze(__("Cancelling credit note application…"));
					frappe
						.call({
							method: "efris.efris.api.credit_note_status.cancel_credit_note",
							args: {
								sales_invoice: frm.docname,
								reason_code,
								reason: values.reason || "",
								invoice_apply_category_code: category,
							},
						})
						.then((r) => {
							if (r && r.message) {
								frappe.show_alert(
									{
										message: __("EFRIS cancellation submitted ({0}).", [
											r.message.status_label,
										]),
										indicator: "orange",
									},
									6,
								);
								frm.reload_doc();
							}
						})
						.always(() => frappe.dom.unfreeze());
				},
			);
		},
	});
	dlg.show();
}

function approve_credit_note_dialog(frm) {
	const dlg = new frappe.ui.Dialog({
		title: __("Approve / Reject Credit Note Application (T113)"),
		fields: [
			{
				fieldtype: "Select",
				fieldname: "approve_status",
				label: __("Decision"),
				options: "101 - Approved\n103 - Rejected",
				default: "101 - Approved",
				reqd: 1,
			},
			{
				fieldtype: "Small Text",
				fieldname: "remark",
				label: __("Remark"),
				reqd: 1,
				description: __("URA requires a remark on both approval and rejection."),
			},
		],
		primary_action_label: __("Submit"),
		primary_action(values) {
			const code = (values.approve_status || "").split(" ")[0];
			dlg.hide();
			frappe.dom.freeze(__("Submitting approval to EFRIS…"));
			frappe
				.call({
					method: "efris.efris.api.credit_note_status.approve_credit_note_application",
					args: {
						sales_invoice: frm.docname,
						approve_status: code,
						remark: values.remark,
					},
				})
				.then((r) => {
					if (r && r.message) {
						frappe.show_alert(
							{
								message: __("EFRIS recorded {0}.", [r.message.status_label]),
								indicator: code === "101" ? "green" : "orange",
							},
							6,
						);
						frm.reload_doc();
					}
				})
				.always(() => frappe.dom.unfreeze());
		},
	});
	dlg.show();
}

function view_credit_note_application(frm) {
	frappe.dom.freeze(__("Fetching credit note application details…"));
	frappe
		.call({
			method: "efris.efris.api.credit_note_status.get_credit_note_application",
			args: { sales_invoice: frm.docname },
		})
		.then((r) => {
			if (!r || !r.message) return;
			show_credit_note_application_dialog(r.message);
		})
		.always(() => frappe.dom.unfreeze());
}

const PAYMENT_MODES = {
	101: "Credit", 102: "Cash", 103: "Cheque", 104: "Demand Draft",
	105: "Mobile Money", 106: "Visa/Master", 107: "EFT", 108: "POS",
	109: "RTGS", 110: "Swift",
};

const TAX_CATEGORY = {
	"01": "A: Standard (18%)", "02": "B: Zero (0%)", "03": "C: Exempt",
	"04": "D: Deemed (18%)", "05": "E: Excise", "06": "OTT",
	"07": "Stamp Duty", "08": "Local Hotel", "09": "UCC Levy", 10: "Others",
};

function show_credit_note_application_dialog(res) {
	const esc = frappe.utils.escape_html;
	const fmt = (v) => (v === undefined || v === null || v === "" ? "" : esc(String(v)));
	const num = (v) =>
		v === undefined || v === null || v === ""
			? ""
			: esc(format_number(Number(v), null, 2));

	const d = res.details || {};
	const goods = d.goodsDetails || [];
	const taxes = d.taxDetails || [];
	const payways = d.payWay || [];
	const summary = d.summary || {};
	const basic = d.basicInformation || {};

	const goods_rows = goods
		.map(
			(g) => `<tr>
				<td>${fmt(g.orderNumber)}</td>
				<td>${fmt(g.itemName || g.item)}</td>
				<td>${fmt(g.itemCode)}</td>
				<td class="text-right">${num(g.qty)}</td>
				<td>${fmt(g.unit || g.unitOfMeasure)}</td>
				<td class="text-right">${num(g.unitPrice)}</td>
				<td class="text-right">${num(g.total)}</td>
				<td class="text-right">${fmt(g.taxRate)}</td>
				<td class="text-right">${num(g.tax)}</td>
				<td class="text-right">${num(g.discountTotal)}</td>
				<td>${fmt(g.goodsCategoryName || g.goodsCategoryId)}</td>
			</tr>`,
		)
		.join("");

	const tax_rows = taxes
		.map(
			(t) => `<tr>
				<td>${fmt(TAX_CATEGORY[t.taxCategoryCode] || t.taxCategoryCode)}</td>
				<td class="text-right">${fmt(t.taxRate)}</td>
				<td class="text-right">${num(t.netAmount)}</td>
				<td class="text-right">${num(t.taxAmount)}</td>
				<td class="text-right">${num(t.grossAmount || t["grossAmount "])}</td>
			</tr>`,
		)
		.join("");

	const pay_rows = payways
		.map(
			(p) => `<tr>
				<td>${fmt(PAYMENT_MODES[p.paymentMode] || p.paymentMode)}</td>
				<td class="text-right">${num(p.paymentAmount)}</td>
				<td>${fmt(p.orderNumber)}</td>
			</tr>`,
		)
		.join("");

	const html = `
		<div style="margin-bottom:12px">
			<strong>${__("Application ID")}:</strong> ${fmt(res.application_id)}
			&nbsp;|&nbsp; <strong>${__("Invoice Kind")}:</strong> ${fmt(basic.invoiceKind)}
			&nbsp;|&nbsp; <strong>${__("Invoice Type")}:</strong> ${fmt(basic.invoiceType)}
			&nbsp;|&nbsp; <strong>${__("Industry")}:</strong> ${fmt(basic.invoiceIndustryCode)}
		</div>

		<h5>${__("Goods")}</h5>
		<div style="overflow:auto;max-height:280px;margin-bottom:14px">
			<table class="table table-bordered table-sm">
				<thead><tr>
					<th>#</th><th>${__("Item")}</th><th>${__("Code")}</th>
					<th class="text-right">${__("Qty")}</th><th>${__("UoM")}</th>
					<th class="text-right">${__("Unit Price")}</th>
					<th class="text-right">${__("Total")}</th>
					<th class="text-right">${__("Rate")}</th>
					<th class="text-right">${__("Tax")}</th>
					<th class="text-right">${__("Discount")}</th>
					<th>${__("Category")}</th>
				</tr></thead>
				<tbody>${goods_rows || `<tr><td colspan="11" class="text-muted">${__("No goods")}</td></tr>`}</tbody>
			</table>
		</div>

		<h5>${__("Tax Details")}</h5>
		<table class="table table-bordered table-sm" style="margin-bottom:14px">
			<thead><tr>
				<th>${__("Category")}</th><th class="text-right">${__("Rate")}</th>
				<th class="text-right">${__("Net")}</th>
				<th class="text-right">${__("Tax")}</th>
				<th class="text-right">${__("Gross")}</th>
			</tr></thead>
			<tbody>${tax_rows || `<tr><td colspan="5" class="text-muted">${__("No tax rows")}</td></tr>`}</tbody>
		</table>

		<h5>${__("Summary")}</h5>
		<table class="table table-bordered table-sm" style="margin-bottom:14px">
			<thead><tr>
				<th></th><th class="text-right">${__("Credit")}</th>
				<th class="text-right">${__("Original Invoice")}</th>
			</tr></thead>
			<tbody>
				<tr><th>${__("Net")}</th><td class="text-right">${num(summary.netAmount)}</td><td class="text-right">${num(summary.previousNetAmount)}</td></tr>
				<tr><th>${__("Tax")}</th><td class="text-right">${num(summary.taxAmount)}</td><td class="text-right">${num(summary.previousTaxAmount)}</td></tr>
				<tr><th>${__("Gross")}</th><td class="text-right">${num(summary.grossAmount)}</td><td class="text-right">${num(summary.previousGrossAmount)}</td></tr>
			</tbody>
		</table>

		<h5>${__("Payment")}</h5>
		<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${__("Mode")}</th>
				<th class="text-right">${__("Amount")}</th>
				<th>${__("Order")}</th>
			</tr></thead>
			<tbody>${pay_rows || `<tr><td colspan="3" class="text-muted">${__("No payment rows")}</td></tr>`}</tbody>
		</table>
	`;

	const dlg = new frappe.ui.Dialog({
		title: __("EFRIS Credit Note Application (T118)"),
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "body" }],
	});
	dlg.fields_dict.body.$wrapper.html(html);
	dlg.show();
}

function show_efris_qr(payload) {
	const src = `https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=${encodeURIComponent(payload)}`;
	frappe.msgprint({
		title: __("EFRIS QR Code"),
		indicator: "green",
		message: `<div style="text-align:center"><img src="${src}" alt="QR"/><br/><pre style="white-space:pre-wrap">${frappe.utils.escape_html(payload)}</pre></div>`,
	});
}
