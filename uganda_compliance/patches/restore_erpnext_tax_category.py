import frappe


def execute():
	"""Give the Tax Category DocType back to ERPNext.

	The app used to ship a copy of ERPNext's Tax Category (same fields) under its EFRIS module,
	so the DocType record pointed at this app: uninstalling uganda_compliance would have deleted
	ERPNext's Tax Category DocType and table, and users whose module profile blocks EFRIS lost it.
	Runs before model sync so the orphan-DocType cleanup never sees it without a controller.
	"""
	if frappe.db.get_value("DocType", "Tax Category", "module") == "Accounts":
		return
	frappe.db.set_value("DocType", "Tax Category", "module", "Accounts", update_modified=False)
	frappe.reload_doc("accounts", "doctype", "tax_category", force=True)
	frappe.clear_cache(doctype="Tax Category")
