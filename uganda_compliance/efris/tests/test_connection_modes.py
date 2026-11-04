"""EFRIS connection modes: Online (URA) and Offline Enabler.

HTTP is faked at ``requests.post`` so the real make_post / post_req / response decoding run.
Regression tests named ``test_old_app_*`` cover bugs of the earlier enabler integration
(``ura_efris``) that this port avoids.
"""

import base64
import gzip
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
import requests

from uganda_compliance.efris import efris_queue
from uganda_compliance.efris.api_classes import efris_api, request_utils
from uganda_compliance.efris.api_classes.efris_api import EfrisRejection
from uganda_compliance.efris.api_classes.encryption_utils import decrypt_aes_ecb, encrypt_aes_ecb
from uganda_compliance.efris.doctype.e_invoicing_settings import e_invoicing_settings
from uganda_compliance.efris.tests.efris_test_utils import (
	TEST_DEVICE,
	TEST_TIN,
	FakeURA,
	ensure_settings,
	fake_ura,
	make_pos_invoice,
	reload,
	run_queued,
)
from uganda_compliance.efris.tests.test_efris_queue import EfrisTestCase
from uganda_compliance.efris.tests.test_endpoint_permissions import AsUser, make_user
from uganda_compliance.tillking import get_missing_credentials

ENABLER_URL = "http://enabler.example.invalid:9880/efristcs/ws/tcsapp/getInformation"
ENABLER_HTTPS_URL = "https://enabler.example.invalid/efristcs/ws/tcsapp/getInformation"
ENABLER_DEVICE = "TCS0000000000000001"
ENABLER_TOKEN = "fake-enabler-token-123"
AES_KEY = b"k" * 16
NOT_THE_KEY = AssertionError("Offline Enabler mode must not load, decrypt or use the private key")


def set_mode(company, mode, url=ENABLER_URL, token=None):
	s = ensure_settings(company)
	s.connection_mode = mode
	if mode == "Offline Enabler":
		s.enabler_url = url
		s.device_no = ENABLER_DEVICE
	s.enabler_access_token = token or ""
	s.flags.ignore_mandatory = True
	s.save(ignore_permissions=True)
	frappe.local.efris_company_settings_cache = {}
	return s


class Resp:
	def __init__(self, body, status=200):
		self.status_code = status
		self.ok = status < 400
		self.text = body if isinstance(body, str) else json.dumps(body)

	def raise_for_status(self):
		if not self.ok:
			raise requests.HTTPError(f"{self.status_code} Server Error")


def plain_reply(content=None, code="00", message="SUCCESS", gzipped=False):
	raw = json.dumps(content).encode() if content is not None else b""
	if gzipped:
		raw = gzip.compress(raw)
	return {
		"data": {
			"content": base64.b64encode(raw).decode() if raw else "",
			"signature": "",
			"dataDescription": {"codeType": "0", "encryptCode": "1", "zipCode": "1" if gzipped else "0"},
		},
		"returnStateInfo": {"returnCode": code, "returnMessage": message},
	}


class FakeHTTP:
	"""requests.post replacement. ``replies[code]``: list of reply dicts / Resp / exceptions;
	``default(code, content)`` answers otherwise."""

	def __init__(self):
		self.calls = []
		self.replies = {}

	def __call__(self, url, data=None, headers=None, timeout=None, **kw):
		envelope = json.loads(data)
		code = envelope["globalInfo"]["interfaceCode"]
		desc = envelope["data"]["dataDescription"]
		content = envelope["data"]["content"]
		decoded = None
		if content and desc.get("codeType") == "0":
			decoded = json.loads(base64.b64decode(content))
		self.calls.append(
			frappe._dict(
				url=url, envelope=envelope, headers=headers or {}, timeout=timeout, code=code, content=decoded
			)
		)
		scripted = self.replies.get(code)
		reply = scripted.pop(0) if scripted else self.default(code, decoded)
		if isinstance(reply, Exception):
			raise reply
		return reply if isinstance(reply, Resp) else Resp(reply)

	def default(self, code, content):
		if code == "T101":
			return plain_reply({"currentTime": "04/11/2026 12:00:00"})
		return plain_reply({"echo": content})

	def calls_for(self, code):
		return [c for c in self.calls if c.code == code]


