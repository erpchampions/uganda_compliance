import tomllib
from pathlib import Path

import frappe
from frappe.utils.file_manager import save_file

from uganda_compliance import tillking
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import (
	get_e_company_client_settings,
	get_e_company_settings,
)
from uganda_compliance.efris.tests.efris_test_utils import (
	TEST_TIN,
	fake_ura,
	make_pos_invoice,
	reload,
	run_queued,
)
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase


class TestConfigureEfris(EfrisTestCase):
	def _settings(self):
		return frappe.get_doc("E Invoicing Settings", {"company": self.company})

	def _attach_key(self, settings, field):
		f = save_file(
			f"{field}-{frappe.generate_hash(length=6)}.p12",
			b"not-a-real-key",
			settings.doctype,
			settings.name,
			is_private=1,
		)
		settings.set(field, f.file_url)
		settings.set(f"{field}_password", "test-pass")
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)

	def _clear_keys(self):
		s = self._settings()
		s.sandbox_private_key = s.live_private_key = None
		s.flags.ignore_mandatory = True
		s.save(ignore_permissions=True)
		frappe.db.delete("__Auth", {"doctype": "E Invoicing Settings", "name": s.name})

	def test_sandbox_provisioning_without_key_stays_disabled(self):
		self._clear_keys()
		out = tillking.configure_efris(self.company, tin=TEST_TIN, device_no="1000000001_02")
		self.assertEqual(out["mode"], "Sandbox")
		self.assertFalse(out["enabled"])
		self.assertIn("Sandbox Private Key", out["missing"])
		self.assertTrue(out["auto_send"])
		self.assertEqual(out["sales_invoice_submission"], "Background")
		s = self._settings()
		self.assertEqual((s.enabled, s.sandbox_mode, s.device_no), (0, 1, "1000000001_02"))
		# disabled settings -> POS sales are not queued for EFRIS
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
		self.assertFalse(reload(inv).efris_status)
		self.assertEqual(ura.enqueued, [])

	def test_sandbox_enabled_once_key_uploaded_and_idempotent(self):
		self._clear_keys()
		self._attach_key(self._settings(), "sandbox_private_key")
		out = tillking.configure_efris(self.company, tin=TEST_TIN, device_no="1000000001_01")
		self.assertTrue(out["enabled"])
		self.assertEqual(out["missing"], [])
		again = tillking.configure_efris(self.company, tin=TEST_TIN, device_no="1000000001_01")
		self.assertEqual(again["settings"], out["settings"])
		self.assertEqual(frappe.db.count("E Invoicing Settings", {"company": self.company}), 1)

	def test_go_live_blocked_without_live_credentials(self):
		self._clear_keys()
		self._attach_key(self._settings(), "sandbox_private_key")
		tillking.configure_efris(self.company, tin=TEST_TIN, device_no="1000000001_01")
		with self.assertRaises(frappe.ValidationError):
			tillking.set_efris_mode(self.company, "Production")
		s = self._settings()
		self.assertEqual((s.enabled, s.sandbox_mode), (1, 1), "tenant stays live on sandbox")

	def test_go_live_switches_to_production_after_smoke_test(self):
		self._clear_keys()
		self._attach_key(self._settings(), "sandbox_private_key")
		self._attach_key(self._settings(), "live_private_key")
		with fake_ura() as ura:
			out = tillking.set_efris_mode(self.company, "production")
		self.assertEqual(out["mode"], "Production")
		self.assertTrue(out["enabled"])
		self.assertEqual(out["smoke_test"], {"ok": True, "message": None})
		self.assertEqual(ura.calls_for("T119")[0]["content"]["tin"], TEST_TIN)
		self.assertEqual(get_e_company_settings(self.company).sandbox_mode, 0)

	def test_go_live_smoke_test_failure_raises(self):
		self._clear_keys()
		self._attach_key(self._settings(), "sandbox_private_key")
		self._attach_key(self._settings(), "live_private_key")
		with fake_ura() as ura:
			ura.responses["T119"] = [(False, "Invalid signature")]
			with self.assertRaises(frappe.ValidationError) as cm:
				tillking.set_efris_mode(self.company, "Production")
		self.assertIn("Invalid signature", str(cm.exception))

	def test_invalid_mode_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			tillking.configure_efris(self.company, tin=TEST_TIN, mode="Live")

	def test_settings_cache_not_stale_after_mode_switch(self):
		# regression: module-level cache kept serving sandbox settings after go-live
		self.assertEqual(get_e_company_settings(self.company).sandbox_mode, 1)
		frappe.db.set_value("E Invoicing Settings", {"company": self.company}, "sandbox_mode", 0)
		frappe.local.efris_company_settings_cache = None  # next request / job
		self.assertEqual(get_e_company_settings(self.company).sandbox_mode, 0)

	def test_client_settings_hide_secrets_and_check_permission(self):
		out = get_e_company_client_settings(self.company)
		self.assertEqual(out.auto_send_submitted_invoice, 1)
		for secret in ("sandbox_private_key", "live_private_key", "live_portal_url", "tin"):
			self.assertNotIn(secret, out)
		email = "efris-nobody@example.ug"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Mukasa", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				get_e_company_client_settings(self.company)
		finally:
			frappe.set_user("Administrator")

	def test_pyproject_toml_parses(self):
		# regression: develop@cc4f451 broke the [project] header ("dit[project]")
		path = Path(frappe.get_app_path("uganda_compliance")).parent / "pyproject.toml"
		data = tomllib.loads(path.read_text())
		self.assertEqual(data["project"]["name"], "uganda_compliance")


class TestEfrisPosReceipt(EfrisTestCase):
	FORMAT = "EFRIS POS Receipt 80mm"

	def _render(self, inv):
		return frappe.get_print("POS Invoice", inv.name, print_format=self.FORMAT)

	def test_receipt_shows_pending_state_before_fiscalisation(self):
		with fake_ura():
			inv = make_pos_invoice(self.ctx)
		html = self._render(inv)
		self.assertIn("EFRIS PENDING", html)
		self.assertIn("SANDBOX", html)
		self.assertNotIn("Verification Code", html)
		self.assertIn(inv.name, html)

	def test_receipt_shows_fdn_verification_code_and_qr(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
		inv = reload(inv)
		einv = frappe.get_doc("E Invoice", inv.name)
		html = self._render(inv)
		self.assertNotIn("EFRIS PENDING", html)
		self.assertIn(inv.efris_irn, html)
		self.assertIn(einv.antifake_code, html)
		self.assertIn('src="data:image/png;base64,', html)
		self.assertIn("80mm", html)

	def test_receipt_for_return_shows_credit_note_pending(self):
		from erpnext.accounts.doctype.pos_invoice.pos_invoice import make_sales_return

		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			run_queued(ura)
			ret = make_sales_return(inv.name)
			ret.insert(ignore_permissions=True)
			ret.submit()
			run_queued(ura)
		html = self._render(ret)
		self.assertIn("CREDIT NOTE", html)
		self.assertIn("PENDING URA APPROVAL", html)
		self.assertIn(reload(inv).efris_irn, html)

	def test_non_efris_receipt_has_no_efris_block(self):
		frappe.db.set_value("E Invoicing Settings", {"company": self.company}, "enabled", 0)
		with fake_ura():
			inv = make_pos_invoice(self.ctx)
		frappe.db.set_value("POS Invoice", inv.name, "efris_invoice", 0)
		html = self._render(reload(inv))
		self.assertNotIn("URA EFRIS", html)
