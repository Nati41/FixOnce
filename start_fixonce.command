#!/bin/bash

# Get the directory where this script is located (absolute path)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Run the native app launcher
python3 "$SCRIPT_DIR/app_launcher.py"
