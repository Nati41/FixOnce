#!/bin/bash
# ============================================================
# FixOnce macOS Installer Builder
# Creates FixOnce Installer.app and packages it into a DMG
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
APP_NAME="FixOnce Installer"
RUNTIME_APP_NAME="FixOnce"
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
APP_ONLY=0
if [ "${1:-}" = "--app-only" ]; then
    APP_ONLY=1
fi

echo "========================================"
echo "  FixOnce macOS Installer Builder"
echo "  Version: $VERSION"
echo "========================================"
echo ""

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
AUDIT_REPORT="$BUILD_DIR/packaging_audit.txt"

copy_if_exists() {
    local src="$1"
    local dest="$2"
    if [ -e "$src" ]; then
        mkdir -p "$(dirname "$dest")"
        cp -R "$src" "$dest"
        echo "INCLUDED $dest" >> "$AUDIT_REPORT"
    else
        echo "MISSING_OPTIONAL $src" >> "$AUDIT_REPORT"
    fi
}

exclude_path() {
    echo "EXCLUDED $1" >> "$AUDIT_REPORT"
}

copy_data_allowlist() {
    local target="$1"
    mkdir -p "$target/data"

    local files=(
        ".cursorrules"
        ".windsurfrules"
        ".gitkeep"
        "active_project.template.json"
        "activity_log.template.json"
        "app-icon.png"
        "dashboard.html"
        "dashboard_app.html"
        "dashboard_minimal.html"
        "fixonce_logo.svg"
        "global-agent-rules.md"
        "global-claude-md.md"
        "global-cursor-rules.md"
        "installer.html"
        "logo.png"
        "privacy.html"
        "project_memory.template.json"
        "security.html"
        "session_registry.template.json"
        "terms.html"
    )

    for file in "${files[@]}"; do
        copy_if_exists "$PROJECT_ROOT/data/$file" "$target/data/$file"
    done

    exclude_path "data/projects_v2/"
    exclude_path "data/global/*.db"
    exclude_path "data/*runtime state json"
    exclude_path "data/*test*.html"
    exclude_path "data/*backup*"
    exclude_path "data/*.migrated"
}

copy_scripts_allowlist() {
    local target="$1"
    mkdir -p "$target/scripts"

	    local files=(
	        "install.py"
	        "app_launcher.py"
	        "menubar_app.py"
	        "semantic_setup.py"
	    )

    for file in "${files[@]}"; do
        copy_if_exists "$PROJECT_ROOT/scripts/$file" "$target/scripts/$file"
    done

    exclude_path "scripts/clean_for_test.sh"
    exclude_path "scripts/run_all_tests.py"
    exclude_path "scripts/mcp_smoke_test.py"
    exclude_path "scripts/windows_build_check.py"
    exclude_path "scripts/build_release.py"
    exclude_path "scripts/create_icons.py"
    exclude_path "scripts/macos_app_launcher.c"
	}

copy_assets_allowlist() {
    local target="$1"
    mkdir -p "$target/assets"

    if [ -d "$PROJECT_ROOT/assets/menubar" ]; then
        cp -R "$PROJECT_ROOT/assets/menubar" "$target/assets/"
        echo "INCLUDED $target/assets/menubar" >> "$AUDIT_REPORT"
    else
        echo "MISSING_OPTIONAL $PROJECT_ROOT/assets/menubar" >> "$AUDIT_REPORT"
    fi
}

copy_extension_allowlist() {
    local target="$1"
    mkdir -p "$target/extension"

    local files=(
        "manifest.json"
        "background.js"
        "bridge.js"
        "content.js"
        "element-picker.js"
        "icon128.png"
        "icon16.png"
        "icon48.png"
        "injected.js"
        "logger.js"
        "picker-bridge.js"
        "popup.html"
        "popup.js"
    )

    for file in "${files[@]}"; do
        copy_if_exists "$PROJECT_ROOT/extension/$file" "$target/extension/$file"
    done

    exclude_path "extension/store/"
    exclude_path "extension/package.sh"
    exclude_path "extension/README.md"
}

audit_bundle() {
    local bundle="$1"
    local name="$2"
    local size

    {
        echo ""
        echo "BUNDLE $name"
        echo "PATH $bundle"
    } >> "$AUDIT_REPORT"

    find "$bundle" -type f | sort >> "$AUDIT_REPORT"
    size=$(du -sh "$bundle" | awk '{print $1}')
    echo "SIZE $name $size" >> "$AUDIT_REPORT"

    local forbidden=()
    while IFS= read -r match; do
        forbidden+=("$match")
    done < <(find "$bundle" \( \
        -path "*/data/projects_v2" -o \
        -path "*/data/projects_v2/.backups" -o \
        -path "*/src/.fixonce" -o \
        -path "*.embeddings" -o \
        -name "server.log" -o \
        -name "current_port.txt" -o \
        -name "install_state.json" -o \
        -name "ai_connections.json" -o \
        -name "mcp_session.json" -o \
        -name "mcp_compliance.json" -o \
        -name "activity_log.json" -o \
        -name "boundary_state.json" -o \
        -name "test_error.html" -o \
        -name "test_site.html" -o \
        -name "dashboard_full_backup.html" -o \
        -name "*.migrated" -o \
        -iname "*stress*project*" -o \
        -iname "*test_proj*" -o \
        -iname "*FixOnce-Tests*" \
    \) -print)

    if [ "${#forbidden[@]}" -gt 0 ]; then
        echo "" >> "$AUDIT_REPORT"
        echo "AUDIT_FAILED $name" >> "$AUDIT_REPORT"
        printf '%s\n' "${forbidden[@]}" >> "$AUDIT_REPORT"
        echo "Packaging audit failed for $name. Forbidden files were included:"
        printf '  %s\n' "${forbidden[@]}"
        echo "Audit report: $AUDIT_REPORT"
        exit 1
    fi

    echo "AUDIT_OK $name" >> "$AUDIT_REPORT"
}

create_app_icon() {
    local source_icns="$PROJECT_ROOT/assets/FixOnce.icns"
    local source_png="$PROJECT_ROOT/data/app-icon.png"
    local output_icns="$1"

    if [ -f "$source_icns" ]; then
        cp "$source_icns" "$output_icns"
        return
    fi

    if [ ! -f "$source_png" ]; then
        echo "Missing FixOnce icon asset: $source_icns or $source_png"
        exit 1
    fi

    sips -s format icns "$source_png" --out "$output_icns" >/dev/null
}

# ============================================================
# Step 1: Create .app bundle structure
# ============================================================
echo "[1/5] Creating app bundle structure..."

APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
CONTENTS="$APP_BUNDLE/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

mkdir -p "$MACOS"
mkdir -p "$RESOURCES"
create_app_icon "$RESOURCES/AppIcon.icns"
echo "INCLUDED $RESOURCES/AppIcon.icns" >> "$AUDIT_REPORT"

# ============================================================
# Step 2: Create Info.plist
# ============================================================
echo "[2/5] Creating Info.plist..."

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>FixOnce Installer</string>
    <key>CFBundleDisplayName</key>
    <string>FixOnce Installer</string>
    <key>CFBundleIdentifier</key>
    <string>com.fixonce.installer</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>installer</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
    <key>NSHumanReadableCopyright</key>
    <string>Copyright 2026 FixOnce. All rights reserved.</string>
</dict>
</plist>
PLIST

# ============================================================
# Create runtime FixOnce.app bundle
# ============================================================
RUNTIME_APP_BUNDLE="$BUILD_DIR/$RUNTIME_APP_NAME.app"
RUNTIME_CONTENTS="$RUNTIME_APP_BUNDLE/Contents"
RUNTIME_MACOS="$RUNTIME_CONTENTS/MacOS"
RUNTIME_RESOURCES="$RUNTIME_CONTENTS/Resources"

mkdir -p "$RUNTIME_MACOS"
mkdir -p "$RUNTIME_RESOURCES"
cp "$RESOURCES/AppIcon.icns" "$RUNTIME_RESOURCES/AppIcon.icns"

cat > "$RUNTIME_CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>FixOnce</string>
    <key>CFBundleDisplayName</key>
    <string>FixOnce</string>
    <key>CFBundleIdentifier</key>
    <string>com.fixonce.app</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>fixonce</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
PLIST

cat > "$RUNTIME_MACOS/fixonce" << 'RUNTIME_SCRIPT'
#!/bin/bash
# FixOnce.app - daily product launcher

FIXONCE_DIR="$HOME/FixOnce"
LOG_FILE="$HOME/.fixonce/logs/app-launcher.log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ICON_FILE="$SCRIPT_DIR/../Resources/AppIcon.icns"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $1" >> "$LOG_FILE"
}

show_error() {
    local message="$1"
    osascript <<OSA >/dev/null 2>&1 || true
display dialog "$message" with title "FixOnce" buttons {"OK"} default button "OK" with icon POSIX file "$ICON_FILE"
OSA
}

main() {
    log "FixOnce.app launched"

    if [ ! -d "$FIXONCE_DIR" ]; then
        show_error "FixOnce is not installed for this user.\n\nRun FixOnce Installer.app to install FixOnce."
        exit 1
    fi

    if pgrep -f "$FIXONCE_DIR/scripts/app_launcher.py --menubar" >/dev/null 2>&1; then
        log "FixOnce menu bar app already running"
        exit 0
    fi

    exec "$FIXONCE_DIR/venv/bin/python" "$FIXONCE_DIR/scripts/app_launcher.py" --menubar
}

main
RUNTIME_SCRIPT

chmod +x "$RUNTIME_MACOS/fixonce"

# ============================================================
# Step 3: Copy FixOnce source files
# ============================================================
echo "[3/5] Copying FixOnce files..."

echo "FixOnce packaging audit" > "$AUDIT_REPORT"
echo "VERSION $VERSION" >> "$AUDIT_REPORT"
echo "INCLUDED $RESOURCES/AppIcon.icns" >> "$AUDIT_REPORT"
echo "INCLUDED $RUNTIME_RESOURCES/AppIcon.icns" >> "$AUDIT_REPORT"

