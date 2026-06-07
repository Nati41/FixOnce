# FixOnce Installer for Windows
# Usage: Right-click and choose Run with PowerShell
# Or: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

function Write-Step { param($msg) Write-Host "`n[$script:step/8] $msg" -ForegroundColor Cyan; $script:step++ }
function Write-OK { param($msg) Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  WARN  $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "  ERROR  $msg" -ForegroundColor Red }

$script:step = 1

Write-Host ""
Write-Host "FixOnce Installer for Windows" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\FixOnce"
$InstalledExe = Join-Path $InstallDir "FixOnce.exe"
$UserDataDir = Join-Path $env:USERPROFILE ".fixonce"
$RepairMode = $false
$LauncherScript = Join-Path $ScriptDir "scripts\app_launcher.py"
$PackagedExe = Join-Path $ScriptDir "FixOnce.exe"
if (-not (Test-Path $PackagedExe)) {
    $DistExe = Join-Path $ScriptDir "dist\FixOnce\FixOnce.exe"
    if (Test-Path $DistExe) { $PackagedExe = $DistExe }
}

function Test-FixOnceInstalled {
    if (Test-Path $InstalledExe) { return $true }

    $installState = Join-Path $UserDataDir "install_state.json"
    if (Test-Path $installState) {
        try {
            $state = Get-Content $installState -Raw | ConvertFrom-Json
            if ($state.installed -eq $true -and $state.install_dir -and (Test-Path (Join-Path $state.install_dir "FixOnce.exe"))) {
                $script:InstalledExe = Join-Path $state.install_dir "FixOnce.exe"
                $script:InstallDir = $state.install_dir
                return $true
            }
        } catch {
            return $false
        }
    }

    return $false
}

