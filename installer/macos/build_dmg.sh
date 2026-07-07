#!/bin/bash
# ============================================================
# FixOnce macOS DMG Builder
# Creates a drag-and-drop DMG from the PyInstaller app bundle
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
BUILD_DIR="$SCRIPT_DIR/build"
APP_SOURCE="$DIST_DIR/FixOnce.app"
DMG_NAME="FixOnce-mac-beta"
VERSION=$(
    python3 - "$PROJECT_ROOT/src/version.py" <<'PY' 2>/dev/null || echo "1.0.0"
import pathlib
import re
import sys
text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.MULTILINE)
print(match.group(1) if match else "1.0.0")
PY
)

echo "========================================"
echo "  FixOnce macOS DMG Builder"
echo "  Version: $VERSION"
echo "========================================"
echo ""

# Verify source app exists
if [ ! -d "$APP_SOURCE" ]; then
    echo "ERROR: $APP_SOURCE not found."
    echo ""
    echo "Run build_app.sh first to create the app bundle:"
    echo "  ./installer/macos/build_app.sh"
    exit 1
fi

# Clean and prepare
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

DMG_PATH="$BUILD_DIR/$DMG_NAME.dmg"
DMG_TEMP="$BUILD_DIR/dmg_temp"

echo "[1/3] Preparing DMG contents..."
mkdir -p "$DMG_TEMP"

# Copy the app
cp -R "$APP_SOURCE" "$DMG_TEMP/"

# Create Applications symlink for drag-and-drop
ln -s /Applications "$DMG_TEMP/Applications"

# Create README
cat > "$DMG_TEMP/README.txt" << 'README'
FixOnce for macOS
=================

Installation:
  Drag FixOnce.app to the Applications folder.

First Launch:
  Open FixOnce from Applications.
  The app will appear in your menu bar.
  Click the menu bar icon to access FixOnce.

Uninstall:
  Drag FixOnce.app from Applications to Trash.
  Delete ~/.fixonce if you want to remove all data.

Note:
  This beta build is unsigned. On first launch, you may need to:
  1. Right-click the app and select "Open"
  2. Click "Open" in the security dialog

Support: https://fixonce.ai
README

echo "[2/3] Creating DMG..."
if hdiutil create -volname "FixOnce" \
    -srcfolder "$DMG_TEMP" \
    -ov -format UDZO \
    "$DMG_PATH"; then
    echo "  DMG created successfully"
else
    echo ""
    echo "  DMG Creation Failed"
    echo ""
    echo "  Staged contents available at: $DMG_TEMP"
    exit 1
fi

# Cleanup temp
rm -rf "$DMG_TEMP"

echo "[3/3] Verifying DMG..."

# Verify DMG
DMG_SIZE=$(du -h "$DMG_PATH" | cut -f1)
APP_SIZE=$(du -sh "$APP_SOURCE" | cut -f1)

echo ""
echo "========================================"
echo "  Build Complete"
echo "========================================"
echo ""
echo "Output:    $DMG_PATH"
echo "DMG Size:  $DMG_SIZE"
echo "App Size:  $APP_SIZE"
echo "Version:   $VERSION"
echo ""
echo "To test:   open \"$DMG_PATH\""
echo ""

# Quick verification
echo "Verification:"
echo "  - DMG exists: $([ -f "$DMG_PATH" ] && echo "YES" || echo "NO")"

# Mount and verify contents
MOUNT_POINT=$(hdiutil attach "$DMG_PATH" -nobrowse -noautoopen 2>/dev/null | grep "/Volumes" | awk '{print $NF}')
if [ -n "$MOUNT_POINT" ]; then
    echo "  - FixOnce.app in DMG: $([ -d "$MOUNT_POINT/FixOnce.app" ] && echo "YES" || echo "NO")"
    echo "  - Applications link: $([ -L "$MOUNT_POINT/Applications" ] && echo "YES" || echo "NO")"
    echo "  - README.txt: $([ -f "$MOUNT_POINT/README.txt" ] && echo "YES" || echo "NO")"
    echo "  - Icon in bundle: $([ -f "$MOUNT_POINT/FixOnce.app/Contents/Resources/FixOnce.icns" ] && echo "YES" || echo "NO")"
    echo "  - Info.plist: $([ -f "$MOUNT_POINT/FixOnce.app/Contents/Info.plist" ] && echo "YES" || echo "NO")"

    # Check for hardcoded paths
    HARDCODED=$(grep -r "/Users/haimdayan" "$MOUNT_POINT/FixOnce.app/Contents/Info.plist" 2>/dev/null || true)
    if [ -z "$HARDCODED" ]; then
        echo "  - No hardcoded dev paths in Info.plist: YES"
    else
        echo "  - WARNING: Hardcoded paths found in Info.plist"
    fi

    hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
else
    echo "  - Could not mount DMG for verification"
fi

echo ""
