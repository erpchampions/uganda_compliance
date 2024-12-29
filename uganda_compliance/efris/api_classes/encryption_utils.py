import frappe
import base64
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from .request_utils import fetch_data, guidv4, post_req
from cryptography.hazmat.primitives import hashes
import os
import json
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_mode_decrypted_password


def encrypt_aes_ecb(data, key):
    padding_length = 16 - (len(data) % 16)
    padding = bytes([padding_length] * padding_length)
    padded_data = data + padding.decode()

    cipher = AES.new(key, AES.MODE_ECB)
    ct_bytes = cipher.encrypt(padded_data.encode("utf-8"))
    ct = base64.b64encode(ct_bytes).decode("utf-8")
    return ct

def decrypt_aes_ecb(aeskey, ciphertext):
    ciphertext = base64.b64decode(ciphertext)
    cipher = AES.new(aeskey, AES.MODE_ECB)
    plaintext_with_padding = cipher.decrypt(ciphertext).decode()
    padding_length = ord(plaintext_with_padding[-1])
    plaintext = plaintext_with_padding[:-padding_length]
    return plaintext

def get_AES_key(tin, device_no, private_key, sandbox_mode):
    try:
        data = fetch_data()
        efris_log_info("Data fetched successfully - inside get_AES_key")

        brn = "" # TODO: add BRN to E Company details on E Invoice Settings
        dataExchangeId = guidv4()
        
        data["globalInfo"]["interfaceCode"] = "T104"
        data["globalInfo"]["dataExchangeId"] = dataExchangeId
        data["globalInfo"]["deviceNo"] = device_no
        data["globalInfo"]["tin"] = tin
        data["globalInfo"]["brn"] = brn

        #data_json = json.dumps(data).replace("'", '"').replace("\n", "").replace("\r", "")
        data_json = json.dumps(data, separators=(',', ':'))  # Minimize JSON size
        
        efris_log_info("Request data converted to JSON successfully")

        resp = post_req(data_json, sandbox_mode)
        efris_log_info("POST request to fetch AES key successful")

        jsonresp = json.loads(resp)
        efris_log_info("Response JSON parsed successfully")

        b64content = jsonresp["data"]["content"]
        content = json.loads(base64.b64decode(b64content).decode("utf-8"))
        efris_log_info("Content extracted from response")

        b64passwordDes = content["passowrdDes"]
        passwordDes = base64.b64decode(b64passwordDes)
        efris_log_info("PasswordDes decoded successfully")


        # Convert the private key to a PEM format byte string for RSA import
        pkey_str = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )

        efris_log_info("pkey_str converted...")

        # Decrypt AES key using the private key
        cipher = PKCS1_v1_5.new(RSA.import_key(pkey_str))
        aesKey = cipher.decrypt(passwordDes, None)

        efris_log_info("AES key decrypted successfully")
        return base64.b64decode(aesKey)

    except Exception as e:
        efris_log_error("An error occurred in get_AES_key(): " + str(e))
        return None


def get_private_key(key_file_path, e_settings):
    try:
        
        key_file_path = frappe.get_site_path(key_file_path.lstrip('/'))  # Ensure correct path construction
        
        if not os.path.exists(key_file_path):
            efris_log_error(f"Key file does not exist at provided key_file_path")
            return None

        with open(key_file_path, "rb") as f:
            pfx_data = f.read()            


        private_key_password  = get_mode_decrypted_password(e_settings)
        password_bytes = private_key_password.encode('utf-8') if private_key_password else b""

        pfx = pkcs12.load_key_and_certificates(pfx_data, password_bytes, default_backend())
        
        private_key = pfx[0]  # The private key is the first element

        if private_key is None:
            efris_log_info('Private key extraction failed: private_key is None')
            return None
        
        efris_log_info("get_private_key()...done")
        return private_key
    except Exception as e:
        efris_log_info(f'Error extracting private key: {e}')
        return None

def sign_data(private_key, data):
    try:
        # Use the private key to sign the data
        signature = private_key.sign(
            data,
            asym_padding.PKCS1v15(),
            hashes.SHA1()
        )

        efris_log_info("Data signed successfully")
        return signature
    except Exception as e:
        efris_log_error(f'Error signing data: {e}')
        return None
