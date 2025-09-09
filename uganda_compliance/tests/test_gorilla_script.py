import random
import uuid
import json
import base64
import requests
from datetime import datetime
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.backends import default_backend
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives import hashes
from Crypto.Hash import SHA1
import os
import logging
import pytz
from collections import defaultdict

logging.basicConfig(filename='logs/efris_logfile.log', level=logging.DEBUG)

#TIN: 1008352899
#Device: 1008352899_01

def main():
    logging.info("Starting...")
    # resp_content = make_post("T130", goodsUpload)
    # resp_content = make_post("T130", serviceUpload)
    # resp_content = make_post("T109", invoiceUpload_Goods)
    # resp_content = make_post("T130", invoiceUpload_Goods_NonExcise)
    #resp_content = make_post("T131", Goods_stock_adjustment_T131)
    resp_content = make_post("T110", credit_note_applicaton_T110)
    logging.info(f"Main response: {resp_content}")

random_integer = random.randint(1, 1000000)

e_jsonUpload = []

goodsUpload = [
    {
        "operationType": "101",
        "goodsName": "Raw Coffee Seeds-TEST3",
        "goodsCode": "Raw Coffee Seeds-TEST3",
        "measureUnit": "KGM",
        "unitPrice": "35",
        "currency": "102",
        "commodityCategoryId": "10152008",
        "haveExciseTax": "102",
        "stockPrewarning": "0",
        "havePieceUnit": "102",
        "goodsOtherUnits": [],
    }
]