# Copy essential directories using release allowlists.
cp -R "$PROJECT_ROOT/src" "$RESOURCES/"
echo "INCLUDED $RESOURCES/src" >> "$AUDIT_REPORT"
rm -rf "$RESOURCES/src/.fixonce"
exclude_path "src/.fixonce/"
copy_scripts_allowlist "$RESOURCES"
copy_data_allowlist "$RESOURCES"
copy_assets_allowlist "$RESOURCES"
cp -R "$PROJECT_ROOT/hooks" "$RESOURCES/" 2>/dev/null || true
echo "INCLUDED $RESOURCES/hooks" >> "$AUDIT_REPORT"
copy_extension_allowlist "$RESOURCES"
cp "$PROJECT_ROOT/requirements.txt" "$RESOURCES/"
echo "INCLUDED $RESOURCES/requirements.txt" >> "$AUDIT_REPORT"
cp "$PROJECT_ROOT/CLAUDE.md" "$RESOURCES/" 2>/dev/null || true
echo "INCLUDED $RESOURCES/CLAUDE.md" >> "$AUDIT_REPORT"
cp -R "$RUNTIME_APP_BUNDLE" "$RESOURCES/"
echo "INCLUDED $RESOURCES/FixOnce.app" >> "$AUDIT_REPORT"

# Clean up __pycache__ and .pyc files
find "$RESOURCES" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$RESOURCES" -name "*.pyc" -delete 2>/dev/null || true
find "$RESOURCES" -name ".DS_Store" -delete 2>/dev/null || true

# ============================================================
# Step 4: Create main executable
# ============================================================
echo "[4/5] Creating installer executable..."

cat > "$MACOS/installer" << 'INSTALLER_SCRIPT'
#!/bin/bash
# ============================================================
# FixOnce Installer - Main Executable
# ============================================================

set -o pipefail
trap on_installer_exit EXIT

# Get the Resources directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES="$SCRIPT_DIR/../Resources"
ICON_FILE="$RESOURCES/AppIcon.icns"
BRAND_IMAGE_FILE="$RESOURCES/data/app-icon.png"

# Installation target
INSTALL_DIR="$HOME/FixOnce"
RUNTIME_APP_SOURCE="$RESOURCES/FixOnce.app"
RUNTIME_APP_PATH="/Applications/FixOnce.app"
RUNTIME_APP_FALLBACK="$HOME/Applications/FixOnce.app"
INSTALL_LOG_DIR="$HOME/.fixonce/logs"
LOG_FILE="$INSTALL_LOG_DIR/install.log"
LAUNCHCTL_LOG="$INSTALL_LOG_DIR/launchctl.log"
PROGRESS_FILE="$HOME/.fixonce/install_progress.html"
PROGRESS_OPENED=0
PROGRESS_STEP=0
PROGRESS_PERCENT=0
PROGRESS_TITLE="Starting FixOnce Installer"
PROGRESS_DETAIL="Opening installer..."
PROGRESS_STATE="running"
PROGRESS_PULSE_PID=""
INSTALL_COMPLETED=0

# Colors for terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================
# Helper Functions
# ============================================================

log() {
    mkdir -p "$INSTALL_LOG_DIR"
    echo -e "$1" | tee -a "$LOG_FILE"
}

show_dialog() {
    local message="$1"
    osascript <<OSA
display dialog "$message" with title "FixOnce Installer" buttons {"OK"} default button "OK" with icon POSIX file "$ICON_FILE"
OSA
}

show_error() {
    local message="$1"
    osascript <<OSA
display dialog "$message" with title "FixOnce Installer" buttons {"OK"} default button "OK" with icon POSIX file "$ICON_FILE"
OSA
}

show_progress() {
    osascript -e "display notification \"$1\" with title \"FixOnce Installer\""
}

html_escape() {
    printf '%s' "$1" | sed \
        -e 's/&/\&amp;/g' \
        -e 's/</\&lt;/g' \
        -e 's/>/\&gt;/g' \
        -e 's/"/\&quot;/g'
}

status_class() {
    case "$1" in
        connected|configured|ready|ok) echo "ok" ;;
        ready_to_connect|not_connected|warning) echo "warn" ;;
        failed|error) echo "error" ;;
        *) echo "pending" ;;
    esac
}

percent_for_step() {
    case "$1" in
        1) echo 0 ;;
        2) echo 20 ;;
        3) echo 40 ;;
        4) echo 60 ;;
        5) echo 80 ;;
        6) echo 100 ;;
        *) echo 0 ;;
    esac
}

step_class() {
    local index="$1"
    if [ "$PROGRESS_STATE" = "failed" ] && [ "$index" -eq "$PROGRESS_STEP" ]; then
        echo "error"
    elif [ "$index" -lt "$PROGRESS_STEP" ] || { [ "$PROGRESS_STATE" = "success" ] && [ "$index" -le 6 ]; }; then
        echo "done"
    elif [ "$index" -eq "$PROGRESS_STEP" ]; then
        echo "active"
    else
        echo "pending"
    fi
}

step_mark() {
    local class="$1"
    case "$class" in
        done) echo "✓" ;;
        active) echo "•" ;;
        error) echo "!" ;;
        *) echo "" ;;
    esac
}

detect_server_status() {
    local port
	    port=$(discover_runtime_port 2>/dev/null || true)
	    if [ -n "$port" ] && curl -fsS --connect-timeout 1 "http://localhost:$port/api/health" >/dev/null 2>&1; then
	        echo "connected|Connected|FixOnce is running"
	    else
	        echo "warning|Starting|FixOnce is still starting"
	    fi
}

detect_mcp_status() {
    local session_file="$HOME/.fixonce/mcp_session_health.json"
    if [ -f "$session_file" ] && grep -q '"state"[[:space:]]*:[[:space:]]*"connected"' "$session_file" 2>/dev/null; then
        echo "connected|Connected|MCP session is connected"
        return
    fi

    if grep -q "fixonce" "$HOME/.codex/config.toml" "$HOME/.claude.json" "$HOME/.claude/settings.json" "$INSTALL_DIR/.mcp.json" 2>/dev/null; then
        echo "configured|Connected|AI tool integration is configured"
    else
        echo "warning|Needs setup|No FixOnce MCP configuration was detected"
    fi
}

detect_extension_status() {
    local port
    port=$(discover_runtime_port 2>/dev/null || true)
    if [ -n "$port" ] && curl -fsS --connect-timeout 1 "http://localhost:$port/api/status" 2>/dev/null | grep -q '"extension_connected"[[:space:]]*:[[:space:]]*true'; then
        echo "connected|Connected|Browser extension is connected"
    else
        echo "ready_to_connect|Ready to connect|Extension handshake has not completed yet"
    fi
}

