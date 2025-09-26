// Client Script: Page = "Point of Sale"
// Purpose: Add "Send To EFRIS" button on the POS receipt after submission
// Conditions: efris_invoice = true AND efris_posted = false

// Client Script: Page = "Point of Sale"
// Purpose: Add "Send To EFRIS" button on the POS receipt after submission
// Conditions: efris_invoice = true AND efris_posted = false

(function () {
    'use strict';

    // Configuration
    const CONFIG = {
        buttonText: 'Send To EFRIS',
        buttonLoadingText: 'Sending...',
        serverMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.send_pos_to_efris',
        flagsMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.pos_invoice_flags'
    };

    function tryAddEfrisButton() {
        // Target the specific print button class used in ERPNext POS
        let printBtn = document.querySelector('.print-btn');
        
        // Alternative selectors based on the POS structure
        if (!printBtn) {
            printBtn = document.querySelector('.summary-btn.print-btn');
        }
        
        if (!printBtn) {
            printBtn = document.querySelector('[class*="print-btn"]');
        }
        
        // Fallback: search within summary containers
        if (!printBtn) {
            const summaryContainer = document.querySelector('.summary-btns, .pos-summary-container, [class*="summary"]');
            if (summaryContainer) {
                printBtn = summaryContainer.querySelector('.print-btn') || 
                          summaryContainer.querySelector('[class*="print"]');
            }
        }

        if (!printBtn) {
            console.log('Print button (.print-btn) not found - checking DOM structure...');
            // Debug: Log relevant elements
            const summaryBtns = document.querySelectorAll('.summary-btn, [class*="summary"], [class*="print"]');
            console.log('Summary/Print related elements:', Array.from(summaryBtns).map(el => ({
                tagName: el.tagName,
                className: el.className,
                text: el.innerText?.trim() || el.textContent?.trim(),
                visible: el.offsetParent !== null
            })));
            return;
        }
        
        console.log('Found Print button:', printBtn, 'Classes:', printBtn.className);

        // Prevent duplicate buttons
        if (printBtn.dataset.efrisAdded) {
            console.log('EFRIS button already added');
            return;
        }

        // Find the summary buttons container (same pattern as ERPNext POS)
        const container = printBtn.parentElement || 
                         printBtn.closest('.summary-btns') || 
                         printBtn.closest('[class*="summary"]') ||
                         printBtn.parentNode;

        if (!container) {
            console.log('Container for EFRIS button not found');
            return;
        }

        // Create the EFRIS button with same styling as other summary buttons
        const efrisBtn = document.createElement('div');
        efrisBtn.className = 'summary-btn btn btn-default efris-btn mr-4';
        efrisBtn.style.cursor = 'pointer';
        efrisBtn.innerText = CONFIG.buttonText;
        efrisBtn.setAttribute('data-efris-btn', 'true');
        
        // Initially disabled until server check
        efrisBtn.classList.add('disabled');
        efrisBtn.style.opacity = '0.6';
        efrisBtn.style.pointerEvents = 'none';

        // Insert after print button
        if (printBtn.nextSibling) {
            container.insertBefore(efrisBtn, printBtn.nextSibling);
        } else {
            container.appendChild(efrisBtn);
        }

        // Mark as added
        printBtn.dataset.efrisAdded = '1';

        console.log('EFRIS button added to DOM');

        // Function to extract POS Invoice docname from the receipt
        function findPosInvoiceDocname() {
            console.log('Looking for POS Invoice docname...');
            
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
                        console.log('Found docname from URL:', docname);
                        return docname;
                    }
                    
                    // Also check the anchor text itself
                    const anchorText = anchor.innerText?.trim();
                    if (anchorText && /^[A-Z0-9-]+$/i.test(anchorText)) {
                        console.log('Found docname from anchor text:', anchorText);
                        return anchorText;
                    }
                }
            }

            // Method 2: Look for invoice number in text content - more comprehensive patterns
            const textElements = document.querySelectorAll('div, span, p, a, small, h1, h2, h3, h4, h5, h6, strong, b');
            for (const element of textElements) {
                const text = element.innerText?.trim() || element.textContent?.trim();
                if (text) {
                    // Match comprehensive POS invoice patterns (including your format)
                    const patterns = [
                        /\b(FBK-PSINV-[0-9]{4}-[0-9]+)\b/i,  // Your format: FBK-PSINV-2025-0009
                        /\b([A-Z]+-PSINV-[0-9]{4}-[0-9]+)\b/i, // Generic company prefix
                        /\b(PSINV-[0-9]{4}-[0-9]+)\b/i,      // PSINV-2025-0011
                        /\b(POSINV-[A-Z0-9-]+)\b/i,         // POSINV variants
                        /\b(POS-INV-[A-Z0-9-]+)\b/i,        // POS-INV variants
                        /\b([A-Z]{2,4}-[0-9]{4}-[0-9]+)\b/i  // Generic: XXX-2025-0000
                    ];
                    
                    for (const pattern of patterns) {
                        const match = text.match(pattern);
                        if (match && match[1]) {
                            console.log('Found docname from text pattern:', match[1], 'in element:', element.tagName);
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
                    console.log('Found docname from data attribute:', dataName);
                    return dataName;
                }
            }

            // Method 4: Check for current POS context (if available in global scope)
            if (window.cur_frm && window.cur_frm.doc && window.cur_frm.doc.name) {
                const contextDocname = window.cur_frm.doc.name;
                console.log('Found docname from current form context:', contextDocname);
                return contextDocname;
            }

            // Method 5: Check for any visible text that looks like an invoice number
            const allVisibleText = Array.from(document.querySelectorAll('*'))
                .filter(el => el.offsetParent !== null) // Only visible elements
                .map(el => el.innerText?.trim())
                .filter(Boolean)
                .join(' ');
                
            const fallbackPatterns = [
                /\b([A-Z]{2,5}-[A-Z]*[0-9]{4}-[0-9]+)\b/gi,
                /\b([A-Z]+INV-[0-9-]+)\b/gi
            ];
            
            for (const pattern of fallbackPatterns) {
                const matches = allVisibleText.match(pattern);
                if (matches && matches.length > 0) {
                    console.log('Found docname from fallback pattern:', matches[0]);
                    return matches[0];
                }
            }

            console.log('Could not find POS Invoice docname - available text:', 
                       Array.from(document.querySelectorAll('*'))
                           .filter(el => el.offsetParent !== null && el.innerText?.trim())
                           .slice(0, 10)
                           .map(el => el.innerText.trim().substring(0, 50))
            );
            return null;
        }

        // Check if the invoice is eligible for EFRIS submission
        function checkEfrisEligibility() {
            const docname = findPosInvoiceDocname();
            
            if (!docname) {
                console.log('No docname found, keeping button disabled');
                efrisBtn.remove();
                return;
            }

            console.log('Found POS Invoice:', docname);

            // Call server to check if invoice should show EFRIS button
            frappe.call({
                method: CONFIG.flagsMethod,
                args: { docname: docname },
                callback: function(r) {
                    console.log('Server response for flags:', r);
                    
                    if (r.exc) {
                        console.error('Error checking EFRIS flags:', r.exc);
                        efrisBtn.remove();
                        return;
                    }

                    const data = r.message || {};
                    
                    if (data.efris_invoice === true || data.efris_invoice === 1) {
                        if (data.efris_posted === false || data.efris_posted === 0 || !data.efris_posted) {
                            // Enable button
                            efrisBtn.classList.remove('disabled');
                            efrisBtn.style.opacity = '1';
                            efrisBtn.style.pointerEvents = 'auto';
                            console.log('EFRIS button enabled - Invoice eligible');
                        } else {
                            console.log('Invoice already posted to EFRIS - removing button');
                            efrisBtn.remove();
                        }
                    } else {
                        console.log('Invoice not marked for EFRIS - removing button');
                        efrisBtn.remove();
                    }
                },
                error: function(r) {
                    console.error('Error in server call:', r);
                    efrisBtn.remove();
                }
            });
        }

        // Button click handler
        efrisBtn.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Prevent clicks on disabled button
            if (efrisBtn.classList.contains('disabled')) {
                return;
            }
            
            if (!confirm('Send this POS Invoice to EFRIS now?')) {
                return;
            }

            const docname = findPosInvoiceDocname();
            if (!docname) {
                frappe.msgprint({
                    title: 'Error',
                    message: 'Could not detect POS Invoice name on this receipt.',
                    indicator: 'red'
                });
                return;
            }

            // Disable button and show loading state
            efrisBtn.classList.add('disabled');
            efrisBtn.style.opacity = '0.6';
            efrisBtn.style.pointerEvents = 'none';
            efrisBtn.innerText = CONFIG.buttonLoadingText;

            console.log('Sending to EFRIS:', docname);

            // Send to EFRIS
            frappe.call({
                method: CONFIG.serverMethod,
                args: { docname: docname },
                callback: function(r) {
                    console.log('EFRIS submission response:', r);
                    
                    if (r.exc) {
                        const errorMsg = r.exc || 'Unknown error occurred';
                        frappe.msgprint({
                            title: 'EFRIS Error',
                            message: 'Error sending to EFRIS: ' + errorMsg,
                            indicator: 'red'
                        });
                        
                        // Re-enable button
                        efrisBtn.classList.remove('disabled');
                        efrisBtn.style.opacity = '1';
                        efrisBtn.style.pointerEvents = 'auto';
                        efrisBtn.innerText = CONFIG.buttonText;
                        return;
                    }

                    const response = r.message || {};
                    
                    if (response.status === 'success') {
                        frappe.msgprint({
                            title: 'Success',
                            message: 'Invoice successfully sent to EFRIS!',
                            indicator: 'green'
                        });
                        
                        // Remove button and optionally refresh
                        efrisBtn.remove();
                        
                        // Optional: Refresh page after short delay
                        setTimeout(function() {
                            if (confirm('Refresh page to update invoice status?')) {
                                location.reload();
                            }
                        }, 1500);
                        
                    } else if (response.status === 'already_posted') {
                        frappe.msgprint({
                            title: 'Info',
                            message: 'Invoice already posted to EFRIS',
                            indicator: 'blue'
                        });
                        efrisBtn.remove();
                        
                    } else {
                        const errorMsg = response.error || response.message || 'Unknown error';
                        frappe.msgprint({
                            title: 'EFRIS Error',
                            message: 'Error sending to EFRIS: ' + errorMsg,
                            indicator: 'red'
                        });
                        
                        // Re-enable button
                        efrisBtn.disabled = false;
                        efrisBtn.innerText = CONFIG.buttonText;
                    }
                },
                error: function(r) {
                    console.error('Server error:', r);
                    frappe.msgprint({
                        title: 'Server Error',
                        message: 'Failed to communicate with server',
                        indicator: 'red'
                    });
                    
                    // Re-enable button
                    efrisBtn.classList.remove('disabled');
                    efrisBtn.style.opacity = '1';
                    efrisBtn.style.pointerEvents = 'auto';
                    efrisBtn.innerText = CONFIG.buttonText;
                }
            });
        });

        // Check eligibility after adding button
        setTimeout(checkEfrisEligibility, 100);
    }

