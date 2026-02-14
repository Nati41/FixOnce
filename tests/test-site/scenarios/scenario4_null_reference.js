/**
 * Scenario 4: TypeError - Cannot read property of null (DOM element)
 *
 * This is a common bug when DOM element doesn't exist.
 * The fix: Check if element exists before accessing properties
 */

// FIXED: Check if elements exist before accessing
function updateUserProfile() {
    const nameElement = document.getElementById('user-profile-name');
    const avatarElement = document.querySelector('.user-avatar');

    if (nameElement) {
        nameElement.textContent = 'John Doe';
    }
    if (avatarElement) {
        avatarElement.src = '/images/john.jpg';
        avatarElement.style.display = 'block';
    }
}

// FIXED: Optional chaining with nullish coalescing
function getNestedValue(obj) {
    return obj?.user?.profile?.settings?.theme ?? 'default';
}

// Test data with missing nested properties
const incompleteData = {
    user: {
        profile: null // profile is null!
    }
};

// Trigger errors
try {
    updateUserProfile();
} catch (e) {
    window.fixonceReport && window.fixonceReport(e);
}

try {
    getNestedValue(incompleteData);
} catch (e) {
    window.fixonceReport && window.fixonceReport(e);
}

/**
 * EXPECTED FIXES:
 *
 * Fix 1 - Check element exists:
 *   const nameElement = document.getElementById('user-profile-name');
 *   if (nameElement) {
 *       nameElement.textContent = 'John Doe';
 *   }
 *
 * Fix 2 - Optional chaining for nested access:
 *   return obj?.user?.profile?.settings?.theme;
 *
 * Fix 3 - Nullish coalescing for default:
 *   return obj?.user?.profile?.settings?.theme ?? 'default';
 */
