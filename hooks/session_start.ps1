# FixOnce Hook: SessionStart (Windows)
# CRITICAL: Reminds Claude to connect to FixOnce on every session

param()

# Read hook input from stdin
$inputJson = $input | Out-String

try {
    $hookInput = $inputJson | ConvertFrom-Json -ErrorAction SilentlyContinue
    $cwd = $hookInput.cwd
    $sessionId = $hookInput.session_id
} catch {
    $cwd = ""
    $sessionId = ""
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

# Notify FixOnce server (silent, don't fail if server not running)
try {
    $body = @{
        event = "start"
        session_id = $sessionId
        cwd = $cwd
        timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    } | ConvertTo-Json

    Invoke-RestMethod -Uri "http://localhost:$fixoncePort/api/activity/session" `
        -Method Post `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 2 `
        -ErrorAction SilentlyContinue | Out-Null
} catch {
    # Server might not be running - that's OK
}

# OUTPUT A REMINDER TO CLAUDE - This message appears in Claude's context
Write-Output "🧠 FixOnce: BEFORE responding to user, you MUST call fo_init(cwd=`"$cwd`") to connect. This is mandatory - do not skip this step."

exit 0
