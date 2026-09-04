import frappe


def before_install():
	"""Remove a stale Desktop Icon left behind by a previous failed install.

	The app ships its icon as desktop_icon/uganda_compliance.json. When an install
	aborts after that icon was inserted (a customised site can fail later in the
	doctype sync), the icon survives the rollback and the next attempt dies with
	DuplicateEntryError on "Uganda Compliance". Clearing the leftover first makes
	re-installing idempotent; a healthy site has no such icon at this point.
	"""
	if not frappe.db.table_exists("Desktop Icon"):
		return
	for name in frappe.get_all(
		"Desktop Icon",
		filters={"app": "uganda_compliance", "standard": 1},
		pluck="name",
	):
		frappe.delete_doc("Desktop Icon", name, force=True, ignore_permissions=True)
	frappe.db.commit()
