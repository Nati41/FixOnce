# FixOnce Hook: PreToolUse for Codex (Windows)
# Injects area-based context when agent touches a file.

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

function Get-BlockContextUnavailable {
    return '{"decision":"block","reason":"FIXONCE_BLOCKING_WARNING FixOnce context server is unavailable; refusing to read protected file before context is checked."}'
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
        # Simple tokenization (doesn't handle all edge cases)
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

    return $paths | Select-Object -Unique
}

# Read hook input from stdin
$inputJson = $input | Out-String
Write-DebugLog "START raw_stdin=$inputJson"

try {
    $hookInput = $inputJson | ConvertFrom-Json
} catch {
    Write-DebugLog "ERROR parsing JSON: $_"
    Write-Output '{"decision": "approve"}'
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
    Write-DebugLog 'OUTPUT={"decision": "approve"} reason=no_file_paths'
    Write-Output '{"decision": "approve"}'
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
            $reason = $context | ConvertTo-Json
            Write-DebugLog "OUTPUT_BLOCK reason=$context"
            Write-Output "{`"decision`":`"block`",`"reason`":$reason}"
            exit 0
        }

        if ($count -eq 0) { continue }

        $combinedContext += "$context`n"
    } catch {
        Write-DebugLog "ERROR querying area context: $_"
        if (Test-ProtectedPath -Path $filePath) {
            Write-DebugLog "OUTPUT_BLOCK reason=context_unavailable protected_path=$filePath"
            Write-Output (Get-BlockContextUnavailable)
            exit 0
        }
        continue
    }
}

if (-not $combinedContext) {
    Write-DebugLog 'OUTPUT={"decision": "approve"} reason=no_combined_context'
    Write-Output '{"decision": "approve"}'
    exit 0
}

# Escape for JSON
$contextEscaped = $combinedContext | ConvertTo-Json

# Return context for injection
$output = @{
    decision = "approve"
    message = $combinedContext.Trim()
} | ConvertTo-Json -Compress

Write-Output $output
Write-DebugLog "OUTPUT_APPROVE message=$combinedContext"

exit 0
