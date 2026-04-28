"""Namespaced logger for the EFRIS integration.

All transport-level diagnostics go through `get_logger()` so log lines carry a
consistent prefix and can be filtered/rotated independently of bench logs.
"""
import frappe


def get_logger():
    return frappe.logger("efris", allow_site=True, file_count=5)
