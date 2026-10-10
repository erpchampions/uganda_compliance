import frappe

FORMAT = "EFRIS POS Receipt 80mm"

OLD = """  <div class="rule"></div>
  <div class="c small">{{ _("Thank you!") }}</div>
"""
NEW = """  <div class="rule"></div>
  {%- for code in (tk_momo_merchant_codes() if tk_momo_merchant_codes is defined else []) %}
  <div class="c small">{{ _("Pay with {0}: merchant code {1}").format(code.label, code.code | e) }}</div>
  {%- endfor %}
  <div class="c small">{{ _("Thank you!") }}</div>
"""


def execute():
	"""The EFRIS 80 mm receipt prints the shop's MoMo / Airtel merchant codes above the
	thank-you line, when Till King (tillking_tenant_core) provides them and they are set.

	As in efris_receipt_momo_txn_id: the JSON keeps its ``modified`` date (migrate never
	overwrites a receipt changed on a site); only the shipped footer is replaced, with
	``db.set_value`` so developer mode does not export the format over the app's JSON.
	"""
	html = frappe.db.get_value("Print Format", FORMAT, "html")
	if not html or OLD not in html:
		return
	frappe.db.set_value("Print Format", FORMAT, "html", html.replace(OLD, NEW))
	frappe.clear_cache(doctype="POS Invoice")
