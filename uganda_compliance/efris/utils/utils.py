
import json
import frappe
from frappe import _
import os
from frappe.utils import get_bench_path
import logging

class HandledException(frappe.ValidationError): pass

bench_path = get_bench_path()

log_folder_path = os.path.join(bench_path, 'logs')

os.makedirs(log_folder_path, exist_ok=True)

log_file_path = os.path.join(log_folder_path, 'efris_logfile.log')

frappe.log_error(f"log_file_path:{log_file_path}")

# Configure logging
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

def safe_load_json(message):
    try:
        json_message = json.loads(message)
    except Exception:
        json_message = message

    return json_message

def efris_log_info(message):
    logger.info(message)

def efris_log_warning(message):
    logger.warning(message)

def efris_log_error(message):
    logger.error(message)

def format_amount(amount):
    amt_float = float(amount)    
    amt_string = "{:.2f}"
    return amt_string.format(amt_float)

def test_job():
    print("Test job executed!")