render_progress_window() {
    local title detail meta_refresh success_block failure_block onboarding_block connect_block percent_text icon_url extension_url
    title=$(html_escape "$PROGRESS_TITLE")
    detail=$(html_escape "$PROGRESS_DETAIL")
    percent_text=$(html_escape "$PROGRESS_PERCENT")
    icon_url="file://$(html_escape "$BRAND_IMAGE_FILE")"
    extension_url="file://$(html_escape "$INSTALL_DIR/extension")"
    meta_refresh='<meta http-equiv="refresh" content="1">'
    success_block=""
    failure_block=""
    onboarding_block=""
    connect_block=""

    if [ "$PROGRESS_STATE" = "success" ]; then
        meta_refresh=""
        success_block='<section class="result ok"><strong>Installation complete.</strong><span>FixOnce is installed and running from the menu bar.</span></section>'

        local server_status mcp_status extension_status
        local server_state server_label server_detail
        local mcp_state mcp_label mcp_detail
        local extension_state extension_label extension_detail

        server_status=$(detect_server_status)
        mcp_status=$(detect_mcp_status)
        extension_status=$(detect_extension_status)

        IFS='|' read -r server_state server_label server_detail <<< "$server_status"
        IFS='|' read -r mcp_state mcp_label mcp_detail <<< "$mcp_status"
        IFS='|' read -r extension_state extension_label extension_detail <<< "$extension_status"

        connect_block='
        <div class="extension-help" id="extensionHelp" style="display: '"$([ "$extension_state" = "connected" ] && echo "none" || echo "block")"';">
            <button class="button" type="button" onclick="openChromeExtensions()">Open Chrome extensions page</button>
            <button class="button secondary" type="button" onclick="openExtensionFolder()">Open extension folder</button>
            <button class="button secondary" type="button" onclick="refreshExtensionStatus()">Refresh connection / Recheck status</button>
            <p>In Chrome, open <code>chrome://extensions/</code>, enable <strong>Developer mode</strong>, click <strong>Load unpacked</strong>, and select:</p>
            <code>'"$(html_escape "$INSTALL_DIR/extension")"'</code>
            <p>If the extension is already installed, click its reload button on the Chrome extensions page, then click <strong>Refresh connection / Recheck status</strong>.</p>
        </div>'

        onboarding_block='
        <section class="onboarding">
            <h2>Post-install status</h2>
            <div class="status-row '"$(status_class "$server_state")"'" id="serverStatusRow"><span>Server</span><strong>'"$(html_escape "$server_label")"'</strong><small>'"$(html_escape "$server_detail")"'</small></div>
            <div class="status-row '"$(status_class "$mcp_state")"'" id="mcpStatusRow"><span>MCP</span><strong>'"$(html_escape "$mcp_label")"'</strong><small>'"$(html_escape "$mcp_detail")"'</small></div>
            <div class="status-row '"$(status_class "$extension_state")"'" id="extensionStatusRow"><span>Browser Ext</span><strong id="extensionStatusLabel">'"$(html_escape "$extension_label")"'</strong><small id="extensionStatusDetail">'"$(html_escape "$extension_detail")"'</small></div>
            '"$connect_block"'
        </section>'
    elif [ "$PROGRESS_STATE" = "failed" ]; then
        meta_refresh=""
        failure_block='<section class="result error"><strong>Installation failed.</strong><span>Check the installer log in <code>~/.fixonce/logs/</code>.</span></section>'
    fi

    local s1 s2 s3 s4 s5 s6
    local m1 m2 m3 m4 m5 m6
    s1=$(step_class 1); s2=$(step_class 2); s3=$(step_class 3); s4=$(step_class 4); s5=$(step_class 5); s6=$(step_class 6)
    m1=$(step_mark "$s1"); m2=$(step_mark "$s2"); m3=$(step_mark "$s3"); m4=$(step_mark "$s4"); m5=$(step_mark "$s5"); m6=$(step_mark "$s6")

    cat > "$PROGRESS_FILE" << HTML
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    $meta_refresh
    <title>FixOnce Installer</title>
    <style>
        :root { color-scheme: light dark; --bg: #f6f7f9; --panel: #ffffff; --text: #171b22; --muted: #667085; --line: #d9dee7; --ok: #15803d; --warn: #b7791f; --error: #b42318; --active: #155eef; }
        @media (prefers-color-scheme: dark) { :root { --bg: #0f1115; --panel: #171a21; --text: #f3f4f6; --muted: #a2a8b3; --line: #303642; } }
        * { box-sizing: border-box; }
        body { margin: 0; min-height: 100vh; background: var(--bg); color: var(--text); font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; display: grid; place-items: center; padding: 28px; }
        main { width: min(760px, 100%); background: var(--panel); border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 18px 48px rgba(0,0,0,.18); padding: 28px; }
        h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: 0; }
        h2 { margin: 0 0 14px; font-size: 18px; letter-spacing: 0; }
        .detail { color: var(--muted); margin: 0 0 22px; }
        .brand-head { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
        .brand-logo { width: 48px; height: 48px; border-radius: 12px; }
        .brand-copy h1 { margin: 0 0 4px; }
        .brand-copy p { margin: 0; color: var(--muted); }
        .progress-head { display: flex; justify-content: space-between; gap: 16px; align-items: baseline; margin: 0 0 8px; }
        .progress-head strong { font-size: 16px; }
        .progress-head span { color: var(--muted); font-variant-numeric: tabular-nums; }
        .progress-track { height: 12px; background: rgba(102,112,133,.18); border: 1px solid var(--line); border-radius: 999px; overflow: hidden; margin-bottom: 22px; }
        .progress-fill { width: ${percent_text}%; height: 100%; background: linear-gradient(90deg, var(--active), #15803d); border-radius: inherit; transition: width .25s ease; position: relative; }
        .progress-fill::after { content: ""; position: absolute; inset: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,.35), transparent); animation: sweep 1.2s linear infinite; }
        @keyframes sweep { from { transform: translateX(-100%); } to { transform: translateX(100%); } }
        .steps { display: grid; gap: 10px; margin: 0 0 22px; padding: 0; list-style: none; }
        .steps li { display: grid; grid-template-columns: 28px 1fr; align-items: center; min-height: 38px; border: 1px solid var(--line); border-radius: 8px; padding: 8px 11px; color: var(--muted); }
        .steps li span:first-child { width: 22px; height: 22px; border-radius: 50%; border: 1px solid var(--line); display: grid; place-items: center; font-size: 13px; }
        .steps li.done { color: var(--text); border-color: rgba(21,128,61,.35); }
        .steps li.done span:first-child { background: var(--ok); border-color: var(--ok); color: white; }
        .steps li.active { color: var(--text); border-color: rgba(21,94,239,.45); background: rgba(21,94,239,.08); }
        .steps li.active span:first-child { background: var(--active); border-color: var(--active); color: white; }
        .steps li.error { color: var(--text); border-color: rgba(180,35,24,.45); background: rgba(180,35,24,.08); }
        .steps li.error span:first-child { background: var(--error); border-color: var(--error); color: white; }
        .result { display: grid; gap: 4px; border-radius: 8px; padding: 14px; margin-bottom: 20px; }
        .result.ok { background: rgba(21,128,61,.1); border: 1px solid rgba(21,128,61,.28); }
        .result.error { background: rgba(180,35,24,.1); border: 1px solid rgba(180,35,24,.28); }
        .onboarding { border-top: 1px solid var(--line); padding-top: 20px; }
        .status-row { display: grid; grid-template-columns: 170px 150px 1fr; gap: 12px; align-items: center; border: 1px solid var(--line); border-radius: 8px; padding: 12px; margin: 8px 0; }
        .status-row strong::after { margin-left: 6px; }
        .status-row.ok strong::after { content: "✓"; color: var(--ok); }
        .status-row.warn strong::after { content: "⚠"; color: var(--warn); }
        .status-row.error strong::after { content: "!"; color: var(--error); }
        .status-row small { color: var(--muted); }
        .extension-help { margin-top: 14px; border: 1px solid rgba(183,121,31,.35); background: rgba(183,121,31,.08); border-radius: 8px; padding: 14px; }
        .button { display: inline-block; color: white; background: var(--active); border: 1px solid transparent; border-radius: 7px; padding: 9px 13px; text-decoration: none; font-weight: 600; margin-bottom: 8px; cursor: pointer; font: inherit; }
        .button.secondary { background: transparent; color: var(--active); border: 1px solid rgba(21,94,239,.45); margin-left: 8px; }
        code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
    </style>
</head>
<body>
<main>
    <div class="brand-head">
        <img class="brand-logo" src="$icon_url" alt="FixOnce">
        <div class="brand-copy">
            <h1>FixOnce</h1>
            <p>$title</p>
        </div>
    </div>
    <p class="detail">$detail</p>
    <div class="progress-head"><strong>Current step: $title</strong><span>${percent_text}%</span></div>
    <div class="progress-track" aria-label="Installation progress"><div class="progress-fill"></div></div>
    <ol class="steps">
        <li class="$s1"><span>$m1</span><span>Checking system</span></li>
        <li class="$s2"><span>$m2</span><span>Preparing installation</span></li>
        <li class="$s3"><span>$m3</span><span>Installing files</span></li>
        <li class="$s4"><span>$m4</span><span>Configuring integrations</span></li>
        <li class="$s5"><span>$m5</span><span>Starting FixOnce services</span></li>
        <li class="$s6"><span>$m6</span><span>Starting menu bar app</span></li>
    </ol>
    $success_block
    $failure_block
    $onboarding_block
</main>
<script>
const PORTS = [5000, 5001, 5002, 5003, 5004, 5005];
async function findFixOnceBase() {
    for (const port of PORTS) {
        try {
            const url = "http://localhost:" + port;
            const res = await fetch(url + "/api/ping", { cache: "no-store" });
            const data = await res.json();
            if (data.service === "fixonce") return url;
        } catch (_) {}
    }
    return null;
}
async function postInstallerAction(path) {
    const base = await findFixOnceBase();
    if (!base) return false;
    try {
        const res = await fetch(base + path, { method: "POST" });
        return res.ok;
    } catch (_) {
        return false;
    }
}
async function openChromeExtensions() {
    const ok = await postInstallerAction("/api/installer/open-chrome-extensions");
    if (!ok) window.location.href = "chrome://extensions/";
}
async function openExtensionFolder() {
    const ok = await postInstallerAction("/api/installer/open-extension-folder");
    if (!ok) window.location.href = "$extension_url";
}
async function refreshExtensionStatus() {
    const base = await findFixOnceBase();
    if (!base) return;
    try {
        const res = await fetch(base + "/api/installer/extension-status", { cache: "no-store" });
        const data = await res.json();
        const connected = Boolean(data.extension && data.extension.connected);
        if (connected) {
            const row = document.getElementById("extensionStatusRow");
            row.className = "status-row ok";
            document.getElementById("extensionStatusLabel").textContent = "Connected";
            document.getElementById("extensionStatusDetail").textContent = "Browser extension handshake completed";
            document.getElementById("extensionHelp").style.display = "none";
            const result = document.querySelector(".result.ok strong");
            if (result) result.textContent = "Installation complete.";
        }
    } catch (_) {}
}
refreshExtensionStatus();
setInterval(refreshExtensionStatus, 3000);
</script>
</body>
</html>
HTML
}

open_progress_window() {
    render_progress_window
    if [ "$PROGRESS_OPENED" -eq 0 ]; then
        open "$PROGRESS_FILE" >/dev/null 2>&1 || true
        PROGRESS_OPENED=1
    fi
}

set_progress() {
    PROGRESS_STEP="$1"
    PROGRESS_PERCENT="$(percent_for_step "$1")"
    PROGRESS_TITLE="$2"
    PROGRESS_DETAIL="$3"
    PROGRESS_STATE="running"
    render_progress_window
}

set_progress_at() {
    PROGRESS_STEP="$1"
    PROGRESS_PERCENT="$2"
    PROGRESS_TITLE="$3"
    PROGRESS_DETAIL="$4"
    PROGRESS_STATE="running"
    render_progress_window
}

stop_progress_pulse() {
    if [ -n "$PROGRESS_PULSE_PID" ]; then
        kill "$PROGRESS_PULSE_PID" >/dev/null 2>&1 || true
        wait "$PROGRESS_PULSE_PID" >/dev/null 2>&1 || true
        PROGRESS_PULSE_PID=""
    fi
}

start_progress_pulse() {
    stop_progress_pulse

    local step="$1"
    local start_percent="$2"
    local end_percent="$3"
    local title="$4"
    local detail="$5"

    set_progress_at "$step" "$start_percent" "$title" "$detail"

    (
        local percent="$start_percent"
        local tick=0
        while true; do
            sleep 2
            tick=$((tick + 1))
            if [ "$percent" -lt "$end_percent" ]; then
                percent=$((percent + 1))
            fi

            PROGRESS_STEP="$step"
            PROGRESS_PERCENT="$percent"
            PROGRESS_TITLE="$title"
            case $((tick % 3)) in
                0) PROGRESS_DETAIL="$detail" ;;
                1) PROGRESS_DETAIL="$detail." ;;
                2) PROGRESS_DETAIL="$detail.." ;;
            esac
            PROGRESS_STATE="running"
            render_progress_window
        done
    ) &
    PROGRESS_PULSE_PID="$!"
}

mark_install_success() {
    stop_progress_pulse
    PROGRESS_STEP=6
    PROGRESS_PERCENT=100
    PROGRESS_TITLE="FixOnce is ready"
    PROGRESS_DETAIL="Installation completed successfully."
    PROGRESS_STATE="success"
    INSTALL_COMPLETED=1
    render_progress_window
}

mark_install_failure() {
    stop_progress_pulse
    local exit_code="${1:-1}"
    if [ "$INSTALL_COMPLETED" -eq 0 ]; then
        PROGRESS_TITLE="FixOnce installation failed"
        PROGRESS_DETAIL="The installer stopped before completion. Exit code: $exit_code."
        PROGRESS_STATE="failed"
        render_progress_window
    fi
}

open_extension_connect_help() {
    open -a "Google Chrome" "chrome://extensions/" >/dev/null 2>&1 || open "chrome://extensions/" >/dev/null 2>&1 || true
    open "$INSTALL_DIR/extension" >/dev/null 2>&1 || true
    osascript -e 'display dialog "Connect FixOnce Browser Extension\n\n1. In Chrome, open chrome://extensions/\n2. Enable Developer mode\n3. Click Load unpacked\n4. Select ~/FixOnce/extension\n\nIf the extension is already installed, click its reload button, then refresh the FixOnce dashboard." with title "FixOnce Installer" buttons {"OK"} default button "OK" with icon note' >/dev/null 2>&1 || true
}