//     // Enhanced DOM observer with better targeting
        const observer = new MutationObserver(function(mutations) {
        let shouldCheck = false;
        
                // mutations.forEach(function(mutation) {
                //     if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                //         for (let node of mutation.addedNodes) {
                //             if (node.nodeType === 1) { // Element node
                //                 const nodeText = node.innerText || '';
                //                 const nodeClass = node.className || '';
                                
                //                 // Check if it's receipt-related content or contains summary buttons
                //                 if (nodeClass.includes('summary') ||
                //                     nodeClass.includes('pos-receipt') ||
                //                     nodeClass.includes('invoice-wrapper') ||
                //                     nodeClass.includes('print-btn') ||
                //                     nodeClass.includes('summary-btn') ||
                //                     (node.tagName === 'DIV' && nodeClass.includes('btn')) ||
                //                     (node.querySelector && node.querySelector('.print-btn, .summary-btn'))) {
                //                     shouldCheck = true;
                //                     break;
                //                 }
                //             }
                //         }
                //     }
                // });
        // const observer = new MutationObserver(function(mutations) {
        //         let shouldCheck = false;
                
                mutations.forEach(function(mutation) {
                    if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
                        for (let node of mutation.addedNodes) {
                            if (node.nodeType === 1) { // Element node
                                try {
                                    const nodeText = node.innerText || '';
                                    // Properly handle className which could be a string or DOMTokenList
                                    const nodeClass = typeof node.className === 'string' ? 
                                                    node.className : 
                                                    (node.className ? node.className.toString() : '');
                                    
                                    if (nodeClass && (
                                        nodeClass.includes('summary') ||
                                        nodeClass.includes('pos-receipt') ||
                                        nodeClass.includes('invoice-wrapper') ||
                                        nodeClass.includes('print-btn') ||
                                        nodeClass.includes('summary-btn') ||
                                        nodeClass.includes('recent-order') ||
                                        nodeClass.includes('order-item') ||
                                        (node.tagName === 'DIV' && nodeClass.includes('btn'))
                                    )) {
                                        shouldCheck = true;
                                        break;
                                    }
                                    
                                    // Check for relevant child elements
                                    if (node.querySelector && (
                                        node.querySelector('.print-btn, .summary-btn') || 
                                        node.querySelector('[data-name]') ||
                                        node.querySelector('.recent-order-item, .order-summary-item')
                                    )) {
                                        shouldCheck = true;
                                        break;
                                    }
                                } catch (e) {
                                    console.warn('Error processing DOM node:', e);
                                }
                            }
                        }
                    }
                });
                
                if (shouldCheck) {
                    console.log('DOM change detected, checking for buttons...');
                    setTimeout(tryAddEfrisButton, 300);
                }
            });
                
        if (shouldCheck) {
            console.log('DOM change detected, checking for Print Receipt button...');
            setTimeout(tryAddEfrisButton, 200);
        }
    });

    // Start observing
    observer.observe(document.body, { 
        childList: true, 
        subtree: true 
    });

    // Multiple initialization attempts with different delays
    const initializationDelays = [500, 1000, 2000, 3000];
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            initializationDelays.forEach(delay => {
                setTimeout(() => {
                    console.log(`Initialization attempt after ${delay}ms`);
                    tryAddEfrisButton();
                }, delay);
            });
        });
    } else {
        initializationDelays.forEach(delay => {
            setTimeout(() => {
                console.log(`Initialization attempt after ${delay}ms`);
                tryAddEfrisButton();
            }, delay);
        });
    }

    // Also try when POS events occur (if available)
    if (window.frappe && frappe.ui) {
        $(document).on('pos_profile_selected pos_invoice_created pos_payment_complete', function() {
            console.log('POS event detected, trying to add EFRIS button...');
            setTimeout(tryAddEfrisButton, 1000);
        });
    }

    console.log('POS EFRIS Button script initialized');
})();

// Updated version without IIFE for better compatibility
// (function () {
//     'use strict';

//     // Configuration
//     const CONFIG = {
//         buttonText: 'Send To EFRIS',
//         buttonLoadingText: 'Sending...',
//         serverMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.send_pos_to_efris',
//         flagsMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.pos_invoice_flags',
//         debugMode: true // Set to true to keep buttons visible for debugging
//     };

//     // Detect current page context
//     function getCurrentPageContext() {
//         const currentPath = window.location.pathname + window.location.hash;
        
//         if (currentPath.includes('/pos') || currentPath.includes('point-of-sale')) {
//             if (currentPath.includes('recent-orders') || document.querySelector('.recent-order-list, [data-fieldname="recent_orders"]')) {
//                 return 'recent_orders';
//             }
//             return 'pos_receipt';
//         }
        
//         // Check for POS modal or receipt container
//         if (document.querySelector('.pos-receipt-container, .pos-invoice-wrapper, .pos-modal')) {
//             return 'pos_receipt';
//         }
        
//         // Check for recent orders container
//         if (document.querySelector('.recent-order-list, .recent-orders, [data-fieldname="recent_orders"]')) {
//             return 'recent_orders';
//         }
        
//         return 'unknown';
//     }