@contextmanager
def fake_http():
	http = FakeHTTP()
	with patch.object(request_utils.requests, "post", http):
		yield http


@contextmanager
def no_private_key():
	"""Any use of the private key, its password, T104 or signing fails the test."""
	with (
		patch.object(efris_api, "get_private_key", side_effect=NOT_THE_KEY),
		patch.object(efris_api, "get_mode_private_key_path", side_effect=NOT_THE_KEY),
		patch.object(efris_api, "get_AES_key", side_effect=NOT_THE_KEY),
		patch.object(efris_api, "sign_data", side_effect=NOT_THE_KEY),
		patch.object(efris_api, "encrypt_aes_ecb", side_effect=NOT_THE_KEY),
		patch(
			"uganda_compliance.efris.api_classes.encryption_utils.get_mode_decrypted_password",
			side_effect=NOT_THE_KEY,
		),
	):
		yield


@contextmanager
def online_crypto():
	"""Online mode with a fake key: T104 and signing faked, AES real."""
	with (
		patch.object(efris_api, "get_private_key", return_value=object()),
		patch.object(efris_api, "get_AES_key", return_value=AES_KEY),
		patch.object(efris_api, "sign_data", return_value=b"fake-signature"),
	):
		yield


def online_reply(content, code="00", message="SUCCESS"):
	return {
		"data": {"content": encrypt_aes_ecb(json.dumps(content), AES_KEY), "signature": ""},
		"returnStateInfo": {"returnCode": code, "returnMessage": message},
	}


@contextmanager
def real_make_post_queue():
	"""Queue worker with the real make_post (HTTP faked); no commits, enqueues captured."""
	with (
		fake_http() as http,
		patch.object(efris_queue.frappe, "enqueue", lambda *a, **kw: None),
		patch.object(frappe.db, "commit", lambda *a, **kw: None),
	):
		yield http


def kampala_now():
	return datetime.now(ZoneInfo("Africa/Kampala"))


def ura_invoice(fdn, data_source="106"):
	return {
		"basicInformation": {
			"invoiceNo": fdn,
			"invoiceId": f"ID{fdn}",
			"antifakeCode": f"AF{fdn[-8:]}",
			"issuedDate": kampala_now().strftime("%d/%m/%Y %H:%M:%S"),
			"dataSource": data_source,
		},
		"summary": {"qrCode": f"https://efristest.example.invalid/validate?invoiceNo={fdn}"},
	}