show_post_install_onboarding_dialog() {
    local extension_status extension_state
    extension_status=$(detect_extension_status)
    IFS='|' read -r extension_state _ <<< "$extension_status"

    if [ "$extension_state" != "connected" ]; then
        local result
        result=$(osascript -e 'display dialog "FixOnce is installed and running.\n\nServer: Connected ✓\nMCP: Connected ✓\nBrowser Extension: Ready to connect\n\nOpen Chrome extensions now to connect the browser extension?" with title "FixOnce Installer" buttons {"Done", "Connect Extension"} default button "Connect Extension" with icon note' 2>/dev/null || true)
        if [[ "$result" == *"Connect Extension"* ]]; then
            open_extension_connect_help
        fi
    else
        osascript -e 'display dialog "Installation complete\n\nServer: Connected ✓\nMCP: Connected ✓\nBrowser Extension: Connected ✓" with title "FixOnce Installer" buttons {"Done"} default button "Done" with icon note' >/dev/null 2>&1 || true
    fi
}

on_installer_exit() {
    local exit_code="$?"
    stop_progress_pulse
    if [ "$exit_code" -ne 0 ]; then
        mark_install_failure "$exit_code"
    fi
}

ask_continue() {
    result=$(osascript -e 'display dialog "'"$1"'" with title "FixOnce Installer" buttons {"Cancel", "Continue"} default button "Continue" with icon caution' 2>/dev/null)
    if [[ "$result" == *"Cancel"* ]]; then
        return 1
    fi
    return 0
}

installed_runtime_app() {
    if [ -d "$RUNTIME_APP_PATH" ]; then
        echo "$RUNTIME_APP_PATH"
    elif [ -d "$RUNTIME_APP_FALLBACK" ]; then
        echo "$RUNTIME_APP_FALLBACK"
    fi
}

is_fixonce_installed() {
    [ -d "$INSTALL_DIR" ] && [ -n "$(installed_runtime_app)" ]
}

open_fixonce_app() {
    local app_path
    app_path="$(installed_runtime_app)"
    if [ -n "$app_path" ]; then
        open "$app_path" >/dev/null 2>&1
        return 0
    fi
    return 1
}

uninstall_fixonce() {
    local choice
    choice=$(osascript -e 'display dialog "Uninstall FixOnce?\n\nThis removes the FixOnce app, local server files, and LaunchAgent.\n\nYour ~/.fixonce memory data will be left in place." with title "FixOnce Installer" buttons {"Cancel", "Uninstall"} default button "Cancel" with icon caution' 2>/dev/null || true)
    if [[ "$choice" != *"Uninstall"* ]]; then
        return 0
    fi

    local domain="gui/$(id -u)"
    launchctl bootout "$domain/com.fixonce.server" >/dev/null 2>&1 || true
    launchctl unload "$HOME/Library/LaunchAgents/com.fixonce.server.plist" >/dev/null 2>&1 || true
    rm -f "$HOME/Library/LaunchAgents/com.fixonce.server.plist"
    rm -rf "$INSTALL_DIR"
    rm -rf "$RUNTIME_APP_FALLBACK"
    if [ -w "/Applications" ]; then
        rm -rf "$RUNTIME_APP_PATH"
    else
        rm -rf "$RUNTIME_APP_PATH" >/dev/null 2>&1 || true
    fi

    osascript -e 'display dialog "FixOnce has been uninstalled.\n\nYour ~/.fixonce memory data was not deleted." with title "FixOnce Installer" buttons {"OK"} default button "OK" with icon note' >/dev/null 2>&1 || true
}

handle_already_installed() {
    if ! is_fixonce_installed; then
        return 1
    fi

    osascript <<OSA >/dev/null 2>&1 || true
display dialog "FixOnce is already installed." with title "FixOnce Installer" buttons {"Continue"} default button "Continue" with icon POSIX file "$ICON_FILE"
OSA

    local selection
    selection=$(osascript <<'OSA' 2>/dev/null || true
set choices to {"Open FixOnce", "Repair Installation", "Uninstall", "Close"}
set picked to choose from list choices with title "FixOnce Installer" with prompt "FixOnce is already installed." OK button name "Choose" cancel button name "Close"
if picked is false then
    return "Close"
else
    return item 1 of picked
end if
OSA
)

    case "$selection" in
        "Open FixOnce")
            open_fixonce_app || show_error "Could not open FixOnce.app."
            exit 0
            ;;
        "Repair Installation")
            log "Repair installation selected"
            return 1
            ;;
        "Uninstall")
            uninstall_fixonce
            exit 0
            ;;
        *)
            exit 0
            ;;
    esac
}

install_runtime_app() {
    log "${BLUE}Installing FixOnce.app...${NC}"
    set_progress_at 4 79 "Configuring integrations" "Installing FixOnce.app for daily use."

    if [ ! -d "$RUNTIME_APP_SOURCE" ]; then
        show_error "Installation failed: FixOnce.app was not bundled correctly."
        exit 1
    fi

    if [ -w "/Applications" ]; then
        rm -rf "$RUNTIME_APP_PATH"
        cp -R "$RUNTIME_APP_SOURCE" "$RUNTIME_APP_PATH"
        log "${GREEN}✓${NC} Installed FixOnce.app at $RUNTIME_APP_PATH"
    else
        mkdir -p "$HOME/Applications"
        rm -rf "$RUNTIME_APP_FALLBACK"
        cp -R "$RUNTIME_APP_SOURCE" "$RUNTIME_APP_FALLBACK"
        log "${YELLOW}!${NC} /Applications is not writable. Installed FixOnce.app at $RUNTIME_APP_FALLBACK"
    fi
}

create_desktop_shortcut() {
    local app_path
    app_path="$(installed_runtime_app)"
    if [ -z "$app_path" ]; then
        return 1
    fi
    ln -sfn "$app_path" "$HOME/Desktop/FixOnce.app"
}

