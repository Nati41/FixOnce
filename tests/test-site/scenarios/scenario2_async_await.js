/**
 * Scenario 2: Unhandled Promise Rejection - Missing try/catch
 *
 * This is a common async/await bug when network requests fail.
 * The fix: Wrap await in try/catch or use .catch()
 */

// BUG: No error handling for failed API call
async function fetchUserData(userId) {
    const response = await fetch(`/api/users/${userId}`);
    const data = await response.json();
    return data;
}

// This will fail if server returns 404/500 or network error
async function displayUser() {
    const user = await fetchUserData(999); // Non-existent user
    document.getElementById('user-name').textContent = user.name;
    document.getElementById('user-email').textContent = user.email;
}

// Trigger the error
displayUser().catch(e => {
    window.fixonceReport && window.fixonceReport(e);
});

/**
 * EXPECTED FIX:
 * Wrap the fetch call in try/catch:
 *
 * async function fetchUserData(userId) {
 *     try {
 *         const response = await fetch(`/api/users/${userId}`);
 *         if (!response.ok) {
 *             throw new Error(`HTTP error! status: ${response.status}`);
 *         }
 *         const data = await response.json();
 *         return data;
 *     } catch (error) {
 *         console.error('Failed to fetch user:', error);
 *         return null;
 *     }
 * }
 */
