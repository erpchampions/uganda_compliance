// Reusable T121 (Acquire Exchange Rate) helper.
//
// Exposes `efris.exchange_rate`:
//   * `fetch(currency, issueDate)` — returns a Promise resolving to
//     `{currency, rate, importDutyLevy, inComeTax, exportLevy}`.
//   * `apply_to_form(frm, opts)` — fetch and write the rate onto a form.
//   * `add_button(frm, opts)` — add an "EFRIS → Fetch Exchange Rate" custom
//     button that calls `apply_to_form` with the same opts.
//
// `opts` (all optional):
//   currency_field:   form field with the currency code     (default "currency")
//   date_field:       form field with the issue date        (default "posting_date")
//   rate_field:       form field to write the rate into     (default "conversion_rate")
//   on_success(frm, data): extra hook after fields are set
//
// Use from any transaction form (Sales Invoice, Purchase Invoice, …):
//
//   frappe.ui.form.on("Sales Invoice", {
//       refresh(frm) { efris.exchange_rate.add_button(frm); },
//   });

(function () {
	window.efris = window.efris || {};

	const DEFAULTS = {
		currency_field: "currency",
		date_field: "posting_date",
		rate_field: "conversion_rate",
		on_success: null,
	};

	function fetch(currency, issue_date, company) {
		if (!currency) {
			return Promise.reject(new Error(__("Currency is required.")));
		}
		return frappe
			.call({
				method: "efris.efris.api.exchange_rate.fetch_rate",
				args: { currency, issue_date: issue_date || null, company: company || null },
			})
			.then((r) => r.message);
	}

	function apply_to_form(frm, opts) {
		const o = Object.assign({}, DEFAULTS, opts || {});
		const currency = frm.doc[o.currency_field];
		const issue_date = frm.doc[o.date_field];
		const company = frm.doc.company;

		if (!currency) {
			frappe.msgprint({
				title: __("EFRIS"),
				message: __("Set {0} before fetching the EFRIS rate.", [__(o.currency_field)]),
				indicator: "orange",
			});
			return Promise.resolve(null);
		}

		frappe.dom.freeze(__("Fetching EFRIS rate…"));
		return fetch(currency, issue_date, company)
			.then((data) => {
				if (!data) return null;
				frm.set_value(o.rate_field, data.rate);
				frappe.show_alert({
					message: __("EFRIS rate {0} {1} = {2} UGX", [1, data.currency, data.rate]),
					indicator: "green",
				});
				if (typeof o.on_success === "function") o.on_success(frm, data);
				return data;
			})
			.catch((err) => {
				frappe.msgprint({
					title: __("EFRIS"),
					message: err.message || __("Failed to fetch EFRIS rate."),
					indicator: "red",
				});
			})
			.finally(() => frappe.dom.unfreeze());
	}

	function add_button(frm, opts) {
		frm.add_custom_button(
			__("Fetch Exchange Rate (T121)"),
			() => apply_to_form(frm, opts),
			__("EFRIS"),
		);
	}

	efris.exchange_rate = { fetch, apply_to_form, add_button };
})();