write_install_state() {
    local state="$1"
    local detail="${2:-}"
    local install_state_dir="$HOME/.fixonce"
    local install_state_file="$install_state_dir/install_state.json"
    mkdir -p "$install_state_dir"

    local state_python="${SELECTED_PYTHON:-}"
    if [ -z "$state_python" ]; then
        for candidate in /usr/local/bin/python3.13 /opt/homebrew/bin/python3.13 /usr/local/bin/python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.11 /opt/homebrew/bin/python3.11 /usr/local/bin/python3.10 /opt/homebrew/bin/python3.10 /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
            if [ -x "$candidate" ]; then
                state_python="$candidate"
                break
            fi
        done
    fi

    if [ -z "$state_python" ]; then
        return 0
    fi

    "$state_python" - "$install_state_file" "$state" "$detail" "$INSTALL_DIR" << 'PY'
import json
import sys
from datetime import datetime, timezone

target, state, detail, install_dir = sys.argv[1:]
payload = {
    "state": state,
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "detail": detail,
    "install_dir": install_dir,
    "metadata": {"source": "macos_installer_app"},
}

with open(target, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
PY
}

# ============================================================
# Pre-flight Checks
# ============================================================

# Global: selected Python interpreter (set by preflight)
SELECTED_PYTHON=""
SELECTED_PYTHON_VERSION=""

preflight() {
    log "${BLUE}Running pre-flight checks...${NC}"

    # ========== PYTHON DISCOVERY ==========
    # Find Python >= 3.10 with absolute path
    # Priority: python3.13, python3.12, python3.11, python3.10, then python3 if version OK
    log "  Searching for Python >= 3.10..."

    PYTHON_CANDIDATES=(
        "/usr/local/bin/python3.13"
        "/opt/homebrew/bin/python3.13"
        "/usr/local/bin/python3.12"
        "/opt/homebrew/bin/python3.12"
        "/usr/local/bin/python3.11"
        "/opt/homebrew/bin/python3.11"
        "/usr/local/bin/python3.10"
        "/opt/homebrew/bin/python3.10"
        "/usr/local/bin/python3"
        "/opt/homebrew/bin/python3"
        "/usr/bin/python3"
    )

    for candidate in "${PYTHON_CANDIDATES[@]}"; do
        if [ -x "$candidate" ]; then
            # Get version
            VERSION=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
            MAJOR=$("$candidate" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)
            MINOR=$("$candidate" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)

            if [ -n "$MAJOR" ] && [ -n "$MINOR" ]; then
                log "    Found: $candidate (Python $VERSION)"

                # Check version >= 3.10
                if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; then
                    SELECTED_PYTHON="$candidate"
                    SELECTED_PYTHON_VERSION="$VERSION"
                    log "  ${GREEN}✓${NC} Selected: $SELECTED_PYTHON (Python $SELECTED_PYTHON_VERSION)"
                    break
                else
                    log "    ${YELLOW}!${NC} Skipping $candidate (Python $VERSION < 3.10)"
                fi
            fi
        fi
    done

    # Fail if no suitable Python found
    if [ -z "$SELECTED_PYTHON" ]; then
        log "${RED}✗${NC} No Python >= 3.10 found!"
        show_error "Python 3.10 or higher is required.\n\nFound interpreters are too old.\n\nInstall Python 3.10+ from:\n• python.org\n• brew install python@3.12"
        exit 1
    fi

    # ========== OTHER CHECKS ==========
    # Check disk space (need at least 100MB)
    FREE_SPACE=$(df -m "$HOME" | awk 'NR==2 {print $4}')
    if [ "$FREE_SPACE" -lt 100 ]; then
        show_error "Not enough disk space.\n\nRequired: 100MB\nAvailable: ${FREE_SPACE}MB"
        exit 1
    fi
    log "${GREEN}✓${NC} Disk space OK (${FREE_SPACE}MB free)"

    # Check write permissions
    if ! touch "$HOME/.fixonce_test" 2>/dev/null; then
        show_error "Cannot write to home directory.\n\nPlease check permissions for:\n$HOME"
        exit 1
    fi
    rm -f "$HOME/.fixonce_test"
    log "${GREEN}✓${NC} Write permissions OK"

    log "${GREEN}Pre-flight checks passed${NC}"
}

# ============================================================
# Installation (Complete Purge + Fresh Copy)
# ============================================================

install_files() {
    log "${BLUE}Installing FixOnce...${NC}"
    set_progress 2 "Preparing installation" "Removing old files and preparing a clean FixOnce folder."
    write_install_state "INSTALLING" "Copying application files"

    # ========== COMPLETE PURGE ==========
    # Remove any existing installation to ensure clean state
    if [ -d "$INSTALL_DIR" ]; then
        log "  Removing old installation at $INSTALL_DIR..."
        rm -rf "$INSTALL_DIR"
    fi

    # Remove old CLI symlink
    if [ -L "/usr/local/bin/fixonce" ] || [ -f "/usr/local/bin/fixonce" ]; then
        log "  Removing old CLI symlink..."
        rm -f "/usr/local/bin/fixonce" 2>/dev/null || sudo rm -f "/usr/local/bin/fixonce" 2>/dev/null || true
    fi

    # ========== FRESH INSTALL ==========
    log "  Creating fresh installation directory..."
    set_progress_at 2 24 "Preparing installation" "Creating the FixOnce installation directory."
    mkdir -p "$INSTALL_DIR"

    # Copy ALL files using cp -a (preserves attributes, follows structure)
    log "  Copying source files..."
    start_progress_pulse 3 30 36 "Installing files" "Copying FixOnce application files"
    cp -a "$RESOURCES/src" "$INSTALL_DIR/"
    set_progress_at 3 32 "Installing files" "Copying installer scripts."
	    cp -a "$RESOURCES/scripts" "$INSTALL_DIR/"
	    set_progress_at 3 34 "Installing files" "Copying dashboard assets."
	    cp -a "$RESOURCES/data" "$INSTALL_DIR/"
	    cp -a "$RESOURCES/assets" "$INSTALL_DIR/" 2>/dev/null || true
	    set_progress_at 3 35 "Installing files" "Copying browser extension files."
    cp -a "$RESOURCES/extension" "$INSTALL_DIR/" 2>/dev/null || true
    cp -a "$RESOURCES/requirements.txt" "$INSTALL_DIR/"
    cp -a "$RESOURCES/CLAUDE.md" "$INSTALL_DIR/" 2>/dev/null || true
    stop_progress_pulse

    # ========== VERIFY COPY ==========
    log "  Verifying installation..."
    set_progress_at 3 38 "Installing files" "Verifying copied FixOnce files."

    # Check critical files exist
    CRITICAL_FILES=(
        "src/config.py"
        "src/server.py"
        "src/version.py"
        "src/mcp_server/mcp_memory_server_v2.py"
	        "src/core/port_manager.py"
	        "scripts/install.py"
	        "scripts/menubar_app.py"
	        "requirements.txt"
	        "data/dashboard.html"
    )

    MISSING_FILES=""
    for file in "${CRITICAL_FILES[@]}"; do
        if [ ! -f "$INSTALL_DIR/$file" ]; then
            MISSING_FILES="$MISSING_FILES\n  - $file"
        fi
    done

    if [ -n "$MISSING_FILES" ]; then
        log "${RED}✗${NC} Copy failed! Missing files:$MISSING_FILES"
        show_error "Installation failed: Source files not copied correctly.\n\nMissing files:$MISSING_FILES\n\nPlease re-download the installer."
        exit 1
    fi

    # Verify config.py has Path.home() (not hardcoded paths)
    if ! grep -q "Path.home()" "$INSTALL_DIR/src/config.py"; then
        log "${RED}✗${NC} config.py doesn't use Path.home() - wrong version!"
        show_error "Installation failed: Wrong version of config.py bundled."
        exit 1
    fi

    log "${GREEN}✓${NC} Files copied and verified at $INSTALL_DIR"

    # ========== USER DATA DIRECTORY ==========
    # Create user-specific data directory
    USER_DATA="$HOME/.fixonce"
    mkdir -p "$USER_DATA"
    mkdir -p "$USER_DATA/projects_v2"
    mkdir -p "$USER_DATA/logs"

    log "${GREEN}✓${NC} User data directory created at $USER_DATA"

    # Create .fixonce metadata in INSTALL_DIR for project detection
    mkdir -p "$INSTALL_DIR/.fixonce"
    PROJECT_ID="FixOnce_$(openssl rand -hex 4)"
    cat > "$INSTALL_DIR/.fixonce/metadata.json" << EOF
{
  "fixonce_version": "$VERSION",
  "project_id": "$PROJECT_ID",
  "name": "FixOnce",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "working_dir_original": "$INSTALL_DIR"
}
EOF
    log "${GREEN}✓${NC} Created project metadata"
}

# ============================================================
# Install Python Dependencies
# ============================================================

install_dependencies() {
    log "${BLUE}Installing Python dependencies...${NC}"
    set_progress_at 3 40 "Installing files" "Preparing the Python environment."
    write_install_state "INSTALLING" "Installing application dependencies"

    cd "$INSTALL_DIR"

    # Verify requirements.txt exists
    if [ ! -f "$INSTALL_DIR/requirements.txt" ]; then
        log "${RED}✗${NC} requirements.txt not found!"
        show_error "Installation failed: requirements.txt missing.\n\nPlease re-download the installer."
        exit 1
    fi

    # Create virtual environment using SELECTED_PYTHON (set by preflight)
    # Always recreate to ensure correct Python version
    if [ -d "$INSTALL_DIR/venv" ]; then
        log "  Removing old venv (may have wrong Python version)..."
        rm -rf "$INSTALL_DIR/venv"
    fi

    log "  Creating virtual environment with $SELECTED_PYTHON..."
    start_progress_pulse 3 41 44 "Installing files" "Creating the Python virtual environment"
    if "$SELECTED_PYTHON" -m venv "$INSTALL_DIR/venv"; then
        stop_progress_pulse
        set_progress_at 3 45 "Installing files" "Python virtual environment created."
    else
        stop_progress_pulse
        log "${RED}✗${NC} Failed to create virtual environment"
        show_error "Installation failed: Could not create Python virtual environment.\n\nUsed: $SELECTED_PYTHON\n\nTry: brew install python@3.12"
        exit 1
    fi
    log "${GREEN}✓${NC} Created virtual environment"

    # Use absolute paths for venv python/pip
    VENV_PYTHON="$INSTALL_DIR/venv/bin/python"
    VENV_PIP="$INSTALL_DIR/venv/bin/pip"

    # Verify venv python exists
    if [ ! -f "$VENV_PYTHON" ]; then
        log "${RED}✗${NC} venv Python not found at $VENV_PYTHON"
        show_error "Installation failed: Virtual environment is corrupted.\n\nTry deleting ~/FixOnce/venv and reinstalling."
        exit 1
    fi

    # Verify venv Python version >= 3.10
    VENV_VERSION=$("$VENV_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
    VENV_MAJOR=$("$VENV_PYTHON" -c 'import sys; print(sys.version_info.major)' 2>/dev/null)
    VENV_MINOR=$("$VENV_PYTHON" -c 'import sys; print(sys.version_info.minor)' 2>/dev/null)

    log "  venv Python version: $VENV_VERSION"

    if [ "$VENV_MAJOR" -ne 3 ] || [ "$VENV_MINOR" -lt 10 ]; then
        log "${RED}✗${NC} venv Python $VENV_VERSION < 3.10 - fastmcp won't work!"
        show_error "Virtual environment created with wrong Python.\n\nvenv Python: $VENV_VERSION (need >= 3.10)\n\nInstall Python 3.10+:\nbrew install python@3.12"
        exit 1
    fi
    log "${GREEN}✓${NC} venv Python $VENV_VERSION >= 3.10"

    # Upgrade pip first
    log "  Upgrading pip..."
    start_progress_pulse 3 46 49 "Installing files" "Upgrading Python packaging tools"
    if "$VENV_PYTHON" -m pip install --upgrade pip 2>&1 | tee -a "$LOG_FILE"; then
        stop_progress_pulse
        set_progress_at 3 50 "Installing files" "Python packaging tools are ready."
    else
        stop_progress_pulse
        log "${YELLOW}!${NC} pip upgrade failed (continuing anyway)"
    fi

    # Install dependencies with explicit path and error checking
    log "  Installing dependencies from requirements.txt..."
    start_progress_pulse 3 51 57 "Installing files" "Installing FixOnce Python dependencies"
	    if "$VENV_PYTHON" -m pip install -r "$INSTALL_DIR/requirements.txt" 2>&1 | tee -a "$LOG_FILE"; then
	        stop_progress_pulse
	        set_progress_at 3 58 "Installing files" "FixOnce Python dependencies installed."
    else
        stop_progress_pulse
        log "${RED}✗${NC} pip install failed!"
        show_error "Installation failed: Could not install Python dependencies.\n\nCheck the log at:\n$LOG_FILE\n\nCommon fixes:\n• Check internet connection\n• Try: pip install flask flask-cors"
	        exit 1
	    fi

    set_progress_at 3 58 "Installing files" "Installing FixOnce menu bar support."
    if "$VENV_PYTHON" -m pip install "rumps>=0.4.0" 2>&1 | tee -a "$LOG_FILE"; then
        log "    ${GREEN}✓${NC} rumps"
    else
        log "${RED}✗${NC} Could not install menu bar support"
        show_error "Installation failed: Could not install FixOnce menu bar support.\n\nCheck the log at:\n$LOG_FILE"
        exit 1
    fi

	    # Verify critical packages are installed
    log "  Verifying packages..."
    set_progress_at 3 59 "Installing files" "Verifying installed Python packages."
    MISSING_PACKAGES=""

    # Check each package individually with logging
    # flask
    set_progress_at 3 60 "Installing files" "Verifying Flask."
    if "$VENV_PYTHON" -c "import flask" 2>/dev/null; then
        log "    ${GREEN}✓${NC} flask"
    else
        log "    ${RED}✗${NC} flask"
        MISSING_PACKAGES="$MISSING_PACKAGES flask"
    fi

    # flask_cors
    set_progress_at 3 61 "Installing files" "Verifying Flask-CORS."
    if "$VENV_PYTHON" -c "from flask_cors import CORS" 2>/dev/null; then
        log "    ${GREEN}✓${NC} flask-cors"
    else
        log "    ${RED}✗${NC} flask-cors"
        MISSING_PACKAGES="$MISSING_PACKAGES flask-cors"
    fi

    # requests
    set_progress_at 3 62 "Installing files" "Verifying Requests."
    if "$VENV_PYTHON" -c "import requests" 2>/dev/null; then
        log "    ${GREEN}✓${NC} requests"
    else
        log "    ${RED}✗${NC} requests"
        MISSING_PACKAGES="$MISSING_PACKAGES requests"
    fi

    # fastmcp (MCP server)
    set_progress_at 3 63 "Installing files" "Verifying FastMCP."
    if "$VENV_PYTHON" -c "from fastmcp import FastMCP" 2>/dev/null; then
        log "    ${GREEN}✓${NC} fastmcp"
    else
        log "    ${RED}✗${NC} fastmcp"
        MISSING_PACKAGES="$MISSING_PACKAGES fastmcp"
    fi

    # watchdog (optional but helpful)
    set_progress_at 3 64 "Installing files" "Checking optional watchdog support."
	    if "$VENV_PYTHON" -c "import watchdog" 2>/dev/null; then
	        log "    ${GREEN}✓${NC} watchdog"
	    else
	        log "    ${YELLOW}!${NC} watchdog (optional)"
	    fi

    # rumps (macOS menu bar)
    set_progress_at 3 65 "Installing files" "Verifying menu bar support."
    if "$VENV_PYTHON" -c "import rumps" 2>/dev/null; then
        log "    ${GREEN}✓${NC} rumps"
    else
        log "    ${RED}✗${NC} rumps"
        MISSING_PACKAGES="$MISSING_PACKAGES rumps"
    fi

    if [ -n "$MISSING_PACKAGES" ]; then
        log "${RED}✗${NC} Missing packages:$MISSING_PACKAGES"
        log "  Attempting manual install..."
        # Try to install missing packages
        start_progress_pulse 3 65 67 "Installing files" "Repairing missing Python packages"
        "$VENV_PYTHON" -m pip install $MISSING_PACKAGES 2>&1 | tee -a "$LOG_FILE"
        stop_progress_pulse

        # Re-verify EACH package
        log "  Re-verifying after manual install..."
        set_progress_at 3 68 "Installing files" "Rechecking repaired Python packages."
        STILL_MISSING=""

        if ! "$VENV_PYTHON" -c "import flask" 2>/dev/null; then
            STILL_MISSING="$STILL_MISSING flask"
        fi
        if ! "$VENV_PYTHON" -c "from flask_cors import CORS" 2>/dev/null; then
            STILL_MISSING="$STILL_MISSING flask-cors"
        fi
        if ! "$VENV_PYTHON" -c "import requests" 2>/dev/null; then
            STILL_MISSING="$STILL_MISSING requests"
        fi
        if ! "$VENV_PYTHON" -c "from fastmcp import FastMCP" 2>/dev/null; then
            STILL_MISSING="$STILL_MISSING fastmcp"
        fi

        if [ -n "$STILL_MISSING" ]; then
            log "${RED}✗${NC} Still missing after retry:$STILL_MISSING"
            show_error "Installation incomplete: Some packages failed to install.\n\nMissing:$STILL_MISSING\n\nTry running:\n$VENV_PIP install flask flask-cors fastmcp requests"
            exit 1
        fi

        log "${GREEN}✓${NC} Manual install succeeded"
    fi

    log "${GREEN}✓${NC} Dependencies installed and verified"
    set_progress_at 3 70 "Installing files" "Python environment is ready."
}

# ============================================================
# Configure MCP
# ============================================================

configure_mcp() {
    log "${BLUE}Configuring MCP integration...${NC}"
    start_progress_pulse 4 72 75 "Configuring integrations" "Connecting FixOnce to supported AI tools"

    # Run the existing install.py MCP configuration
    cd "$INSTALL_DIR"
    source venv/bin/activate

    python3 scripts/install.py --mcp-only 2>/dev/null || {
        stop_progress_pulse
        set_progress_at 4 75 "Configuring integrations" "Applying fallback integration configuration."
        # Fallback: configure manually
        CLAUDE_CONFIG="$HOME/.claude.json"
        MCP_ENTRY='{
  "mcpServers": {
    "fixonce": {
      "command": "'"$INSTALL_DIR"'/venv/bin/fastmcp",
      "args": ["run", "'"$INSTALL_DIR"'/src/mcp_server/mcp_memory_server_v2.py", "--transport", "stdio"],
      "env": {
        "PYTHONPATH": "'"$INSTALL_DIR"'/src",
        "FASTMCP_CHECK_FOR_UPDATES": "off",
        "FASTMCP_SHOW_CLI_BANNER": "false"
      }
    }
  }
}'

        if [ -f "$CLAUDE_CONFIG" ]; then
            # Backup existing config
            cp "$CLAUDE_CONFIG" "$CLAUDE_CONFIG.backup.$(date +%s)"
            log "${YELLOW}!${NC} Backed up existing Claude config"
        fi

        # For now, just note that MCP needs manual setup
        log "${YELLOW}!${NC} MCP configuration may need manual setup"
    }
    stop_progress_pulse

    log "${GREEN}✓${NC} MCP configuration complete"
    set_progress_at 4 76 "Configuring integrations" "AI tool integrations are configured."
}

# ============================================================
	# Setup LaunchAgent (creates plist but does NOT load yet)
	# ============================================================

	setup_launchagent() {
	    log "${BLUE}Setting up auto-start...${NC}"
	    set_progress_at 5 80 "Starting FixOnce services" "Preparing automatic startup."
	    write_install_state "STARTING" "Preparing automatic startup"

	    LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
	    SERVER_PLIST_FILE="$LAUNCH_AGENTS/com.fixonce.server.plist"
	    TRAY_PLIST_FILE="$LAUNCH_AGENTS/com.fixonce.tray.plist"
	    USER_LOGS="$HOME/.fixonce/logs"

	    mkdir -p "$LAUNCH_AGENTS"
	    mkdir -p "$USER_LOGS"

	    # Unload any existing agents first.
	    launchctl unload "$SERVER_PLIST_FILE" 2>/dev/null || true
	    launchctl unload "$TRAY_PLIST_FILE" 2>/dev/null || true
	    launchctl remove com.fixonce.server 2>/dev/null || true
	    launchctl remove com.fixonce.tray 2>/dev/null || true
	    pkill -f "$INSTALL_DIR/scripts/app_launcher.py --menubar" 2>/dev/null || true

	    cat > "$SERVER_PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fixonce.server</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/venv/bin/python</string>
        <string>$INSTALL_DIR/src/server.py</string>
        <string>--flask-only</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$USER_LOGS/server.log</string>
    <key>StandardErrorPath</key>
    <string>$USER_LOGS/server.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

	    cat > "$TRAY_PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fixonce.tray</string>
    <key>ProgramArguments</key>
    <array>
        <string>$INSTALL_DIR/venv/bin/python</string>
        <string>$INSTALL_DIR/scripts/app_launcher.py</string>
        <string>--menubar</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>ThrottleInterval</key>
    <integer>30</integer>
    <key>StandardOutPath</key>
    <string>$USER_LOGS/tray.log</string>
    <key>StandardErrorPath</key>
    <string>$USER_LOGS/tray.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$INSTALL_DIR/venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>PYTHONPATH</key>
        <string>$INSTALL_DIR/src</string>
    </dict>
</dict>
</plist>
EOF

	    touch "$USER_LOGS/server.log" "$USER_LOGS/server.error.log" "$USER_LOGS/tray.log" "$USER_LOGS/tray.error.log"
	    log "${GREEN}✓${NC} Auto-start services prepared"
	}

# ============================================================
# Startup Recovery: load service, wait for readiness, retry once
# ============================================================

clear_stale_runtime_state() {
    local runtime_file="$HOME/.fixonce/runtime.json"
    local lock_file="$HOME/.fixonce/server.lock"

    if [ -f "$runtime_file" ]; then
        local runtime_pid
        runtime_pid=$(python3 -c "import json; import pathlib; p=pathlib.Path('$runtime_file'); data=json.loads(p.read_text()) if p.exists() else {}; print(data.get('pid',''))" 2>/dev/null)
        if [ -n "$runtime_pid" ] && ! kill -0 "$runtime_pid" 2>/dev/null; then
            rm -f "$runtime_file"
        fi
    fi

    if [ -f "$lock_file" ]; then
        local lock_pid
        lock_pid=$(cat "$lock_file" 2>/dev/null || true)
        if [ -n "$lock_pid" ] && ! kill -0 "$lock_pid" 2>/dev/null; then
            rm -f "$lock_file"
        fi
    fi
}

load_launchagent() {
    local label="$1"
    local plist_file="$2"
    local domain="gui/$(id -u)"

    launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
    launchctl unload "$plist_file" >/dev/null 2>&1 || true

    if launchctl bootstrap "$domain" "$plist_file" >"$LAUNCHCTL_LOG" 2>&1; then
        return 0
    fi

    if launchctl kickstart -k "$domain/$label" >> "$LAUNCHCTL_LOG" 2>&1; then
        return 0
    fi

    if launchctl load "$plist_file" >> "$LAUNCHCTL_LOG" 2>&1; then
        return 0
    fi

    return 1
}

load_launchagent_service() {
    load_launchagent "com.fixonce.server" "$HOME/Library/LaunchAgents/com.fixonce.server.plist"
}

load_launchagent_tray() {
    load_launchagent "com.fixonce.tray" "$HOME/Library/LaunchAgents/com.fixonce.tray.plist"
}

discover_runtime_port() {
    local runtime_file="$HOME/.fixonce/runtime.json"
    if [ -f "$runtime_file" ]; then
        python3 -c "import json; print(json.load(open('$runtime_file')).get('port', ''))" 2>/dev/null
        return
    fi

    for p in 5000 5001 5002 5003 5004 5005 5006 5007 5008 5009; do
        if curl -fsS --connect-timeout 1 "http://localhost:$p/api/health" >/dev/null 2>&1; then
            echo "$p"
            return
        fi
    done
}

validate_runtime_ownership() {
    local port="$1"
    local expected_user="$2"
    local expected_install_dir="$3"
    local runtime_file="$HOME/.fixonce/runtime.json"

    python3 - "$runtime_file" "$port" "$expected_user" "$expected_install_dir" << 'PY'
import json
import os
import pathlib
import sys
import urllib.request

runtime_file = pathlib.Path(sys.argv[1])
port = int(sys.argv[2])
expected_user = sys.argv[3]
expected_install_dir = os.path.realpath(sys.argv[4])

if not runtime_file.exists():
    print("runtime.json is missing")
    sys.exit(1)

try:
    runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"runtime.json is invalid: {exc}")
    sys.exit(1)

runtime_port = runtime.get("port")
runtime_user = runtime.get("user")
runtime_install_path = runtime.get("install_path")

if runtime_port != port:
    print(f"runtime port mismatch: expected {port}, got {runtime_port}")
    sys.exit(1)

if runtime_user != expected_user:
    print(f"runtime user mismatch: expected {expected_user}, got {runtime_user}")
    sys.exit(1)

if os.path.realpath(runtime_install_path or "") != expected_install_dir:
    print(
        f"runtime install_path mismatch: expected {expected_install_dir}, "
        f"got {os.path.realpath(runtime_install_path or '')}"
    )
    sys.exit(1)

try:
    with urllib.request.urlopen(f"http://localhost:{port}/api/ping", timeout=2) as response:
        ping = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    print(f"/api/ping failed: {exc}")
    sys.exit(1)

if ping.get("service") != "fixonce":
    print(f"unexpected service identity: {ping.get('service')}")
    sys.exit(1)

if ping.get("user") != expected_user:
    print(f"ping user mismatch: expected {expected_user}, got {ping.get('user')}")
    sys.exit(1)

if os.path.realpath(ping.get("install_path") or "") != expected_install_dir:
    print(
        f"ping install_path mismatch: expected {expected_install_dir}, "
        f"got {os.path.realpath(ping.get('install_path') or '')}"
    )
    sys.exit(1)

print("ok")
PY
}