//     function tryAddEfrisButton() {
//         const pageContext = getCurrentPageContext();
//         console.log('Page context detected:', pageContext);
        
//         let printBtn = null;
//         let targetContainer = null;
        
//         // Different selectors based on page context
//         if (pageContext === 'pos_receipt') {
//             // Receipt view selectors
//             printBtn = document.querySelector('.print-btn') ||
//                       document.querySelector('.summary-btn.print-btn') ||
//                       document.querySelector('[class*="print-btn"]');
                      
//             if (!printBtn) {
//                 const summaryContainer = document.querySelector('.summary-btns, .pos-summary-container, [class*="summary"]');
//                 if (summaryContainer) {
//                     printBtn = summaryContainer.querySelector('.print-btn') || 
//                               summaryContainer.querySelector('[class*="print"]');
//                 }
//             }
            
//         } else if (pageContext === 'recent_orders') {
//             // Recent orders view selectors - look for print buttons in order items
//             const orderItems = document.querySelectorAll('.recent-order-item, .order-summary-item, [data-name]');
            
//             for (const item of orderItems) {
//                 const itemPrintBtn = item.querySelector('.print-btn, [class*="print"], .btn[onclick*="print"]');
//                 if (itemPrintBtn && !itemPrintBtn.dataset.efrisAdded) {
//                     // Process each order item separately
//                     addEfrisButtonToOrderItem(item, itemPrintBtn);
//                 }
//             }
            
//             // Fallback: Try to add button anyway if we can find a docname and suitable container
//             console.log('Attempting fallback button placement...');
//             const docname = findPosInvoiceDocname();
            
//             if (docname) {
//                 console.log('Found docname for fallback:', docname);
//                 // Try to find any suitable container for the button
//                 const fallbackContainer = document.querySelector('.summary-btns') ||
//                                         document.querySelector('.pos-summary-container') ||
//                                         document.querySelector('[class*="summary"]') ||
//                                         document.querySelector('.pos-actions') ||
//                                         document.querySelector('.receipt-actions') ||
//                                         document.querySelector('.btn-group') ||
//                                         document.querySelector('.actions');
                
//                 if (fallbackContainer) {
//                     console.log('Using fallback container for EFRIS button');
//                     createAndAttachEfrisButton(fallbackContainer, null, docname);
//                 } else {
//                     console.log('No fallback container found');
//                 }
//             }
//             return; // Exit early for recent orders as we handle them individually
//         }

//         if (!printBtn) {
//             console.log('Print button not found for context:', pageContext);
//             return;
//         }
        
//         console.log('Found Print button:', printBtn, 'Classes:', printBtn.className);

//         // Prevent duplicate buttons
//         if (printBtn.dataset.efrisAdded) {
//             console.log('EFRIS button already added');
//             return;
//         }

//         // Find the container
//         const container = printBtn.parentElement || 
//                          printBtn.closest('.summary-btns') || 
//                          printBtn.closest('[class*="summary"]') ||
//                          printBtn.parentNode;

//         if (!container) {
//             console.log('Container for EFRIS button not found');
//             return;
//         }

//         createAndAttachEfrisButton(container, printBtn);
//     }

//     // Handle individual order items in recent orders view
//     function addEfrisButtonToOrderItem(orderItem, printBtn) {
//         if (printBtn.dataset.efrisAdded) {
//             return;
//         }

//         // Extract docname from order item
//         const docname = extractDocnameFromOrderItem(orderItem);
//         if (!docname) {
//             console.log('No docname found in order item');
//             return;
//         }

//         console.log('Processing order item with docname:', docname);

//         // Check if this specific invoice needs EFRIS button
//         checkEfrisEligibilityForOrder(docname, function(shouldShow) {
//             if (shouldShow) {
//                 const container = printBtn.parentElement || printBtn.closest('.btn-group, .order-actions') || printBtn.parentNode;
//                 if (container) {
//                     createAndAttachEfrisButton(container, printBtn, docname);
//                 }
//             }
//         });
//     }

//     // Extract docname from order item in recent orders
//     function extractDocnameFromOrderItem(orderItem) {
//         // Check data attributes
//         const dataName = orderItem.getAttribute('data-name') || 
//                          orderItem.getAttribute('data-docname') ||
//                          orderItem.getAttribute('data-invoice-name');
        
//         if (dataName) {
//             return dataName;
//         }

//         // Look for docname in text content of the item
//         const textElements = orderItem.querySelectorAll('div, span, p, a, small, strong, b');
//         for (const element of textElements) {
//             const text = element.innerText?.trim() || element.textContent?.trim();
//             if (text) {
//                 const patterns = [
//                     /\b(FBK-PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b([A-Z]+-PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b(PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b([A-Z]{2,4}-[0-9]{4}-[0-9]+)\b/i
//                 ];
                
//                 for (const pattern of patterns) {
//                     const match = text.match(pattern);
//                     if (match && match[1]) {
//                         return match[1];
//                     }
//                 }
//             }
//         }

//         return null;
//     }

//     // Create and attach EFRIS button - with fallback for no print button
//     function createAndAttachEfrisButton(container, printBtn = null, knownDocname = null) {
//         // If no print button found, try to find a suitable container anyway
//         if (!container && !printBtn) {
//             // Look for common POS containers
//             container = document.querySelector('.summary-btns') ||
//                        document.querySelector('.pos-summary-container') ||
//                        document.querySelector('[class*="summary"]') ||
//                        document.querySelector('.pos-actions') ||
//                        document.querySelector('.receipt-actions');
                       
//             if (container) {
//                 console.log('Using fallback container:', container.className);
//             } else {
//                 console.log('No suitable container found for EFRIS button');
//                 return;
//             }
//         }
        
//         // Create the EFRIS button
//         const efrisBtn = document.createElement('div');
//         efrisBtn.className = 'summary-btn btn btn-default efris-btn mr-4';
//         efrisBtn.style.cursor = 'pointer';
//         efrisBtn.style.margin = '5px';
//         efrisBtn.style.padding = '8px 12px';
//         efrisBtn.style.border = '1px solid #ccc';
//         efrisBtn.style.borderRadius = '4px';
//         efrisBtn.style.backgroundColor = '#f8f9fa';
//         efrisBtn.innerText = CONFIG.buttonText;
//         efrisBtn.setAttribute('data-efris-btn', 'true');
        
//         // Initially disabled until server check
//         efrisBtn.classList.add('disabled');
//         efrisBtn.style.opacity = '0.6';
//         efrisBtn.style.pointerEvents = 'none';

//         // Insert the button
//         if (printBtn && printBtn.nextSibling) {
//             container.insertBefore(efrisBtn, printBtn.nextSibling);
//         } else {
//             container.appendChild(efrisBtn);
//         }

//         // Mark print button as processed (if exists)
//         if (printBtn) {
//             printBtn.dataset.efrisAdded = '1';
//         }

//         console.log('EFRIS button added to DOM');

//         // Check eligibility
//         const docname = knownDocname || findPosInvoiceDocname();
//         if (docname) {
//             checkEfrisEligibility(efrisBtn, docname);
//         } else {
//             console.log('No docname found, removing button');
//             efrisBtn.remove();
//         }

//         // Add click handler
//         efrisBtn.addEventListener('click', function(e) {
//             handleEfrisButtonClick(e, efrisBtn, docname);
//         });
//     }

//     // Enhanced docname finding with better error handling
//     function findPosInvoiceDocname() {
//         console.log('🔍 Looking for POS Invoice docname...');
        
//         // Method 1: Look for anchor tags with pos-invoice links
//         const posInvoiceSelectors = [
//             'a[href*="pos-invoice"]',
//             'a[href*="pos_invoice"]', 
//             'a[href*="/app/pos-invoice/"]',
//             'a[href*="/app/pos_invoice/"]'
//         ];

//         for (const selector of posInvoiceSelectors) {
//             const anchor = document.querySelector(selector);
//             if (anchor) {
//                 const href = anchor.getAttribute('href') || '';
//                 const match = href.match(/pos[-_]?invoice\/([^\/\?#]+)/i);
//                 if (match && match[1]) {
//                     const docname = decodeURIComponent(match[1]);
//                     console.log('✅ Found docname from URL:', docname);
//                     return docname;
//                 }
                
