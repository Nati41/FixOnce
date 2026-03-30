# FixOnce Installer for Windows
# Usage: Right-click → Run with PowerShell
# Or: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

function Write-Step { param($msg) Write-Host "`n[$script:step/7] $msg" -ForegroundColor Cyan; $script:step++ }
function Write-OK { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "  ✗ $msg" -ForegroundColor Red }

$script:step = 1

Write-Host ""
Write-Host "🧠 FixOnce Installer for Windows" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ============ Step 1: Check Python ============
Write-Step "Checking Python..."

$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $pythonCmd = $found.Source
        break
    }
}

if (-not $pythonCmd) {
    Write-Err "Python not found!"
    Write-Host ""
    Write-Host "  Please install Python 3.9+ from:" -ForegroundColor Yellow
    Write-Host "  https://www.python.org/downloads/" -ForegroundColor White
    Write-Host ""
    Write-Host "  IMPORTANT: Check 'Add Python to PATH' during installation!" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

# Check Python version
$versionOutput = & $pythonCmd --version 2>&1
$versionMatch = [regex]::Match($versionOutput, "(\d+)\.(\d+)")
if ($versionMatch.Success) {
    $major = [int]$versionMatch.Groups[1].Value
    $minor = [int]$versionMatch.Groups[2].Value

    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 9)) {
        Write-Err "Python $major.$minor is too old. Need Python 3.9+"
        Write-Host "  Download from: https://www.python.org/downloads/"
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-OK "Python $major.$minor"
} else {
    Write-Warn "Could not determine Python version, continuing..."
}

# ============ Step 2: Check pip ============
Write-Step "Checking pip..."

