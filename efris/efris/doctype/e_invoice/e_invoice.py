# Copyright (c) 2026, Ignite Digital and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class EInvoice(Document):
	@frappe.whitelist()
	def upload(self) -> dict:
		"""Push this E-Invoice to EFRIS via T109."""
		from efris.efris.api.invoice import upload_e_invoice

		return upload_e_invoice(self.name)