//                 const anchorText = anchor.innerText?.trim();
//                 if (anchorText && /^[A-Z0-9-]+$/i.test(anchorText)) {
//                     console.log('✅ Found docname from anchor text:', anchorText);
//                     return anchorText;
//                 }
//             }
//         }

//         // Method 2: Enhanced pattern matching
//         const textElements = document.querySelectorAll('div, span, p, a, small, h1, h2, h3, h4, h5, h6, strong, b, [class*="invoice"], [class*="receipt"]');
//         console.log('🔍 Scanning', textElements.length, 'elements for invoice patterns...');
        
//         for (const element of textElements) {
//             const text = element.innerText?.trim() || element.textContent?.trim();
//             if (text) {
//                 const patterns = [
//                     /\b(FBK-PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b([A-Z]+-PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b(PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b(POSINV-[A-Z0-9-]+)\b/i,
//                     /\b(POS-INV-[A-Z0-9-]+)\b/i,
//                     /\b([A-Z]{2,4}-[0-9]{4}-[0-9]+)\b/i
//                 ];
                
//                 for (const pattern of patterns) {
//                     const match = text.match(pattern);
//                     if (match && match[1]) {
//                         console.log('✅ Found docname from text pattern:', match[1], 'in element:', element.tagName, 'text:', text.substring(0, 100));
//                         return match[1];
//                     }
//                 }
//             }
//         }

//         // Method 3: Check current context
//         if (window.cur_frm && window.cur_frm.doc && window.cur_frm.doc.name) {
//             const contextDocname = window.cur_frm.doc.name;
//             console.log('✅ Found docname from current form context:', contextDocname);
//             return contextDocname;
//         }

//         // Method 4: Check for data attributes
//         const elementsWithData = document.querySelectorAll('[data-name], [data-docname], [id*="invoice"], [data-invoice]');
//         console.log('🔍 Checking', elementsWithData.length, 'elements with data attributes...');
        
//         for (const element of elementsWithData) {
//             const dataName = element.getAttribute('data-name') || 
//                             element.getAttribute('data-docname') ||
//                             element.id;
                            
//             if (dataName && /^[A-Z0-9-]+$/i.test(dataName) && dataName.length > 5) {
//                 console.log('✅ Found docname from data attribute:', dataName);
//                 return dataName;
//             }
//         }

//         console.log('❌ Could not find POS Invoice docname');
//         console.log('📋 Available text samples:', 
//                    Array.from(document.querySelectorAll('*'))
//                        .filter(el => el.offsetParent !== null && el.innerText?.trim())
//                        .slice(0, 10)
//                        .map(el => el.innerText.trim().substring(0, 100))
//         );
//         return null;
//     }

//     // Check EFRIS eligibility for a specific docname
//     function checkEfrisEligibilityForOrder(docname, callback) {
//         console.log('🔍 Starting EFRIS eligibility check for:', docname);
        
//         frappe.call({
//             method: CONFIG.flagsMethod,
//             args: { docname: docname },
//             callback: function(r) {
//                 console.log('📞 Server response received for', docname, ':', r);
                
//                 if (r.exc) {
//                     console.error('❌ Error checking EFRIS flags for', docname, ':', r.exc);
//                     console.error('Full error object:', r);
//                     callback(false);
//                     return;
//                 }

//                 const data = r.message || {};
//                 console.log('📋 EFRIS flags for', docname, ':', JSON.stringify(data, null, 2));
                
//                 // Check if invoice is submitted, marked for EFRIS, and not yet posted
//                 const isSubmitted = data.docstatus === 1;
//                 const isEfrisInvoice = data.efris_invoice === true || data.efris_invoice === 1;
//                 const notPosted = data.efris_posted === false || data.efris_posted === 0 || !data.efris_posted;
                
//                 console.log(`📊 Invoice ${docname} Analysis:`);
//                 console.log(`   📝 Submitted (docstatus=1): ${isSubmitted} (actual: ${data.docstatus})`);
//                 console.log(`   🏷️  EFRIS Invoice: ${isEfrisInvoice} (actual: ${data.efris_invoice})`);
//                 console.log(`   📤 Not Posted: ${notPosted} (actual: ${data.efris_posted})`);
                
//                 const shouldShow = isSubmitted && isEfrisInvoice && notPosted;
//                 console.log(`🎯 Final Decision - Show Button: ${shouldShow}`);
                
//                 if (!shouldShow) {
//                     console.log('🚫 Button will be REMOVED because:');
//                     if (!isSubmitted) console.log('   - Invoice is not submitted (docstatus !== 1)');
//                     if (!isEfrisInvoice) console.log('   - Invoice is not marked for EFRIS');
//                     if (!notPosted) console.log('   - Invoice is already posted to EFRIS');
//                 }
                
//                 callback(shouldShow);
//             },
//             error: function(r) {
//                 console.error('🔥 Server error for', docname, ':', r);
//                 callback(false);
//             }
//         });
//     }

//     // Check EFRIS eligibility and update button state
//     function checkEfrisEligibility(efrisBtn, docname) {
//         if (!docname) {
//             console.log('❌ No docname provided, removing button');
//             efrisBtn.remove();
//             return;
//         }

//         console.log('🔍 Checking EFRIS eligibility for:', docname);
//         console.log('🔘 Button current state: visible, disabled');

//         checkEfrisEligibilityForOrder(docname, function(shouldShow) {
//             console.log('🎯 Eligibility check result for', docname, ':', shouldShow);
            
//             if (shouldShow) {
//                 // Enable button
//                 efrisBtn.classList.remove('disabled');
//                 efrisBtn.style.opacity = '1';
//                 efrisBtn.style.pointerEvents = 'auto';
//                 efrisBtn.style.backgroundColor = '#28a745';
//                 efrisBtn.style.color = 'white';
//                 console.log('✅ EFRIS button ENABLED for:', docname);
//             } else {
//                 if (CONFIG.debugMode) {
//                     // In debug mode, keep button but mark it as debug
//                     efrisBtn.innerText = 'EFRIS (DEBUG - NOT ELIGIBLE)';
//                     efrisBtn.style.backgroundColor = '#ffc107';
//                     efrisBtn.style.color = 'black';
//                     efrisBtn.style.opacity = '1';
//                     console.log('🐛 DEBUG MODE: Keeping button visible despite not being eligible');
//                 } else {
//                     console.log('🗑️  REMOVING EFRIS button for:', docname, '(not eligible)');
//                     efrisBtn.remove();
//                 }
//             }
//         });
//     }

//     // Handle EFRIS button click
//     function handleEfrisButtonClick(e, efrisBtn, docname) {
//         e.preventDefault();
        
//         if (efrisBtn.classList.contains('disabled')) {
//             return;
//         }
        
//         if (!confirm('Send this POS Invoice to EFRIS now?')) {
//             return;
//         }

//         const finalDocname = docname || findPosInvoiceDocname();
//         if (!finalDocname) {
//             frappe.msgprint({
//                 title: 'Error',
//                 message: 'Could not detect POS Invoice name.',
//                 indicator: 'red'
//             });
//             return;
//         }

//         // Set loading state
//         efrisBtn.classList.add('disabled');
//         efrisBtn.style.opacity = '0.6';
//         efrisBtn.style.pointerEvents = 'none';
//         efrisBtn.innerText = CONFIG.buttonLoadingText;

//         console.log('Sending to EFRIS:', finalDocname);

//         // Send to EFRIS
//         frappe.call({
//             method: CONFIG.serverMethod,
//             args: { docname: finalDocname },
//             callback: function(r) {
//                 console.log('EFRIS submission response:', r);
                
//                 if (r.exc) {
//                     const errorMsg = r.exc || 'Unknown error occurred';
//                     frappe.msgprint({
//                         title: 'EFRIS Error',
//                         message: 'Error sending to EFRIS: ' + errorMsg,
//                         indicator: 'red'
//                     });
                    
//                     // Re-enable button
//                     efrisBtn.classList.remove('disabled');
//                     efrisBtn.style.opacity = '1';
//                     efrisBtn.style.pointerEvents = 'auto';
//                     efrisBtn.innerText = CONFIG.buttonText;
//                     return;
//                 }

