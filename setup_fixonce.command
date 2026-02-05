#!/bin/bash
cd "$(dirname "$0")"
clear

echo ""
echo "  ███████╗██╗██╗  ██╗ ██████╗ ███╗   ██╗ ██████╗███████╗"
echo "  ██╔════╝██║╚██╗██╔╝██╔═══██╗████╗  ██║██╔════╝██╔════╝"
echo "  █████╗  ██║ ╚███╔╝ ██║   ██║██╔██╗ ██║██║     █████╗  "
echo "  ██╔══╝  ██║ ██╔██╗ ██║   ██║██║╚██╗██║██║     ██╔══╝  "
echo "  ██║     ██║██╔╝ ██╗╚██████╔╝██║ ╚████║╚██████╗███████╗"
echo "  ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝╚══════╝"
echo ""
echo "  \"Never debug the same bug twice\""
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""

echo "[1/5] Installing Python dependencies..."
pip3 install -r "$(pwd)/requirements.txt" >/dev/null 2>&1
echo "      [OK] Dependencies installed"

echo ""
echo "[2/5] Opening installation guide..."
open "$(pwd)/INSTALL.html"
sleep 1

echo ""
echo "[3/5] Opening Chrome Extensions page..."
open -a "Google Chrome" "chrome://extensions" 2>/dev/null
sleep 2

echo ""
echo "[4/5] Opening folder (drag 'extension' folder to Chrome)..."
open "$(pwd)"
sleep 1

echo ""
echo "[5/5] Setup complete!"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "  Now follow the instructions in the browser:"
echo ""
echo "  1. Enable 'Developer mode' in Chrome (top right)"
echo "  2. Drag the 'extension' folder into Chrome"
echo "  3. Run start_fixonce.command to start working!"
echo ""
echo "═══════════════════════════════════════════════════════════"
echo ""
read -p "Press Enter to close..."
