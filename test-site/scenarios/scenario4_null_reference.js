/**
 * Scenario 4: TypeError - Cannot read property of null (DOM element)
 *
 * This is a common bug when DOM element doesn't exist.
 * The fix: Check if element exists before accessing properties
 */

// BUG: Element might not exist in DOM
function updateUserProfile() {
    const nameElement = document.getElementById('user-profile-name');
    const avatarElement = document.querySelector('.user-avatar');

    // These will crash if elements don't exist
    nameElement.textContent = 'John Doe';
    avatarElement.src = '/images/john.jpg';
    avatarElement.style.display = 'block';
}

// BUG: Chained property access without null checks
function getNestedValue(obj) {
    return obj.user.profile.settings.theme;
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
