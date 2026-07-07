#!/bin/bash
# ============================================================
# FixOnce macOS App Builder
# Builds a self-contained FixOnce.app using PyInstaller
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$PROJECT_ROOT/dist"
VENV_DIR="$PROJECT_ROOT/venv"

echo "=============================================="
echo "  FixOnce macOS App Builder"
echo "=============================================="
echo ""
echo "Project root: $PROJECT_ROOT"
echo "Build output: $BUILD_DIR"
echo ""

# Ensure venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install PyInstaller if needed
echo "[2/4] Checking PyInstaller..."
if ! pip show pyinstaller >/dev/null 2>&1; then
    echo "Installing PyInstaller..."
    pip install pyinstaller
fi

# Install dependencies
echo "[3/4] Installing dependencies..."
pip install -r "$PROJECT_ROOT/requirements.txt" -q

# Install macOS-specific dependencies
pip install rumps pyobjc-framework-Cocoa -q

# Build the app
echo "[4/4] Building FixOnce.app..."
cd "$PROJECT_ROOT"

# Clean previous build
rm -rf "$BUILD_DIR/FixOnce.app" "$BUILD_DIR/FixOnce" build/

# Run PyInstaller
pyinstaller fixonce_macos.spec --noconfirm

# Verify output
if [ -d "$BUILD_DIR/FixOnce.app" ]; then
    echo ""
    echo "=============================================="
    echo "  Build successful!"
    echo "=============================================="
    echo ""
    echo "Output: $BUILD_DIR/FixOnce.app"
    echo ""
    echo "To install:"
    echo "  cp -r $BUILD_DIR/FixOnce.app /Applications/"
    echo ""
    echo "To test:"
    echo "  open $BUILD_DIR/FixOnce.app"
    echo ""
else
    echo ""
    echo "ERROR: Build failed - FixOnce.app not created"
    exit 1
fi
