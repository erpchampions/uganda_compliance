# Copyright (c) 2026, Ignite Digital and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

SERVER_URLS = {
	"Sandbox": "https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation",
	"Production": "https://efris.ura.go.ug/efrisws/ws/taapp",
}


class EFRISSettings(Document):
	def validate(self):
		# Default the server URL from the selected environment if left blank.
		if not self.efris_server_url and self.environment:
			self.efris_server_url = SERVER_URLS.get(self.environment, "")

		# A signing key must never be world-readable: force the attachment private.
		self._enforce_private_key_file()

		if self.enabled:
			for field in ("tin", "device_no", "efris_server_url"):
				if not self.get(field):
					label = self.meta.get_label(field)
					frappe.throw(_("{0} is required to enable EFRIS.").format(label))

	def is_vat_registered(self) -> bool:
		"""True when the taxpayer holds an active VAT registration (tax type 301).

		EFRIS tax type code ``301`` is VAT. A row whose ``cancellation_date`` is
		set is a lapsed registration and doesn't count. VAT-registered taxpayers
		must issue tax invoices (invoiceKind 1); non-VAT taxpayers issue receipts
		(invoiceKind 2). See URA return code 2240.
		"""
		for row in self.get("tax_types") or []:
			if (row.get("tax_type_code") or "").strip() == "301" and not row.get("cancellation_date"):
				return True
		return False

	def _enforce_private_key_file(self):
		"""Ensure the attached RSA private key is stored as a private File.

		An Attach field accepts public files, which would expose the signing
		key at a guessable URL. If a public file is attached, flip it to
		private and re-point the field at the new ``/private/files`` URL.
		"""
		if not self.private_key:
			return

		file_doc = frappe.db.get_value(
			"File", {"file_url": self.private_key}, ["name", "is_private"], as_dict=True
		)
		if not file_doc or file_doc.is_private:
			return

		file = frappe.get_doc("File", file_doc.name)
		file.is_private = 1
		file.save(ignore_permissions=True)
		# file_url changes (/files/... -> /private/files/...) when made private.
		self.private_key = file.file_url

	@frappe.whitelist()
	def test_connection(self) -> dict:
		"""Ping EFRIS with T101 (server time) to verify connectivity and credentials."""
		from efris.efris.api.client import efris_errors
		from efris.efris.api.interfaces import get_server_time

		with efris_errors(_("EFRIS Connection Failed")):
			result = get_server_time(company=self.company)

		frappe.msgprint(_("EFRIS connection OK."), alert=True, indicator="green")
		return result

	@frappe.whitelist()
	def sync_dictionary(self) -> str:
		"""Queue a background T115 sync to refresh EFRIS Dictionary."""
		from efris.efris.api.dictionary import enqueue_sync

		job_id = enqueue_sync(company=self.company)
		frappe.msgprint(
			_("EFRIS dictionary sync started in the background. Check Background Jobs for progress."),
			alert=True,
			indicator="blue",
		)
		return job_id

	@frappe.whitelist()
	def sync_commodity_categories(self) -> dict:
		"""Run T124 page 1 inline and queue the rest in the background."""
		from efris.efris.api.commodity_category import sync_commodity_categories as run_sync

		result = run_sync(company=self.company)
		if result.get("queued"):
			frappe.msgprint(
				_(
					"Imported {0} categories. {1} more pages are syncing in the background "
					"(check Background Jobs for progress)."
				).format(result["imported"], result["total_pages"] - 1),
				alert=True,
				indicator="blue",
			)
		else:
			frappe.msgprint(
				_("Imported {0} commodity categories.").format(result["imported"]),
				alert=True,
				indicator="green",
			)
		return result

	@frappe.whitelist()
	def sync_excise_duty(self) -> dict:
		"""Run T125 synchronously and refresh EFRIS Excise Duty.

		The catalogue is small and the inline call gives the user immediate
		feedback (and a real error if URA rejects the request).
		"""
		from efris.efris.api.excise_duty import sync_excise_duty as run_sync

		result = run_sync(company=self.company)
		frappe.msgprint(
			_("EFRIS excise duty synced: {0} rows upserted, {1} pruned.").format(
				result.get("rows_upserted", 0), result.get("rows_pruned", 0)
			),
			alert=True,
			indicator="green",
		)
		return result

	@frappe.whitelist()
	def map_modes_of_payment(self) -> dict:
		"""Default ``Mode of Payment.efris_dictionary`` from the payWay catalogue.

		Verifies the EFRIS Dictionary has been synced (T115) first, then
		guesses a URA payWay code per Mode of Payment based on name + ``type``,
		and points the field at the matching ``payWay-<code>`` row. Only
		writes to records where the field is blank, so re-running won't
		overwrite curator choices.
		"""
		dict_codes = {
			row.name.split("-", 1)[1]
			for row in frappe.get_all(
				"EFRIS Dictionary",
				filters={"name": ["like", "payWay-%"]},
				fields=["name"],
			)
			if "-" in row.name
		}
		if not dict_codes:
			frappe.throw(
				_(
					"No EFRIS Dictionary entries in category 'payWay' found. "
					"Run Sync Dictionary (T115) first."
				)
			)

		rows = frappe.get_all(
			"Mode of Payment",
			filters={"efris_dictionary": ["in", ("", None)]},
			fields=["name", "mode_of_payment", "type"],
		)
		mapped = 0
		skipped: list[str] = []
		for row in rows:
			code = _guess_pay_way_code(row.get("mode_of_payment") or row.name, row.get("type"))
			if not code or code not in dict_codes:
				skipped.append(row["name"])
				continue
			frappe.db.set_value(
				"Mode of Payment",
				row["name"],
				"efris_dictionary",
				f"payWay-{code}",
				update_modified=False,
			)
			mapped += 1

		frappe.msgprint(
			_("Mapped {0} Mode(s) of Payment to EFRIS payWay. {1} unmapped.").format(
				mapped, len(skipped)
			),
			alert=True,
			indicator="green" if mapped else "orange",
		)
		return {"mapped": mapped, "unmapped": skipped}

	@frappe.whitelist()
	def fetch_branches(self) -> dict:
		"""T138 — fetch the taxpayer's branches and save them locally.

		For each branch:
		  * upserts an ERPNext ``Branch`` record (autonamed by ``branch``
		    field == branchName) and stamps ``efris_branch_id`` on it,
		  * mirrors the row into the EFRIS Settings ``branches`` table so the
		    user can see / re-map them.
		"""
		from efris.efris.api.client import efris_errors
		from efris.efris.api.interfaces import get_branches

		with efris_errors(_("EFRIS Branches Fetch Failed")):
			response = get_branches(company=self.company)

		records = _extract_branch_records(response)

		# Preserve any user-set ERPNext Branch mapping across refreshes.
		existing_map = {
			row.branch_id: row.branch for row in (self.branches or []) if row.branch_id
		}
		self.set("branches", [])

		for rec in records:
			branch_id = (rec.get("branchId") or "").strip()
			branch_name = (rec.get("branchName") or "").strip()
			if not branch_id:
				continue

			linked_branch = existing_map.get(branch_id) or _upsert_branch(branch_name, branch_id)

			self.append(
				"branches",
				{"branch_id": branch_id, "branch_name": branch_name, "branch": linked_branch},
			)

		self.save(ignore_permissions=True)
		frappe.msgprint(
			_("Fetched {0} EFRIS branches.").format(len(records)),
			alert=True,
			indicator="green",
		)
		return {"count": len(records)}

	@frappe.whitelist()
	def upload_certificate(self, file_url: str) -> dict:
		"""T136 — upload a .crt / .cer public-key certificate to EFRIS.

		``verifyString`` is the file name AES-ECB encrypted with a key made of
		the first 10 chars of the TIN concatenated with today's date as
		``yymmdd`` (16 bytes → AES-128). ``fileContent`` is the raw file bytes
		base64-encoded.
		"""
		import base64
		from datetime import datetime

		from efris.efris.api.client import efris_errors
		from efris.efris.api.crypto import encrypt_aes_ecb
		from efris.efris.api.interfaces import upload_certificate as call_t136

		if not file_url:
			frappe.throw(_("Attach a certificate file (.crt or .cer) first."))
		if not self.tin or len(self.tin) < 10:
			frappe.throw(_("EFRIS Settings TIN must be at least 10 characters."))

		file_doc = frappe.get_doc("File", {"file_url": file_url})
		file_name = file_doc.file_name or ""
		if not file_name.lower().endswith((".crt", ".cer")):
			frappe.throw(_("FileName must be in '.crt' and '.cer' format."))

		content = file_doc.get_content()
		if isinstance(content, str):
			content = content.encode("latin-1")
		file_content_b64 = base64.b64encode(content).decode("ascii")

		aes_key = (self.tin[:10] + datetime.now().strftime("%y%m%d")).encode("utf-8")
		verify_string = encrypt_aes_ecb(file_name, aes_key)

		with efris_errors(_("EFRIS Certificate Upload Failed")):
			result = call_t136(file_name, verify_string, file_content_b64, company=self.company)

		frappe.msgprint(
			_("Certificate {0} uploaded to EFRIS.").format(file_name),
			alert=True,
			indicator="green",
		)
		return result

	@frappe.whitelist()
	def fetch_taxpayer_details(self) -> str:
		"""Run T103 login and store the taxpayer / device / branch profile."""
		from efris.efris.api.client import efris_errors
		from efris.efris.api.interfaces import fetch_taxpayer_details as run_fetch_taxpayer_details

		with efris_errors(_("EFRIS Login Failed")):
			run_fetch_taxpayer_details(company=self.company, save=True)

		self.reload()
		frappe.msgprint(
			_("Taxpayer details fetched from EFRIS."), alert=True, indicator="green"
		)
		return "ok"


