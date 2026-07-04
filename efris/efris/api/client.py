"""EFRIS HTTP API client.

``EFRISClient`` builds the signed/encrypted envelope, posts it to the URA
EFRIS endpoint, validates the return code and decrypts the response content.

For each call (apart from the plaintext bootstrap interfaces T101/T104), a
fresh AES key is fetched inline via T104, the inner JSON payload is
AES-256-ECB encrypted with that key, the BASE64 ciphertext is RSA-SHA1 signed
with the taxpayer .p12, and the response content is decrypted with the same
AES key.

Configuration lives on the company-specific ``EFRIS Settings`` DocType.
"""

from __future__ import annotations

import base64
import json
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import frappe
import requests
from frappe import _

from efris.efris.api.crypto import (
	AESKeyRequest,
	decrypt_aes_ecb,
	encrypt_aes_ecb,
	fetch_aes_key,
	load_private_key,
	sign_data,
)

SUCCESS_CODES = {"", "00"}

# Already-submitted / duplicate codes — safe to treat as success (idempotent).
IDEMPOTENT_CODES = {"1040", "306"}

# Interfaces that send their request as plain base64 JSON (no AES, no
# signature). T101 is a health check and T104 bootstraps the AES key, so
# neither has one available at request time.
PLAINTEXT_REQUEST_INTERFACES = {"T101", "T104", "T123", "T124", "T125", "T136"}

# Plaintext-request interfaces that URA still requires to be RSA-signed.
# T101/T104 are bootstrap (no signing); the rest must carry a signature even
# though the content isn't AES-encrypted.
SIGNED_PLAINTEXT_REQUEST_INTERFACES = {"T123", "T124", "T125"}

# Interfaces whose response content is plain base64 JSON (no AES).
# T113/T114/T120 take encrypted requests but URA returns the response
# unencrypted (often a ``null`` body) — decrypting would error with
# "Data must be aligned to block boundary in ECB mode".
PLAINTEXT_RESPONSE_INTERFACES = {
	"T101", "T104", "T113", "T114", "T120", "T123", "T124", "T125", "T136",
}

# Plain-language hints for return codes that have a known, actionable cause.
RETURN_CODE_HINTS = {
	"400": "The device is not registered or activated on EFRIS. Verify Device No and TIN "
	"in EFRIS Settings, and confirm the device is activated on the URA portal.",
	"401": "Device error — the device may be deactivated. Check its status on the URA portal.",
	"402": "The device key registered with EFRIS has expired. Check the device's validity "
	"period on the URA portal.",
	"403": "Device error reported by EFRIS. Check the device status on the URA portal.",
	"99": "EFRIS reported an unknown error. Retry shortly; if it persists, contact URA.",
	"1040": "This invoice has already been uploaded to EFRIS.",
	"300": "The original invoice referenced by this credit note was not found on EFRIS.",
	"304": "EFRIS found no application for the given id. The referenceNo / application id sent likely doesn't match URA's index for this interface.",
	"306": "A credit note has already been issued for this invoice.",
	"310": "EFRIS refused to void this application — its current state does not allow voiding. Only applications still in workflow (e.g. 102 Submitted) can be voided; for an approved credit note use T114 (Cancel Application) instead.",
	"1029": "EFRIS reports insufficient stock for one or more items.",
	"2075": "The invoice amount exceeds the limit allowed by EFRIS.",
}


class EFRISError(Exception):
	"""Raised when EFRIS responds with a non-success return code."""

	def __init__(self, code: str, message: str):
		self.code = code
		self.message = message
		super().__init__(f"EFRIS Error {code}: {message}")

	@property
	def is_idempotent(self) -> bool:
		return self.code in IDEMPOTENT_CODES

	@property
	def hint(self) -> str:
		return RETURN_CODE_HINTS.get(self.code, "")


