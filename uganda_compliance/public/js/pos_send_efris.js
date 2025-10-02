// Client Script: Page = "Point of Sale"
// Purpose: Add "Send To EFRIS" button on the POS receipt after submission
// Conditions: efris_invoice = true AND efris_posted = false
// (function () {
//     console.log('📢 Initializing function....');
//     'use strict';
//     const CONFIG = {
//         buttonText: 'Send To EFRIS',
//         serverMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.send_pos_to_efris',
//         flagsMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.pos_invoice_flags'
//     };   
   
//     function findPosInvoiceDocname() {
//             // Priority 1: Right-hand order summary (selected order)
//             const rightPaneInvoice = document.querySelector('.order-summary .invoice-name');
//             if (rightPaneInvoice) {
//                 const text = rightPaneInvoice.innerText || '';
//                 console.log('✅ Found POS Invoice from right pane:', text);
//                 return text.trim();
//             }

//             // Priority 2: Frappe POS JS object (if available)
//             if (frappe?.pos?.pos_cart?.doc?.name) {
//                 console.log("✅ Found POS Invoice from frappe.pos:", frappe.pos.pos_cart.doc.name);
//                 return frappe.pos.pos_cart.doc.name;
//             }

//             // Fallback: first in list (not ideal, but safer than nothing)
//             const invoiceElement = document.querySelector('.invoice-name');
//             if (invoiceElement) {
//                 const text = invoiceElement.innerText || '';
//                 console.log('⚠️ Fallback - Found POS Invoice from left list:', text);
//                 return text.trim();
//             }

//             console.warn("❌ Could not detect POS Invoice docname");
//             return null;
//         }


//     // Function to update button state
//     function updateEfrisButtonState(efrisBtn, invoiceName) {
//         console.log('🔍 Checking eligibility for invoice:', invoiceName);
//         if (invoiceName.startsWith('new-pos-invoice-')) {
//             console.log('⚠️ Invoice is new/unsaved, cannot send to EFRIS yet');
//             efrisBtn.style.opacity = '0.4';
//             efrisBtn.innerText = 'Save Invoice First';
//             efrisBtn.style.pointerEvents = 'none';
//             return;
//         }

//         frappe.call({
//             method: CONFIG.flagsMethod,
//             args: { docname: invoiceName },
//             callback: function (r) {
//                 if (r.message) {
//                     if (r.message.eligible) {
//                         efrisBtn.style.opacity = '1';
//                         efrisBtn.style.pointerEvents = 'auto';
//                         efrisBtn.innerText = CONFIG.buttonText;
//                         console.log('✅ Button active - ready for EFRIS submission');
//                     } else {
//                         efrisBtn.style.opacity = '0.3';
//                         efrisBtn.style.pointerEvents = 'none';
                        
//                         if (r.message.efris_posted) {
//                             efrisBtn.innerText = 'Already Sent to EFRIS';
//                             setTimeout(() => {
//                                 efrisBtn.style.display = 'none';
//                             }, 2000);
//                         } else if (!r.message.efris_invoice) {
//                             efrisBtn.innerText = 'Not EFRIS Invoice';
//                         } else {
//                             efrisBtn.innerText = 'Not Eligible';
//                         }
//                     }
//                 }
//             }
//         });
//     }

//     function addEfrisButton(printBtn) {
//         // console.log('🖨️ Print button detected:', printBtn);
//         if (printBtn.dataset.efrisAdded) return;

//         const efrisBtn = document.createElement('div');
//         efrisBtn.className = 'summary-btn btn btn-default efris-btn ml-2';
//         efrisBtn.innerText = CONFIG.buttonText;
//         efrisBtn.style.cursor = 'pointer';
//         efrisBtn.style.opacity = '0.6';
//         efrisBtn.style.pointerEvents = 'none';

//         printBtn.insertAdjacentElement('afterend', efrisBtn);
//         printBtn.dataset.efrisAdded = '1';
//         // console.log('✅ EFRIS button added next to Print');

//         // Use the comprehensive function to find the invoice name
//         const posInvoice = findPosInvoiceDocname();

//         if (!posInvoice) {
//             console.error('❌ No POS Invoice name found');
//             efrisBtn.innerText = 'Invoice Not Found';
//             efrisBtn.style.opacity = '0.3';
//             return;
//         }

//         console.log('🔍 Final invoice name to use:', posInvoice);
//         // Initial eligibility check
//         updateEfrisButtonState(efrisBtn, posInvoice);
//         // Set up observer to re-check when the page content changes
//         const buttonObserver = new MutationObserver(function(mutations) {
//             mutations.forEach(function(mutation) {
//                 if (mutation.type === 'childList') {
//                     // Re-check for invoice name when DOM changes
//                     const newInvoiceName = findPosInvoiceDocname();
//                     if (newInvoiceName && newInvoiceName !== posInvoice) {
//                         console.log('🔄 DOM changed, rechecking eligibility:', newInvoiceName);
//                         updateEfrisButtonState(efrisBtn, newInvoiceName);
//                     }
//                 }
//             });
//         });