class TestOfflineEnablerTransport(EfrisTestCase):
	def setUp(self):
		super().setUp()
		set_mode(self.company, "Offline Enabler")

	def test_offline_posts_plain_envelope_to_enabler_url(self):
		content = {"tin": TEST_TIN, "ninBrn": ""}
		with fake_http() as http, no_private_key():
			ok, response = efris_api.make_post("T119", content, self.company)

		self.assertTrue(ok, response)
		self.assertEqual(response, {"echo": content})
		(call,) = http.calls
		self.assertEqual(call.url, ENABLER_URL)
		env = call.envelope
		self.assertEqual(env["data"]["signature"], "")
		self.assertEqual(
			env["data"]["dataDescription"], {"codeType": "0", "encryptCode": "1", "zipCode": "0"}
		)
		self.assertEqual(call.content, content, "content is base64(JSON), not encrypted")
		self.assertEqual(env["globalInfo"]["interfaceCode"], "T119")
		self.assertEqual(env["globalInfo"]["deviceNo"], ENABLER_DEVICE)
		self.assertEqual(env["globalInfo"]["tin"], TEST_TIN)
		self.assertNotIn("Authorization", call.headers, "no token configured")

	def test_offline_never_reads_or_sends_private_key(self):
		with fake_http() as http, no_private_key():
			ok, _resp = efris_api.make_post("T109", {"x": 1}, self.company)
		self.assertTrue(ok)
		self.assertEqual([c.code for c in http.calls], ["T109"], "no T104 key exchange")
		body = json.dumps(http.calls[0].envelope)
		self.assertNotIn("PRIVATE KEY", body)
		self.assertEqual(http.calls[0].envelope["data"]["signature"], "")

	def test_offline_sends_access_token_as_bearer_header(self):
		set_mode(self.company, "Offline Enabler", url=ENABLER_HTTPS_URL, token=ENABLER_TOKEN)
		with fake_http() as http, no_private_key():
			ok, _resp = efris_api.make_post("T119", {"tin": TEST_TIN}, self.company)
		self.assertTrue(ok)
		self.assertEqual(http.calls[0].url, ENABLER_HTTPS_URL)
		self.assertEqual(http.calls[0].headers.get("Authorization"), f"Bearer {ENABLER_TOKEN}")
		self.assertNotIn(ENABLER_TOKEN, json.dumps(http.calls[0].envelope), "token only in the header")

	def test_offline_decodes_gzipped_response(self):
		big = {"records": [{"invoiceNo": str(n)} for n in range(50)]}
		with fake_http() as http, no_private_key():
			http.replies["T106"] = [plain_reply(big, gzipped=True)]
			ok, response = efris_api.make_post("T106", {"pageNo": "1"}, self.company)
		self.assertTrue(ok, response)
		self.assertEqual(response, big)

	def test_offline_rejection_carries_return_code(self):
		with fake_http() as http, no_private_key():
			http.replies["T109"] = [plain_reply(code="2253", message="Invoice already uploaded")]
			ok, response = efris_api.make_post("T109", {"x": 1}, self.company)
		self.assertFalse(ok)
		self.assertEqual(response, "Invoice already uploaded")
		self.assertEqual(response.return_code, "2253")
		self.assertTrue(efris_api.is_already_uploaded(response))

	def test_offline_data_source_is_106(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			run_queued(ura, only=inv)
		basic = ura.calls_for("T109")[0]["content"]["basicInformation"]
		self.assertEqual(basic["dataSource"], "106")
		self.assertEqual(basic["deviceNo"], ENABLER_DEVICE)

	def test_test_connection_sends_t101_via_enabler(self):
		user = make_user("efris-accounts-mgr@example.com", "Acc", "Accounts Manager")
		with fake_http() as http, no_private_key(), AsUser(user):
			result = e_invoicing_settings.test_connection(self.company)
		self.assertEqual(result, {"ok": True, "mode": "Offline Enabler", "message": "04/11/2026 12:00:00"})
		(call,) = http.calls
		self.assertEqual((call.url, call.code), (ENABLER_URL, "T101"))

	def test_missing_credentials_do_not_ask_for_a_key_in_offline_mode(self):
		s = frappe.get_doc("E Invoicing Settings", {"company": self.company})
		s.sandbox_private_key = None
		self.assertEqual(get_missing_credentials(s), [])
		s.enabler_url = ""
		self.assertEqual(get_missing_credentials(s), ["Enabler URL"])


class TestOnlineModeUnchanged(EfrisTestCase):
	def setUp(self):
		super().setUp()
		set_mode(self.company, "Online (URA)", token=None)

	def test_online_posts_encrypted_signed_envelope_to_ura_url(self):
		content = {"tin": TEST_TIN, "ninBrn": ""}
		with fake_http() as http, online_crypto():
			http.replies["T119"] = [online_reply({"taxpayer": {"tin": TEST_TIN}})]
			ok, response = efris_api.make_post("T119", content, self.company)

		self.assertTrue(ok, response)
		self.assertEqual(response, {"taxpayer": {"tin": TEST_TIN}})
		(call,) = http.calls
		url = frappe.db.get_value("E Invoicing Settings", {"company": self.company}, "sandbox_portal_url")
		self.assertEqual(call.url, url)
		env = call.envelope
		self.assertEqual(env["data"]["dataDescription"], {"codeType": "1", "encryptCode": "2"})
		self.assertEqual(env["data"]["signature"], base64.b64encode(b"fake-signature").decode())
		self.assertEqual(json.loads(decrypt_aes_ecb(AES_KEY, env["data"]["content"])), content)
		self.assertEqual(env["globalInfo"]["deviceNo"], TEST_DEVICE)
		self.assertNotIn("Authorization", call.headers)

	def test_online_never_sends_the_enabler_token(self):
		s = frappe.get_doc("E Invoicing Settings", {"company": self.company})
		s.enabler_access_token = ENABLER_TOKEN  # left over from an earlier Offline setup
		s.save(ignore_permissions=True)
		frappe.local.efris_company_settings_cache = {}
		with fake_http() as http, online_crypto():
			http.replies["T119"] = [online_reply({})]
			efris_api.make_post("T119", {"tin": TEST_TIN}, self.company)
		self.assertNotIn("Authorization", http.calls[0].headers)

	def test_online_rejection_carries_return_code(self):
		with fake_http() as http, online_crypto():
			http.replies["T109"] = [{"returnStateInfo": {"returnCode": "2253", "returnMessage": "Duplicate"}}]
			ok, response = efris_api.make_post("T109", {"x": 1}, self.company)
		self.assertFalse(ok)
		self.assertEqual((response, response.return_code), ("Duplicate", "2253"))

	def test_online_data_source_is_103(self):
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			run_queued(ura, only=inv)
		self.assertEqual(ura.calls_for("T109")[0]["content"]["basicInformation"]["dataSource"], "103")

	def test_test_connection_sends_plain_t101_to_ura_without_key(self):
		with fake_http() as http, no_private_key():
			result = e_invoicing_settings.test_connection(self.company)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["mode"], "Online (URA)")
		self.assertEqual(http.calls[0].code, "T101")
		self.assertIn("efristest.ura.go.ug", http.calls[0].url)


