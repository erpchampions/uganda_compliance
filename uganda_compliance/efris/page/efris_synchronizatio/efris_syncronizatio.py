# Copyright (c) 2024, ERP Champions Ltd and contributors
# For license information, please see license.txt

# import frappe
from __future__ import unicode_literals
import frappe

import json
from collections import defaultdict
from frappe import _
from json import JSONEncoder
from frappe.model.document import Document
from datetime import datetime
from uganda_compliance.efris.utils.utils import efris_log_info
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings
from uganda_compliance.efris.api_classes.e_invoice import EInvoiceAPI, decode_e_tax_rate, validate_company

from frappe.model.document import Document

class EFRISSynchronizationCetner(Document):
	pass