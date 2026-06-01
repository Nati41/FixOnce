# FixOnce Uninstaller for Windows
# Usage: Right-click → Run with PowerShell

$ErrorActionPreference = "SilentlyContinue"

function Write-OK { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "🧠 FixOnce Uninstaller" -ForegroundColor Cyan
Write-Host "======================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\FixOnce"
if ((Test-Path (Join-Path $ScriptDir "FixOnce.exe")) -and ($ScriptDir -match "\\Programs\\FixOnce$")) {
    $InstallDir = $ScriptDir
}
$UserDataDir = Join-Path $env:USERPROFILE ".fixonce"

Write-Host "This will remove FixOnce from your system." -ForegroundColor Yellow
Write-Host ""
Write-Host "What will be removed:"
Write-Host "  - Scheduled Task (auto-start)"
Write-Host "  - MCP configuration from Codex/Claude/Cursor"
Write-Host "  - Desktop and Start Menu shortcuts"
Write-Host "  - Installed app files"
Write-Host ""
Write-Host "What will NOT be removed:"
Write-Host "  - Runtime data in $UserDataDir"
Write-Host "  - Chrome extension (remove manually)"
Write-Host ""

$confirm = Read-Host "Continue? (y/N)"
if ($confirm -ne 'y' -and $confirm -ne 'Y') {
    Write-Host "Cancelled."
    exit 0
}

Write-Host ""

# Stop server
Write-Host "[1/5] Stopping FixOnce server..."
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.Name -match '^python.*\.exe$|^FixOnce\.exe$') -and
        ($_.CommandLine -match 'server\.py|mcp_memory_server|--server')
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Write-OK "Server stopped"

# Remove Scheduled Task
Write-Host "[2/5] Removing auto-start..."
$taskName = "FixOnceServer"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-OK "Scheduled Task removed"
} else {
    Write-Warn "Scheduled Task not found (already removed?)"
}

# Remove MCP from Claude Code
Write-Host "[3/5] Removing MCP from Claude Code..."
$claudeConfig = Join-Path $env:USERPROFILE ".claude.json"
if (Test-Path $claudeConfig) {
    try {
        $config = Get-Content $claudeConfig | ConvertFrom-Json
        if ($config.mcpServers -and $config.mcpServers.fixonce) {
            $config.mcpServers.PSObject.Properties.Remove('fixonce')
            $config | ConvertTo-Json -Depth 10 | Out-File $claudeConfig -Encoding UTF8
            Write-OK "Removed from Claude Code"
        } else {
            Write-Warn "Not configured in Claude Code"
        }
    } catch {
        Write-Warn "Could not update Claude config"
    }
} else {
    Write-Warn "Claude config not found"
}

# Remove MCP from Cursor
Write-Host "[4/5] Removing MCP from Cursor..."
$cursorConfig = Join-Path $env:APPDATA "Cursor\mcp.json"
if (Test-Path $cursorConfig) {
    try {
        $config = Get-Content $cursorConfig | ConvertFrom-Json
        if ($config.mcpServers -and $config.mcpServers.fixonce) {
            $config.mcpServers.PSObject.Properties.Remove('fixonce')
            $config | ConvertTo-Json -Depth 10 | Out-File $cursorConfig -Encoding UTF8
            Write-OK "Removed from Cursor"
        } else {
            Write-Warn "Not configured in Cursor"
        }
    } catch {
        Write-Warn "Could not update Cursor config"
    }
} else {
    Write-Warn "Cursor config not found"
}

# Remove MCP from Codex
$codexConfig = Join-Path $env:USERPROFILE ".codex\config.toml"
if (Test-Path $codexConfig) {
    try {
        $content = Get-Content $codexConfig -Raw
        $content = [regex]::Replace($content, '(?ms)^\[mcp_servers\.fixonce\]\r?\n(?:.*\r?\n)*?(?=^\[|\z)', '')
        $content = [regex]::Replace($content, '(?ms)^\[mcp_servers\.fixonce\.env\]\r?\n(?:.*\r?\n)*?(?=^\[|\z)', '')
        $content.TrimEnd() | Out-File $codexConfig -Encoding UTF8
        Write-OK "Removed from Codex"
    } catch {
        Write-Warn "Could not update Codex config"
    }
} else {
    Write-Warn "Codex config not found"
}

# Remove shortcuts and installed files
Write-Host "[5/5] Cleaning up..."
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = Join-Path $desktop "FixOnce.lnk"
if (Test-Path $shortcut) {
    Remove-Item $shortcut -Force
    Write-OK "Desktop shortcut removed"
} else {
    Write-Warn "Desktop shortcut not found"
}

$startMenu = [Environment]::GetFolderPath("StartMenu")
$programsDir = Join-Path $startMenu "Programs\FixOnce"
foreach ($shortcutName in @("FixOnce.lnk", "Uninstall FixOnce.lnk")) {
    $startShortcut = Join-Path $programsDir $shortcutName
    if (Test-Path $startShortcut) {
        Remove-Item $startShortcut -Force
        Write-OK "Start Menu shortcut removed: $shortcutName"
    }
}
if (Test-Path $programsDir) {
    Remove-Item $programsDir -Force -ErrorAction SilentlyContinue
}

$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$startupShortcut = Join-Path $startupDir "FixOnceServer.lnk"
if (Test-Path $startupShortcut) {
    Remove-Item $startupShortcut -Force
    Write-OK "Startup autostart shortcut removed"
} else {
    Write-Warn "Startup autostart shortcut not found"
}

$installState = Join-Path $UserDataDir "install_state.json"
if (Test-Path $installState) {
    Remove-Item $installState -Force -ErrorAction SilentlyContinue
    Write-OK "Installation state removed"
}

if ((Test-Path $InstallDir) -and ($InstallDir -ne $UserDataDir)) {
    try {
        Remove-Item $InstallDir -Recurse -Force -ErrorAction Stop
        Write-OK "Installed app files removed"
    } catch {
        Write-Warn "Could not remove installed app files now. Close FixOnce and delete: $InstallDir"
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✓ Uninstall Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Your runtime data in $UserDataDir is preserved."
Write-Host ""
Write-Host "To remove Chrome extension:"
Write-Host "  chrome://extensions/ → Find FixOnce → Remove"
Write-Host ""

Read-Host "Press Enter to close"
