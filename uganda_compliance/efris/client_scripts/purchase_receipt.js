const BASE_CURRENCY = 'UGX';

frappe.ui.form.on("Purchase Receipt", {
    validate: async function(frm) {
        if(!frm.doc.efris_company) {
            console.warn("❌ EFRIS Company not set. Cannot validate EFRIS items.");
            return;
        }
        console.log("✅ Validate Triggered");

        // Ensure Document-Level Exchange Rate is Set
        await set_document_exchange_rate(frm);

        // Cache for Item-Level Exchange Rates
        const currencyRateCache = {};

        // Process each item
        for (let item of frm.doc.items) {
            if (item.warehouse && item.item_code) {
                console.log(`🔄 Checking EFRIS Receipt for Item: ${item.item_code}`);
                await check_efris_stockin(frm, item.doctype, item.name);
            }

            item.efris_receipt = item.efris_receipt || false;

            if (item.efris_item && item.efris_item === 1) {
                console.log(`✅ EFRIS Item is TRUE for ${item.item_code}`);

                // Ensure Item-Level Exchange Rate is Set
                if (!item.efris_currency_exchange_rate && item.efris_currency !== BASE_CURRENCY) {
                    if (currencyRateCache[item.efris_currency]) {
                        console.log(`🔄 Using Cached Exchange Rate for ${item.efris_currency}`);
                        frappe.model.set_value(item.doctype, item.name, 'efris_currency_exchange_rate', currencyRateCache[item.efris_currency]);
                    } else {
                        console.log(`🌍 Fetching Exchange Rate for Item Currency: ${item.efris_currency}`);
                        const rate = await fetch_exchange_rate(item.efris_currency, frm.doc.company, frm);
                        currencyRateCache[item.efris_currency] = rate;
                        frappe.model.set_value(item.doctype, item.name, 'efris_currency_exchange_rate', rate);
                    }
                }

                const PURCHASE_CURRENCY = frm.doc.currency; // Purchase Document Currency
                const ITEM_CURRENCY = item.efris_currency; // Item's EFRIS Currency
                let efris_unit_price;

                // 📊 Scenario 1: UGX Purchase, Non-UGX Item Currency
                if (PURCHASE_CURRENCY === BASE_CURRENCY && ITEM_CURRENCY !== BASE_CURRENCY) {
                    console.log(`📊 Scenario 1: UGX Purchase, Non-UGX Item Currency`);
                    // Convert UGX → Item Currency
                    efris_unit_price = item.base_rate / item.efris_currency_exchange_rate;
                }

                // 📊 Scenario 2: Non-UGX Purchase, UGX Item Currency
                else if (PURCHASE_CURRENCY !== BASE_CURRENCY && ITEM_CURRENCY === BASE_CURRENCY) {
                    console.log(`📊 Scenario 2: Non-UGX Purchase, UGX Item Currency`);
                    // Convert Purchase Currency → UGX
                    efris_unit_price = item.rate * frm.doc.conversion_rate;
                }

                // 📊 Scenario 3: Non-UGX Purchase, Non-UGX Item Currency
                else if (PURCHASE_CURRENCY !== BASE_CURRENCY && ITEM_CURRENCY !== BASE_CURRENCY) {
                    console.log(`📊 Scenario 3: Non-UGX Purchase, Non-UGX Item Currency`);
                    // Convert Purchase Currency → UGX → Item Currency
                    let intermediate_ugx_price = item.rate * frm.doc.conversion_rate;
                    efris_unit_price = intermediate_ugx_price / item.efris_currency_exchange_rate;
                }

                // 📊 Scenario 4: Matching Currencies
                else if (PURCHASE_CURRENCY === ITEM_CURRENCY) {
                    console.log(`📊 Scenario 4: Matching Currencies`);
                    // Use Rate directly
                    efris_unit_price = item.rate;
                }

                // 📊 Fallback: Default to base_rate (Safety Net)
                else {
                    console.warn(`⚠️ Fallback Scenario Triggered`);
                    efris_unit_price = item.base_rate;
                }

                // Apply the calculated price
                console.log(`💲 Final EFRIS Unit Price for ${item.item_code}: ${efris_unit_price}`);
                frappe.model.set_value(item.doctype, item.name, 'efris_unit_price', efris_unit_price);


            } else {
                console.log(`❌ Item ${item.item_code} is not marked as EFRIS`);
                frappe.model.set_value(item.doctype, item.name, 'efris_unit_price', item.rate);
            }
        }
    },

    conversion_rate: function(frm) {
        console.log("🔄 Conversion Rate Changed");
        set_document_exchange_rate(frm);
    },
    after_submit: async function(frm) {
        console.log("✅ After Submit Triggered");            
         add_custom_buttons(frm);
    },
    refresh: async function(frm) {
        console.log("🔄 Onload Triggered");
        add_custom_buttons(frm);
    }
});