class TestAlreadyUploadedRecovery(EfrisTestCase):
	"""Return code 2253: look the invoice up by its seller reference (T106), store URA's FDN
	(T108) and never send the invoice again."""

	def _ura_record(self, inv, fdn):
		return {
			"referenceNo": inv.efris_seller_reference_no,
			"invoiceNo": fdn,
			"grossAmount": str(inv.grand_total),
			"deviceNo": ENABLER_DEVICE,
			"issuedDate": kampala_now().strftime("%d/%m/%Y %H:%M:%S"),
		}

	def _assert_recovered(self, inv, fdn, http):
		inv = reload(inv)
		self.assertEqual(inv.efris_irn, fdn)
		self.assertEqual(inv.efris_status, "Submitted")
		self.assertEqual(len(http.calls_for("T109")), 1, "the invoice is never sent twice")
		einv = frappe.get_doc("E Invoice", inv.name)
		self.assertEqual(einv.docstatus, 1)
		self.assertEqual(einv.antifake_code, f"AF{fdn[-8:]}")
		self.assertTrue(einv.efris_qr_code.endswith(fdn))
		self.assertEqual(inv.efris_data_source, "106:Offline Mode Enabler")

	def test_offline_2253_stores_existing_fdn_and_does_not_resend(self):
		set_mode(self.company, "Offline Enabler")
		fdn = "3240000000999"
		with real_make_post_queue() as http, no_private_key():
			inv = make_pos_invoice(self.ctx)
			# message deliberately unlike URA's usual wording: the code decides, not the text
			http.replies["T109"] = [plain_reply(code="2253", message="Already uploaded")]
			http.replies["T106"] = [
				plain_reply({"page": {"pageCount": 1}, "records": [self._ura_record(reload(inv), fdn)]})
			]
			http.replies["T108"] = [plain_reply(ura_invoice(fdn), gzipped=True)]
			result = efris_queue.process_efris_submission(inv.doctype, inv.name)

		self.assertEqual(result["outcome"], "submitted", result)
		self.assertEqual(
			http.calls_for("T106")[0].content["referenceNo"], reload(inv).efris_seller_reference_no
		)
		self.assertEqual(http.calls_for("T108")[0].content, {"invoiceNo": fdn})
		self._assert_recovered(inv, fdn, http)

	def test_offline_retry_after_timeout_adopts_fdn_instead_of_resending(self):
		"""The enabler fiscalised the invoice but the answer was lost: the queue's retry finds it."""
		set_mode(self.company, "Offline Enabler")
		fdn = "3240000000998"
		with real_make_post_queue() as http, no_private_key():
			inv = make_pos_invoice(self.ctx)
			http.replies["T109"] = [requests.exceptions.Timeout("read timed out")]
			first = efris_queue.process_efris_submission(inv.doctype, inv.name)
			self.assertEqual(first["outcome"], "failed")
			http.replies["T106"] = [
				plain_reply({"page": {"pageCount": 1}, "records": [self._ura_record(reload(inv), fdn)]})
			]
			http.replies["T108"] = [plain_reply(ura_invoice(fdn))]
			second = efris_queue.process_efris_submission(inv.doctype, inv.name)

		self.assertEqual(second["outcome"], "submitted", second)
		self._assert_recovered(inv, fdn, http)

	def test_online_2253_code_triggers_recovery(self):
		set_mode(self.company, "Online (URA)")
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			fdn = ura.next_fdn()
			ura.responses["T109"] = [(False, EfrisRejection("Already uploaded", "2253"))]
			ura.responses["T106"] = [
				(
					True,
					{
						"page": {"pageCount": 1},
						"records": [dict(self._ura_record(reload(inv), fdn), deviceNo=TEST_DEVICE)],
					},
				)
			]
			ura.responses["T108"] = [(True, FakeURA().invoice_response(fdn))]
			(result,) = run_queued(ura, only=inv)
		self.assertEqual(result["outcome"], "submitted", result)
		self.assertEqual(reload(inv).efris_irn, fdn)
		self.assertEqual(len(ura.calls_for("T109")), 1)

	def test_other_return_codes_do_not_trigger_lookup(self):
		set_mode(self.company, "Online (URA)")
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ura.responses["T109"] = [(False, EfrisRejection("Goods code not found", "2179"))]
			(result,) = run_queued(ura, only=inv)
		self.assertEqual(result["outcome"], "failed")
		self.assertEqual(ura.calls_for("T106"), [])