//                 const response = r.message || {};
                
//                 if (response.status === 'success') {
//                     frappe.msgprint({
//                         title: 'Success',
//                         message: 'Invoice successfully sent to EFRIS!',
//                         indicator: 'green'
//                     });
                    
//                     efrisBtn.remove();
                    
//                     setTimeout(function() {
//                         if (confirm('Refresh page to update invoice status?')) {
//                             location.reload();
//                         }
//                     }, 1500);
                    
//                 } else if (response.status === 'already_posted') {
//                     frappe.msgprint({
//                         title: 'Info',
//                         message: 'Invoice already posted to EFRIS',
//                         indicator: 'blue'
//                     });
//                     efrisBtn.remove();
                    
//                 } else {
//                     const errorMsg = response.error || response.message || 'Unknown error';
//                     frappe.msgprint({
//                         title: 'EFRIS Error',
//                         message: 'Error sending to EFRIS: ' + errorMsg,
//                         indicator: 'red'
//                     });
                    
//                     // Re-enable button
//                     efrisBtn.classList.remove('disabled');
//                     efrisBtn.style.opacity = '1';
//                     efrisBtn.style.pointerEvents = 'auto';
//                     efrisBtn.innerText = CONFIG.buttonText;
//                 }
//             },
//             error: function(r) {
//                 console.error('Server error:', r);
//                 frappe.msgprint({
//                     title: 'Server Error',
//                     message: 'Failed to communicate with server',
//                     indicator: 'red'
//                 });
                
//                 // Re-enable button
//                 efrisBtn.classList.remove('disabled');
//                 efrisBtn.style.opacity = '1';
//                 efrisBtn.style.pointerEvents = 'auto';
//                 efrisBtn.innerText = CONFIG.buttonText;
//             }
//         });
//     }

//     // Enhanced DOM observer with proper type checking
//     const observer = new MutationObserver(function(mutations) {
//         let shouldCheck = false;
        
//         mutations.forEach(function(mutation) {
//             if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
//                 for (let node of mutation.addedNodes) {
//                     if (node.nodeType === 1) { // Element node
//                         try {
//                             const nodeText = node.innerText || '';
//                             // Properly handle className which could be a string or DOMTokenList
//                             const nodeClass = typeof node.className === 'string' ? 
//                                              node.className : 
//                                              (node.className ? node.className.toString() : '');
                            
//                             if (nodeClass && (
//                                 nodeClass.includes('summary') ||
//                                 nodeClass.includes('pos-receipt') ||
//                                 nodeClass.includes('invoice-wrapper') ||
//                                 nodeClass.includes('print-btn') ||
//                                 nodeClass.includes('summary-btn') ||
//                                 nodeClass.includes('recent-order') ||
//                                 nodeClass.includes('order-item') ||
//                                 (node.tagName === 'DIV' && nodeClass.includes('btn'))
//                             )) {
//                                 shouldCheck = true;
//                                 break;
//                             }
                            
//                             // Check for relevant child elements
//                             if (node.querySelector && (
//                                 node.querySelector('.print-btn, .summary-btn') || 
//                                 node.querySelector('[data-name]') ||
//                                 node.querySelector('.recent-order-item, .order-summary-item')
//                             )) {
//                                 shouldCheck = true;
//                                 break;
//                             }
//                         } catch (e) {
//                             console.warn('Error processing DOM node:', e);
//                         }
//                     }
//                 }
//             }
//         });
        
//         if (shouldCheck) {
//             console.log('DOM change detected, checking for buttons...');
//             setTimeout(tryAddEfrisButton, 300);
//         }
//     });

//     // Start observing
//     observer.observe(document.body, { 
//         childList: true, 
//         subtree: true 
//     });

//     // Multiple initialization attempts with different strategies
//     const initializationDelays = [500, 1000, 2000, 3000, 5000, 8000];
    
//     function initialize() {
//         initializationDelays.forEach((delay, index) => {
//             setTimeout(() => {
//                 console.log(`Initialization attempt ${index + 1} after ${delay}ms`);
//                 tryAddEfrisButton();
                
//                 // Also try to add to any existing receipts or orders on the page
//                 if (index > 2) { // After 3rd attempt, be more aggressive
//                     addToExistingReceipts();
//                 }
//             }, delay);
//         });
//     }
    
//     // Try to add EFRIS buttons to any existing receipts/orders on the page
//     function addToExistingReceipts() {
//         console.log('Scanning for existing receipts/orders...');
        
//         // Look for any elements that might contain invoice names
//         const possibleInvoiceElements = document.querySelectorAll('[data-name], [data-docname]');
//         possibleInvoiceElements.forEach(el => {
//             const docname = el.getAttribute('data-name') || el.getAttribute('data-docname');
//             if (docname && docname.match(/^[A-Z0-9-]+$/)) {
//                 console.log('Found potential invoice element:', docname);
//                 // Try to find a button container near this element
//                 const nearbyContainer = el.querySelector('.btn-group, .actions, [class*="btn"]') ||
//                                       el.closest('[class*="summary"], [class*="action"]');
//                 if (nearbyContainer && !nearbyContainer.querySelector('[data-efris-btn]')) {
//                     console.log('Adding EFRIS button to existing receipt:', docname);
//                     createAndAttachEfrisButton(nearbyContainer, null, docname);
//                 }
//             }
//         });
        
//         // Also look for text content that looks like invoice names
//         const allElements = document.querySelectorAll('div, span, p, a');
//         for (const el of allElements) {
//             if (el.dataset.efrisProcessed) continue;
            
//             const text = (el.innerText || el.textContent || '').trim();
//             const match = text.match(/\b(FBK-PSINV-[0-9]{4}-[0-9]+|[A-Z]+-PSINV-[0-9]{4}-[0-9]+)\b/);
            
//             if (match) {
//                 console.log('Found invoice name in text:', match[1]);
//                 el.dataset.efrisProcessed = 'true';
                
//                 // Look for a nearby container that might hold buttons
//                 const container = el.closest('[class*="summary"], [class*="action"], .receipt, .order') ||
//                                 el.parentElement;
                                
//                 if (container && !container.querySelector('[data-efris-btn]')) {
//                     console.log('Adding EFRIS button near invoice text');
//                     createAndAttachEfrisButton(container, null, match[1]);
//                 }
//                 break; // Only process one per scan
//             }
//         }
//     }

//     if (document.readyState === 'loading') {
//         document.addEventListener('DOMContentLoaded', initialize);
//     } else {
//         initialize();
//     }

//     // Listen for POS events
//     if (window.frappe && frappe.ui) {
//         $(document).on('pos_profile_selected pos_invoice_created pos_payment_complete recent_orders_loaded', function(e) {
//             console.log('POS event detected:', e.type);
//             setTimeout(tryAddEfrisButton, 1000);
//         });
//     }

//     // Listen for route changes (for SPA navigation)
//     if (window.frappe && frappe.router) {
//         frappe.router.on('change', function() {
//             console.log('Route changed, re-initializing EFRIS buttons...');
//             setTimeout(tryAddEfrisButton, 1500);
//         });
//     }

//     console.log('Enhanced POS EFRIS Button script initialized');
// })();

//latest update  V-3

// (function () {
//     'use strict';

//     // Configuration
//     const CONFIG = {
//         buttonText: 'Send To EFRIS',
//         buttonLoadingText: 'Sending...',
//         serverMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.send_pos_to_efris',
//         flagsMethod: 'uganda_compliance.efris.api_classes.pos_send_efris.pos_invoice_flags',
//         debugMode: false // Set to false for production
//     };

//     // Detect current page context
//     function getCurrentPageContext() {
//         const currentPath = window.location.pathname + window.location.hash;
        
//         if (currentPath.includes('/pos') || currentPath.includes('point-of-sale')) {
//             if (currentPath.includes('recent-orders') || document.querySelector('.recent-order-list, [data-fieldname="recent_orders"]')) {
//                 return 'recent_orders';
//             }
//             return 'pos_receipt';
//         }
        