class EFRISClient:
	"""Thin transport client around the EFRIS interface protocol."""

	def __init__(self, company: str | None = None, settings=None):
		if settings is None:
			from efris.efris.doctype.efris_settings.efris_settings import get_efris_settings

			settings = get_efris_settings(company)
		self.settings = settings
		self.company = settings.company
		self.tin = settings.tin
		self.brn = settings.brn or ""
		self.username = "admin"
		self.device_no = settings.device_no
		self.device_mac = settings.device_mac or "FFFFFFFFFFFF"
		self.branch_id = settings.branch_id or ""
		self.base_url = (settings.efris_server_url or "").rstrip("/")
		self.timeout = settings.request_timeout or 30
		self._private_key = None

	# -- credentials ----------------------------------------------------

	@property
	def private_key(self):
		if self._private_key is None:
			pw = self.settings.get_password("private_key_password", raise_exception=False)
			self._private_key = load_private_key(self.settings.private_key, pw)
		return self._private_key

	# -- envelope -------------------------------------------------------

	def _build_envelope(self) -> dict:
		"""Return a fresh request envelope with a unique dataExchangeId."""
		return {
			"data": {
				"content": "",
				"signature": "",
				"dataDescription": {
					"codeType": "0",
					"encryptCode": "1",
					"zipCode": "0",
				},
			},
			"globalInfo": {
				"appId": "AP04",
				"version": "1.1.20191201",
				"dataExchangeId": uuid.uuid4().hex,
				"interfaceCode": "",
				"requestCode": "TP",
				"requestTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
				"responseCode": "TA",
				"userName": self.username,
				"deviceMAC": self.device_mac,
				"deviceNo": self.device_no,
				"tin": self.tin,
				"brn": self.brn,
				"taxpayerID": "1",
				"longitude": self.settings.longitude or "32.58",
				"latitude": self.settings.latitude or "0.31",
				"agentType": "0",
				"extendField": {
					"responseDateFormat": "dd/MM/yyyy",
					"responseTimeFormat": "dd/MM/yyyy HH:mm:ss",
				},
			},
			"returnStateInfo": {"returnCode": "", "returnMessage": ""},
		}

	def _aes_key_request(self) -> AESKeyRequest:
		"""Bundle this client's connection details for an inline T104 call."""
		return AESKeyRequest(
			envelope_builder=self._build_envelope,
			private_key=self.private_key,
			server_url=self.base_url,
			tin=self.tin,
			device_no=self.device_no,
			brn=self.brn,
			timeout=self.timeout,
		)

	# -- transport ------------------------------------------------------

	def call(
		self,
		interface_code: str,
		payload: dict | None = None,
		reference_no: str = "",
		operator: str = "",
	) -> dict:
		"""Send one EFRIS interface request and return the decrypted response body.

		Raises ``EFRISError`` on a non-success return code and
		``requests.HTTPError`` on a transport-level failure.
		"""
		if not self.base_url:
			frappe.throw(_("EFRIS server URL is not configured in EFRIS Settings."))

		payload = payload or {}
		envelope = self._build_envelope()
		envelope["globalInfo"]["interfaceCode"] = interface_code
		envelope["globalInfo"]["extendField"]["referenceNo"] = reference_no
		envelope["globalInfo"]["extendField"]["operatorName"] = operator or frappe.session.user

		aes_key: bytes | None = None
		if interface_code in PLAINTEXT_REQUEST_INTERFACES:
			# Plain request: base64-encoded JSON. T123/T124/T125 must still be
			# RSA-signed even though the content isn't AES-encrypted.
			content_b64 = (
				base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("utf-8")
				if payload
				else ""
			)
			envelope["data"]["content"] = content_b64
			if interface_code in SIGNED_PLAINTEXT_REQUEST_INTERFACES:
				envelope["data"]["signature"] = base64.b64encode(
					sign_data(self.private_key, content_b64.encode("utf-8"))
				).decode("utf-8")
				envelope["data"]["dataDescription"] = {
					"codeType": "1",
					"encryptCode": "1",
					"zipCode": "0",
				}
			else:
				envelope["data"]["dataDescription"] = {
					"codeType": "0",
					"encryptCode": "1",
					"zipCode": "0",
				}
		else:
			# Encrypted request: AES-encrypt the inner JSON with a fresh
			# per-call key from T104, then RSA-SHA1 sign the ciphertext.
			aes_key = fetch_aes_key(self._aes_key_request())
			content_b64 = encrypt_aes_ecb(json.dumps(payload, separators=(",", ":")), aes_key)
			envelope["data"]["content"] = content_b64
			envelope["data"]["signature"] = base64.b64encode(
				sign_data(self.private_key, content_b64.encode("utf-8"))
			).decode("utf-8")
			envelope["data"]["dataDescription"] = {
				"codeType": "1",
				"encryptCode": "2",
				"zipCode": "0",
			}

		response = requests.post(
			self.base_url,
			data=json.dumps(envelope, separators=(",", ":")),
			headers={"Content-Type": "application/json"},
			timeout=self.timeout,
		)
		response.raise_for_status()
		result = response.json()

		state = result.get("returnStateInfo", {})
		return_code = state.get("returnCode", "")

		data = result.get("data") or {}
		content = data.get("content") or ""

		# On a non-success return code, attempt to decode data.content anyway —
		# URA usually puts the per-entry detail there. Then raise with both
		# the global message and the per-entry text included.
		if return_code not in SUCCESS_CODES:
			detail = ""
			if content:
				try:
					decoded_payload = self._decode_content(
						content, interface_code, aes_key
					)
					detail = json.dumps(decoded_payload, indent=2)[:4000]
				except Exception:
					detail = ""
			try:
				frappe.log_error(
					message=(json.dumps(result, indent=2)[:16000] + "\n\n--- decoded content ---\n" + detail)[:32000],
					title=f"EFRIS {interface_code} failed (code {return_code or '?'})",
				)
			except Exception:
				pass
			message = state.get("returnMessage", "")
			if detail:
				message = f"{message}\n{detail}"
			raise EFRISError(return_code, message)

		if not content:
			return result

		return self._decode_content(content, interface_code, aes_key)

	def _decode_content(
		self, content: str, interface_code: str, aes_key: bytes | None
	) -> Any:
		"""Decode the ``data.content`` blob URA returns — plaintext or AES."""
		# Normalise URL-safe base64 — some URA interfaces use '-'/'_' instead
		# of '+'/'/'. base64.b64decode silently drops those, breaking the
		# decode.
		content = content.replace("-", "+").replace("_", "/")
		decoded = base64.b64decode(content)

		# URA may gzip the content before base64-encoding (T115 and likely
		# others do this regardless of zipCode). The wire order is
		# AES-encrypt -> gzip -> base64, so we must gunzip *before* AES.
		gzipped = decoded[:2] == b"\x1f\x8b"
		if gzipped:
			import gzip

			decoded = gzip.decompress(decoded)

		if interface_code in PLAINTEXT_RESPONSE_INTERFACES:
			return json.loads(decoded.decode("utf-8"))

		# AES-encrypted response. For T103 (plain request, encrypted
		# response) we still need an AES key.
		if aes_key is None:
			aes_key = fetch_aes_key(self._aes_key_request())
		ciphertext_b64 = base64.b64encode(decoded).decode("ascii") if gzipped else content
		return json.loads(decrypt_aes_ecb(aes_key, ciphertext_b64))