_PAY_WAY_NAME_RULES: list[tuple[str, str]] = [
	("credit card", "106"),
	("visa", "106"),
	("master", "106"),
	("debit card", "106"),
	("mobile money", "105"),
	("momo", "105"),
	("airtel", "105"),
	("mtn", "105"),
	("demand draft", "104"),
	("bank draft", "104"),
	("swift", "110"),
	("rtgs", "109"),
	("pos terminal", "108"),
	("point of sale", "108"),
	("cheque", "103"),
	("check", "103"),
	("eft", "107"),
	("wire", "107"),
	("bank transfer", "107"),
	("credit", "101"),
	("cash", "102"),
]


_PAY_WAY_TYPE_RULES: dict[str, str] = {
	"Cash": "102",
	"Bank": "107",
	"Phone": "105",
	"General": "101",
}


def _guess_pay_way_code(name: str, payment_type: str | None) -> str:
	name_lc = (name or "").lower()
	for substring, code in _PAY_WAY_NAME_RULES:
		if substring in name_lc:
			return code
	return _PAY_WAY_TYPE_RULES.get(payment_type or "", "")


def _extract_branch_records(response) -> list[dict]:
	"""Normalise T138's response into a flat list of branch dicts.

	URA can return either a bare list or a dict wrapping a list under any key.
	"""
	if isinstance(response, list):
		return [r for r in response if isinstance(r, dict)]
	if isinstance(response, dict):
		if "branchId" in response or "branchName" in response:
			return [response]
		for value in response.values():
			if isinstance(value, list):
				return [r for r in value if isinstance(r, dict)]
	return []


def _upsert_branch(branch_name: str, branch_id: str) -> str:
	"""Create/refresh an ERPNext Branch named ``branch_name`` with the EFRIS ID.

	Returns the Branch name. Empty input → empty string (skip mapping).
	"""
	if not branch_name:
		return ""

	if frappe.db.exists("Branch", branch_name):
		frappe.db.set_value("Branch", branch_name, "efris_branch_id", branch_id)
		return branch_name

	doc = frappe.get_doc({
		"doctype": "Branch",
		"branch": branch_name,
		"efris_branch_id": branch_id,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def get_efris_settings(company: str | None = None) -> "EFRISSettings":
	"""Return the EFRIS Settings document for a company.

	Falls back to the session/global default company when ``company`` is not
	given. Raises if no settings record exists for the resolved company.
	"""
	company = company or frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default(
		"company"
	)
	if not company:
		frappe.throw(_("No company specified and no default company is set."))

	if not frappe.db.exists("EFRIS Settings", company):
		frappe.throw(_("EFRIS Settings have not been configured for company {0}.").format(company))

	return frappe.get_doc("EFRIS Settings", company)