//         // Check for POS modal or receipt container
//         if (document.querySelector('.pos-receipt-container, .pos-invoice-wrapper, .pos-modal')) {
//             return 'pos_receipt';
//         }
        
//         // Check for recent orders container
//         if (document.querySelector('.recent-order-list, .recent-orders, [data-fieldname="recent_orders"]')) {
//             return 'recent_orders';
//         }
        
//         return 'unknown';
//     }

//     function tryAddEfrisButton() {
//         const pageContext = getCurrentPageContext();
//         console.log('Page context detected:', pageContext);
        
//         let printBtn = null;
//         let targetContainer = null;
        
//         // Different selectors based on page context
//         if (pageContext === 'pos_receipt') {
//             // Receipt view selectors
//             printBtn = document.querySelector('.print-btn') ||
//                       document.querySelector('.summary-btn.print-btn') ||
//                       document.querySelector('[class*="print-btn"]');
                      
//             if (!printBtn) {
//                 const summaryContainer = document.querySelector('.summary-btns, .pos-summary-container, [class*="summary"]');
//                 if (summaryContainer) {
//                     printBtn = summaryContainer.querySelector('.print-btn') || 
//                               summaryContainer.querySelector('[class*="print"]');
//                 }
//             }
            
//         } else if (pageContext === 'recent_orders') {
//             // Recent orders view selectors - look for print buttons in order items
//             const orderItems = document.querySelectorAll('.recent-order-item, .order-summary-item, [data-name]');
            
//             for (const item of orderItems) {
//                 const itemPrintBtn = item.querySelector('.print-btn, [class*="print"], .btn[onclick*="print"]');
//                 if (itemPrintBtn && !itemPrintBtn.dataset.efrisAdded) {
//                     // Process each order item separately
//                     addEfrisButtonToOrderItem(item, itemPrintBtn);
//                 }
//             }
            
//             // Fallback: Try to add button anyway if we can find a docname and suitable container
//             console.log('Attempting fallback button placement...');
//             const docname = findPosInvoiceDocname();
            
//             if (docname) {
//                 console.log('Found docname for fallback:', docname);
//                 // Try to find any suitable container for the button
//                 const fallbackContainer = document.querySelector('.summary-btns') ||
//                                         document.querySelector('.pos-summary-container') ||
//                                         document.querySelector('[class*="summary"]') ||
//                                         document.querySelector('.pos-actions') ||
//                                         document.querySelector('.receipt-actions') ||
//                                         document.querySelector('.btn-group') ||
//                                         document.querySelector('.actions');
                
//                 if (fallbackContainer) {
//                     console.log('Using fallback container for EFRIS button');
//                     createAndAttachEfrisButton(fallbackContainer, null, docname);
//                 } else {
//                     console.log('No fallback container found');
//                 }
//             }
//             return; // Exit early for recent orders as we handle them individually
//         }

//         if (!printBtn) {
//             console.log('Print button not found for context:', pageContext);
//             return;
//         }
        
//         console.log('Found Print button:', printBtn, 'Classes:', printBtn.className);

//         // Prevent duplicate buttons
//         if (printBtn.dataset.efrisAdded) {
//             console.log('EFRIS button already added');
//             return;
//         }

//         // Find the container
//         const container = printBtn.parentElement || 
//                          printBtn.closest('.summary-btns') || 
//                          printBtn.closest('[class*="summary"]') ||
//                          printBtn.parentNode;

//         if (!container) {
//             console.log('Container for EFRIS button not found');
//             return;
//         }

//         createAndAttachEfrisButton(container, printBtn);
//     }

//     // Handle individual order items in recent orders view
//     function addEfrisButtonToOrderItem(orderItem, printBtn) {
//         if (printBtn.dataset.efrisAdded) {
//             return;
//         }

//         // Extract docname from order item
//         const docname = extractDocnameFromOrderItem(orderItem);
//         if (!docname) {
//             console.log('No docname found in order item');
//             return;
//         }

//         console.log('Processing order item with docname:', docname);

//         // Check if this specific invoice needs EFRIS button
//         checkEfrisEligibilityForOrder(docname, function(shouldShow) {
//             if (shouldShow) {
//                 const container = printBtn.parentElement || printBtn.closest('.btn-group, .order-actions') || printBtn.parentNode;
//                 if (container) {
//                     createAndAttachEfrisButton(container, printBtn, docname);
//                 }
//             }
//         });
//     }

//     // Extract docname from order item in recent orders
//     function extractDocnameFromOrderItem(orderItem) {
//         // Check data attributes
//         const dataName = orderItem.getAttribute('data-name') || 
//                          orderItem.getAttribute('data-docname') ||
//                          orderItem.getAttribute('data-invoice-name');
        
//         if (dataName) {
//             return dataName;
//         }

//         // Look for docname in text content of the item
//         const textElements = orderItem.querySelectorAll('div, span, p, a, small, strong, b');
//         for (const element of textElements) {
//             const text = element.innerText?.trim() || element.textContent?.trim();
//             if (text) {
//                 const patterns = [
//                     /\b(FBK-PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b([A-Z]+-PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b(PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b([A-Z]{2,4}-[0-9]{4}-[0-9]+)\b/i
//                 ];
                
//                 for (const pattern of patterns) {
//                     const match = text.match(pattern);
//                     if (match && match[1]) {
//                         return match[1];
//                     }
//                 }
//             }
//         }

//         return null;
//     }

//     // Create and attach EFRIS button - with fallback for no print button
//     function createAndAttachEfrisButton(container, printBtn = null, knownDocname = null) {
//         // Check if EFRIS button already exists
//         if (container.querySelector('[data-efris-btn]')) {
//             console.log('EFRIS button already exists in container');
//             return;
//         }
        
//         // If no print button found, try to find a suitable container anyway
//         if (!container && !printBtn) {
//             // Look for common POS containers
//             container = document.querySelector('.summary-btns') ||
//                        document.querySelector('.pos-summary-container') ||
//                        document.querySelector('[class*="summary"]') ||
//                        document.querySelector('.pos-actions') ||
//                        document.querySelector('.receipt-actions');
                       
//             if (container) {
//                 console.log('Using fallback container:', container.className);
//             } else {
//                 console.log('No suitable container found for EFRIS button');
//                 return;
//             }
//         }
        
//         // Create the EFRIS button
//         const efrisBtn = document.createElement('div');
//         efrisBtn.className = 'summary-btn btn btn-default efris-btn mr-4';
//         efrisBtn.style.cssText = `
//             cursor: pointer;
//             margin: 5px;
//             padding: 8px 12px;
//             border: 1px solid #ccc;
//             border-radius: 4px;
//             background-color: #f8f9fa;
//             color: #333;
//             font-size: 14px;
//             display: inline-block;
//             text-align: center;
//             user-select: none;
//         `;
//         efrisBtn.innerText = CONFIG.buttonText;
//         efrisBtn.setAttribute('data-efris-btn', 'true');
        
//         // Initially disabled until server check
//         efrisBtn.classList.add('disabled');
//         efrisBtn.style.opacity = '0.6';
//         efrisBtn.style.pointerEvents = 'none';

//         // Insert the button
//         if (printBtn && printBtn.nextSibling) {
//             container.insertBefore(efrisBtn, printBtn.nextSibling);
//         } else {
//             container.appendChild(efrisBtn);
//         }

//         // Mark print button as processed (if exists)
//         if (printBtn) {
//             printBtn.dataset.efrisAdded = '1';
//         }

//         console.log('EFRIS button added to DOM');

//         // Check eligibility
//         const docname = knownDocname || findPosInvoiceDocname();
//         if (docname) {
//             checkEfrisEligibility(efrisBtn, docname);
//         } else {
//             console.log('No docname found, removing button');
//             efrisBtn.remove();
//         }

//         // Add click handler
//         efrisBtn.addEventListener('click', function(e) {
//             handleEfrisButtonClick(e, efrisBtn, docname);
//         });
//     }

//     // Enhanced docname finding with better error handling
//     function findPosInvoiceDocname() {
//         console.log('🔍 Looking for POS Invoice docname...');
        