wait_for_runtime_health() {
    local max_attempts="${1:-30}"
    local attempt=0
    local current_user="$(whoami)"

    while [ $attempt -lt $max_attempts ]; do
        attempt=$((attempt + 1))
        local progress=$((82 + attempt / 3))
        if [ "$progress" -gt 94 ]; then
            progress=94
        fi
        set_progress_at 5 "$progress" "Starting FixOnce services" "Waiting for FixOnce service health check ($attempt/$max_attempts)."
        sleep 1

        local runtime_port
        runtime_port=$(discover_runtime_port)
        if [ -n "$runtime_port" ] && curl -fsS --connect-timeout 1 "http://localhost:$runtime_port/api/health" >/dev/null 2>&1; then
            local ownership_result
            if ownership_result=$(validate_runtime_ownership "$runtime_port" "$current_user" "$INSTALL_DIR" 2>&1); then
                echo "$runtime_port"
                return 0
            fi
            echo "$ownership_result" >> "$LAUNCHCTL_LOG"
        fi

        if [ $((attempt % 5)) -eq 0 ]; then
            log "  Waiting for FixOnce to finish starting... ($attempt/$max_attempts)" >&2
        fi
    done

    return 1
}

inspect_startup_failure() {
    local user_logs="$HOME/.fixonce/logs"
    local launchctl_log="$LAUNCHCTL_LOG"
    local runtime_file="$HOME/.fixonce/runtime.json"

    log "  Last launchctl output:"
    tail -10 "$launchctl_log" 2>/dev/null | while read line; do
        log "    $line"
    done

    if [ -f "$runtime_file" ]; then
        log "  Current runtime.json:"
        tail -20 "$runtime_file" 2>/dev/null | while read line; do
            log "    $line"
        done
    fi

    log "  Last server log lines:"
    tail -10 "$user_logs/server.log" 2>/dev/null | while read line; do
        log "    $line"
    done

    log "  Last server error log lines:"
    tail -10 "$user_logs/server.error.log" 2>/dev/null | while read line; do
        log "    $line"
    done
}

