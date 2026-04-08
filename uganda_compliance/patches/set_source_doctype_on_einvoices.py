import frappe


def execute():
	"""Backfill source_doctype = 'Sales Invoice' on all existing E Invoice records."""
	frappe.db.sql("""
		UPDATE `tabE Invoice`
		SET source_doctype = 'Sales Invoice'
		WHERE (source_doctype IS NULL OR source_doctype = '')
	""")
	frappe.db.commit()
