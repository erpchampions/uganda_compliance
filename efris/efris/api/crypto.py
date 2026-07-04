"""Encryption helpers for the EFRIS API.

EFRIS wraps every request payload in an encrypted envelope:

* the inner JSON payload is AES-256-ECB encrypted (PKCS#7 padded) and
  BASE64-encoded into ``data.content``;
* ``data.content`` is then RSA-SHA1 signed into ``data.signature``.

The AES key is fetched fresh per call via interface T104: URA returns it
RSA-PKCS#1-v1.5 encrypted with the taxpayer's public key inside the
``passowrdDes`` field, base64-encoded once more inside the ciphertext.

The RSA private key is the taxpayer's .p12 keystore issued by URA.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import frappe
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.serialization import pkcs12


def encrypt_aes_ecb(plaintext: str, aes_key: bytes) -> str:
	"""AES-256-ECB encrypt ``plaintext`` (PKCS#7 padded) and return BASE64."""
	pad_len = AES.block_size - (len(plaintext) % AES.block_size)
	padded = plaintext + chr(pad_len) * pad_len
	cipher = AES.new(aes_key, AES.MODE_ECB)
	ct = cipher.encrypt(padded.encode("utf-8"))
	return base64.b64encode(ct).decode("utf-8")


def decrypt_aes_ecb(aes_key: bytes, ciphertext_b64: str) -> str:
	"""Decrypt a BASE64 AES-256-ECB ciphertext and return the plaintext string."""
	ciphertext = base64.b64decode(ciphertext_b64)
	cipher = AES.new(aes_key, AES.MODE_ECB)
	padded = cipher.decrypt(ciphertext).decode("utf-8")
	pad_len = ord(padded[-1])
	return padded[:-pad_len]


def load_private_key(file_url: str, password: str | None):
	"""Load the taxpayer's RSA private key from the attached .p12 file.

	``file_url`` is the value of EFRIS Settings ``private_key`` (a Frappe File
	URL). Returns a ``cryptography`` RSAPrivateKey suitable for signing and
	for re-export to a PEM form that ``Crypto.PublicKey.RSA`` can import.
	"""
	if not file_url:
		frappe.throw("EFRIS private key file is not attached in EFRIS Settings.")

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	pfx_data = file_doc.get_content()
	if isinstance(pfx_data, str):
		pfx_data = pfx_data.encode("latin-1")

	pw_bytes = password.encode("utf-8") if password else None
	key, _cert, _extra = pkcs12.load_key_and_certificates(pfx_data, pw_bytes, default_backend())
	if key is None:
		frappe.throw("EFRIS private key extraction failed — check the file and its password.")
	return key


def sign_data(private_key, data: bytes) -> bytes:
	"""RSA-SHA1 sign ``data`` with the taxpayer private key (PKCS#1 v1.5)."""
	return private_key.sign(data, asym_padding.PKCS1v15(), hashes.SHA1())


@dataclass(frozen=True)
class AESKeyRequest:
	"""Inputs needed to bootstrap an AES key via the T104 interface.

	All fields are derived from an ``EFRISClient``; bundling them keeps the
	``fetch_aes_key`` signature flat instead of threading seven positional
	arguments through every call site.
	"""

	envelope_builder: Callable[[], dict]
	private_key: Any
	server_url: str
	tin: str
	device_no: str
	brn: str
	timeout: int


def fetch_aes_key(req: AESKeyRequest) -> bytes:
	"""Run T104 inline and return the raw AES key bytes.

	URA's flow (per the reference EFRIS integration):
	  1. POST a plaintext T104 envelope.
	  2. BASE64-decode ``data.content`` to get the inner JSON.
	  3. BASE64-decode ``passowrdDes`` to get the RSA ciphertext.
	  4. RSA-PKCS#1-v1.5 decrypt with the taxpayer private key — yields the
	     AES key BASE64-encoded as ASCII.
	  5. BASE64-decode that to get the raw 16/24/32-byte AES key.
	"""
	import json

	import requests

	envelope = req.envelope_builder()
	envelope["globalInfo"]["interfaceCode"] = "T104"
	envelope["globalInfo"]["tin"] = req.tin
	envelope["globalInfo"]["deviceNo"] = req.device_no
	envelope["globalInfo"]["brn"] = req.brn or ""

	response = requests.post(
		req.server_url,
		data=json.dumps(envelope, separators=(",", ":")),
		headers={"Content-Type": "application/json"},
		timeout=req.timeout,
	)
	response.raise_for_status()
	try:
		body = response.json()
	except ValueError:
		# URA returned a 2xx with a non-JSON body — typically an HTML error /
		# maintenance page or an empty response from a misconfigured Server URL.
		# Surface the status and a snippet so the cause is obvious instead of a
		# bare "Expecting value: line 1 column 1 (char 0)".
		raw = response.text or ""
		content_type = response.headers.get("Content-Type", "")
		frappe.log_error(
			message=(
				f"URL: {req.server_url}\n"
				f"HTTP {response.status_code}\n"
				f"Content-Type: {content_type}\n\n"
				f"--- body ---\n{raw[:32000]}"
			),
			title="EFRIS T104 non-JSON response",
		)
		intro = frappe._(
			"EFRIS T104 (AES key) returned a non-JSON response (HTTP {0}). "
			"Check the EFRIS Server URL is correct and the service is reachable."
		).format(response.status_code)
		if "html" in content_type.lower() and raw.strip():
			# URA (or an upstream proxy) returned an HTML error/maintenance page.
			# Render it inside a sandboxed iframe so the actual page is visible
			# without letting its scripts run in the desk session.
			srcdoc = frappe.utils.escape_html(raw)
			iframe = (
				f'<iframe sandbox srcdoc="{srcdoc}" '
				'style="width:100%;height:50vh;border:1px solid var(--border-color);"></iframe>'
			)
			frappe.throw(
				f"<p>{intro}</p>{iframe}",
				title=frappe._("EFRIS Server Error"),
				wide=True,
				allow_dangerous_html=True,
			)
		snippet = raw.strip()[:500] or "(empty response body)"
		frappe.throw(f"{intro}\n\n{snippet}", title=frappe._("EFRIS Server Error"))

	state = body.get("returnStateInfo", {})
	code = state.get("returnCode", "")
	if code not in ("", "00"):
		from efris.efris.api.client import EFRISError

		raise EFRISError(code, state.get("returnMessage", ""))

	content_b64 = body["data"]["content"]
	content = json.loads(base64.b64decode(content_b64).decode("utf-8"))
	password_des = base64.b64decode(content["passowrdDes"])

	pkey_pem = req.private_key.private_bytes(
		encoding=serialization.Encoding.PEM,
		format=serialization.PrivateFormat.PKCS8,
		encryption_algorithm=serialization.NoEncryption(),
	)
	cipher = PKCS1_v1_5.new(RSA.import_key(pkey_pem))
	aes_key_b64 = cipher.decrypt(password_des, None)
	if not aes_key_b64:
		frappe.throw("EFRIS T104 RSA decryption failed — the .p12 does not match URA's registered public key.")

	return base64.b64decode(aes_key_b64)