class TestSettingsAndPermissions(EfrisTestCase):
	def test_existing_settings_default_to_online(self):
		self.assertEqual(
			frappe.get_meta("E Invoicing Settings").get_field("connection_mode").default, "Online (URA)"
		)
		s = ensure_settings(self.company)
		self.assertFalse(e_invoicing_settings.is_offline_enabler(s))

	def test_offline_mode_requires_enabler_url(self):
		s = ensure_settings(self.company)
		s.connection_mode = "Offline Enabler"
		s.enabler_url = ""
		s.flags.ignore_mandatory = True
		self.assertRaises(frappe.ValidationError, s.save, ignore_permissions=True)

	def test_access_token_requires_https(self):
		s = ensure_settings(self.company)
		s.update({"connection_mode": "Offline Enabler", "enabler_url": ENABLER_URL})
		s.enabler_access_token = ENABLER_TOKEN
		s.flags.ignore_mandatory = True
		self.assertRaises(frappe.ValidationError, s.save, ignore_permissions=True)

	def test_clearing_token_while_switching_to_http_is_allowed(self):
		"""Regression: the https check read the stored token, so removing it in the same save
		as moving to an http URL was refused."""
		set_mode(self.company, "Offline Enabler", url=ENABLER_HTTPS_URL, token=ENABLER_TOKEN)
		s = set_mode(self.company, "Offline Enabler", url=ENABLER_URL, token=None)
		self.assertFalse(s.get_password("enabler_access_token", raise_exception=False))

	def test_test_connection_refuses_users_without_role(self):
		set_mode(self.company, "Offline Enabler")
		user = make_user("efris-clerk@example.com", "Clerk", "Sales User", "Accounts User")
		with fake_http() as http, AsUser(user):
			self.assertRaises(frappe.PermissionError, e_invoicing_settings.test_connection, self.company)
		self.assertEqual(http.calls, [], "nothing is sent before the role check")


