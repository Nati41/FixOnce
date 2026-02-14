/**
 * Scenario 2: Unhandled Promise Rejection - Missing try/catch
 *
 * This is a common async/await bug when network requests fail.
 * The fix: Wrap await in try/catch or use .catch()
 */

// FIXED: Added try/catch for error handling
async function fetchUserData(userId) {
    try {
        const response = await fetch(`/api/users/${userId}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Failed to fetch user:', error);
        return null;
    }
}

// FIXED: Handle null response from fetchUserData
async function displayUser() {
    const user = await fetchUserData(999); // Non-existent user
    if (!user) {
        console.log('User not found');
        return;
    }
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