// 1️⃣ **Document-Level Exchange Rate Fetch**
async function set_document_exchange_rate(frm) {
    if (!frm.doc.efris_company) {
        console.warn("❌ EFRIS Company not set. Cannot fetch exchange rates.");
        return;
    }

    if (frm.doc.currency !== BASE_CURRENCY && !frm.doc.efris_currency_exchange_rate) {
        console.log(`🌍 Fetching Document Exchange Rate for ${frm.doc.currency}`);
        const rate = await fetch_exchange_rate(frm.doc.currency, frm.doc.company, frm);
        frm.set_value('efris_currency_exchange_rate', rate);
        frm.refresh_field('efris_currency_exchange_rate');

        if (frm.doc.conversion_rate == 0) {
            console.log(`🔄 Setting Conversion Rate from Document Exchange Rate: ${rate}`);
            frm.set_value('conversion_rate', rate);
            frm.refresh_field('conversion_rate');
        }
    }
}

// 2️⃣ **Fetch Exchange Rate Utility**
async function fetch_exchange_rate(currency, company, frm) {
    return new Promise((resolve) => {
        frappe.call({
            method: 'uganda_compliance.efris.api_classes.stock_in.query_currency_exchange_rate',
            args: {
                doc: JSON.stringify({
                    currency: currency,
                    company: company,
                    doctype: frm.doc.doctype,
                    name: frm.doc.name
                })
            },
            callback: function(r) {
                if (r.message && r.message.rate) {
                    console.log(`✅ Fetched Exchange Rate for ${currency}: ${r.message.rate}`);
                    resolve(r.message.rate);
                } else {
                    console.warn(`❌ Failed to fetch Exchange Rate for ${currency}`);
                    resolve(1); 
                }
            }
        });
    });
}

// 3️⃣ **Check EFRIS Receipt**
function check_efris_stockin(frm, cdt, cdn) {
    let row = locals[cdt][cdn];
    return new Promise((resolve) => {
        if (row.warehouse && row.item_code) {
            frappe.call({
                method: 'uganda_compliance.efris.api_classes.e_goods_services.check_efris_item_for_purchase_receipt',
                args: {
                    accept_warehouse: row.warehouse,
                    item_code: row.item_code
                },
                callback: function(r) {
                    if (r.message) {
                        frappe.model.set_value(cdt, cdn, 'efris_receipt', r.message.is_efris);
                        console.log(`✅ EFRIS Receipt set for ${row.item_code}: ${r.message.is_efris}`);
                    }
                    resolve();
                }
            });
        } else {
            resolve();
        }
    });
}

async function add_custom_buttons(frm) {  
    console.log("🔄 Checking conditions for adding custom buttons...");
    const isEfrisWarehouse = await is_efris_warehouse(frm.doc.set_warehouse);
    console.log(`Is EFRIS Warehouse: ${isEfrisWarehouse}`);

    if (!isEfrisWarehouse || frm.doc.docstatus != 1 || !frm.doc.efris_company || frm.doc.efris_submitted ) {
        console.log("Skipping EFRIS submission button for non-EFRIS or return invoices");
        return;
    }

    const auto_send_submitted_invoice = await get_auto_send_submitted_invoice_flag(frm);  
    console.log(`Auto Send Submitted Invoice Flag: ${auto_send_submitted_invoice}`);    

    if (auto_send_submitted_invoice != 1) {
        frm.add_custom_button(__('Submit To EFRIS'), async function () {
            frappe.confirm(
                __('Are you sure you want to submit?'),
                async function () {
                    // Yes callback
                    try {
                        const response = await frappe.call({
                            method: 'uganda_compliance.efris.api_classes.stock_in.send_purchase_receipt',
                            args: { doc: frm.doc },
                            freeze: true,
                            freeze_message: __('Submitting to EFRIS...')
                        });

                        if (response.message) {
                            frappe.msgprint(__('Purchase Receipt submitted to EFRIS successfully.'));
                            frm.reload_doc();
                        } else {
                            console.log(__('Failed to submit Purchase Receipt to EFRIS.'));
                        }
                    } catch (error) {
                        console.error("Error submitting to EFRIS:", error);
                        frappe.msgprint(__('An error occurred while submitting to EFRIS.'));
                    }
                },
                function () {
                    // No callback (do nothing)
                    console.log("Submission to EFRIS was cancelled by the user.");
                }
            );
        });
    }
}

function get_auto_send_submitted_invoice_flag(frm) {    
    return new Promise((resolve) => {
        if (!frm.doc.efris_company || frm.doc.efris_submitted !== 1) {
            return resolve(0);
        }

        frappe.call({
            method: "uganda_compliance.efris.doctype.e_invoicing_settings.e_invoicing_settings.get_e_company_settings",
            args: { company_name: frm.doc.company },
            callback: function(r) {
                if (r.message && r.message.auto_send_submitted_invoice == 1) {
                    console.log("Auto send submitted invoice is enabled in EFRIS settings");
                    resolve(1);
                } else {
                    resolve(0);
                }
            }
        });
    });
}
function is_efris_warehouse(warehouse_name) {
    if (!warehouse_name) {
        console.warn("Warehouse name is not provided.");
        return Promise.resolve(false);
    }
    return new Promise((resolve) => {
        frappe.call({
            method: "uganda_compliance.efris.api_classes.stock_in.is_efris_warehouse",
            args: { warehouse_name: warehouse_name },
            callback: function(r) {
                if (r.message) {
                    console.log(`Warehouse ${warehouse_name} is an EFRIS warehouse: ${r.message}`);
                    resolve(r.message);
                } else {
                    console.warn(`Failed to determine if warehouse ${warehouse_name} is an EFRIS warehouse.`);
                    resolve(false);
                }
            }
        });
    });
}