"""URA request envelope builder.

URA expects every request wrapped in a `globalInfo` / `data` / `returnStateInfo`
envelope. This module owns its construction. The hardcoded TIN / deviceNo
defaults present in the legacy `request_utils.fetch_data` were misleading —
they're always overwritten before send. We initialise them empty here.
"""
import uuid
from datetime import datetime

import pytz


UG_TIMEZONE = "Africa/Kampala"


def guidv4() -> str:
    return uuid.uuid4().hex


def get_ug_time_str() -> str:
    now = datetime.now().astimezone(pytz.timezone(UG_TIMEZONE))
    return now.strftime("%Y-%m-%d %H:%M:%S")


def build_envelope() -> dict:
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
            "dataExchangeId": guidv4(),
            "interfaceCode": "",
            "requestTime": get_ug_time_str(),
            "requestCode": "TP",
            "responseCode": "TA",
            "userName": "admin",
            "deviceMAC": "FFFFFFFFFFFF",
            "deviceNo": "",
            "tin": "",
            "brn": "",
            "taxpayerID": "1",
            "longitude": "116.397128",
            "latitude": "39.916527",
            "extendField": {
                "responseDateFormat": "dd/MM/yyyy",
                "responseTimeFormat": "dd/MM/yyyy HH:mm:ss",
            },
        },
        "returnStateInfo": {"returnCode": "", "returnMessage": ""},
    }
