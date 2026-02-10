"""
Scenario 3: KeyError - Accessing missing dictionary key

This is a common Python bug when accessing dict keys without checking.
The fix: Use .get() with default value or check 'in' before accessing
"""

# Simulated API response with missing fields
user_response = {
    "id": 123,
    "name": "John Doe",
    # "email" is missing!
    "role": "admin"
}

# BUG: This will crash because 'email' key doesn't exist
def get_user_email(user_data):
    return user_data["email"]

# BUG: This will also crash
def format_user_info(user_data):
    return f"""
    Name: {user_data["name"]}
    Email: {user_data["email"]}
    Phone: {user_data["phone"]}
    """

# Trigger the error
try:
    email = get_user_email(user_response)
    print(f"User email: {email}")
except KeyError as e:
    print(f"KeyError: {e}")
    # In real scenario, this would be sent to FixOnce

"""
EXPECTED FIX:
Option 1 - Use .get() with default:
    return user_data.get("email", "no-email@example.com")

Option 2 - Check before access:
    if "email" in user_data:
        return user_data["email"]
    return None

Option 3 - Use try/except:
    try:
        return user_data["email"]
    except KeyError:
        return None
"""