def throw_efris_error(exc: Exception, title: str | None = None) -> None:
	"""Convert an EFRIS / transport exception into a clean user-facing error."""
	if isinstance(exc, EFRISError):
		lines = [_("EFRIS Error {0}").format(exc.code)]
		if exc.message:
			lines.append(frappe.utils.escape_html(exc.message))
		if exc.hint:
			lines.append(_(exc.hint))
		message = "<br><br>".join(lines)
	elif isinstance(exc, requests.exceptions.Timeout):
		message = _("EFRIS did not respond in time. Check your connection and try again.")
	elif isinstance(exc, requests.exceptions.ConnectionError):
		message = _(
			"Could not reach the EFRIS server. Check the EFRIS Server URL and your "
			"internet connection."
		)
	elif isinstance(exc, requests.exceptions.RequestException):
		message = _("EFRIS request failed: {0}").format(str(exc))
	else:
		raise exc

	frappe.log_error(message=frappe.get_traceback(with_context=True), title="EFRIS Request Failed")
	frappe.throw(message, title=title or _("EFRIS Error"))


@contextmanager
def efris_errors(title: str | None = None):
	"""Wrap a block of EFRIS calls so failures surface as clean user errors."""
	try:
		yield
	except (EFRISError, requests.exceptions.RequestException) as e:
		throw_efris_error(e, title)