class TestOldAppBugsAvoided(EfrisTestCase):
	"""ura_efris (2024) bugs, one regression each, through our transport."""

	def setUp(self):
		super().setUp()
		set_mode(self.company, "Offline Enabler")

	def _send(self, reply=None, code="T119"):
		with fake_http() as http, no_private_key():
			if reply is not None:
				http.replies[code] = [reply]
			result = efris_api.make_post(code, {"tin": TEST_TIN}, self.company)
		return result, http

	def test_old_app_global_info_key(self):
		"""Old app set data["global_info"]; the enabler reads globalInfo."""
		_result, http = self._send()
		self.assertIn("globalInfo", http.calls[0].envelope)
		self.assertNotIn("global_info", http.calls[0].envelope)

	def test_old_app_int_return_code(self):
		"""Old app did int(returnCode) == 00: crashed on non-numeric/empty codes."""
		for code in ("", "ERR01", None):
			(ok, response), _http = self._send(
				{"returnStateInfo": {"returnCode": code, "returnMessage": "Bad"}}
			)
			self.assertFalse(ok, code)
			self.assertEqual(response, "Bad")

	def test_old_app_hardcoded_data_exchange_id(self):
		with fake_http() as http, no_private_key():
			efris_api.make_post("T119", {}, self.company)
			efris_api.make_post("T119", {}, self.company)
		ids = {c.envelope["globalInfo"]["dataExchangeId"] for c in http.calls}
		self.assertEqual(len(ids), 2)
		self.assertNotIn("9230489223014123", ids)

	def test_old_app_request_time_in_server_timezone(self):
		_result, http = self._send()
		sent = datetime.strptime(http.calls[0].envelope["globalInfo"]["requestTime"], "%Y-%m-%d %H:%M:%S")
		self.assertLess(abs(sent - kampala_now().replace(tzinfo=None)), timedelta(minutes=2))

	def test_old_app_hardcoded_tin_and_device(self):
		_result, http = self._send()
		info = http.calls[0].envelope["globalInfo"]
		self.assertEqual((info["tin"], info["deviceNo"]), (TEST_TIN, ENABLER_DEVICE))
		defaults = request_utils.fetch_data()["globalInfo"]
		self.assertEqual((defaults["tin"], defaults["deviceNo"]), ("", ""))

	def test_old_app_no_timeout(self):
		_result, http = self._send()
		self.assertEqual(http.calls[0].timeout, request_utils.EFRIS_REQUEST_TIMEOUT)

	def test_old_app_no_http_status_check(self):
		(ok, response), _http = self._send(Resp("<html>Bad Gateway</html>", status=502))
		self.assertFalse(ok)
		self.assertIn("502", response)

	def test_old_app_unguarded_response_json(self):
		(ok, _response), _http = self._send(Resp("service is running."))
		self.assertFalse(ok)

	def test_old_app_transport_error_is_a_failure_not_a_crash(self):
		(ok, _response), _http = self._send(requests.exceptions.ConnectionError("enabler box is off"))
		self.assertFalse(ok)

	def test_old_app_invoice_industry_code_106(self):
		"""Old app sent invoiceIndustryCode "106" (an industry code, not the data source)."""
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			run_queued(ura, only=inv)
		basic = ura.calls_for("T109")[0]["content"]["basicInformation"]
		self.assertEqual(basic["dataSource"], "106")
		self.assertNotEqual(basic["invoiceIndustryCode"], "106")

	def test_old_app_2253_parsed_from_message_parentheses(self):
		"""Old app took the 3rd "(...)" of the 2253 message as the reference; we look up the seller
		reference we stored. A message without parentheses must still lead to the lookup."""
		with fake_ura() as ura:
			inv = make_pos_invoice(self.ctx)
			ura.responses["T109"] = [(False, EfrisRejection("Already uploaded", "2253"))]
			run_queued(ura, only=inv)
		(lookup,) = ura.calls_for("T106")
		self.assertEqual(lookup["content"]["referenceNo"], reload(inv).efris_seller_reference_no)
		self.assertEqual(lookup["content"]["deviceNo"], ENABLER_DEVICE)
