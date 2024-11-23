import sys
import json
import frappe
import traceback
from frappe import _
import os
from frappe.utils import get_bench_path
import logging


class HandledException(frappe.ValidationError): pass


# Get the default site path dynamically
bench_path = get_bench_path()
frappe.log_error(f"the  log file path is : {bench_path}")
# Construct the path to the frappe-bench/logs folder
log_folder_path = os.path.join(bench_path, 'logs')

# Ensure the logs folder exists
os.makedirs(log_folder_path, exist_ok=True)

# Set the logging configuration
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


def log_exception(fn):
    '''Decorator to catch & log exceptions'''

    def wrapper(*args, **kwargs):
        return_value = None
        try:
            return_value = fn(*args, **kwargs)
        except HandledException:
            # exception has been logged
            # so just continue raising HandledException to stop futher logging
            raise
        except Exception:
            log_error()
            show_request_failed_error()

        return return_value

    return wrapper

def show_request_failed_error():
    frappe.clear_messages()
    message = _('There was an error while making the request.') + ' '
    message += _('Please try once again and if the issue persists, please contact ERPNext Support.')
    frappe.throw(message, title=_('Request Failed'), exc=HandledException)

def log_error():
    frappe.db.rollback()
    seperator = "--" * 50
    err_tb = traceback.format_exc()
    err_msg = str(sys.exc_info()[1])
    # data = json.dumps(data, indent=4)
    
    message = "\n".join([
        "Error: " + err_msg, seperator,
        # "Data:", data, seperator,
        "Exception:", err_tb
    ])
    frappe.log_error(
        title=_('E-Invoicing Exception'),
        message=message
    )
    frappe.db.commit()

def safe_load_json(message):
    #frappe.log_error(f"message received:{message}")
    try:
        json_message = json.loads(message)
    except Exception:
        json_message = message

    return json_message

def efris_log_info(message):
    frappe.log_error(f"efris_log_info called...")
    logger.info(message)

def efris_log_warning(message):
    logger.warning(message)

def efris_log_error(message):
    logger.error(message)

def format_amount(amount):
    amt_float = float(amount)    
    amt_string = "{:.2f}"
    return amt_string.format(amt_float)