//         // Observe the entire body for changes
//         buttonObserver.observe(document.body, { childList: true, subtree: true });
//         // Click handler
//         efrisBtn.addEventListener('click', function () {

//             const currentInvoice = findPosInvoiceDocname();
//                 if (!currentInvoice || currentInvoice.startsWith('new-pos-invoice-')) {
//                     frappe.msgprint(__('This invoice is not eligible for EFRIS submission.'));
//                     return;
//                 }

//             frappe.call({
//                 method: CONFIG.serverMethod,
//                 args: { docname: currentInvoice },
//                 freeze: true,
//                 freeze_message: __('Sending to EFRIS...'),
//                 callback: function (r) {
//                     if (r.message && r.message.success) {
//                         frappe.msgprint(__('Successfully sent to EFRIS.'));
                        
//                         // Immediately disable the button
//                         efrisBtn.style.opacity = '0.3';
//                         efrisBtn.style.pointerEvents = 'none';
//                         efrisBtn.innerText = 'Sent to EFRIS';
                        
//                         // Hide the button after 3 seconds
//                         setTimeout(() => {
//                             efrisBtn.style.display = 'none';
//                         }, 3000);
                        
//                         console.log('✅ EFRIS submission successful - button disabled');
                        
//                     } else {
//                         frappe.msgprint(__('Failed to send to EFRIS: ') + (r.message?.error || 'Unknown error'));
                        
//                         // Re-check eligibility in case of failure
//                         setTimeout(() => {
//                             updateEfrisButtonState(efrisBtn, posInvoice);
//                         }, 2000);
//                     }
//                 },
//                 error: function (err) {
//                     frappe.msgprint(__('Server error while sending to EFRIS.'));
//                     console.error(err);
//                 }
//             });
//         });
//     }

//     // Main observer for print button
//     const mainObserver = new MutationObserver(() => {
//             const printBtn = document.querySelector('.print-btn');
//             if (printBtn) {
//                 addEfrisButton(printBtn);
//             }
//         });

//         // mainObserver.observe(document.querySelector('.summary-actions') || document.body, {
//         // childList: true,
//         // subtree: false
//         //  });
//          mainObserver.observe(document.body, { childList: true, subtree: true });

//     console.log('👀 Watching for Print button to add EFRIS button...');
// })();

// Client Script: Page = "Point of Sale"
// Purpose: Add "Send To EFRIS" button on the POS receipt after submission
// Conditions: efris_invoice = true AND efris_posted = false

