param(
    [switch]$SkipConfig,
    [switch]$SkipAudit
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$LogRoot = Join-Path $ProjectRoot ".fixonce\runtime_qa"
New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$CleanupLog = Join-Path $LogRoot "cleanup.log"

function Write-CleanupLog {
    param([string]$Message)
    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $CleanupLog -Value "[$Timestamp] $Message"
}

function Stop-StaleFixOnceProcesses {
    $CurrentPid = $PID
    $ProjectNeedle = ([string]$ProjectRoot).ToLowerInvariant()
    Write-CleanupLog "cleanup_start project=$ProjectNeedle current_pid=$CurrentPid"

    $Candidates = @(Get-CimInstance Win32_Process |
        Where-Object {
            $nameValue = $_.Name
            $cmdValue = $_.CommandLine
            if ($null -eq $nameValue) { $nameValue = "" }
            if ($null -eq $cmdValue) { $cmdValue = "" }
            $name = ([string]$nameValue).ToLowerInvariant()
            $cmd = ([string]$cmdValue).ToLowerInvariant()
            $_.ProcessId -ne $CurrentPid -and
            ($name -in @("fixonce.exe", "python.exe", "pythonw.exe", "py.exe", "fastmcp.exe")) -and
            (
                $cmd.Contains($ProjectNeedle) -or
                ($name -eq "fixonce.exe" -and $cmd.Contains("fixonce"))
            )
        })

    foreach ($Process in $Candidates) {
        try {
            Write-CleanupLog "stopping pid=$($Process.ProcessId) name=$($Process.Name) cmd=$($Process.CommandLine)"
            Stop-Process -Id $Process.ProcessId -Force -ErrorAction Stop
            Write-CleanupLog "stopped pid=$($Process.ProcessId)"
        } catch {
            Write-CleanupLog "stop_failed pid=$($Process.ProcessId) error=$($_.Exception.Message)"
        }
    }

    Write-CleanupLog "cleanup_done count=$($Candidates.Count)"
}

Stop-StaleFixOnceProcesses

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if ($null -eq $Python) {
    Write-Host "FAIL Python command not found. Cleanup log: $CleanupLog"
    exit 1
}

$ArgsList = @((Join-Path $ScriptDir "windows_runtime_qa.py"))
if ($SkipConfig) { $ArgsList += "--skip-config" }
if ($SkipAudit) { $ArgsList += "--skip-audit" }

Write-Host "Cleanup log: $CleanupLog"
Write-Host "Running: $($Python.Source) $($ArgsList -join ' ')"
& $Python.Source @ArgsList
exit $LASTEXITCODE
