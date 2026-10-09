import frappe

FORMAT = "EFRIS POS Receipt 80mm"

OLD = """    {%- for p in doc.payments %}{% if p.amount %}
    <tr><td>{{ p.mode_of_payment }}</td><td class="r">{{ p.get_formatted("amount", doc) }}</td></tr>
    {%- endif %}{% endfor %}"""
NEW = """    {%- for p in doc.payments %}{% if p.amount %}
    <tr><td>{{ p.mode_of_payment }}</td><td class="r">{{ p.get_formatted("amount", doc) }}</td></tr>
    {%- if p.reference_no %}
    <tr><td colspan="2">&nbsp;&nbsp;{{ _("Txn ID") }}: {{ p.reference_no | e }}</td></tr>
    {%- endif %}
    {%- endif %}{% endfor %}"""


def execute():
	"""The EFRIS 80 mm receipt prints each MoMo payment's transaction ID under its line
	(as Till King's own 80 mm receipt does).

	The shipped JSON keeps its ``modified`` date so model sync never overwrites a receipt
	changed on a site; this patch replaces only the shipped payment lines, and leaves a
	receipt whose payment lines were changed alone. ``db.set_value``, not ``doc.save``:
	saving a standard print format in developer mode would export it over the app's JSON.
	"""
	html = frappe.db.get_value("Print Format", FORMAT, "html")
	if not html or OLD not in html:
		return
	frappe.db.set_value("Print Format", FORMAT, "html", html.replace(OLD, NEW))
	frappe.clear_cache(doctype="POS Invoice")