(function () {
    console.log('📢 Initializing robust EFRIS button script...');
    'use strict';

    const CONFIG = {
        buttonText: 'Send To EFRIS',
        serverMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.send_pos_to_efris',
        flagsMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.pos_invoice_flags'
    };

    /**
     * Wait until an element exists in the DOM
     */
    function waitForElement(selector, timeout = 5000) {
        return new Promise((resolve, reject) => {
            const start = Date.now();
            const interval = setInterval(() => {
                const el = document.querySelector(selector);
                if (el) {
                    clearInterval(interval);
                    resolve(el);
                } else if (Date.now() - start > timeout) {
                    clearInterval(interval);
                    reject(`Element ${selector} not found`);
                }
            }, 50);
        });
    }

    /**
     * Find the currently selected POS invoice
     * PRIORITY:
     * 1. frappe.pos.pos_cart.doc.name (selected order)
     * 2. Right-hand order-summary DOM
     * 3. Left-hand invoice list DOM (fallback)
     */
    function findPosInvoiceDocname() {
        console.log('🔍 Attempting to find current POS Invoice docname...');

        // 1️⃣ POS internal state
        if (frappe?.pos?.pos_cart?.doc?.name) {
            console.log("✅ Selected invoice from POS internal state:", frappe.pos.pos_cart.doc.name);
            return frappe.pos.pos_cart.doc.name;
        }

        // 2️⃣ Right-hand order-summary DOM
        const rightPaneInvoice = document.querySelector('.order-summary .invoice-name');
        if (rightPaneInvoice) {
            const text = rightPaneInvoice.innerText || '';
            if (text.trim().length > 0) {
                console.log('✅ Found POS Invoice from right-hand order-summary DOM:', text);
                return text.trim();
            }
        }

        // 3️⃣ Fallback left-hand list
        const invoiceElement = document.querySelector('.invoice-name');
        if (invoiceElement) {
            const text = invoiceElement.innerText || '';
            if (text.trim().length > 0) {
                console.log('⚠️ Fallback - Found POS Invoice from left-hand list:', text);
                return text.trim();
            }
        }

        console.warn("❌ Could not detect POS Invoice docname");
        return null;
    }

    /**
     * Update EFRIS button state based on invoice eligibility
     */
    function updateEfrisButtonState(efrisBtn) {
        const invoiceName = findPosInvoiceDocname();
        if (!invoiceName) return;

        console.log('🔍 Checking eligibility for invoice:', invoiceName);

        if (invoiceName.startsWith('new-pos-invoice-')) {
            efrisBtn.style.opacity = '0.4';
            efrisBtn.innerText = 'Save Invoice First';
            efrisBtn.style.pointerEvents = 'none';
            return;
        }

        frappe.call({
            method: CONFIG.flagsMethod,
            args: { docname: invoiceName },
            callback: function (r) {
                if (!r.message) return;

                if (r.message.eligible) {
                    efrisBtn.style.opacity = '1';
                    efrisBtn.style.pointerEvents = 'auto';
                    efrisBtn.innerText = CONFIG.buttonText;
                    console.log('✅ Button active - ready for EFRIS submission');
                } else {
                    efrisBtn.style.opacity = '0.3';
                    efrisBtn.style.pointerEvents = 'none';

                    if (r.message.efris_posted) {
                        efrisBtn.innerText = 'Already Sent to EFRIS';
                        setTimeout(() => { efrisBtn.style.display = 'none'; }, 2000);
                    } else if (!r.message.efris_invoice) {
                        efrisBtn.innerText = 'Not EFRIS Invoice';
                    } else {
                        efrisBtn.innerText = 'Not Eligible';
                    }
                }
            },
            error: function (err) {
                console.error('❌ Error checking eligibility:', err);
            }
        });
    }

    /**
     * Add EFRIS button next to Print button
     */
    function addEfrisButton(printBtn) {
        if (printBtn.dataset.efrisAdded) return;

        console.log('🖊️ Adding EFRIS button next to Print button...');
        const efrisBtn = document.createElement('div');
        efrisBtn.className = 'summary-btn btn btn-default efris-btn ml-2';
        efrisBtn.innerText = CONFIG.buttonText;
        efrisBtn.style.cursor = 'pointer';
        efrisBtn.style.opacity = '0.6';
        efrisBtn.style.pointerEvents = 'none';

        printBtn.insertAdjacentElement('afterend', efrisBtn);
        printBtn.dataset.efrisAdded = '1';

        // Initial eligibility check
        setTimeout(() => updateEfrisButtonState(efrisBtn), 100);

        // MutationObserver for DOM changes (throttled)
        const observer = new MutationObserver(() => updateEfrisButtonState(efrisBtn));
        const container = document.querySelector('.summary-actions') || document.body;
        observer.observe(container, { childList: true, subtree: true });

        // Click handler
        efrisBtn.addEventListener('click', function () {
            const invoiceName = findPosInvoiceDocname();
            if (!invoiceName || invoiceName.startsWith('new-pos-invoice-')) {
                frappe.msgprint(__('This invoice is not eligible for EFRIS submission.'));
                return;
            }

            frappe.call({
                method: CONFIG.serverMethod,
                args: { docname: invoiceName },
                freeze: true,
                freeze_message: __('Sending to EFRIS...'),
                callback: function (r) {
                    if (r.message?.success) {
                        frappe.msgprint(__('Successfully sent to EFRIS.'));
                        efrisBtn.style.opacity = '0.3';
                        efrisBtn.style.pointerEvents = 'none';
                        efrisBtn.innerText = 'Sent to EFRIS';
                        setTimeout(() => { efrisBtn.style.display = 'none'; }, 3000);
                        console.log('✅ EFRIS submission successful');
                    } else {
                        frappe.msgprint(__('Failed to send to EFRIS: ') + (r.message?.error || 'Unknown error'));
                        setTimeout(() => updateEfrisButtonState(efrisBtn), 2000);
                    }
                },
                error: function (err) {
                    frappe.msgprint(__('Server error while sending to EFRIS.'));
                    console.error(err);
                }
            });
        });
    }

    // Main observer for print button
        // Main observer for print button
        const mainObserver = new MutationObserver(() => {
                const printBtn = document.querySelector('.print-btn');
                if (printBtn) {
                    addEfrisButton(printBtn);
                }
            });       
         mainObserver.observe(document.body, { childList: true, subtree: true });

    /**
     * Initialize the script after a short delay to ensure frappe.pos and DOM are ready
     */
    setTimeout(() => {
        waitForElement('.print-btn, .summary-btn.print-btn', 5000)
            .then(printBtn => addEfrisButton(printBtn))
            .catch(console.warn);
    }, 500);

    console.log('👀 Watching for Print button to add EFRIS button...');
})();