//         // Method 1: Look for anchor tags with pos-invoice links
//         const posInvoiceSelectors = [
//             'a[href*="pos-invoice"]',
//             'a[href*="pos_invoice"]', 
//             'a[href*="/app/pos-invoice/"]',
//             'a[href*="/app/pos_invoice/"]'
//         ];

//         for (const selector of posInvoiceSelectors) {
//             const anchor = document.querySelector(selector);
//             if (anchor) {
//                 const href = anchor.getAttribute('href') || '';
//                 const match = href.match(/pos[-_]?invoice\/([^\/\?#]+)/i);
//                 if (match && match[1]) {
//                     const docname = decodeURIComponent(match[1]);
//                     console.log('✅ Found docname from URL:', docname);
//                     return docname;
//                 }
                
//                 const anchorText = anchor.innerText?.trim();
//                 if (anchorText && /^[A-Z0-9-]+$/i.test(anchorText)) {
//                     console.log('✅ Found docname from anchor text:', anchorText);
//                     return anchorText;
//                 }
//             }
//         }

//         // Method 2: Enhanced pattern matching
//         const textElements = document.querySelectorAll('div, span, p, a, small, h1, h2, h3, h4, h5, h6, strong, b, [class*="invoice"], [class*="receipt"]');
//         console.log('🔍 Scanning', textElements.length, 'elements for invoice patterns...');
        
//         for (const element of textElements) {
//             const text = element.innerText?.trim() || element.textContent?.trim();
//             if (text) {
//                 const patterns = [
//                     /\b(FBK-PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b([A-Z]+-PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b(PSINV-[0-9]{4}-[0-9]+)\b/i,
//                     /\b(POSINV-[A-Z0-9-]+)\b/i,
//                     /\b(POS-INV-[A-Z0-9-]+)\b/i,
//                     /\b([A-Z]{2,4}-[0-9]{4}-[0-9]+)\b/i
//                 ];
                
//                 for (const pattern of patterns) {
//                     const match = text.match(pattern);
//                     if (match && match[1]) {
//                         console.log('✅ Found docname from text pattern:', match[1], 'in element:', element.tagName, 'text:', text.substring(0, 100));
//                         return match[1];
//                     }
//                 }
//             }
//         }

//         // Method 3: Check current context
//         if (window.cur_frm && window.cur_frm.doc && window.cur_frm.doc.name) {
//             const contextDocname = window.cur_frm.doc.name;
//             console.log('✅ Found docname from current form context:', contextDocname);
//             return contextDocname;
//         }

//         // Method 4: Check for data attributes
//         const elementsWithData = document.querySelectorAll('[data-name], [data-docname], [id*="invoice"], [data-invoice]');
//         console.log('🔍 Checking', elementsWithData.length, 'elements with data attributes...');
        
//         for (const element of elementsWithData) {
//             const dataName = element.getAttribute('data-name') || 
//                             element.getAttribute('data-docname') ||
//                             element.id;
                            
//             if (dataName && /^[A-Z0-9-]+$/i.test(dataName) && dataName.length > 5) {
//                 console.log('✅ Found docname from data attribute:', dataName);
//                 return dataName;
//             }
//         }

//         console.log('❌ Could not find POS Invoice docname');
//         return null;
//     }

//     // Check EFRIS eligibility for a specific docname
//     function checkEfrisEligibilityForOrder(docname, callback) {
//         console.log('🔍 Starting EFRIS eligibility check for:', docname);
        
//         frappe.call({
//             method: CONFIG.flagsMethod,
//             args: { docname: docname },
//             callback: function(r) {
//                 console.log('📞 Server response received for', docname, ':', r);
                
//                 if (r.exc) {
//                     console.error('❌ Error checking EFRIS flags for', docname, ':', r.exc);
//                     console.error('Full error object:', r);
//                     callback(false);
//                     return;
//                 }

//                 const data = r.message || {};
//                 console.log('📋 EFRIS flags for', docname, ':', JSON.stringify(data, null, 2));
                
//                 // Check if server returned an error
//                 if (data.error || !data.success) {
//                     console.log('❌ Server returned error:', data.error || 'Unknown error');
//                     callback(false);
//                     return;
//                 }
                
//                 // Check if invoice is submitted, marked for EFRIS, and not yet posted
//                 const isSubmitted = data.docstatus === 1;
//                 const isEfrisInvoice = data.efris_invoice === true || data.efris_invoice === 1;
//                 const notPosted = data.efris_posted === false || data.efris_posted === 0 || !data.efris_posted;
                
//                 console.log(`📊 Invoice ${docname} Analysis:`);
//                 console.log(`   📝 Submitted (docstatus=1): ${isSubmitted} (actual: ${data.docstatus})`);
//                 console.log(`   🏷️  EFRIS Invoice: ${isEfrisInvoice} (actual: ${data.efris_invoice})`);
//                 console.log(`   📤 Not Posted: ${notPosted} (actual: ${data.efris_posted})`);
                
//                 const shouldShow = isSubmitted && isEfrisInvoice && notPosted;
//                 console.log(`🎯 Final Decision - Show Button: ${shouldShow}`);
                
//                 if (!shouldShow) {
//                     console.log('🚫 Button will be HIDDEN because:');
//                     if (!isSubmitted) console.log('   - Invoice is not submitted (docstatus !== 1)');
//                     if (!isEfrisInvoice) console.log('   - Invoice is not marked for EFRIS');
//                     if (!notPosted) console.log('   - Invoice is already posted to EFRIS');
//                 }
                
//                 callback(shouldShow);
//             },
//             error: function(r) {
//                 console.error('🔥 Server error for', docname, ':', r);
//                 callback(false);
//             }
//         });
//     }

//     // Check EFRIS eligibility and update button state
//     function checkEfrisEligibility(efrisBtn, docname) {
//         if (!docname) {
//             console.log('❌ No docname provided, removing button');
//             efrisBtn.remove();
//             return;
//         }

//         console.log('🔍 Checking EFRIS eligibility for:', docname);
//         console.log('🔘 Button current state: visible, disabled');

//         checkEfrisEligibilityForOrder(docname, function(shouldShow) {
//             console.log('🎯 Eligibility check result for', docname, ':', shouldShow);
            
//             if (shouldShow) {
//                 // Enable button
//                 efrisBtn.classList.remove('disabled');
//                 efrisBtn.style.opacity = '1';
//                 efrisBtn.style.pointerEvents = 'auto';
//                 efrisBtn.style.backgroundColor = '#28a745';
//                 efrisBtn.style.color = 'white';
//                 efrisBtn.style.borderColor = '#28a745';
//                 console.log('✅ EFRIS button ENABLED for:', docname);
//             } else {
//                 if (CONFIG.debugMode) {
//                     // In debug mode, keep button but mark it as debug
//                     efrisBtn.innerText = 'EFRIS (DEBUG - NOT ELIGIBLE)';
//                     efrisBtn.style.backgroundColor = '#ffc107';
//                     efrisBtn.style.color = 'black';
//                     efrisBtn.style.opacity = '1';
//                     console.log('🐛 DEBUG MODE: Keeping button visible despite not being eligible');
//                 } else {
//                     console.log('🗑️  REMOVING EFRIS button for:', docname, '(not eligible)');
//                     efrisBtn.remove();
//                 }
//             }
//         });
//     }

//     // Handle EFRIS button click
//     function handleEfrisButtonClick(e, efrisBtn, docname) {
//         e.preventDefault();
        
//         if (efrisBtn.classList.contains('disabled')) {
//             return;
//         }
        
//         if (!confirm('Send this POS Invoice to EFRIS now?')) {
//             return;
//         }

//         const finalDocname = docname || findPosInvoiceDocname();
//         if (!finalDocname) {
//             frappe.msgprint({
//                 title: 'Error',
//                 message: 'Could not detect POS Invoice name.',
//                 indicator: 'red'
//             });
//             return;
//         }

//         // Set loading state
//         efrisBtn.classList.add('disabled');
//         efrisBtn.style.opacity = '0.6';
//         efrisBtn.style.pointerEvents = 'none';
//         efrisBtn.style.backgroundColor = '#6c757d';
//         efrisBtn.innerText = CONFIG.buttonLoadingText;

//         console.log('Sending to EFRIS:', finalDocname);