serviceUpload = [
    {
        "operationType": "101",
        "goodsName": "Professional Fees 3",
        "goodsCode": "Professional Fees 3",
        "measureUnit": "101",
        "unitPrice": "1500000",
        "currency": "101",
        "commodityCategoryId": "80101512",
        "haveExciseTax": "102",
        "stockPrewarning": "0",
        "havePieceUnit": "102",
        "goodsOtherUnits": [],
    }
]
invoiceUpload_Goods = {
    
 "agentEntity": {},
 "airlineGoodsDetails": [
  {}
 ],
 "basicInformation": {
  "antifakeCode": "",
  "currency": "UGX",
  "dataSource": "103",
  "deviceNo": "1008352899_01",
  "invoiceIndustryCode": "102",
  "invoiceKind": "1",
  "invoiceNo": "",
  "invoiceType": "1",
  "isBatch": "0",
  "issuedDate": "2025-09-06 16:36:17.635807",
  "operator": "Administrator",
  "oriInvoiceId": ""
 },
 "buyerDetails": {
  "buyerBusinessName": "walk In",
  "buyerCitizenship": "",
  "buyerLegalName": "walk In",
  "buyerNinBrn": "",
  "buyerPassportNum": "",
  "buyerReferenceNo": "",
  "buyerSector": "",
  "buyerTin": "",
  "buyerType": 1,
  "deliveryTermsCode": "CFR",
  "nonResidentFlag": "1"
 },
 "buyerExtend": {
  "cellVillage": "",
  "district": "",
  "divisionSubcounty": "",
  "effectiveRegistrationDate": "",
  "meterStatus": "",
  "municipalityCounty": "",
  "propertyType": "",
  "town": ""
 },
 "edcDetails": {},
 "extend": {},
 "goodsDetails": [
  {
   "categoryId": "",
   "categoryName": "",
   "deemedFlag": "2",
   "discountFlag": "2",
   "discountTaxRate": "",
   "discountTotal": "",
   "exciseFlag": "2",
   "goodsCategoryId": "50201706",
   "goodsCategoryName": "Coffee",
   "item": "Multi-Tax  category item4",
   "itemCode": "Multi-Tax  category item4",
   "orderNumber": "0",
   "pieceMeasureUnit": "GRM",
   "pieceQty": 1000.0,
   "qty": "1.0",
   "tax": "0.0",
   "taxRate": "0",
   "total": "5000.0",
   "totalWeight": 1.0,
   "unitOfMeasure": "103",
   "unitPrice": "5000.0",
   "vatApplicableFlag": "1"
  }
 ],
 "importServicesSeller": {},
 "payWay": [
  {
   "orderNumber": "a",
   "paymentAmount": "5000.0",
   "paymentMode": "101"
  }
 ],
 "sellerDetails": {
  "branchCode": "",
  "branchId": "",
  "branchName": "Test",
  "businessName": "Gorilla Conservation Coffee",
  "emailAddress": "accounts@gccoffee.org",
  "isCheckReferenceNo": "0",
  "legalName": "Gorilla Conservation Coffee",
  "linePhone": "",
  "mobilePhone": "2560778497936",
  "ninBrn": "/209986",
  "referenceNo": "EFRIS-INV-2025-00158",
  "tin": "1008352899"
 },
 "summary": {
  "grossAmount": 5000.0,
  "itemCount": "1",
  "modeCode": "1",
  "netAmount": "5000.0",
  "qrCode": "",
  "remarks": "",
  "taxAmount": 0.0
 },
 "taxDetails": [
  {
   "exciseCurrency": "",
   "exciseUnit": "",
   "grossAmount": 5000.0,
   "netAmount": "5000.0",
   "taxAmount": "0.0",
   "taxCategoryCode": "02",
   "taxRate": "0",
   "taxRateName": ""
  }
 ]

#  "agentEntity": {},
#  "airlineGoodsDetails": [
#   {}
#  ],
#  "basicInformation": {
#   "antifakeCode": "",
#   "currency": "UGX",
#   "dataSource": "103",
#   "deviceNo": "1008352899_01",
#   "invoiceIndustryCode": "102",
#   "invoiceKind": "1",
#   "invoiceNo": "",
#   "invoiceType": "1",
#   "isBatch": "0",
#   "issuedDate": "2025-09-03 12:13:37.455392",
#   "operator": "Administrator",
#   "oriInvoiceId": ""
#  },
#  "buyerDetails": {
#   "buyerBusinessName": "LONG XIANG TECHNOLOGY UGANDA LIMITED",
#   "buyerCitizenship": "",
#   "buyerLegalName": "LONG XIANG TECHNOLOGY UGANDA LIMITED",
#   "buyerNinBrn": "/80034832452725",
#   "buyerPassportNum": "",
#   "buyerReferenceNo": "",
#   "buyerSector": "",
#   "buyerTin": "1035096976",
#   "buyerType": 0,
#   "nonResidentFlag": 1,
#   "deliveryTermsCode": "CFR",
#  },
#  "buyerExtend": {
#   "cellVillage": "",
#   "district": "",
#   "divisionSubcounty": "",
#   "effectiveRegistrationDate": "",
#   "meterStatus": "",
#   "municipalityCounty": "",
#   "propertyType": "",
#   "town": ""
#  },
#  "edcDetails": {},
#  "extend": {},
#  "goodsDetails": [
#   {
#    "categoryId": "",
#    "categoryName": "",
#    "deemedFlag": "2",
#    "discountFlag": "2",
#    "discountTaxRate": "",
#    "discountTotal": "",
#    "exciseFlag": "2",
#    "goodsCategoryId": "50201706",
#    "goodsCategoryName": "Coffee",
#    "item": "Raw Coffee Seeds",
#    "itemCode": "Raw Coffee Seeds-Test",
#    "orderNumber": "0",
#    "qty": "25.0",
#    "tax": "0.0",
#    "taxRate": "0",
#    "total": "1200000.0",
#    "unitOfMeasure": "PA",
#    "unitPrice": "48000",
#    "vatApplicableFlag": "1",
#    "totalWeight": "25",
#    "pieceQty": "25000",
#    "pieceMeasureUnit":"GRM"
#   }
#  ],
#  "importServicesSeller": {},
#  "payWay": [
#   {
#    "orderNumber": "a",
#    "paymentAmount": "1200000.0",
#    "paymentMode": "101"
#   }
#  ],
#  "sellerDetails": {
#   "branchCode": "",
#   "branchId": "",
#   "branchName": "Test",
#   "businessName": "GORILLA CONSERVATION COFFEE LIMITED",
#   "emailAddress": "support@erpchampions.com",
#   "isCheckReferenceNo": "0",
#   "legalName": "GORILLA CONSERVATION COFFEE LIMITED",
#   "linePhone": "",
#   "mobilePhone": "",
#   "ninBrn": "/209986",
#   "referenceNo": "EFRIS-INV-2025-0136",
#   "tin": "1008352899"
#  },
#  "summary": {
#   "grossAmount": "1200000.0",
#   "itemCount": "1",
#   "modeCode": "1",
#   "netAmount": "1200000.0",
#   "qrCode": "",
#   "remarks": "",
#   "taxAmount": "0.0"
#  },
#  "taxDetails": [
#   {
#    "exciseCurrency": "",
#    "exciseUnit": "",
#    "grossAmount": "1200000.0",
#    "netAmount": "1200000.0",
#    "taxAmount": "0.0",
#    "taxCategoryCode": "02",
#    "taxRate": "0.0",
#    "taxRateName": ""
#   }
#  ]
}           



