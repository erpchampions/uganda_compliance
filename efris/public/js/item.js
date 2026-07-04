// Item form additions for EFRIS:
//   * filter EFRIS Dictionary Link pickers (piece measure unit, customs
//     child table) to the right category,
//   * "Upload to EFRIS (T130)" button for manual retry after a failed save.

frappe.ui.form.on("Item", {
	setup(frm) {
		efris.dictionary.set_link_query(frm, "efris_piece_measure_unit", "rateUnit");
		efris.dictionary.set_link_query(
			frm,
			"customs_measure_unit",
			"exportRateUnit",
			"efris_customs_units",
		);
		// Restrict the commodity category picker to leaf nodes — URA only
		// accepts leaf categories on T130.
		frm.set_query("efris_commodity_category", () => ({
			filters: { is_group: 0 },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(
			__("Upload to EFRIS (T130)"),
			() => upload_to_efris(frm),
			__("EFRIS"),
		);
		frm.add_custom_button(
			__("Check on EFRIS (T127)"),
			() => query_efris(frm),
			__("EFRIS"),
		);
		frm.add_custom_button(
			__("Query EFRIS Stock (T128)"),
			() => query_efris_stock(frm),
			__("EFRIS"),
		);
	},

	stock_uom(frm) {
		warn_if_stock_uom_unmapped(frm);
		sync_piece_unit_from_stock_uom_row(frm);
	},

	standard_rate(frm) {
		apply_standard_rate_to_efris(frm);
	},

	efris_piece_unit_price(frm) {
		mirror_piece_price_to_first_uom_row(frm);
	},

	uoms_add(frm) {
		sync_piece_unit_from_stock_uom_row(frm);
	},

	uoms_remove(frm) {
		sync_piece_unit_from_stock_uom_row(frm);
	},
});

// Child-table-level triggers: any change inside the stock_uom row (the UOM
// itself, the EFRIS unit price, or the package_scaled value) should mirror
// onto the Item's piece-unit fields immediately.
frappe.ui.form.on("UOM Conversion Detail", {
	uom(frm, cdt, cdn) {
		warn_if_uom_unmapped(cdt, cdn);
		sync_piece_unit_from_stock_uom_row(frm);
	},
	efris_unit_price(frm, _cdt, _cdn) {
		sync_piece_unit_from_stock_uom_row(frm);
	},
	efris_package_scaled(frm, _cdt, _cdn) {
		sync_piece_unit_from_stock_uom_row(frm);
	},
});

function mirror_piece_price_to_first_uom_row(frm) {
	const price = frm.doc.efris_piece_unit_price;
	if (price == null) return;
	const first_row = (frm.doc.uoms || []).find((r) => r.idx === 1);
	if (!first_row) return;
	frappe.model.set_value(first_row.doctype, first_row.name, "efris_unit_price", price);
}

function apply_standard_rate_to_efris(frm) {
	const rate = frm.doc.standard_rate;
	if (!rate) return;

	frm.set_value("efris_piece_unit_price", rate);

	const stock_uom = frm.doc.stock_uom;
	if (!stock_uom) return;
	const row = (frm.doc.uoms || []).find((r) => r.uom === stock_uom);
	if (!row) return;
	frappe.model.set_value(row.doctype, row.name, "efris_unit_price", rate);
}

async function warn_if_stock_uom_unmapped(frm) {
	const stock_uom = frm.doc.stock_uom;
	if (!stock_uom) return;
	const r = await frappe.db.get_value("UOM", stock_uom, "efris_dictionary");
	if (r && r.message && r.message.efris_dictionary) return;
	frappe.show_alert({
		message: __("Stock UOM {0} has no EFRIS Dictionary entry. Map it before uploading to EFRIS.", [stock_uom]),
		indicator: "orange",
	});
}

async function warn_if_uom_unmapped(cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || !row.uom) return;
	const r = await frappe.db.get_value("UOM", row.uom, "efris_dictionary");
	if (r && r.message && r.message.efris_dictionary) return;
	frappe.show_alert({
		message: __("UOM {0} has no EFRIS Dictionary entry. Map it before uploading to EFRIS.", [row.uom]),
		indicator: "orange",
	});
}

async function sync_piece_unit_from_stock_uom_row(frm) {
	const stock_uom = frm.doc.stock_uom;
	if (!stock_uom) return;

	const row = (frm.doc.uoms || []).find((r) => r.uom === stock_uom);
	if (!row) return;

	const r = await frappe.db.get_value("UOM", stock_uom, "efris_dictionary");
	const measure_unit = r && r.message && r.message.efris_dictionary;
	if (!measure_unit) return; // server-side validate will flag this on save

	frm.set_value("efris_have_piece_unit", 1);
	frm.set_value("efris_piece_measure_unit", measure_unit);
	frm.set_value("efris_piece_unit_price", row.efris_unit_price || 0);
	frm.set_value("efris_piece_scaled_value", row.efris_package_scaled || 1);
}

function query_efris_stock(frm) {
	frappe.dom.freeze(__("Querying EFRIS stock…"));
	frappe
		.call({
			method: "efris.efris.api.goods.query_item_stock",
			args: { name: frm.docname },
		})
		.then((r) => {
			const res = r && r.message;
			if (!res) return;
			if (!res.found) {
				frappe.msgprint({
					title: __("EFRIS Stock"),
					indicator: "orange",
					message: res.message || __("No data."),
				});
				return;
			}
			frappe.msgprint({
				title: __("EFRIS Stock for {0}", [res.goods_code]),
				indicator: "green",
				message: `
					<table class="table table-bordered">
						<tr><th>${__("Stock On Hand")}</th><td>${frappe.utils.escape_html(String(res.stock ?? "—"))}</td></tr>
						<tr><th>${__("Stock Prewarning")}</th><td>${frappe.utils.escape_html(String(res.stock_prewarning ?? "—"))}</td></tr>
						<tr><th>${__("Branch ID")}</th><td>${frappe.utils.escape_html(res.branch_id || "—")}</td></tr>
						<tr><th>${__("Goods ID")}</th><td>${frappe.utils.escape_html(res.goods_id || "—")}</td></tr>
					</table>
				`,
			});
		})
		.always(() => frappe.dom.unfreeze());
}

function query_efris(frm) {
	frappe.dom.freeze(__("Querying EFRIS…"));
	frappe
		.call({
			method: "efris.efris.api.goods.query_item",
			args: { name: frm.docname },
		})
		.then((r) => {
			const res = r && r.message;
			if (!res) return;
			if (res.found) {
				frappe.msgprint({
					title: __("EFRIS Goods Found ({0})", [res.goods_code]),
					indicator: "green",
					message: `<pre>${frappe.utils.escape_html(
						JSON.stringify(res.record, null, 2),
					)}</pre>`,
				});
			} else {
				frappe.msgprint({
					title: __("Not on EFRIS"),
					indicator: "orange",
					message: __(
						"No goods record was returned for code {0}. Upload the item to EFRIS first.",
						[res.goods_code],
					),
				});
			}
		})
		.always(() => frappe.dom.unfreeze());
}

function upload_to_efris(frm) {
	frappe.dom.freeze(__("Uploading to EFRIS…"));
	frappe
		.call({
			method: "efris.efris.api.goods.upload_item",
			args: { name: frm.docname },
		})
		.always(() => {
			frappe.dom.unfreeze();
			frm.reload_doc();
		});
}
