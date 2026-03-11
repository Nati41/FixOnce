"""
Test Project for FixOnce verification.
A minimal project to test:
- New project initialization
- Empty state handling
- Basic project detection
"""


def hello():
    """Simple function to have something in the project."""
    return "Hello from test project"


def buggy_function():
    """Intentionally buggy for error testing."""
    # Uncomment to create an error:
    # raise ValueError("Test error for FixOnce")
    pass


if __name__ == "__main__":
    print(hello())
