#!/bin/bash
# Package FixOnce extension for Chrome Web Store upload

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="$OUTPUT_DIR/fixonce-extension-v2.0.0.zip"

echo "📦 Packaging FixOnce Extension..."
echo ""

# Remove old zip if exists
rm -f "$OUTPUT_FILE"

# Create zip excluding store folder and unnecessary files
cd "$SCRIPT_DIR"
zip -r "$OUTPUT_FILE" . \
    -x "store/*" \
    -x "*.md" \
    -x ".DS_Store" \
    -x "*.sh" \
    -x "*.zip"

echo ""
echo "✅ Package created: $OUTPUT_FILE"
echo ""
echo "📋 Contents:"
unzip -l "$OUTPUT_FILE"
echo ""
echo "🚀 Next steps:"
echo "   1. Go to: https://chrome.google.com/webstore/devconsole"
echo "   2. Click 'New Item'"
echo "   3. Upload: $OUTPUT_FILE"
echo "   4. Fill in store listing (see store/STORE_LISTING.md)"
echo "   5. Add screenshots (see store/SCREENSHOTS_GUIDE.md)"
echo "   6. Enter privacy policy URL"
echo "   7. Submit for review"
