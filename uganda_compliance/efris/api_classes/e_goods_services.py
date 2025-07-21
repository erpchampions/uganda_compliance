import frappe
import json
from uganda_compliance.efris.utils.utils import efris_log_info, efris_log_error
from uganda_compliance.efris.api_classes.efris_api import make_post
from uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings import get_e_company_settings
from functools import lru_cache

@frappe.whitelist()
def has_efris_item_in_stock_ledger_entry(warehouse, company):
    """
    Check if there exists a Stock Ledger Entry for the given warehouse that includes
    at least one item with the 'efris_item' flag set to True.
    """
    try:
        efris_log_info(f"Checking EFRIS items in warehouse {warehouse} for company {company}")
        
        # Optimized single query using SQL JOIN
        result = frappe.db.sql("""
            SELECT sle.name 
            FROM `tabStock Ledger Entry` sle
            INNER JOIN `tabItem` item ON sle.item_code = item.name
            WHERE sle.warehouse = %(warehouse)s 
                AND sle.company = %(company)s
                AND sle.docstatus = 1 
                AND sle.is_cancelled = 0
                AND item.efris_item = 1
            LIMIT 1
        """, {
            'warehouse': warehouse,
            'company': company
        })
        
        has_efris_items = bool(result)
        efris_log_info(f"Warehouse {warehouse} has EFRIS items: {has_efris_items}")
        
        return has_efris_items

    except Exception as e:
        efris_log_error(f"Error checking EFRIS items for warehouse {warehouse}: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "EFRIS Warehouse Validation Error")
        return False
    
@frappe.whitelist()
def check_efris_item_for_purchase_receipt(accept_warehouse, item_code):
    is_efris_warehouse = frappe.db.get_value('Warehouse', accept_warehouse, 'efris_warehouse')

    is_efris_item = frappe.db.get_value('Item', item_code, 'efris_item')

    is_efris = bool(is_efris_warehouse and is_efris_item)

    return {'is_efris': is_efris}

def before_save_item(doc, method):
    is_import = frappe.flags.in_import
    is_registered_item = doc.get("efris_registered", 0)
    if is_import and is_registered_item == 1:
        return

    is_efris_item = doc.get('efris_item')
    if not is_efris_item:
        return

    is_registered_item = doc.get("efris_registered", 0)

    has_opening_stock = doc.get("opening_stock",0)
    efris_log_info(f"The Opening Stock Quantity is {has_opening_stock}")
    if has_opening_stock:
        frappe.throw("You Should Not ADD Opening Stock, Opening Stock is Stocked-In to EFRIS Via Stock Reconciliation")

    e_company = doc.get('efris_e_company', '')
    
    if not is_registered_item:
        query_result = query_item_before_post(doc)
        if query_result:
            update_existing_item(doc, method, e_company)
        else:
            upload_new_item(doc, method, e_company)
    else:
        update_existing_item(doc, method, e_company)

def query_item_before_post(doc):
    e_company = doc.get('efris_e_company', '')
    item_code = ""
    item_code = doc.get('item_code', '')
    efris_log_info(f"Item Code :{item_code}") 
    goodsCode = doc.get('efris_product_code', '')
    efris_log_info(f"EFRIS Product Code is {goodsCode}")
    if goodsCode:
        item_code = goodsCode
    dn_batch_query_goods_T144 = {
        "goodsCode": item_code,
        "tin": get_e_company_settings(e_company).tin
    }
    efris_log_info(f"Querying EFRIS with: {dn_batch_query_goods_T144}")
    success, response = make_post(interfaceCode="T144", content=dn_batch_query_goods_T144, company_name=e_company, reference_doc_type=doc.doctype, reference_document=doc.name)
    
    if success and response:
        efris_log_info(f"Query successful, response: {response}")
        return response 
    else:
        efris_log_info("Item not found in EFRIS.")
        return None

def upload_new_item(doc, method, e_company):
    prepare_and_upload_item(doc, method, operation_type="101", e_company=e_company)  # 101 for new item

def update_existing_item(doc, method, e_company):
    prepare_and_upload_item(doc, method, operation_type="102", e_company=e_company)  # 102 for update item


def prepare_and_upload_item(doc, method, operation_type, e_company):
    if not doc.get('efris_item', 0):
        efris_log_info(f"Item Is Non EFRIS {doc.get('efris_item', 0)}")
        return

    goods_code, item_code, goods_name = get_item_details(doc)
    unit_price, measure_unit, currency, commodity_category_id = get_item_pricing_and_uom(doc)
    goods_other_units, piece_measure_unit, piece_unit_price, piece_scaled_value, have_piece_unit = process_additional_uoms(doc)

    goods_upload = prepare_goods_upload(
        operation_type, goods_name, item_code, measure_unit, unit_price, currency,
        commodity_category_id, have_piece_unit, piece_measure_unit, piece_unit_price,
        piece_scaled_value, goods_other_units
    )

    upload_item_to_efris(doc, e_company, goods_upload)
    
def get_item_details(doc):
    goods_code = doc.get('efris_product_code', '')
    item_code = goods_code if goods_code else doc.get('item_code', '')
    goods_name = doc.get('item_name', '')
    return goods_code, item_code, goods_name


def get_item_pricing_and_uom(doc):
    item_currency = doc.get('efris_currency', '')
    currency = frappe.db.get_value('Currency', {'currency_name': item_currency}, 'efris_currency_code') if item_currency else ''

    if item_currency == 'UGX':
        unit_price = str(doc.get('standard_rate', '0.0'))
        if unit_price == '0.0':
            frappe.throw("Standard Rate cannot be zero")
    else:
        unit_price = str(doc.get('uoms', [])[0].get('efris_unit_price', 0))

    uom = doc.get('stock_uom', '')
    measure_unit = frappe.db.get_value('UOM', {'uom_name': uom}, 'efris_uom_code') or ''
    if not measure_unit:
        frappe.throw(f"EFRIS UOM code must not be empty on Default UOM: {uom}")

    commodity_category_id = doc.get('efris_commodity_code', '')
    return unit_price, measure_unit, currency, commodity_category_id

def process_additional_uoms(doc):
    goods_other_units = []
    piece_measure_unit = ''
    piece_unit_price = ''
    piece_scaled_value = ''
    have_piece_unit = "102"

    if doc.get('efris_has_multiple_uom', 0):
        for item_uom in doc.get('uoms', []):
            if not item_uom.get('efris_uom', 0):
                efris_log_info(f"Skipping {item_uom.get('uom')} as it is not flagged as an EFRIS UOM")
                continue

            uom_value = frappe.db.get_value('UOM', {'uom_name': item_uom.get('uom')}, 'efris_uom_code') or ''
            if not uom_value:
                frappe.throw(f"EFRIS UOM code is empty for UOM: {item_uom.get('uom')}")

            if item_uom.get('efris_package_unit', 0) == 1:
                continue  

            if item_uom.get('efris_is_piece_unit', 0) == 1:
                piece_measure_unit = uom_value
                piece_unit_price = item_uom.get('efris_unit_price', 0.0)
                piece_scaled_value = str(item_uom.get('efris_package_scale_value', 1))
                have_piece_unit = "101"
                continue

            goods_other_units.append({
                "otherUnit": uom_value,
                "otherPrice": item_uom.get('efris_unit_price', 0.0),
                "otherScaled": str(item_uom.get('efris_package_scale_value', 1)),
                'packageScaled': "1"
            })

    return goods_other_units, piece_measure_unit, piece_unit_price, piece_scaled_value, have_piece_unit

def prepare_goods_upload(operation_type, goods_name, item_code, measure_unit, unit_price, currency, commodity_category_id, have_piece_unit, piece_measure_unit, piece_unit_price, piece_scaled_value, goods_other_units):
    return [{
        "operationType": operation_type,
        "goodsName": goods_name,
        "goodsCode": item_code,
        "measureUnit": measure_unit,
        "unitPrice": unit_price,
        "currency": currency,
        "commodityCategoryId": commodity_category_id if measure_unit else "",
        "haveExciseTax": "102",
        "stockPrewarning": "0",
        "havePieceUnit": have_piece_unit,
        "pieceMeasureUnit": piece_measure_unit,
        "pieceUnitPrice": piece_unit_price,
        "packageScaledValue": "1" if have_piece_unit == "101" else "",
        "pieceScaledValue": piece_scaled_value,
        "haveOtherUnit": "101" if goods_other_units else "102",
        "goodsOtherUnits": goods_other_units
    }]


def upload_item_to_efris(doc, e_company, goods_upload):
    efris_log_info(f"The JSON item for Company {e_company} is: {goods_upload}")

    success, response = make_post(
        interfaceCode="T130",
        content=goods_upload,
        company_name=e_company,
        reference_doc_type=doc.doctype,
        reference_document=doc.name
    )

    if success:
        efris_log_info(f"Item successfully uploaded to EFRIS for {e_company}")
        frappe.msgprint(f"Item successfully uploaded to EFRIS for {e_company}")
        if not doc.efris_registered:
            doc.efris_registered = 1
            efris_log_info(f"The Value Of Is EFRIS Registered is updated to {doc.get('efris_registered', '')}")
    else:
        efris_log_error(f"Failed to upload item to EFRIS for {e_company}: {response}")
        frappe.throw(f"Failed to upload item to EFRIS for {e_company}: {response}")


# Cache price lists for the session
@lru_cache(maxsize=1)
def get_cached_price_lists(company, currency):
    """
    Fetch configured price lists for a given company and fallback to default selling price list.
    """
    efris_log_info(f"Fetching and caching price lists for company: {company}")
    settings = get_e_company_settings(company)

    # Get configured price lists
    price_lists = [
        pl['price_list'] for pl in frappe.get_all(
            'EFRIS Price List',
            filters={'parent': settings.name},
            fields=['price_list']
        )
    ]

    # Fallback to default selling price list if none are configured
    if not price_lists:
        default_price_list = frappe.get_value(
            'Price List', {'currency': currency, 'selling': 1}, 'name'
        )
        if default_price_list:
            price_lists.append(default_price_list)
            efris_log_info(f"Using default selling price list: {default_price_list}")
        else:
            efris_log_info("No valid price lists found.")

    return price_lists



@frappe.whitelist()
def create_item_prices(item_code, uoms, currency, company):
    try:
        if isinstance(uoms, str):
            uoms = json.loads(uoms)

        price_lists = get_cached_price_lists(company, currency)
        if not price_lists:
            efris_log_info("No valid price lists found. Skipping price updates.")
            return

        existing_prices = frappe.get_all(
            'Item Price',
            filters={
                'item_code': item_code,
                'price_list': ['in', price_lists]
            },
            fields=['name', 'uom', 'price_list', 'price_list_rate']
        )

        existing_price_map = {
            (ep['uom'], ep['price_list']): ep for ep in existing_prices
        }

        for price_list in price_lists:
            if not price_list:
                efris_log_error("Invalid price_list encountered. Skipping entry.")
                continue

            for uom_row in uoms:
                uom = uom_row.get('uom')
                price = uom_row.get('efris_unit_price')
                if not uom or not price:
                    continue

                key = (uom, price_list)
                if key in existing_price_map:
                    if existing_price_map[key]['price_list_rate'] != price:
                        frappe.db.set_value('Item Price', existing_price_map[key]['name'], 'price_list_rate', price)
                        efris_log_info(f"Updated Item Price: {existing_price_map[key]['name']} to rate {price}")
                else:
                    # Explicit check before creation
                    if not price_list:
                        efris_log_error(f"Cannot create Item Price without a valid price_list.")
                        continue

                    item_price_doc = frappe.get_doc({
                        'doctype': 'Item Price',
                        'item_code': item_code,
                        'uom': uom,
                        'price_list': price_list,
                        'currency': currency,
                        'price_list_rate': price,
                        'selling': 1
                    })
                    item_price_doc.insert(ignore_permissions=True)
                    efris_log_info(f"Created Item Price for {uom} in {price_list} at rate {price}")

        efris_log_info("Item Prices processed successfully.")

    except Exception as e:
        frappe.throw(f"Error creating/updating Item Prices: {str(e)}")



#######################
def validate_efris_uom(uom, label):
    uom_code = frappe.get_value('UOM', {'uom_name': uom}, 'efris_uom_code')
    if not uom_code:
        frappe.throw(f"The Selected {label} UOM ({uom}) is not a valid EFRIS UOM")
    efris_log_info(f"{label} UOM ({uom}) has EFRIS Code {uom_code}")

#####################
def validate_is_efris_item(doc):
    efris_log_info(f"Validating EFRIS Item: {doc.get('item_code')}")
    validate_item_tax_template(doc)
    validate_uoms(doc)

def validate_item_tax_template(doc):
    if not doc.get('taxes'):
        frappe.throw("Please select an Item Tax Template for an EFRIS ITEM.")

def validate_uoms(doc):
    uoms = doc.get("uoms", [])
    has_multiple_uom = doc.get("efris_has_multiple_uom")
    package_uom = ""
    # Defaults for single UOM
    if not has_multiple_uom and len(uoms) == 1:
        single_uom_row = uoms[0]
        single_uom_row.efris_unit_price = doc.get('standard_rate')
        single_uom_row.efris_uom = 1
        single_uom_row.efris_package_scale_value = 1
        single_uom_row.efris_package_unit = 1
        doc.purchase_uom = single_uom_row.get('uom')
        doc.sales_uom = single_uom_row.get('uom')

        efris_log_info(f"Defaults set for single UOM: {single_uom_row.get('uom')}")

    # Validation logic
    piece_unit_count = 0
    package_unit_count = 0
    is_efris_uom_count = 0

    for row in uoms:
        piece_unit = row.get("efris_is_piece_unit")
        package_unit = row.get("efris_package_unit")
        efris_unit_price = row.get("efris_unit_price")
        efris_package_scale_value = row.get("efris_package_scale_value")
        is_efris_uom = row.get("efris_uom")

        if is_efris_uom:
            is_efris_uom_count += 1
        if piece_unit:
            piece_unit_count += 1
        if package_unit:
            package_uom = row.get("uom")
            package_unit_count += 1
            
        
        if is_efris_uom and (not efris_unit_price or not efris_package_scale_value):
            frappe.throw("EFRIS UOMs must have a unit price and scale value.")
    
    doc.purchase_uom = package_uom
    doc.sales_uom = package_uom
    validate_uom_counts(has_multiple_uom, piece_unit_count, package_unit_count, is_efris_uom_count)

def validate_uom_counts(has_multiple_uom, piece_count, package_count, efris_count):
    if has_multiple_uom:
        if efris_count <= 1:
            frappe.throw("You must have additional UOMs if 'Has Multiple UOMs' is True.")
        if piece_count == 0:
            frappe.throw("EFRIS Piece Unit must be set if 'Has Multiple UOMs' is True.")
        if piece_count > 1:
            frappe.throw("Only one EFRIS Piece Measure Unit can be set.")
    else:
        if piece_count > 0:
            frappe.throw("EFRIS Piece Unit should not be set if 'Has Multiple UOMs' is False.")
    if package_count == 0:
        frappe.throw("EFRIS Package Measure Unit must be set.")
    if package_count > 1:
        frappe.throw("Only one EFRIS Package Measure Unit can be set.")


###################
@frappe.whitelist()
def item_validations(doc, method):
    try:
        if frappe.flags.in_import and doc.get("efris_registered"):
            efris_log_info(f"Validation Excludes EFRIS registered Item {doc.get('item_code')}")
            return

        if not doc.get("efris_item"):
            efris_log_info("Non EFRIS Item")
            return

        validate_is_efris_item(doc)

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Item Validation Error")
        frappe.throw(f"Item Validations Failed!")
        
        
@frappe.whitelist()
def get_item_tax_template(company, e_tax_category):
    """
    Fetch the Item Tax Template linked to a specific company and e_tax_category
    in the child table (Item Tax Template Detail).
    """
    try:
        tax_templates = frappe.db.get_all("Item Tax Template",{"company":company})
        if tax_templates:
            efris_log_info(f"Tax Templates:{tax_templates}")
            for doc in tax_templates:
                item_tax = frappe.get_doc("Item Tax Template",{'name':doc.name})
                efris_log_info(f" Template Doc {item_tax}")
                taxes = item_tax.get("taxes",[])               
                for tax in taxes:
                    if tax.efris_e_tax_category == e_tax_category:
                        return item_tax.name
                
        
        return None
    except Exception as e:
        frappe.log_error(f"Error fetching Item Tax Template: {str(e)}")
        return []