try {
    $pipCheck = & $pythonCmd -m pip --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "pip not found"
    }
    Write-OK "pip available"
} catch {
    Write-Warn "pip not found, attempting to install..."
    try {
        & $pythonCmd -m ensurepip --upgrade 2>&1 | Out-Null
        Write-OK "pip installed"
    } catch {
        Write-Err "Could not install pip. Please run: python -m ensurepip"
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# ============ Step 3: Install Dependencies ============
Write-Step "Installing dependencies..."

$requirementsPath = Join-Path $ScriptDir "requirements.txt"
if (-not (Test-Path $requirementsPath)) {
    Write-Err "requirements.txt not found at $requirementsPath"
    Read-Host "Press Enter to exit"
    exit 1
}

try {
    $pipOutput = & $pythonCmd -m pip install -r $requirementsPath 2>&1
    if ($LASTEXITCODE -ne 0) {
        # Check for common errors
        if ($pipOutput -match "Microsoft Visual C\+\+") {
            Write-Err "VC++ Build Tools required for some packages"
            Write-Host ""
            Write-Host "  Download from:" -ForegroundColor Yellow
            Write-Host "  https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor White
            Write-Host ""
            Write-Host "  Install 'Desktop development with C++'" -ForegroundColor Yellow
            Read-Host "Press Enter to exit"
            exit 1
        }
        throw $pipOutput
    }
    Write-OK "Dependencies installed"
} catch {
    Write-Warn "Some dependencies may have failed: $_"
    Write-Host "  Try running manually: pip install -r requirements.txt"
}

# ============ Step 4: Check Write Permissions ============
Write-Step "Checking permissions..."

$dataDir = Join-Path $ScriptDir "data"
if (-not (Test-Path $dataDir)) {
    try {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    } catch {
        Write-Err "Cannot create data directory. Run as Administrator or check folder permissions."
        Read-Host "Press Enter to exit"
        exit 1
    }
}

$testFile = Join-Path $dataDir "test_write.tmp"
try {
    "test" | Out-File $testFile -Force
    Remove-Item $testFile -Force
    Write-OK "Write permissions OK"
} catch {
    Write-Err "Cannot write to data directory: $dataDir"
    Write-Host "  Run installer as Administrator or check folder permissions"
    Read-Host "Press Enter to exit"
    exit 1
}

# ============ Step 5: Configure MCP ============
Write-Step "Configuring MCP for AI editors..."

$mcpServerPath = Join-Path $ScriptDir "src\mcp_server\mcp_memory_server_v2.py"
$srcPath = Join-Path $ScriptDir "src"
$mcpConfig = @{
    mcpServers = @{
        fixonce = @{
            command = $pythonCmd
            args = @($mcpServerPath)
            env = @{
                PYTHONPATH = $srcPath
            }
        }
    }
}

# Claude Code config
$claudeConfig = Join-Path $env:USERPROFILE ".claude.json"
try {
    if (Test-Path $claudeConfig) {
        $existing = Get-Content $claudeConfig | ConvertFrom-Json -AsHashtable
        if (-not $existing.mcpServers) { $existing.mcpServers = @{} }
        $existing.mcpServers.fixonce = $mcpConfig.mcpServers.fixonce
        $existing | ConvertTo-Json -Depth 10 | Out-File $claudeConfig -Encoding UTF8
    } else {
        $mcpConfig | ConvertTo-Json -Depth 10 | Out-File $claudeConfig -Encoding UTF8
    }
    Write-OK "Claude Code configured"
} catch {
    Write-Warn "Could not configure Claude Code: $_"
}

# Cursor config
$cursorDir = Join-Path $env:APPDATA "Cursor"
$cursorConfig = Join-Path $cursorDir "mcp.json"
try {
    if (-not (Test-Path $cursorDir)) { New-Item -ItemType Directory -Path $cursorDir -Force | Out-Null }
    if (Test-Path $cursorConfig) {
        $existing = Get-Content $cursorConfig | ConvertFrom-Json -AsHashtable
        if (-not $existing.mcpServers) { $existing.mcpServers = @{} }
        $existing.mcpServers.fixonce = $mcpConfig.mcpServers.fixonce
        $existing | ConvertTo-Json -Depth 10 | Out-File $cursorConfig -Encoding UTF8
    } else {
        $mcpConfig | ConvertTo-Json -Depth 10 | Out-File $cursorConfig -Encoding UTF8
    }
    Write-OK "Cursor configured"
} catch {
    Write-Warn "Could not configure Cursor: $_"
}

# Codex config
$codexDir = Join-Path $env:USERPROFILE ".codex"
$codexConfig = Join-Path $codexDir "config.toml"
$codexProjectDir = Join-Path $ScriptDir ".codex"
$codexProjectConfig = Join-Path $codexProjectDir "config.toml"
$codexBlock = @"
[mcp_servers.fixonce]
command = "$pythonCmd"
args = ["$mcpServerPath"]

[mcp_servers.fixonce.env]
PYTHONPATH = "$srcPath"
"@

try {
    if (-not (Test-Path $codexDir)) { New-Item -ItemType Directory -Path $codexDir -Force | Out-Null }
    $existing = ""
    if (Test-Path $codexConfig) {
        $existing = Get-Content $codexConfig -Raw
        $existing = [regex]::Replace($existing, '(?ms)^\[mcp_servers\.fixonce\]\r?\n(?:.*\r?\n)*?(?=^\[|\z)', '')
        $existing = [regex]::Replace($existing, '(?ms)^\[mcp_servers\.fixonce\.env\]\r?\n(?:.*\r?\n)*?(?=^\[|\z)', '')
        $existing = $existing.Trim()
    }
    $final = if ([string]::IsNullOrWhiteSpace($existing)) { $codexBlock } else { "$existing`r`n`r`n$codexBlock" }
    $final | Out-File $codexConfig -Encoding UTF8
    Write-OK "Codex configured"
} catch {
    Write-Warn "Could not configure Codex: $_"
}

try {
    if (-not (Test-Path $codexProjectDir)) { New-Item -ItemType Directory -Path $codexProjectDir -Force | Out-Null }
    $codexBlock | Out-File $codexProjectConfig -Encoding UTF8
    Write-OK "Project Codex config created"
} catch {
    Write-Warn "Could not create project Codex config: $_"
}

# ============ Step 5b: Configure Claude Code Hooks ============
Write-Host ""
Write-Host "  Configuring Claude Code hooks..." -ForegroundColor Cyan

$claudeSettingsDir = Join-Path $env:USERPROFILE ".claude"
$claudeSettings = Join-Path $claudeSettingsDir "settings.json"
$hooksDir = Join-Path $ScriptDir "hooks"

# Hook script paths (PowerShell for Windows)
$sessionStartScript = Join-Path $hooksDir "session_start.ps1"
$sessionEndScript = Join-Path $hooksDir "session_end.ps1"
$postToolScript = Join-Path $hooksDir "post_tool_use.ps1"

# Hook commands: run PowerShell with the script
$sessionStartCmd = "powershell.exe -ExecutionPolicy Bypass -File `"$sessionStartScript`""
$sessionEndCmd = "powershell.exe -ExecutionPolicy Bypass -File `"$sessionEndScript`""
$postToolCmd = "powershell.exe -ExecutionPolicy Bypass -File `"$postToolScript`""

try {
    if (-not (Test-Path $claudeSettingsDir)) { New-Item -ItemType Directory -Path $claudeSettingsDir -Force | Out-Null }

    $settings = @{}
    if (Test-Path $claudeSettings) {
        $settings = Get-Content $claudeSettings -Raw | ConvertFrom-Json -AsHashtable
    }

    # Configure hooks
    $settings["hooks"] = @{
        "SessionStart" = @(
            @{
                "matcher" = ""
                "hooks" = @(
                    @{
                        "type" = "command"
                        "command" = $sessionStartCmd
                        "timeout" = 5
                    }
                )
            }
        )
        "SessionEnd" = @(
            @{
                "matcher" = ""
                "hooks" = @(
                    @{
                        "type" = "command"
                        "command" = $sessionEndCmd
                        "timeout" = 5
                    }
                )
            }
        )
        "PostToolUse" = @(
            @{
                "matcher" = "Edit|Write|NotebookEdit|Bash"
                "hooks" = @(
                    @{
                        "type" = "command"
                        "command" = $postToolCmd
                        "timeout" = 5
                    }
                )
            }
        )
    }

    # Enable MCP for all projects
    $settings["enableAllProjectMcpServers"] = $true

    $settings | ConvertTo-Json -Depth 10 | Out-File $claudeSettings -Encoding UTF8
    Write-OK "Claude Code hooks configured (PowerShell, auto-connect enabled)"
} catch {
    Write-Warn "Could not configure Claude Code hooks: $_"
}

# ============ Step 6: Configure Auto-Start ============
Write-Step "Configuring auto-start..."

$taskName = "FixOnceServer"
$serverScript = Join-Path $ScriptDir "src\server.py"

# Check if task already exists
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-OK "Auto-start already configured"
} else {
    try {
        # Find pythonw for background execution
        $pythonwCmd = $pythonCmd -replace "python\.exe$", "pythonw.exe"
        if (-not (Test-Path $pythonwCmd)) { $pythonwCmd = $pythonCmd }

        $action = New-ScheduledTaskAction -Execute $pythonwCmd -Argument "`"$serverScript`" --flask-only" -WorkingDirectory (Join-Path $ScriptDir "src")
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
        Write-OK "Auto-start configured (Task Scheduler with restart on failure)"
    } catch {
        Write-Warn "Could not configure auto-start: $_"
        Write-Host "  You can start manually: python src\server.py"
    }
}

