import frappe
from frappe.utils.nestedset import NestedSet


class EFRISCommodityCategory(NestedSet):
	nsm_parent_field = "parent_efris_commodity_category"

	def on_update(self):
		super().on_update()

	def on_trash(self):
		super().on_trash()
