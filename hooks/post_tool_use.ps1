# FixOnce Hook: PostToolUse (Windows)
# Logs file changes to FixOnce activity feed
# Also checks for browser errors related to the current project
# REMINDER: Outputs reminder to AI to update FixOnce after code changes

param()

# Read hook input from stdin
$inputJson = $input | Out-String

try {
    $hookInput = $inputJson | ConvertFrom-Json -ErrorAction SilentlyContinue
    $toolName = $hookInput.tool_name
    $toolInput = $hookInput.tool_input
    $cwd = $hookInput.cwd
} catch {
    $toolName = ""
    $toolInput = $null
    $cwd = ""
}

# Get canonical port from runtime.json (SINGLE SOURCE OF TRUTH)
$fixoncePort = 5000
$runtimeFile = Join-Path $env:USERPROFILE ".fixonce\runtime.json"

if (Test-Path $runtimeFile) {
    try {
        $runtime = Get-Content $runtimeFile -Raw | ConvertFrom-Json
        if ($runtime.port) {
            $fixoncePort = $runtime.port
        }
    } catch {
        # Use default port
    }
}

# Track if this is a code change (for reminder)
$isCodeChange = $false
$filePath = ""

# Only process file operations
switch ($toolName) {
    { $_ -in @("Edit", "Write", "NotebookEdit") } {
        if ($toolInput -and $toolInput.file_path) {
            $filePath = $toolInput.file_path
            $isCodeChange = $true

            # Log to FixOnce (silent)
            try {
                $body = @{
                    type = "file_change"
                    tool = $toolName
                    file = $filePath
                    cwd = $cwd
                    timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                } | ConvertTo-Json

                Invoke-RestMethod -Uri "http://localhost:$fixoncePort/api/activity/log" `
                    -Method Post `
                    -ContentType "application/json" `
                    -Body $body `
                    -TimeoutSec 2 `
                    -ErrorAction SilentlyContinue | Out-Null
            } catch {
                # Silent fail
            }
        }
    }
    "Bash" {
        if ($toolInput -and $toolInput.command) {
            $command = $toolInput.command
            # Log significant commands (silent)
            if ($command -match "^(npm|yarn|pip|python|node|git)") {
                try {
                    $body = @{
                        type = "command"
                        command = $command
                        cwd = $cwd
                        timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
                    } | ConvertTo-Json

                    Invoke-RestMethod -Uri "http://localhost:$fixoncePort/api/activity/log" `
                        -Method Post `
                        -ContentType "application/json" `
                        -Body $body `
                        -TimeoutSec 2 `
                        -ErrorAction SilentlyContinue | Out-Null
                } catch {
                    # Silent fail
                }
            }
        }
    }
}

# ============================================
# Check for browser errors related to project
# ============================================

# Get FixOnce installation directory from script location
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$fixonceDir = Split-Path -Parent $scriptDir
$fixonceData = Join-Path $fixonceDir "data"
$activeProjectFile = Join-Path $fixonceData "active_project.json"

$projectId = ""
$projectDir = ""
$projectPort = ""

if (Test-Path $activeProjectFile) {
    try {
        $activeProject = Get-Content $activeProjectFile -Raw | ConvertFrom-Json
        $projectId = $activeProject.active_id
        $projectDir = $activeProject.working_dir

        # Get port from project memory file
        if ($projectId) {
            $projectFile = Join-Path $fixonceData "projects_v2\$projectId.json"
            if (Test-Path $projectFile) {
                $projectData = Get-Content $projectFile -Raw | ConvertFrom-Json
                if ($projectData.connected_server -and $projectData.connected_server.port) {
                    $projectPort = $projectData.connected_server.port
                }
            }
        }
    } catch {
        # Ignore errors
    }
}

# Only check if we have project info
if ($projectPort -or $projectDir) {
    try {
        # Get recent browser errors (last 30 seconds)
        $response = Invoke-RestMethod -Uri "http://localhost:$fixoncePort/api/live-errors?since=30" `
            -TimeoutSec 2 `
            -ErrorAction SilentlyContinue

        $errorCount = 0
        if ($response -and $response.count) {
            $errorCount = $response.count
        }

        if ($errorCount -gt 0 -and $response.errors) {
            $relevantErrors = @()

            foreach ($error in $response.errors) {
                $errorUrl = $error.url
                $errorFile = $error.file
                $errorMsg = $error.message
                $errorType = if ($error.type) { $error.type } else { "error" }

                $isRelated = $false

                # Check if error is related to this project
                if ($projectPort) {
                    if ($errorUrl -match "localhost:$projectPort" -or $errorFile -match "localhost:$projectPort") {
                        $isRelated = $true
                    }
                }

                # Fallback: any localhost error is considered related during active dev
                if (-not $isRelated -and ($errorUrl -match "localhost" -or $errorFile -match "localhost")) {
                    $isRelated = $true
                }

                if ($isRelated) {
                    # Truncate message for readability
                    $shortMsg = if ($errorMsg.Length -gt 150) { $errorMsg.Substring(0, 150) } else { $errorMsg }
                    $relevantErrors += "  - [$errorType] $shortMsg"
                }
            }

            # If we have relevant errors, output them
            if ($relevantErrors.Count -gt 0) {
                $portInfo = if ($projectPort) { " (localhost:$projectPort)" } else { "" }
                Write-Output ""
                Write-Output "⚠️ FixOnce: $($relevantErrors.Count) browser errors detected$portInfo"
                $relevantErrors | ForEach-Object { Write-Output $_ }
                Write-Output ""
                Write-Output "📌 Use fo_errors() for full details."
            }
        }
    } catch {
        # Silent fail - server might not be running
    }
}

# ============================================
# REMINDER: Update FixOnce after code changes
# ============================================
if ($isCodeChange) {
    Write-Output ""
    Write-Output "📌 FixOnce: Code changed. Remember to update:"
    Write-Output "   fo_sync(last_change=`"...`", last_file=`"$filePath`")"
    Write-Output ""
}

# Always allow (exit 0)
exit 0
