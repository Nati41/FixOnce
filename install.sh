#!/bin/bash
# FixOnce Installer for Mac/Linux
# Usage: ./install.sh

set -e

echo ""
echo "🧠 FixOnce Installer"
echo "===================="
echo ""

# Get script directory (works even when called from different location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3 first."
    echo "   brew install python3"
    exit 1
fi

echo "✓ Python found: $(python3 --version)"

# Run the Python installer
cd "$SCRIPT_DIR"
python3 scripts/install.py

echo ""
echo "Done! 🎉"
