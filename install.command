#!/bin/bash
# FixOnce One-Click Installer for Mac
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  MESSAGE="Python 3 is required to install FixOnce.
Please install Python 3 from python.org and run this installer again."
  if command -v osascript >/dev/null 2>&1; then
    osascript -e "display dialog \"$MESSAGE\" buttons {\"OK\"} default button \"OK\" with icon caution" >/dev/null 2>&1
  else
    echo "$MESSAGE"
  fi
  exit 1
fi

python3 scripts/install.py