function Show-AlreadyInstalledMenu {
    Write-Host ""
    Write-Host "FixOnce is already installed." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  [1] Open FixOnce"
    Write-Host "  [2] Repair Installation"
    Write-Host "  [3] Uninstall"
    Write-Host "  [4] Close"
    Write-Host ""

    $choice = Read-Host "Choose an option"
    switch ($choice) {
        "1" {
            Start-Process -FilePath $InstalledExe -WorkingDirectory (Split-Path -Parent $InstalledExe)
            exit 0
        }
        "2" {
            $script:RepairMode = $true
            Write-Host ""
            Write-Host "Repairing existing installation..." -ForegroundColor Cyan
        }
        "3" {
            $uninstaller = Join-Path $InstallDir "uninstall.ps1"
            if (-not (Test-Path $uninstaller)) { $uninstaller = Join-Path $ScriptDir "uninstall.ps1" }
            if (Test-Path $uninstaller) {
                Start-Process -FilePath "powershell.exe" -ArgumentList @("-ExecutionPolicy", "Bypass", "-File", "`"$uninstaller`"") -Wait
            } else {
                Write-Warn "Uninstaller not found."
                Read-Host "Press Enter to close"
            }
            exit 0
        }
        default {
            exit 0
        }
    }
}

if (Test-FixOnceInstalled) {
    Show-AlreadyInstalledMenu
}

function Get-LauncherCommand {
    param(
        [switch]$ServerMode
    )

    if (Test-Path $PackagedExe) {
        $args = @()
        if ($ServerMode) { $args += "--server" }
        return @{
            FilePath = $PackagedExe
            Arguments = $args
            WorkingDirectory = (Split-Path -Parent $PackagedExe)
            DisplayName = "FixOnce.exe"
        }
    }

    $pythonwCmd = $pythonCmd -replace "python\.exe$", "pythonw.exe"
    if (-not (Test-Path $pythonwCmd)) { $pythonwCmd = $pythonCmd }

    $args = @("`"$LauncherScript`"")
    if ($ServerMode) { $args += "--server" }

    return @{
        FilePath = $pythonwCmd
        Arguments = $args
        WorkingDirectory = $ScriptDir
        DisplayName = "app launcher"
    }
}

function Get-SourceAppDir {
    if (Test-Path $PackagedExe) {
        return Split-Path -Parent $PackagedExe
    }
    return $ScriptDir
}

function Copy-SupportFile {
    param(
        [string]$FileName,
        [string]$SourceRoot,
        [string]$DestinationRoot
    )

    $source = Join-Path $SourceRoot $FileName
    $destination = Join-Path $DestinationRoot $FileName
    if ((Test-Path $source) -and (-not (Test-Path $destination))) {
        Copy-Item -Path $source -Destination $destination -Force
    }
}

function Install-ApplicationFiles {
    $sourceAppDir = Get-SourceAppDir
    if (-not (Test-Path (Join-Path $sourceAppDir "FixOnce.exe"))) {
        Write-Err "FixOnce.exe was not found in the installer package."
        Write-Host "  Expected: $sourceAppDir\FixOnce.exe" -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }

    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }

    $resolvedSource = (Resolve-Path $sourceAppDir).Path
    $resolvedInstall = (Resolve-Path $InstallDir).Path
    if ($resolvedSource -ne $resolvedInstall) {
        Copy-Item -Path (Join-Path $sourceAppDir "*") -Destination $InstallDir -Recurse -Force
    }

    Copy-SupportFile "install.ps1" $ScriptDir $InstallDir
    Copy-SupportFile "install.bat" $ScriptDir $InstallDir
    Copy-SupportFile "uninstall.ps1" $ScriptDir $InstallDir
    Copy-SupportFile "requirements.txt" $ScriptDir $InstallDir

    $script:ScriptDir = $InstallDir
    $script:LauncherScript = Join-Path $ScriptDir "scripts\app_launcher.py"
    $script:PackagedExe = Join-Path $ScriptDir "FixOnce.exe"
    $script:InstalledExe = $PackagedExe

    Write-OK "Application files installed to $InstallDir"
}

function New-FixOnceShortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetPath,
        [string]$Arguments = "",
        [string]$WorkingDirectory = ""
    )

    $parent = Split-Path -Parent $ShortcutPath
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = if ($WorkingDirectory) { $WorkingDirectory } else { Split-Path -Parent $TargetPath }
    $iconPath = Join-Path $InstallDir "FixOnce.exe"
    if (Test-Path $iconPath) { $shortcut.IconLocation = "$iconPath,0" }
    $shortcut.Save()
}

function Install-Shortcuts {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $startMenu = [Environment]::GetFolderPath("StartMenu")
    $programsDir = Join-Path $startMenu "Programs\FixOnce"
    $exe = Join-Path $InstallDir "FixOnce.exe"
    $uninstaller = Join-Path $InstallDir "uninstall.ps1"

    New-FixOnceShortcut `
        -ShortcutPath (Join-Path $desktop "FixOnce.lnk") `
        -TargetPath $exe `
        -WorkingDirectory $InstallDir

    New-FixOnceShortcut `
        -ShortcutPath (Join-Path $programsDir "FixOnce.lnk") `
        -TargetPath $exe `
        -WorkingDirectory $InstallDir

    if (Test-Path $uninstaller) {
        New-FixOnceShortcut `
            -ShortcutPath (Join-Path $programsDir "Uninstall FixOnce.lnk") `
            -TargetPath "powershell.exe" `
            -Arguments "-ExecutionPolicy Bypass -File `"$uninstaller`"" `
            -WorkingDirectory $InstallDir
    }

    Write-OK "Shortcuts created"
    Write-Host "    Desktop FixOnce -> $exe" -ForegroundColor DarkGray
    Write-Host "    Start Menu FixOnce -> $exe" -ForegroundColor DarkGray
    if (Test-Path $uninstaller) {
        Write-Host "    Start Menu Uninstall FixOnce -> $uninstaller" -ForegroundColor DarkGray
    }
}

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

# ============ Step 4: Install Application Files ============
Write-Step "Installing application files..."

Install-ApplicationFiles

# ============ Step 5: Check Write Permissions ============
Write-Step "Checking runtime permissions..."

if (-not (Test-Path $UserDataDir)) {
    New-Item -ItemType Directory -Path $UserDataDir -Force | Out-Null
}

$testFile = Join-Path $UserDataDir "test_write.tmp"
try {
    "test" | Out-File $testFile -Force
    Remove-Item $testFile -Force
    Write-OK "Write permissions OK"
} catch {
    Write-Err "Cannot write to runtime directory: $UserDataDir"
    Write-Host "  Check folder permissions and try again"
    Read-Host "Press Enter to exit"
    exit 1
}

# ============ Step 6: Configure AI App Connections ============
Write-Step "Connecting FixOnce to your AI apps..."

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
$codexBlock = @"
[mcp_servers.fixonce]
command = "$pythonCmd"
args = ["$mcpServerPath"]

[mcp_servers.fixonce.env]
PYTHONPATH = "$srcPath"
FIXONCE_ACTOR = "codex"
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

# ============ Step 6b: Configure Claude Code Hooks ============
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

# ============ Step 7: Configure Auto-Start ============
Write-Step "Configuring auto-start..."

$taskName = "FixOnceServer"

# Check if task already exists
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($existingTask) {
    Write-OK "Auto-start already configured"
} else {
    try {
        $serverLaunch = Get-LauncherCommand -ServerMode
        $argumentString = ($serverLaunch.Arguments -join " ")
        $action = New-ScheduledTaskAction -Execute $serverLaunch.FilePath -Argument $argumentString -WorkingDirectory $serverLaunch.WorkingDirectory
        $trigger = New-ScheduledTaskTrigger -AtLogOn
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
        Write-OK "Auto-start configured (Task Scheduler with restart on failure)"
    } catch {
        Write-Warn "Could not configure auto-start: $_"
        Write-Host "  You can still launch FixOnce from the app icon."
    }
}

# ============ Step 8: Chrome Extension ============
Write-Step "Optional browser extension setup..."

$extensionDir = Join-Path $ScriptDir "extension"
Write-Host ""
Write-Host "  The Chrome extension is optional. To capture browser errors, connect it here:" -ForegroundColor Yellow
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

# ============ Shortcuts ============
Write-Host ""
Write-Host "  Creating shortcuts..." -ForegroundColor Cyan

try {
    Install-Shortcuts
} catch {
    Write-Warn "Could not create shortcuts: $_"
}

# ============ Step 8b: Mark Installation Complete ============
Write-Host ""
Write-Host "  Marking installation complete..." -ForegroundColor Cyan

try {
    if (-not (Test-Path $UserDataDir)) { New-Item -ItemType Directory -Path $UserDataDir -Force | Out-Null }

    $installState = Join-Path $UserDataDir "install_state.json"
    $state = @{
        "installed" = $true
        "installed_at" = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        "version" = "1.0.13"
        "installer" = "powershell"
        "install_dir" = $InstallDir
        "app_exe" = (Join-Path $InstallDir "FixOnce.exe")
    }
    $state | ConvertTo-Json | Out-File $installState -Encoding UTF8
    Write-OK "Installation state saved"
} catch {
    Write-Warn "Could not save installation state: $_"
}

# ============ Launch App ============
Write-Host "`n[OK] Launching FixOnce..." -ForegroundColor Cyan

try {
    $appLaunch = Get-LauncherCommand
    Start-Process -FilePath $appLaunch.FilePath -ArgumentList $appLaunch.Arguments -WorkingDirectory $appLaunch.WorkingDirectory
    Write-OK "FixOnce launched"
} catch {
    Write-Warn "Could not launch FixOnce automatically. Open FixOnce from the app icon."
}

# ============ Done ============
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Open FixOnce when you start working." -ForegroundColor White
Write-Host "  Restart your AI app after setup so it can connect to FixOnce." -ForegroundColor White
Write-Host "  The Chrome extension is optional." -ForegroundColor White
Write-Host ""
Write-Host "  To uninstall: .\uninstall.ps1" -ForegroundColor Yellow
Write-Host ""

Read-Host "Press Enter to close"
