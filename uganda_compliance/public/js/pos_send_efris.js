// Client Script: Page = "Point of Sale"
// Purpose: Add "Send To EFRIS" button on the POS receipt after submission
// Conditions: efris_invoice = true AND efris_posted = false
(function () {
    'use strict';

    const CONFIG = {
        buttonText: 'Send To EFRIS',
        serverMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.send_pos_to_efris',
        flagsMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.pos_invoice_flags'
    };

    // Comprehensive POS Invoice docname detection function
    function findPosInvoiceDocname() {
        console.log('🔍 Looking for POS Invoice docname...');
        
        // Method 1: Look for anchor tags with pos-invoice links
        const posInvoiceSelectors = [
            'a[href*="pos-invoice"]',
            'a[href*="pos_invoice"]', 
            'a[href*="/app/pos-invoice/"]',
            'a[href*="/app/pos_invoice/"]'
        ];

        for (const selector of posInvoiceSelectors) {
            const anchor = document.querySelector(selector);
            if (anchor) {
                const href = anchor.getAttribute('href') || '';
                const match = href.match(/pos[-_]?invoice\/([^\/\?#]+)/i);
                if (match && match[1]) {
                    const docname = decodeURIComponent(match[1]);
                    console.log('📄 Found docname from URL:', docname);
                    return docname;
                }
                
                // Also check the anchor text itself
                const anchorText = anchor.innerText?.trim();
                if (anchorText && /^[A-Z0-9-]+$/i.test(anchorText)) {
                    console.log('📄 Found docname from anchor text:', anchorText);
                    return anchorText;
                }
            }
        }

        // Method 2: Look for invoice number in text content
        const textElements = document.querySelectorAll('div, span, p, a, small, h1, h2, h3, h4, h5, h6, strong, b');
        for (const element of textElements) {
            const text = element.innerText?.trim() || element.textContent?.trim();
            if (text) {
                const patterns = [
                    /\b(FBK-PSINV-[0-9]{5})\b/i,
                    /\b([A-Z]+-PSINV-[0-9]{5})\b/i,
                    /\b(PSINV-[0-9]{5})\b/i,
                    /\b(POSINV-[A-Z0-9-]+)\b/i,
                    /\b(POS-INV-[A-Z0-9-]+)\b/i,
                    /\b([A-Z]{2,4}-[0-9]{5})\b/i
                ];
                
                for (const pattern of patterns) {
                    const match = text.match(pattern);
                    if (match && match[1]) {
                        console.log('📄 Found docname from text pattern:', match[1]);
                        return match[1];
                    }
                }
            }
        }

        // Method 3: Look in data attributes or IDs
        const elementsWithData = document.querySelectorAll('[data-name], [data-docname], [id*="invoice"], [data-invoice]');
        for (const element of elementsWithData) {
            const dataName = element.getAttribute('data-name') || 
                            element.getAttribute('data-docname') ||
                            element.id;
                            
            if (dataName && /^[A-Z0-9-]+$/i.test(dataName)) {
                console.log('📄 Found docname from data attribute:', dataName);
                return dataName;
            }
        }

        // Method 4: Check for current POS context
        if (window.cur_frm && window.cur_frm.doc && window.cur_frm.doc.name) {
            const contextDocname = window.cur_frm.doc.name;
            console.log('📄 Found docname from current form context:', contextDocname);
            return contextDocname;
        }

        // Method 5: Check for any visible text
        const allVisibleText = Array.from(document.querySelectorAll('*'))
            .filter(el => el.offsetParent !== null)
            .map(el => el.innerText?.trim())
            .filter(Boolean)
            .join(' ');
            
        const fallbackPatterns = [
            /\b([A-Z]{2,5}-[A-Z]*[0-9]{5})\b/gi,
            /\b([A-Z]+INV-[0-9-]+)\b/gi
        ];
        
        for (const pattern of fallbackPatterns) {
            const matches = allVisibleText.match(pattern);
            if (matches && matches.length > 0) {
                console.log('📄 Found docname from fallback pattern:', matches[0]);
                return matches[0];
            }
        }

        console.log('❌ Could not find POS Invoice docname');
        return null;
    }

    // Function to update button state
    function updateEfrisButtonState(efrisBtn, invoiceName) {
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
                if (r.message) {
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
                            setTimeout(() => {
                                efrisBtn.style.display = 'none';
                            }, 2000);
                        } else if (!r.message.efris_invoice) {
                            efrisBtn.innerText = 'Not EFRIS Invoice';
                        } else {
                            efrisBtn.innerText = 'Not Eligible';
                        }
                    }
                }
            }
        });
    }

    function addEfrisButton(printBtn) {
        if (printBtn.dataset.efrisAdded) return;

        const efrisBtn = document.createElement('div');
        efrisBtn.className = 'summary-btn btn btn-default efris-btn ml-2';
        efrisBtn.innerText = CONFIG.buttonText;
        efrisBtn.style.cursor = 'pointer';
        efrisBtn.style.opacity = '0.6';
        efrisBtn.style.pointerEvents = 'none';

        printBtn.insertAdjacentElement('afterend', efrisBtn);
        printBtn.dataset.efrisAdded = '1';
        console.log('✅ EFRIS button added next to Print');

        // Use the comprehensive function to find the invoice name
        const posInvoice = findPosInvoiceDocname();

        if (!posInvoice) {
            console.error('❌ No POS Invoice name found');
            efrisBtn.innerText = 'Invoice Not Found';
            efrisBtn.style.opacity = '0.3';
            return;
        }

        console.log('🔍 Final invoice name to use:', posInvoice);

        // Initial eligibility check
        updateEfrisButtonState(efrisBtn, posInvoice);

        // Set up observer to re-check when the page content changes
        const buttonObserver = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.type === 'childList') {
                    // Re-check for invoice name when DOM changes
                    const newInvoiceName = findPosInvoiceDocname();
                    if (newInvoiceName && newInvoiceName !== posInvoice) {
                        console.log('🔄 DOM changed, rechecking eligibility:', newInvoiceName);
                        updateEfrisButtonState(efrisBtn, newInvoiceName);
                    }
                }
            });
        });

        // Observe the entire body for changes
        buttonObserver.observe(document.body, { childList: true, subtree: true });

        // Click handler
        efrisBtn.addEventListener('click', function () {
            if (efrisBtn.style.pointerEvents === 'none' || posInvoice.startsWith('new-pos-invoice-')) {
                frappe.msgprint(__('This invoice is not eligible for EFRIS submission.'));
                return;
            }

            frappe.call({
                method: CONFIG.serverMethod,
                args: { docname: posInvoice },
                freeze: true,
                freeze_message: __('Sending to EFRIS...'),
                callback: function (r) {
                    if (r.message && r.message.success) {
                        frappe.msgprint(__('Successfully sent to EFRIS.'));
                        
                        // Immediately disable the button
                        efrisBtn.style.opacity = '0.3';
                        efrisBtn.style.pointerEvents = 'none';
                        efrisBtn.innerText = 'Sent to EFRIS';
                        
                        // Hide the button after 3 seconds
                        setTimeout(() => {
                            efrisBtn.style.display = 'none';
                        }, 3000);
                        
                        console.log('✅ EFRIS submission successful - button disabled');
                        
                    } else {
                        frappe.msgprint(__('Failed to send to EFRIS: ') + (r.message?.error || 'Unknown error'));
                        
                        // Re-check eligibility in case of failure
                        setTimeout(() => {
                            updateEfrisButtonState(efrisBtn, posInvoice);
                        }, 2000);
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
    const mainObserver = new MutationObserver(() => {
        const printBtn = document.querySelector('.print-btn');
        if (printBtn) {
            addEfrisButton(printBtn);
        }
    });

    mainObserver.observe(document.body, { childList: true, subtree: true });

    console.log('👀 Watching for Print button to add EFRIS button...');
})();