credit_note_applicaton_T110 = {  
 "applicationTime": "2025-09-08 08:49:59",
 "basicInformation": {
  "invoiceIndustryCode": "102",
  "invoiceKind": "1",
  "operator": "Administrator"
 },
 "buyerDetails": {
  "buyerAddress": "",
  "buyerBusinessName": "",
  "buyerCitizenship": "",
  "buyerEmail": "",
  "buyerLegalName": "",
  "buyerLinePhone": "",
  "buyerMobilePhone": "",
  "buyerNinBrn": "",
  "buyerPassportNum": "",
  "buyerPlaceOfBusi": "",
  "buyerReferenceNo": "",
  "buyerSector": "1",
  "buyerTin": "",
  "buyerType": "1",
  "deliveryTermsCode": "CFR",
  "nonResidentFlag": "1"
 },
 "contactEmail": "",
 "contactMobileNum": "",
 "contactName": "",
 "currency": "UGX",
 "goodsDetails": [
  {
   "categoryId": "",
   "categoryName": "",
   "deemedFlag": "2",
   "discountFlag": "2",
   "exciseCurrency": "",
   "exciseFlag": "2",
   "exciseRate": "",
   "exciseRateName": "",
   "exciseRule": "",
   "exciseTax": "",
   "exciseUnit": "",
   "goodsCategoryId": "50201706",
   "goodsCategoryName": "",
   "item": "Multi-Tax  category item4",
   "itemCode": "Multi-Tax  category item4",
   "orderNumber": "0",
   "pieceMeasureUnit": "GRM",
   "pieceQty": -1000.0,
   "qty": "-1.0",
   "tax": "0.0",
   "taxRate": "0",
   "total": "-5000.0",
   "totalWeight": -1.0,
   "unitOfMeasure": "103",
   "unitPrice": "5000.0",
   "vatApplicableFlag": "1"
  }
 ],
 "importServicesSeller": {
  "importAddress": "",
  "importAttachmentContent": "",
  "importAttachmentName": "",
  "importBusinessName": "",
  "importContactNumber": "",
  "importEmailAddress": "",
  "importInvoiceDate": ""
 },
 "invoiceApplyCategoryCode": "101",
 "oriInvoiceId": "133629401862367009",
 "oriInvoiceNo": "325041473287",
 "payWay": [
  {
   "orderNumber": "a",
   "paymentAmount": 5000.0,
   "paymentMode": "101"
  }
 ],
 "reason": "102:Cancellation of the purchase.",
 "reasonCode": "102",
 "remarks": "",
 "sellersReferenceNo": "EFRIS-INV-2025-0065",
 "source": "103",
 "summary": {
  "grossAmount": -5000.0,
  "itemCount": "1",
  "modeCode": "0",
  "netAmount": -5000.0,
  "qrCode": "",
  "taxAmount": 0.0
 },
 "taxDetails": [
  {
   "exciseCurrency": "",
   "exciseUnit": "",
   "grossAmount": -5000.0,
   "netAmount": -5000.0,
   "taxAmount": "0.0",
   "taxCategoryCode": "02",
   "taxRate": "0",
   "taxRateName": ""
  }
 ]

}




