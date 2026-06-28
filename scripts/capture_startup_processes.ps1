# FixOnce Startup Process Capture
# Run this script, then double-click FixOnce shortcut within 3 seconds
# It will capture all new processes for 10 seconds

$ErrorActionPreference = "Continue"
$captureSeconds = 10
$outputFile = Join-Path $env:USERPROFILE ".fixonce\logs\startup_capture.txt"

# Ensure log directory exists
$logDir = Split-Path -Parent $outputFile
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

Write-Host ""
Write-Host "=== FixOnce Startup Process Capture ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Double-click the FixOnce desktop shortcut NOW!" -ForegroundColor Yellow
Write-Host "Capturing for $captureSeconds seconds..." -ForegroundColor Yellow
Write-Host ""

# Get baseline of existing processes
$baseline = Get-Process | Select-Object -ExpandProperty Id

# Capture start time
$startTime = Get-Date
$endTime = $startTime.AddSeconds($captureSeconds)

# Arrays to collect data
$newProcesses = @()
$conhostEvents = @()

# Poll for new processes
while ((Get-Date) -lt $endTime) {
    $current = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -notin $baseline }

    foreach ($proc in $current) {
        $key = "$($proc.ProcessId)"
        if ($key -notin $newProcesses.ProcessId) {
            $elapsed = ((Get-Date) - $startTime).TotalSeconds
            $entry = [PSCustomObject]@{
                Time = [math]::Round($elapsed, 2)
                ProcessId = $proc.ProcessId
                ParentProcessId = $proc.ParentProcessId
                Name = $proc.Name
                CommandLine = $proc.CommandLine
            }
            $newProcesses += $entry

            # Special tracking for conhost.exe
            if ($proc.Name -eq "conhost.exe") {
                $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.ParentProcessId)" -ErrorAction SilentlyContinue
                $conhostEvents += [PSCustomObject]@{
                    ConhostPID = $proc.ProcessId
                    ParentPID = $proc.ParentProcessId
                    ParentName = $parentProc.Name
                    ParentCmdLine = $parentProc.CommandLine
                    Time = [math]::Round($elapsed, 2)
                }
            }
        }
    }

    Start-Sleep -Milliseconds 50
}

Write-Host "Capture complete!" -ForegroundColor Green
Write-Host ""

# Build output
$output = @()
$output += "=== FixOnce Startup Process Capture ==="
$output += "Captured: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$output += "Duration: $captureSeconds seconds"
$output += ""
$output += "=== ALL NEW PROCESSES ==="
$output += ""

foreach ($proc in ($newProcesses | Sort-Object Time)) {
    $output += "[$($proc.Time)s] PID=$($proc.ProcessId) PPID=$($proc.ParentProcessId)"
    $output += "  Name: $($proc.Name)"
    $output += "  Cmd:  $($proc.CommandLine)"
    $output += ""
}

$output += "=== CONHOST.EXE INSTANCES ==="
$output += ""

if ($conhostEvents.Count -eq 0) {
    $output += "(none detected)"
} else {
    foreach ($ch in $conhostEvents) {
        $output += "conhost.exe PID=$($ch.ConhostPID) at $($ch.Time)s"
        $output += "  Parent PID: $($ch.ParentPID)"
        $output += "  Parent Name: $($ch.ParentName)"
        $output += "  Parent Cmd: $($ch.ParentCmdLine)"
        $output += ""
    }
}

$output += "=== PROCESS TREE ==="
$output += ""

# Build tree showing parent relationships
$allPids = $newProcesses | ForEach-Object { $_.ProcessId, $_.ParentProcessId } | Sort-Object -Unique
foreach ($proc in ($newProcesses | Sort-Object Time)) {
    $indent = ""
    $parentChain = @()
    $currentPPID = $proc.ParentProcessId

    # Walk up parent chain
    for ($i = 0; $i -lt 5; $i++) {
        $parent = $newProcesses | Where-Object { $_.ProcessId -eq $currentPPID } | Select-Object -First 1
        if ($parent) {
            $parentChain = @($parent.Name) + $parentChain
            $currentPPID = $parent.ParentProcessId
        } else {
            # Check if parent is FixOnce or explorer
            $extParent = Get-CimInstance Win32_Process -Filter "ProcessId = $currentPPID" -ErrorAction SilentlyContinue
            if ($extParent) {
                $parentChain = @("[$($extParent.Name)]") + $parentChain
            }
            break
        }
    }

    $chain = ($parentChain + @($proc.Name)) -join " -> "
    $output += "$chain (PID $($proc.ProcessId))"
}

# Write to file
$output | Out-File -FilePath $outputFile -Encoding UTF8

Write-Host "=== RESULTS ===" -ForegroundColor Cyan
Write-Host ""
$output | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "Full log saved to: $outputFile" -ForegroundColor Green
Write-Host ""
Write-Host "Copy the output above and paste it back to me." -ForegroundColor Yellow