verify_and_enable_service() {
    log "${BLUE}Starting FixOnce in the background...${NC}"
    set_progress_at 5 81 "Starting FixOnce services" "Starting the local FixOnce service."
    write_install_state "WAITING_HEALTH" "Starting FixOnce services"

    local port=""
    local attempt=1
    local max_attempts=2

    while [ $attempt -le $max_attempts ]; do
        if [ $attempt -gt 1 ]; then
            log "${YELLOW}!${NC} First startup attempt did not become ready. Repairing and retrying..."
            set_progress_at 5 84 "Starting FixOnce services" "Retrying service startup after automatic repair."
            write_install_state "RECOVERY" "Retrying background startup"
            setup_launchagent
        fi

        clear_stale_runtime_state
        set_progress_at 5 82 "Starting FixOnce services" "Clearing stale runtime state."

        if ! load_launchagent_service; then
            log "${RED}✗${NC} Could not load the auto-start service"
            inspect_startup_failure
            attempt=$((attempt + 1))
            continue
        fi

        if port=$(wait_for_runtime_health 35); then
            if ! [[ "$port" =~ ^[0-9]+$ ]]; then
                log "${RED}✗${NC} Invalid runtime port detected: $port"
                return 1
            fi
            log "${GREEN}✓${NC} FixOnce is ready on port $port"
	            set_progress_at 5 95 "Starting FixOnce services" "FixOnce service is ready."
            write_install_state "READY" "FixOnce is ready"
            mkdir -p "$HOME/.fixonce"
            cat > "$HOME/.fixonce/config.json" << EOF
{
  "port": $port,
  "user": "$(whoami)",
  "install_dir": "$INSTALL_DIR",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
            return 0
        fi

        log "${YELLOW}!${NC} FixOnce did not become ready after startup attempt $attempt"
        inspect_startup_failure
        attempt=$((attempt + 1))
    done

    write_install_state "FAILED" "Automatic startup failed after retry"
    return 1
}

start_menu_bar_app() {
    log "${BLUE}Starting FixOnce menu bar app...${NC}"

    if load_launchagent_tray; then
        log "${GREEN}✓${NC} FixOnce menu bar app started"
        return 0
    fi

    log "${YELLOW}!${NC} Could not load menu bar auto-start service; opening FixOnce.app directly"
    open_fixonce_app
}

# ============================================================
# Create CLI symlink
# ============================================================

create_cli() {
    log "${BLUE}Creating CLI command...${NC}"
    set_progress_at 4 77 "Configuring integrations" "Installing the FixOnce command-line helper."

    CLI_SCRIPT="$INSTALL_DIR/fixonce"

    cat > "$CLI_SCRIPT" << 'CLISCRIPT'
#!/bin/bash
# FixOnce CLI - Multi-user aware with self-healing

FIXONCE_DIR="$HOME/FixOnce"
VENV_PYTHON="$FIXONCE_DIR/venv/bin/python"
VENV_PIP="$FIXONCE_DIR/venv/bin/pip"
PLIST="$HOME/Library/LaunchAgents/com.fixonce.server.plist"
CONFIG_FILE="$HOME/.fixonce/config.json"
CURRENT_USER=$(whoami)

# Check if dependencies are installed
check_deps() {
    if [ ! -f "$VENV_PYTHON" ]; then
        echo "ERROR: Virtual environment not found at $FIXONCE_DIR/venv"
        echo "Try reinstalling FixOnce."
        return 1
    fi

    MISSING=""
    # Check flask
    if ! "$VENV_PYTHON" -c "import flask" 2>/dev/null; then
        MISSING="$MISSING flask"
    fi
    # Check flask-cors
    if ! "$VENV_PYTHON" -c "from flask_cors import CORS" 2>/dev/null; then
        MISSING="$MISSING flask-cors"
    fi
    # Check requests
    if ! "$VENV_PYTHON" -c "import requests" 2>/dev/null; then
        MISSING="$MISSING requests"
    fi
    # Check fastmcp (MCP server)
    if ! "$VENV_PYTHON" -c "from fastmcp import FastMCP" 2>/dev/null; then
        MISSING="$MISSING fastmcp"
    fi

    if [ -n "$MISSING" ]; then
        echo "WARNING: Missing Python packages:$MISSING"
        return 1
    fi
    return 0
}

# Self-healing: install missing dependencies
repair_deps() {
    echo "Repairing dependencies..."
    if [ ! -f "$FIXONCE_DIR/requirements.txt" ]; then
        echo "ERROR: requirements.txt not found"
        return 1
    fi

    echo "Running: pip install -r requirements.txt"
    "$VENV_PYTHON" -m pip install -r "$FIXONCE_DIR/requirements.txt"

    if check_deps; then
        echo "Dependencies repaired successfully!"
        return 0
    else
        echo "Repair failed. Try manual fix:"
        echo "  $VENV_PIP install flask flask-cors fastmcp requests"
        return 1
    fi
}

# Find our port (checks user ownership via /api/ping)
find_my_port() {
    # First check saved config
    if [ -f "$CONFIG_FILE" ]; then
        SAVED_PORT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE')).get('port', ''))" 2>/dev/null)
        if [ -n "$SAVED_PORT" ]; then
            OWNER=$(curl -s "http://localhost:$SAVED_PORT/api/ping" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
            INSTALL_PATH=$(curl -s "http://localhost:$SAVED_PORT/api/ping" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('install_path',''))" 2>/dev/null)
            if [ "$OWNER" = "$CURRENT_USER" ] && [ "$(python3 -c "import os; print(os.path.realpath('$INSTALL_PATH'))" 2>/dev/null)" = "$(python3 -c "import os; print(os.path.realpath('$FIXONCE_DIR'))")" ]; then
                echo "$SAVED_PORT"
                return
            fi
        fi
    fi

    # Scan ports to find ours
    for p in 5000 5001 5002 5003 5004 5005 5006 5007 5008 5009; do
        RESPONSE=$(curl -s "http://localhost:$p/api/ping" 2>/dev/null)
        if echo "$RESPONSE" | grep -q '"service":"fixonce"'; then
            OWNER=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
            INSTALL_PATH=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('install_path',''))" 2>/dev/null)
            if [ "$OWNER" = "$CURRENT_USER" ] && [ "$(python3 -c "import os; print(os.path.realpath('$INSTALL_PATH'))" 2>/dev/null)" = "$(python3 -c "import os; print(os.path.realpath('$FIXONCE_DIR'))")" ]; then
                echo "$p"
                return
            fi
        fi
    done
}

case "$1" in
    start)
        # Check deps before starting
        if ! check_deps; then
            echo ""
            read -p "Would you like to repair dependencies? [y/N] " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                repair_deps || exit 1
            else
                exit 1
            fi
        fi

        launchctl load "$PLIST" 2>/dev/null
        sleep 2
        PORT=$(find_my_port)
        if [ -n "$PORT" ]; then
            echo "FixOnce started on port $PORT"
        else
            echo "FixOnce may have failed to start. Check: fixonce doctor"
        fi
        ;;
    stop)
        launchctl unload "$PLIST" 2>/dev/null
        echo "FixOnce stopped"
        ;;
    restart)
        launchctl unload "$PLIST" 2>/dev/null
        sleep 1
        launchctl load "$PLIST"
        sleep 2
        PORT=$(find_my_port)
        echo "FixOnce restarted on port ${PORT:-?}"
        ;;
    status)
        PORT=$(find_my_port)
        if [ -n "$PORT" ]; then
            echo "FixOnce is running on port $PORT (user: $CURRENT_USER)"
        else
            echo "FixOnce is not running for user $CURRENT_USER"
            # Check if it's a dependency issue
            if ! check_deps; then
                echo "Run 'fixonce repair' to fix missing dependencies"
            fi
        fi
        ;;
    port)
        echo "Port status:"
        for p in 5000 5001 5002 5003 5004 5005; do
            RESPONSE=$(curl -s "http://localhost:$p/api/ping" 2>/dev/null)
            if echo "$RESPONSE" | grep -q '"service":"fixonce"'; then
                OWNER=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('user',''))" 2>/dev/null)
                if [ "$OWNER" = "$CURRENT_USER" ]; then
                    echo "  Port $p: FixOnce (yours)"
                else
                    echo "  Port $p: FixOnce (user: $OWNER)"
                fi
            fi
        done
        ;;
    repair)
        repair_deps
        ;;
    doctor)
        # Check deps first
        if ! check_deps; then
            echo "Dependencies missing - attempting repair first..."
            repair_deps
        fi
        cd "$FIXONCE_DIR"
        "$VENV_PYTHON" scripts/install.py --doctor
        echo ""
        echo "Log files: ~/.fixonce/logs/"
        ls -la "$HOME/.fixonce/logs/" 2>/dev/null || echo "  (no logs yet)"
        ;;
    logs)
        LOG_DIR="$HOME/.fixonce/logs"
        if [ ! -d "$LOG_DIR" ]; then
            echo "No logs directory found at $LOG_DIR"
            exit 1
        fi
        echo "=== Server Log (last 20 lines) ==="
        tail -20 "$LOG_DIR/server.log" 2>/dev/null || echo "(empty)"
        echo ""
        echo "=== Error Log (last 20 lines) ==="
        tail -20 "$LOG_DIR/server.error.log" 2>/dev/null || echo "(empty)"
        echo ""
        echo "Log files: $LOG_DIR/"
        ;;
    dashboard)
        PORT=$(find_my_port)
        if [ -n "$PORT" ]; then
            open "http://localhost:$PORT"
        else
            echo "FixOnce server not found."
            if ! check_deps; then
                echo "Dependencies missing. Run: fixonce repair"
            else
                echo "Try: fixonce start"
            fi
            exit 1
        fi
        ;;
    *)
        echo "Usage: fixonce {start|stop|restart|status|port|repair|doctor|logs|dashboard}"
        echo ""
        echo "Commands:"
        echo "  start      Start FixOnce server"
        echo "  stop       Stop FixOnce server"
        echo "  restart    Restart FixOnce server"
        echo "  status     Show if FixOnce is running"
        echo "  port       Show port allocation for all users"
        echo "  repair     Reinstall Python dependencies"
        echo "  doctor     Run diagnostics"
        echo "  logs       Show server logs"
        echo "  dashboard  Open dashboard in browser"
        exit 1
        ;;
