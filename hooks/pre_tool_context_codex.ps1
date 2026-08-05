# FixOnce Hook: PreToolUse for Codex (Windows)
# Injects area-based context when agent touches a file.
#
# Output formats (official Codex PreToolUse spec):
#
# 1. No context: empty output (allow)
#
# 2. Relevant context (non-blocking):
#    {"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"..."}}
#
# 3. Confirmed conflict (blocking):
#    {"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}
#
# DO NOT USE: ask, approve, top-level deny

param()

$ErrorActionPreference = "SilentlyContinue"

function Write-DebugLog {
    param([string]$Message)
    if ($env:FIXONCE_HOOK_DEBUG) {
        $logPath = if ($env:FIXONCE_HOOK_DEBUG_LOG) { $env:FIXONCE_HOOK_DEBUG_LOG } else { "$env:TEMP\fixonce_codex_pretool_debug.log" }
        $timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        Add-Content -Path $logPath -Value "$timestamp $Message" -ErrorAction SilentlyContinue
    }
}

function Test-ProtectedPath {
    param([string]$Path)
    $protectedPatterns = @(
        "src/core/project_context.py",
        "*/src/core/project_context.py"
    )
    foreach ($pattern in $protectedPatterns) {
        if ($Path -like $pattern -or $Path -like "*$pattern") {
            return $true
        }
    }
    return $false
}

function Write-BlockOutput {
    param([string]$Reason)
    $output = @{
        hookSpecificOutput = @{
            hookEventName = "PreToolUse"
            permissionDecision = "deny"
            permissionDecisionReason = $Reason
        }
    } | ConvertTo-Json -Compress -Depth 3
    Write-Output $output
}

function Write-ContextOutput {
    param([string]$Context)
    $output = @{
        hookSpecificOutput = @{
            hookEventName = "PreToolUse"
            additionalContext = $Context
        }
    } | ConvertTo-Json -Compress -Depth 3
    Write-Output $output
}