def efris_log_info(message):
    logging.info(message)

def efris_log_warning(message):
    logging.warning(message)

def efris_log_error(message):
    logging.error(message)

def make_post(interfaceCode, content):
    try:
        data = fetch_data()
        efris_log_info("Data fetched successfully")

        aes_key = get_AES_key()
        efris_log_info("AES key fetched successfully")

        deviceNo = "1008352899_01"
        tin = "1008352899"
        brn = ""

        json_content = json.dumps(content)
        efris_log_info("Content converted to JSON successfully: " + json_content)

        isAESEncrypted = encrypt_aes_ecb(json_content, aes_key)
        efris_log_info("Content encrypted with AES successfully")

        isAESEncrypted = base64.b64decode(isAESEncrypted)
        newEncrypteddata = base64.b64encode(isAESEncrypted).decode("utf-8")

        if isAESEncrypted:
            efris_log_info("AES encryption successful")
            data["globalInfo"]["deviceNo"] = deviceNo
            data["globalInfo"]["tin"] = tin
            data["globalInfo"]["brn"] = brn
            data["globalInfo"]["interfaceCode"] = interfaceCode
            data["data"]["content"] = base64.b64encode(isAESEncrypted).decode("utf-8")
            data["data"]["dataDescription"] = {"codeType": "1", "encryptCode": "2"}

            private_key = get_private_key()
            efris_log_info("Private key fetched successfully in make_post()")

            signature = sign_data(private_key, newEncrypteddata.encode())
            efris_log_info("signature done...")

            if signature:
                b4signature = base64.b64encode(signature).decode()
                data["data"]["signature"] = b4signature

        data_json = json.dumps(data).replace("'", '"').replace("\n", "").replace("\r", "")
        efris_log_info("Request data converted to JSON successfully")
        efris_log_info("Request data:\n")
        efris_log_info(data_json)

        json_resp = post_req(data_json)

        resp = json.loads(json_resp)
        efris_log_info("Server response successfully parsed")

        errorMsg = resp["returnStateInfo"]["returnMessage"]
        efris_log_info("returnStateInfoMsg: " + errorMsg)
        if errorMsg != "SUCCESS":
            return False, errorMsg

        respcontent = resp["data"]["content"]
        efris_response = decrypt_aes_ecb(aes_key, respcontent)
        efris_log_info("Response content decrypted successfully")
        resp_json = json.loads(efris_response)
        efris_log_info("Decrypted JSON Data:")
        efris_log_info(resp_json)
        return True, resp_json

    except Exception as e:
        efris_log_error("An error occurred: " + str(e))
        return False, str(e)

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

def to_ug_datetime(date_time):
    ug_time_zone = "Africa/Kampala"
    uganda_time = date_time.astimezone(pytz.timezone(ug_time_zone))
    uganda_time_str = uganda_time.strftime("%Y-%m-%d %H:%M:%S")
    return uganda_time_str

def get_ug_time_str():
    ug_time_zone = "Africa/Kampala"
    now = datetime.now()
    uganda_time = now.astimezone(pytz.timezone(ug_time_zone))
    uganda_time_str = uganda_time.strftime("%Y-%m-%d %H:%M:%S")
    return uganda_time_str

