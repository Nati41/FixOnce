/**
 * Scenario 1: TypeError - Cannot read properties of undefined (reading 'map')
 *
 * This is a common React bug when data hasn't loaded yet from API.
 * The fix: Add optional chaining or null check before .map()
 */

// Simulated API response - initially undefined
let products = undefined;

// BUG: This will crash because products is undefined
function renderProducts() {
    const productList = (products || []).map(product => {
        return `<div class="product">
            <h3>${product.name}</h3>
            <p>$${product.price}</p>
        </div>`;
    });

    return productList.join('');
}

// This triggers the error
try {
    renderProducts();
} catch (e) {
    // Error is caught and sent to FixOnce
    window.fixonceReport && window.fixonceReport(e);
}

// Simulated API call that loads data after delay
setTimeout(() => {
    products = [
        { name: 'Widget', price: 29.99 },
        { name: 'Gadget', price: 49.99 }
    ];
    console.log('Products loaded:', products);
}, 2000);

/**
 * EXPECTED FIX:
 * Change line 13 from:
 *   const productList = products.map(product => {
 * To:
 *   const productList = products?.map(product => {
 * Or:
 *   const productList = (products || []).map(product => {
 */