esac
CLISCRIPT

    chmod +x "$CLI_SCRIPT"

    # Create symlink in /usr/local/bin if possible
    if [ -w "/usr/local/bin" ]; then
        ln -sf "$CLI_SCRIPT" /usr/local/bin/fixonce
        log "${GREEN}✓${NC} CLI installed: fixonce"
    else
        log "${YELLOW}!${NC} Run 'sudo ln -s $CLI_SCRIPT /usr/local/bin/fixonce' for global CLI"
    fi
}

# ============================================================
# Main Installation Flow
# ============================================================

main() {
    echo "" > "$LOG_FILE"
    handle_already_installed || true

    write_install_state "NOT_INSTALLED" "Installer opened"
    open_progress_window

    log ""
    log "${BLUE}========================================"
    log "  FixOnce Installer"
    log "========================================${NC}"
    log ""

    # Show welcome dialog
    osascript <<OSA >/dev/null 2>&1 || exit 0
display dialog "Install FixOnce\n\nThis setup will:\n• Install FixOnce\n• Connect your AI tools\n• Start FixOnce automatically\n• Start the FixOnce menu bar app\n\nClick Continue to begin." with title "FixOnce Installer" buttons {"Cancel", "Continue"} default button "Continue" with icon POSIX file "$ICON_FILE"
OSA

    # Run installation steps
    set_progress 1 "Checking system" "Checking Python, disk space, permissions, and existing installation state."
    preflight

    set_progress 2 "Preparing installation" "Preparing a clean FixOnce installation in your home folder."
    install_files

    set_progress_at 3 40 "Installing files" "Creating the Python environment and installing FixOnce dependencies."
    install_dependencies

    set_progress_at 4 72 "Configuring integrations" "Connecting FixOnce to supported AI tools and installing the command-line helper."
    configure_mcp
    create_cli
    install_runtime_app

    set_progress_at 5 80 "Starting FixOnce services" "Starting the local FixOnce service and waiting for it to become ready."
    setup_launchagent      # Creates plist but doesn't load

    # Health gate: verify server works BEFORE enabling LaunchAgent
    if ! verify_and_enable_service; then
        log "${RED}Installation failed: Server health check failed${NC}"
        log "Automatic startup could not be completed."
        log ""
        log "Installer checked:"
        log "  1. Background service loading"
        log "  2. Startup retry and repair"
        log "  3. Server logs in $HOME/.fixonce/logs/"
        show_error "FixOnce could not finish starting automatically.\n\nThe installer retried startup and collected logs.\n\nSee:\n$HOME/.fixonce/logs/\n\nYou should not need Terminal for normal installs, so this needs follow-up."
        exit 1
    fi

    set_progress_at 6 98 "Starting FixOnce" "Starting the FixOnce menu bar app and preparing post-install status."
    start_menu_bar_app

    log ""
    log "${GREEN}========================================"
    log "  Installation Complete!"
    log "========================================${NC}"
    log ""
    log "FixOnce is now installed and ready."
    log ""
    log "Quick commands:"
    log "  fixonce status    - Check FixOnce"
    log "  fixonce dashboard - Open FixOnce"
    log "  fixonce doctor    - Run diagnostics"
    log ""

    mark_install_success

    local result
    result=$(osascript <<OSA 2>/dev/null || true
display dialog "Installation complete.\n\nFixOnce has been installed successfully.\n\nUse FixOnce.app for daily use." with title "FixOnce Installer" buttons {"Done", "Create Desktop Shortcut", "Open FixOnce"} default button "Done" with icon POSIX file "$ICON_FILE"
OSA
)
    if [[ "$result" == *"Open FixOnce"* ]]; then
        open_fixonce_app || show_error "Could not open FixOnce.app."
    elif [[ "$result" == *"Create Desktop Shortcut"* ]]; then
        create_desktop_shortcut
    fi
}

# Run main
main 2>&1 | tee -a "$LOG_FILE"
INSTALLER_SCRIPT

chmod +x "$MACOS/installer"

audit_bundle "$RUNTIME_APP_BUNDLE" "FixOnce.app"
audit_bundle "$APP_BUNDLE" "FixOnce Installer.app"

echo ""
echo "Packaging audit: $AUDIT_REPORT"
echo "FixOnce.app size: $(du -sh "$RUNTIME_APP_BUNDLE" | cut -f1)"
echo "FixOnce Installer.app size: $(du -sh "$APP_BUNDLE" | cut -f1)"

if [ "$APP_ONLY" -eq 1 ]; then
    echo ""
    echo "========================================"
    echo "  App Prototype Build Complete!"
    echo "========================================"
    echo ""
    echo "Output: $APP_BUNDLE"
    echo ""
    echo "To test: open \"$APP_BUNDLE\""
    echo ""
    exit 0
fi

# ============================================================
# Step 5: Create DMG
# ============================================================
echo "[5/5] Creating DMG..."

DMG_PATH="$BUILD_DIR/$DMG_NAME.dmg"
DMG_TEMP="$BUILD_DIR/dmg_temp"

mkdir -p "$DMG_TEMP"
cp -R "$APP_BUNDLE" "$DMG_TEMP/"

# Create README
cat > "$DMG_TEMP/README - Install FixOnce.txt" << 'README'
FixOnce macOS Beta Installer
============================

To install FixOnce:
1. Double-click "FixOnce Installer.app"
2. Click Continue / Install
3. FixOnce.app will be installed into Applications
4. Use FixOnce.app for daily use

macOS security note:
This beta DMG is unsigned and not notarized yet.
If macOS blocks the app, right-click "FixOnce Installer.app" and choose Open.
If macOS still blocks it, this build needs signing/notarization before wider testing.

Requirements:
- macOS 10.15 or later
- Python 3.10 or later

After installation:
- FixOnce will start automatically on login
- Open FixOnce.app to start FixOnce and open the dashboard
- FixOnce Installer.app is only for install, repair, update, or uninstall
- Advanced users can run: fixonce status

For help: https://github.com/Nati41/FixOnce
README

if ! hdiutil create -volname "FixOnce Installer" \
    -srcfolder "$DMG_TEMP" \
    -ov -format UDZO \
    "$DMG_PATH"; then
    echo ""
    echo "========================================"
    echo "  DMG Creation Failed"
    echo "========================================"
    echo ""
    echo "hdiutil is unavailable or broken in this environment."
    echo "The installer staging folder is ready and was kept at:"
    echo "$DMG_TEMP"
    echo ""
    echo "Staged DMG root contents:"
    find "$DMG_TEMP" -maxdepth 1 -mindepth 1 -print | sed 's#^.*/#  - #'
    echo ""
    echo "To create the DMG on a real macOS machine, run:"
    echo "bash installer/macos/build_installer.sh"
    echo ""
    exit 1
fi

# Clean up
rm -rf "$DMG_TEMP"

echo ""
echo "========================================"
echo "  Build Complete!"
echo "========================================"
echo ""
echo "Output: $DMG_PATH"
echo "Size: $(du -h "$DMG_PATH" | cut -f1)"
echo ""
echo "To test: open \"$DMG_PATH\""
echo ""