def fetch_data():
    now = get_ug_time_str()
    return {
        "data": {
            "content": "",
            "signature": "",
            "dataDescription": {
                "codeType": "0",
                "encryptCode": "1",
                "zipCode": "0"
            }
        },
        "globalInfo": {
            "appId": "AP04",
            "version": "1.1.20191201",
            "dataExchangeId": "9230489223014123",
            "interfaceCode": "T101",
            "requestTime": now,
            "requestCode": "TP",
            "responseCode": "TA",
            "userName": "admin",
            "deviceMAC": "FFFFFFFFFFFF",
            "deviceNo": "1008352899_01",
            "tin": "1008352899",
            "brn": "",
            "taxpayerID": "1",
            "longitude": "116.397128",
            "latitude": "39.916527",
            "extendField": {
                "responseDateFormat": "dd/MM/yyyy",
                "responseTimeFormat": "dd/MM/yyyy HH:mm:ss"
            }
        },
        "returnStateInfo": {
            "returnCode": "",
            "returnMessage": ""
        }
    }

def get_private_key_path():
    # Dynamically construct the correct path based on where the script is running
    base_dir = os.path.dirname(os.path.abspath(__file__))
    private_key_path = os.path.join(base_dir,"test_keys", "gorrilla_keys.p12")
    
    if not os.path.exists(private_key_path):
        raise FileNotFoundError(f"Private key file not found at: {private_key_path}")
    
    return private_key_path

def get_AES_key():
    try:
        data = fetch_data()
        efris_log_info("Data fetched successfully - inside get_AES_key")

        deviceNo = "1008352899_01"
        tin = "1008352899"
        brn = ""
        dataExchangeId = guidv4()

        data["globalInfo"]["interfaceCode"] = "T104"
        data["globalInfo"]["dataExchangeId"] = dataExchangeId
        data["globalInfo"]["deviceNo"] = deviceNo
        data["globalInfo"]["tin"] = tin
        data["globalInfo"]["brn"] = brn

        data_json = json.dumps(data).replace("'", '"').replace("\n", "").replace("\r", "")
        efris_log_info("Request data converted to JSON successfully")

        resp = post_req(data_json)
        efris_log_info("POST request to fetch AES key successful")

        jsonresp = json.loads(resp)
        efris_log_info("Response JSON parsed successfully")

        b64content = jsonresp["data"]["content"]
        content = json.loads(base64.b64decode(b64content).decode("utf-8"))
        efris_log_info("Content extracted from response")

        b64passwordDes = content["passowrdDes"]
        passwordDes = base64.b64decode(b64passwordDes)
        efris_log_info("PasswordDes decoded successfully")

        privKey = get_private_key()
        efris_log_info("Private key fetched successfully")

        # Convert the private key to a PEM format byte string for RSA import
        pkey_str = privKey.private_bytes(
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

def guidv4():
    my_uuid = uuid.uuid4()
    my_uuid_str = str(my_uuid)
    my_uuid_str_32 = my_uuid_str.replace("-", "")
    return my_uuid_str_32

def post_req(data):
    efris_log_info("post_req()...starting")
    url = "https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation"
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, data=data, headers=headers)
    print(response.text)
    efris_log_info("post_req()...done, response:" + response.text)
    return response.text

def post_reqs(data, url, headers):
    efris_log_info("post_req()...")
    response = requests.post(url, data=data, headers=headers)
    print(response.text)
    return response.text

def get_private_key():
    try:
        efris_log_info("get_private_key() starts...")
        key_file_path = get_private_key_path()       
         
        with open(key_file_path, "rb") as f:
            pfx_data = f.read()
            efris_log_info("read the key...")

        pfx = pkcs12.load_key_and_certificates(pfx_data, b"efris", default_backend())
        efris_log_info("pfx done...")

        private_key = pfx[0]  # The private key is the first element

        if private_key is None:
            efris_log_info('Private key extraction failed: private_key is None')
            return None
        
        efris_log_info("get_private_key()...done")
        return private_key
    except Exception as e:
        efris_log_error(f'Error extracting private key: {e}')
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

def safe_load_json(message):
    try:
        json_message = json.loads(message)
    except Exception:
        json_message = message

    return json_message

def format_amount(amount):
    amt_float = float(amount)    
    amt_string = "{:.2f}"
    return amt_string.format(amt_float)

if __name__ == "__main__":
    main()