function Test-LooksLikePath {
    param([string]$Token, [string]$Cwd)
    if (-not $Token -or $Token.StartsWith("-")) { return $false }
    if ($Token -eq "." -or $Token -eq "..") { return $false }

    $normalized = $Token.Trim("'`"")
    if (-not $normalized) { return $false }

    $candidate = if ([System.IO.Path]::IsPathRooted($normalized)) {
        $normalized
    } else {
        Join-Path $Cwd $normalized
    }

    if (Test-Path $candidate) { return $true }

    $extensions = @(".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".html", ".css", ".json", ".yaml", ".yml", ".toml", ".md", ".txt", ".ps1")
    foreach ($ext in $extensions) {
        if ($normalized -like "*$ext" -and $normalized -match "/") {
            return $true
        }
    }
    return $false
}

function Get-PathsFromCommand {
    param([string]$Command, [string]$Cwd, [int]$Depth = 0)

    $paths = @()
    if (-not $Command -or $Depth -gt 2) { return $paths }

    # Handle patch format
    if ($Command.StartsWith("*** Begin Patch")) {
        $lines = $Command -split "`n"
        foreach ($line in $lines) {
            if ($line -match "^\*\*\* (?:Add|Update|Delete) File: (.+)$") {
                $path = $Matches[1]
                if (Test-LooksLikePath -Token $path -Cwd $Cwd) {
                    $paths += $path
                }
            }
        }
        return $paths
    }

    # Parse command tokens
    $tokens = @()
    try {
        $tokens = $Command -split '\s+' | Where-Object { $_ }
    } catch {
        $tokens = $Command -split '\s+' | Where-Object { $_ }
    }

    if ($tokens.Count -eq 0) { return $paths }

    $tool = [System.IO.Path]::GetFileName($tokens[0])

    # Handle shell wrappers
    if ($tool -in @("bash", "sh", "zsh", "cmd", "powershell", "pwsh")) {
        for ($i = 0; $i -lt $tokens.Count - 1; $i++) {
            if ($tokens[$i] -in @("-c", "-lc", "-Command")) {
                $subPaths = Get-PathsFromCommand -Command $tokens[$i + 1] -Cwd $Cwd -Depth ($Depth + 1)
                $paths += $subPaths
            }
        }
    }

    $readTools = @("sed", "cat", "head", "tail", "grep", "rg", "awk", "type", "Get-Content")
    $scriptTools = @("python", "python3", "perl", "ruby", "node")
    $writeIndicators = @("open(", "write(", "Path(", ".write_text(", ".write_bytes(",
                         "with open", ">>", "> ", "tee ", "sed -i", "shutil.copy",
                         "shutil.move", "os.rename", "pathlib", "Set-Content", "Out-File")

    if ($tool -in $readTools -or $tool -in $scriptTools) {
        foreach ($token in $tokens[1..($tokens.Count - 1)]) {
            if (Test-LooksLikePath -Token $token -Cwd $Cwd) {
                $paths += $token
            }
        }
    }

    # Detect path-like strings in one-liners
    $pathPattern = "['\`"]([^'\`"]+/[^'\`"]+\.(?:py|js|ts|tsx|jsx|sh|html|css|json|yaml|yml|toml|md|txt|ps1))['\`"]"
    $matches = [regex]::Matches($Command, $pathPattern)
    foreach ($match in $matches) {
        $path = $match.Groups[1].Value
        if (Test-LooksLikePath -Token $path -Cwd $Cwd) {
            $paths += $path
        }
    }

    # For python/python3 commands running a script file, parse the script for write targets
    if ($tool -in $scriptTools) {
        $scriptFile = $null
        foreach ($token in $tokens[1..($tokens.Count - 1)]) {
            if (-not $token.StartsWith("-") -and (Test-LooksLikePath -Token $token -Cwd $Cwd)) {
                $scriptFile = $token
                break
            }
        }

        if ($scriptFile) {
            $scriptPath = if ([System.IO.Path]::IsPathRooted($scriptFile)) {
                $scriptFile
            } else {
                Join-Path $Cwd $scriptFile
            }

            if ((Test-Path $scriptPath) -and ($scriptPath -match "\.(py|js|rb|pl)$")) {
                try {
                    $scriptContent = Get-Content $scriptPath -Raw -ErrorAction Stop
                    $hasWrites = $false
                    foreach ($ind in $writeIndicators) {
                        if ($scriptContent -like "*$ind*") {
                            $hasWrites = $true
                            break
                        }
                    }
                    if ($hasWrites) {
                        $scriptMatches = [regex]::Matches($scriptContent, "['\`"]([^'\`"]+\.(?:py|js|ts|tsx|jsx|sh|html|css|json|yaml|yml|toml))['\`"]")
                        foreach ($m in $scriptMatches) {
                            $p = $m.Groups[1].Value
                            if ($p -like "*/*" -or $p -like "src*") {
                                $paths += $p
                            }
                        }
                    }
                } catch {
                    # Ignore errors reading script
                }
            }
        }
    }

    return $paths | Select-Object -Unique
}

# Read hook input from stdin
$inputJson = $input | Out-String
Write-DebugLog "START raw_stdin=$inputJson"

try {
    $hookInput = $inputJson | ConvertFrom-Json
} catch {
    Write-DebugLog "ERROR parsing JSON: $_"
    # Empty output = allow
    exit 0
}

$toolName = $hookInput.tool_name
$toolInput = $hookInput.tool_input
$cwd = if ($hookInput.cwd) { $hookInput.cwd } else { (Get-Location).Path }

Write-DebugLog "TOOL_NAME=$toolName"

# Extract file paths
$filePaths = @()

# Direct file_path or path
if ($toolInput.file_path) {
    $filePaths += $toolInput.file_path
}
if ($toolInput.path) {
    $filePaths += $toolInput.path
}

# Extract from command
if ($toolInput.cmd) {
    $filePaths += Get-PathsFromCommand -Command $toolInput.cmd -Cwd $cwd
}
if ($toolInput.command) {
    $filePaths += Get-PathsFromCommand -Command $toolInput.command -Cwd $cwd
}

$filePaths = $filePaths | Where-Object { $_ } | Select-Object -Unique

Write-DebugLog "FILE_PATHS=$($filePaths -join '|')"

# Only process on actual files
if ($filePaths.Count -eq 0) {
    Write-DebugLog 'OUTPUT=(empty) reason=no_file_paths'
    # Empty output = allow
    exit 0
}

# Get canonical port from runtime.json
$fixoncePort = 5000
$runtimeFile = Join-Path $env:USERPROFILE ".fixonce\runtime.json"
if (Test-Path $runtimeFile) {
    try {
        $runtime = Get-Content $runtimeFile -Raw | ConvertFrom-Json
        if ($runtime.port) {
            $fixoncePort = $runtime.port
        }
    } catch {
        Write-DebugLog "ERROR reading runtime.json: $_"
    }
}

$combinedContext = ""

foreach ($filePath in $filePaths) {
    if (-not $filePath) { continue }

    # Skip non-source files
    $ext = [System.IO.Path]::GetExtension($filePath).ToLower()
    if ($ext -in @(".json", ".lock", ".log", ".md", ".txt", ".csv")) {
        continue
    }

    # Query area context
    try {
        $encodedPath = [System.Uri]::EscapeDataString($filePath)
        $url = "http://localhost:$fixoncePort/api/activity/area-context?path=$encodedPath"
        $response = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 2 -ErrorAction Stop

        Write-DebugLog "AREA_CONTEXT path=$filePath port=$fixoncePort response=$($response | ConvertTo-Json -Compress)"

        $context = $response.context
        $count = $response.count

        if (-not $context) { continue }

        if ($context -match "FIXONCE_BLOCKING_WARNING") {
            Write-DebugLog "OUTPUT_BLOCK reason=FIXONCE_BLOCKING_WARNING"
            Write-BlockOutput -Reason $context
            exit 0
        }

        if ($count -eq 0) { continue }

        $combinedContext += "$context`n"
    } catch {
        Write-DebugLog "ERROR querying area context: $_"
        if (Test-ProtectedPath -Path $filePath) {
            Write-DebugLog "OUTPUT_BLOCK reason=context_unavailable protected_path=$filePath"
            Write-BlockOutput -Reason "FIXONCE_BLOCKING_WARNING: FixOnce context server is unavailable. Cannot verify project memory before editing protected file."
            exit 0
        }
        continue
    }
}

if (-not $combinedContext) {
    Write-DebugLog 'OUTPUT=(empty) reason=no_combined_context'
    # Empty output = allow
    exit 0
}

# Check if this is a write operation that may conflict with active decisions
$isWriteOp = $toolName -in @("Edit", "Write", "apply_patch", "str_replace_editor", "exec_command", "exec", "Bash", "bash", "shell")

# Detect confirmed conflicts: high-relevance decisions (>=75%) or avoid patterns (>=70%)
# IMPORTANT: High relevance alone does NOT trigger a block.
# We must verify the edit actually contradicts the decision.
$conflictDetected = $false
$hasRelevantDecision = $false
$conflictDecision = ""
$conflictReason = ""

if ($isWriteOp) {
    # Check for high-relevance decisions (75%+)
    if ($combinedContext -match '📌 Decision \(([7-9][5-9]|[89][0-9]|100)%\):') {
        $hasRelevantDecision = $true
        $match = [regex]::Match($combinedContext, '📌 Decision \([7-9][0-9]%\): ([^.]+)')
        if ($match.Success) {
            $conflictDecision = "📌 Decision: $($match.Groups[1].Value)"
        }
    }

    # Check for avoid patterns (70%+)
    if ($combinedContext -match '🚫 Avoid \(([7-9][0-9]|100)%\):') {
        $hasRelevantDecision = $true
        if (-not $conflictDecision) {
            $match = [regex]::Match($combinedContext, '🚫 Avoid \([7-9][0-9]%\): ([^.]+)')
            if ($match.Success) {
                $conflictDecision = "🚫 Avoid: $($match.Groups[1].Value)"
            }
        }
    }

    # If we have a relevant decision, check if the edit actually contradicts it
    if ($hasRelevantDecision) {
        # Get edit content
        $editContent = ""
        if ($toolName -in @("Edit", "Write", "str_replace_editor")) {
            $editContent = $toolInput.new_string
            if (-not $editContent) { $editContent = $toolInput.content }
        } elseif ($toolName -eq "apply_patch") {
            $editContent = $toolInput.command
        } else {
            $editContent = $toolInput.cmd
            if (-not $editContent) { $editContent = $toolInput.command }
        }

        if ($editContent) {
            $editLower = $editContent.ToLower()
            $decisionLower = $conflictDecision.ToLower()

            # Check for mechanical edits (whitespace, comments only)
            $isMechanical = $true
            $lines = $editContent -split "`n"
            foreach ($line in $lines) {
                $trimmed = $line.Trim()
                if ($trimmed -and -not ($trimmed -match '^\s*$' -or $trimmed -match '^\s*#' -or $trimmed -match '^\s*//' -or $trimmed -match '^\s*import\s+' -or $trimmed -match '^\s*from\s+\w+\s+import')) {
                    $isMechanical = $false
                    break
                }
            }

            if (-not $isMechanical) {
                # Check for technology conflicts
                $techConflicts = @{
                    "argparse" = @("click", "typer", "fire")
                    "click" = @("argparse", "typer", "fire")
                    "typer" = @("argparse", "click", "fire")
                    "postgresql" = @("mysql", "sqlite", "mongodb")
                    "mysql" = @("postgresql", "sqlite", "mongodb")
                    "flask" = @("django", "fastapi")
                    "django" = @("flask", "fastapi")
                    "fastapi" = @("flask", "django")
                }

                foreach ($tech in $techConflicts.Keys) {
                    if ($decisionLower -like "*$tech*") {
                        foreach ($conflict in $techConflicts[$tech]) {
                            if ($editLower -like "*$conflict*" -or $editLower -like "*import $conflict*" -or $editLower -like "*from $conflict*") {
                                $conflictDetected = $true
                                $conflictReason = "introduces $conflict"
                                break
                            }
                        }
                    }
                    if ($conflictDetected) { break }
                }
            }
        }
    }
}

# If confirmed conflict on write operation, BLOCK the edit
if ($conflictDetected) {
    $reasonText = if ($conflictReason) { "This edit $conflictReason" } else { "This edit introduces changes that contradict the decision" }
    $blockReason = @"
⚠️ ARCHITECTURAL CONFLICT DETECTED

$conflictDecision

Conflict reason: $reasonText.

This edit is BLOCKED because it would invalidate an active project decision.

⛔ YOU MUST ASK THE USER before proceeding.

Tell the user:
"This change conflicts with a documented project decision. How would you like to proceed?"

Options to present to the user:
1. Supersede the old decision (user explicitly confirms replacing it)
2. Add as exception (keep old decision, add scoped exception)
3. Cancel the change

DO NOT call fo_decide(supersede) without explicit user approval.
The original task request is NOT approval to change project decisions.
"@

    Write-DebugLog "OUTPUT_BLOCK conflict_detected decision=$conflictDecision reason=$conflictReason"
    Write-BlockOutput -Reason $blockReason
    exit 0
}

# No conflict: inject context via additionalContext (non-blocking)
Write-DebugLog "OUTPUT_CONTEXT context=$combinedContext"
Write-ContextOutput -Context $combinedContext.Trim()
exit 0
