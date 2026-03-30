# FixOnce Hook: SessionEnd (Windows)
# Notifies FixOnce when a Claude session ends

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

# Notify FixOnce server (silent)
try {
    $body = @{
        event = "end"
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

exit 0
