import frappe
import json
import base64
import requests
from datetime import datetime
from .encryption_utils import encrypt_aes_ecb, decrypt_aes_ecb, get_AES_key, get_private_key, sign_data
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from .request_utils import fetch_data, post_req
from uganda_compliance.efris.doctype.e_invoice_request_log.e_invoice_request_log import log_request_to_efris
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings, get_mode_private_key_path



##############
def make_post(interfaceCode, content, company_name, reference_doc_type=None, reference_document=None):
    efris_log_info("make_post called...")
    try:
        e_settings = get_e_company_settings(company_name)
        tin, device_no, private_key_path, sandbox_mode = (
            e_settings.tin,
            e_settings.device_no,
            get_mode_private_key_path(e_settings),
            e_settings.sandbox_mode
        )
        brn = ""  # TODO: Add BRN to E Company details under E Invoice Settings
        
        data = fetch_data()
        efris_log_info("Data fetched successfully")

        try:
            private_key = get_private_key(private_key_path, e_settings)
        except Exception as e:
            return False, f"Failed to retrieve private key: {e}"

        efris_log_info("Private key fetched successfully")

        aes_key = get_AES_key(tin, device_no, private_key, sandbox_mode)
        efris_log_info("AES key fetched successfully")

        json_content = json.dumps(content)
        efris_log_info("Content converted to JSON successfully: " + json_content)

        isAESEncrypted = encrypt_aes_ecb(json_content, aes_key)
        efris_log_info("Content encrypted with AES successfully")

        isAESEncrypted = base64.b64decode(isAESEncrypted)
        newEncrypteddata = base64.b64encode(isAESEncrypted).decode("utf-8")

        if isAESEncrypted:
            efris_log_info("AES encryption successful")
            data["globalInfo"]["deviceNo"] = device_no
            data["globalInfo"]["tin"] = tin
            data["globalInfo"]["brn"] = brn
            data["globalInfo"]["interfaceCode"] = interfaceCode
            data["data"]["content"] = base64.b64encode(isAESEncrypted).decode("utf-8")
            data["data"]["dataDescription"] = {"codeType": "1", "encryptCode": "2"}

            signature = sign_data(private_key, newEncrypteddata.encode())
            efris_log_info("Signature completed...")

            if signature:
                b4signature = base64.b64encode(signature).decode()
                data["data"]["signature"] = b4signature

        data_json = json.dumps(data).replace("'", '"').replace("\n", "").replace("\r", "")
        efris_log_info("Request data converted to JSON successfully")
        efris_log_info("Request data:\n")
        efris_log_info(data_json)
        print("===========================================================")
        print(str(data_json))
        json_resp = post_req(data_json, e_settings.sandbox_mode)

        resp = json.loads(json_resp)
        efris_log_info("Server response successfully parsed")

        errorMsg = resp["returnStateInfo"]["returnMessage"]
        efris_log_info("returnStateInfoMsg: " + errorMsg)
        if errorMsg != "SUCCESS":
            log_request_to_efris(
                request_data=content,
                request_full=data,
                response_data={"error": errorMsg},
                response_full=resp,
                reference_doc_type=reference_doc_type,
                reference_document=reference_document
            )
            return False, errorMsg

        respcontent = resp["data"]["content"]
        efris_response = decrypt_aes_ecb(aes_key, respcontent)
        efris_log_info("Response content decrypted successfully")

        resp_json = json.loads(efris_response)
        efris_log_info("Decrypted JSON Data:")
        efris_log_info(resp_json)
        log_request_to_efris(
             request_data=content,
            request_full=data,
            response_data=json.loads(efris_response),
            response_full=resp_json,
            reference_doc_type=reference_doc_type,
            reference_document=reference_document
        )
        return True, resp_json

    except Exception as e:
        efris_log_error(f"An error occurred: {e}")
        return False, str(e)