# ============ Step 7: Chrome Extension ============
Write-Step "Chrome Extension setup..."

$extensionDir = Join-Path $ScriptDir "extension"
Write-Host ""
Write-Host "  To capture browser errors, install the Chrome extension:" -ForegroundColor Yellow
Write-Host ""

# Try to open Chrome extensions page
try {
    Start-Process "chrome://extensions/"
    Write-Host "  Chrome extensions page opened!" -ForegroundColor Green
} catch {
    Write-Host "  Open Chrome and go to: chrome://extensions/" -ForegroundColor White
}

Write-Host ""
Write-Host "  1. Enable 'Developer mode' (top right toggle)" -ForegroundColor White
Write-Host "  2. Click 'Load unpacked'" -ForegroundColor White
Write-Host "  3. Select folder: $extensionDir" -ForegroundColor Cyan
Write-Host ""

# ============ Step 7b: Mark Installation Complete ============
Write-Host ""
Write-Host "  Marking installation complete..." -ForegroundColor Cyan

$userDataDir = Join-Path $env:USERPROFILE ".fixonce"
try {
    if (-not (Test-Path $userDataDir)) { New-Item -ItemType Directory -Path $userDataDir -Force | Out-Null }

    $installState = Join-Path $userDataDir "install_state.json"
    $state = @{
        "installed" = $true
        "installed_at" = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        "version" = "1.0.12"
        "installer" = "powershell"
    }
    $state | ConvertTo-Json | Out-File $installState -Encoding UTF8
    Write-OK "Installation state saved"
} catch {
    Write-Warn "Could not save installation state: $_"
}

# ============ Start Server ============
Write-Host "`n[✓] Starting FixOnce..." -ForegroundColor Cyan

try {
    Start-Process -FilePath $pythonCmd -ArgumentList "`"$serverScript`" --flask-only" -WorkingDirectory (Join-Path $ScriptDir "src") -WindowStyle Hidden
    Start-Sleep -Seconds 2

    # Open dashboard
    Start-Process "http://localhost:5000"
    Write-OK "FixOnce started! Dashboard opening..."
} catch {
    Write-Warn "Could not auto-start. Run manually: python src\server.py"
}

# ============ Done ============
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✓ Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  FixOnce will start automatically on login." -ForegroundColor White
Write-Host "  Dashboard: http://localhost:5000" -ForegroundColor Cyan
Write-Host ""
Write-Host "  To uninstall: .\uninstall.ps1" -ForegroundColor Yellow
Write-Host ""

Read-Host "Press Enter to close"
