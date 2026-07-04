// Client-side helpers for filtering EFRIS Dictionary Link fields by category.
//
// Loaded via app_include_js in hooks.py so it's available on every Desk page.
//
// Usage on a regular Link field:
//
//   frappe.ui.form.on("Sales Invoice", {
//       setup(frm) {
//           efris.dictionary.set_link_query(frm, "efris_currency", "currencyType");
//       },
//   });
//
// Usage on a child-table Link field (pass the parent fieldname as 3rd arg):
//
//   efris.dictionary.set_link_query(frm, "tax_category", "taxCategory", "items");

frappe.provide("efris.dictionary");

efris.dictionary.QUERY_METHOD = "efris.efris.api.dictionary.dictionary_query";

/**
 * Wire a Link field (or child-table Link field) so its picker is filtered to
 * EFRIS Dictionary rows in a given category.
 *
 * @param {object} frm           The form object (from frappe.ui.form.on).
 * @param {string} fieldname     The Link field's name.
 * @param {string} category      EFRIS category (e.g. "currencyType", "payWay").
 * @param {string} [parentfield] If the field lives in a child table, the
 *                               child table's fieldname on the parent form.
 * @param {object} [extra]       Additional filters (e.g. { code: "101" }).
 */
efris.dictionary.set_link_query = function (frm, fieldname, category, parentfield, extra) {
	const query = () => ({
		query: efris.dictionary.QUERY_METHOD,
		filters: Object.assign({ category }, extra || {}),
	});
	if (parentfield) {
		frm.set_query(fieldname, parentfield, query);
	} else {
		frm.set_query(fieldname, query);
	}
};

/**
 * Inline filter-builder for callers that want to construct the query
 * themselves (e.g. ReportView, list filters).
 *
 *   { query: efris.dictionary.QUERY_METHOD, filters: efris.dictionary.filters("payWay") }
 */
efris.dictionary.filters = function (category, extra) {
	return Object.assign({ category }, extra || {});
};

/**
 * Look up an EFRIS Dictionary code from a human-readable name.
 * Returns a Promise resolving to the code string, or null if no match.
 *
 *   const code = await efris.dictionary.code_for("currencyType", "UGX"); // "101"
 *
 * @param {string} category   EFRIS category (e.g. "currencyType").
 * @param {string} name       The entry_name to look up.
 * @returns {Promise<string|null>}
 */
efris.dictionary.code_for = async function (category, name) {
	if (!name) return null;
	const r = await frappe.db.get_value("EFRIS Dictionary", {
		category,
		entry_name: name,
	}, "code");
	return (r && r.message && r.message.code) || null;
};

/**
 * Inverse — look up the entry_name from a code.
 *
 *   const label = await efris.dictionary.name_for("currencyType", "101"); // "UGX"
 *
 * @param {string} category   EFRIS category.
 * @param {string} code       The code to look up.
 * @returns {Promise<string|null>}
 */
efris.dictionary.name_for = async function (category, code) {
	if (!code) return null;
	const r = await frappe.db.get_value("EFRIS Dictionary", {
		category,
		code,
	}, "entry_name");
	return (r && r.message && r.message.entry_name) || null;
};