//         // Send to EFRIS
//         frappe.call({
//             method: CONFIG.serverMethod,
//             args: { docname: finalDocname },
//             callback: function(r) {
//                 console.log('EFRIS submission response:', r);
                
//                 if (r.exc) {
//                     const errorMsg = r.exc || 'Unknown error occurred';
//                     frappe.msgprint({
//                         title: 'EFRIS Error',
//                         message: 'Error sending to EFRIS: ' + errorMsg,
//                         indicator: 'red'
//                     });
                    
//                     // Re-enable button
//                     efrisBtn.classList.remove('disabled');
//                     efrisBtn.style.opacity = '1';
//                     efrisBtn.style.pointerEvents = 'auto';
//                     efrisBtn.style.backgroundColor = '#28a745';
//                     efrisBtn.innerText = CONFIG.buttonText;
//                     return;
//                 }

//                 const response = r.message || {};
                
//                 if (response.status === 'success') {
//                     frappe.msgprint({
//                         title: 'Success',
//                         message: 'Invoice successfully sent to EFRIS!',
//                         indicator: 'green'
//                     });
                    
//                     // Remove button after successful submission
//                     efrisBtn.remove();
                    
//                     setTimeout(function() {
//                         if (confirm('Refresh page to update invoice status?')) {
//                             location.reload();
//                         }
//                     }, 1500);
                    
//                 } else if (response.status === 'already_posted') {
//                     frappe.msgprint({
//                         title: 'Info',
//                         message: 'Invoice already posted to EFRIS',
//                         indicator: 'blue'
//                     });
//                     efrisBtn.remove();
                    
//                 } else {
//                     const errorMsg = response.error || response.message || 'Unknown error';
//                     frappe.msgprint({
//                         title: 'EFRIS Error',
//                         message: 'Error sending to EFRIS: ' + errorMsg,
//                         indicator: 'red'
//                     });
                    
//                     // Re-enable button
//                     efrisBtn.classList.remove('disabled');
//                     efrisBtn.style.opacity = '1';
//                     efrisBtn.style.pointerEvents = 'auto';
//                     efrisBtn.style.backgroundColor = '#28a745';
//                     efrisBtn.innerText = CONFIG.buttonText;
//                 }
//             },
//             error: function(r) {
//                 console.error('Server error:', r);
//                 frappe.msgprint({
//                     title: 'Server Error',
//                     message: 'Failed to communicate with server',
//                     indicator: 'red'
//                 });
                
//                 // Re-enable button
//                 efrisBtn.classList.remove('disabled');
//                 efrisBtn.style.opacity = '1';
//                 efrisBtn.style.pointerEvents = 'auto';
//                 efrisBtn.style.backgroundColor = '#28a745';
//                 efrisBtn.innerText = CONFIG.buttonText;
//             }
//         });
//     }

//     // Enhanced DOM observer with proper type checking
//     const observer = new MutationObserver(function(mutations) {
//         let shouldCheck = false;
        
//         mutations.forEach(function(mutation) {
//             if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
//                 for (let node of mutation.addedNodes) {
//                     if (node.nodeType === 1) { // Element node
//                         try {
//                             const nodeText = node.innerText || '';
//                             // Properly handle className which could be a string or DOMTokenList
//                             const nodeClass = typeof node.className === 'string' ? 
//                                              node.className : 
//                                              (node.className ? node.className.toString() : '');
                            
//                             if (nodeClass && (
//                                 nodeClass.includes('summary') ||
//                                 nodeClass.includes('pos-receipt') ||
//                                 nodeClass.includes('invoice-wrapper') ||
//                                 nodeClass.includes('print-btn') ||
//                                 nodeClass.includes('summary-btn') ||
//                                 nodeClass.includes('recent-order') ||
//                                 nodeClass.includes('order-item') ||
//                                 (node.tagName === 'DIV' && nodeClass.includes('btn'))
//                             )) {
//                                 shouldCheck = true;
//                                 break;
//                             }
                            
//                             // Check for relevant child elements
//                             if (node.querySelector && (
//                                 node.querySelector('.print-btn, .summary-btn') || 
//                                 node.querySelector('[data-name]') ||
//                                 node.querySelector('.recent-order-item, .order-summary-item')
//                             )) {
//                                 shouldCheck = true;
//                                 break;
//                             }
//                         } catch (e) {
//                             console.warn('Error processing DOM node:', e);
//                         }
//                     }
//                 }
//             }
//         });
        
//         if (shouldCheck) {
//             console.log('DOM change detected, checking for buttons...');
//             setTimeout(tryAddEfrisButton, 300);
//         }
//     });

//     // Start observing
//     observer.observe(document.body, { 
//         childList: true, 
//         subtree: true 
//     });

//     // Multiple initialization attempts with different strategies
//     const initializationDelays = [500, 1000, 2000, 3000, 5000, 8000];
    
//     function initialize() {
//         initializationDelays.forEach((delay, index) => {
//             setTimeout(() => {
//                 console.log(`Initialization attempt ${index + 1} after ${delay}ms`);
//                 tryAddEfrisButton();
                
//                 // Also try to add to any existing receipts or orders on the page
//                 if (index > 2) { // After 3rd attempt, be more aggressive
//                     addToExistingReceipts();
//                 }
//             }, delay);
//         });
//     }
    
//     // Try to add EFRIS buttons to any existing receipts/orders on the page
//     function addToExistingReceipts() {
//         console.log('Scanning for existing receipts/orders...');
        
//         // Look for any elements that might contain invoice names
//         const possibleInvoiceElements = document.querySelectorAll('[data-name], [data-docname]');
//         possibleInvoiceElements.forEach(el => {
//             const docname = el.getAttribute('data-name') || el.getAttribute('data-docname');
//             if (docname && docname.match(/^[A-Z0-9-]+$/)) {
//                 console.log('Found potential invoice element:', docname);
//                 // Try to find a button container near this element
//                 const nearbyContainer = el.querySelector('.btn-group, .actions, [class*="btn"]') ||
//                                       el.closest('[class*="summary"], [class*="action"]');
//                 if (nearbyContainer && !nearbyContainer.querySelector('[data-efris-btn]')) {
//                     console.log('Adding EFRIS button to existing receipt:', docname);
//                     createAndAttachEfrisButton(nearbyContainer, null, docname);
//                 }
//             }
//         });
        
//         // Also look for text content that looks like invoice names
//         const allElements = document.querySelectorAll('div, span, p, a');
//         for (const el of allElements) {
//             if (el.dataset.efrisProcessed) continue;
            
//             const text = (el.innerText || el.textContent || '').trim();
//             const match = text.match(/\b(FBK-PSINV-[0-9]{4}-[0-9]+|[A-Z]+-PSINV-[0-9]{4}-[0-9]+)\b/);
            
//             if (match) {
//                 console.log('Found invoice name in text:', match[1]);
//                 el.dataset.efrisProcessed = 'true';
                
//                 // Look for a nearby container that might hold buttons
//                 const container = el.closest('[class*="summary"], [class*="action"], .receipt, .order') ||
//                                 el.parentElement;
                                
//                 if (container && !container.querySelector('[data-efris-btn]')) {
//                     console.log('Adding EFRIS button near invoice text');
//                     createAndAttachEfrisButton(container, null, match[1]);
//                 }
//                 break; // Only process one per scan
//             }
//         }
//     }

//     if (document.readyState === 'loading') {
//         document.addEventListener('DOMContentLoaded', initialize);
//     } else {
//         initialize();
//     }

//     // Listen for POS events
//     if (window.frappe && frappe.ui) {
//         $(document).on('pos_profile_selected pos_invoice_created pos_payment_complete recent_orders_loaded', function(e) {
//             console.log('POS event detected:', e.type);
//             setTimeout(tryAddEfrisButton, 1000);
//         });
//     }

//     // Listen for route changes (for SPA navigation)
//     if (window.frappe && frappe.router) {
//         frappe.router.on('change', function() {
//             console.log('Route changed, re-initializing EFRIS buttons...');
//             setTimeout(tryAddEfrisButton, 1500);
//         });
//     }

//     console.log('Enhanced POS EFRIS Button script initialized');
// })();         