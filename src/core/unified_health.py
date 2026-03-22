"""
Unified Health Engine for FixOnce.

Combines signals from:
- Command Engine (pending/delivered/failed/timeout)
- Component Stability (broken/blocked)
- Browser Errors

Returns a single health status for the Orb.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple

# Configuration
COMMAND_TIMEOUT_MINUTES = 5
COMMAND_PENDING_WARNING_MINUTES = 2
ERROR_THRESHOLD = 5


def check_command_timeouts(ai_queue: List[Dict], audit_log: List[Dict] = None) -> Tuple[List[Dict], List[Dict]]:
    """
    Check for timed-out commands and mark them as failed_timeout.

    Args:
        ai_queue: The current command queue
        audit_log: The audit log to append timeout events

    Returns:
        Tuple of (updated_queue, timed_out_commands)
    """
    now = datetime.now()
    timeout_threshold = now - timedelta(minutes=COMMAND_TIMEOUT_MINUTES)
    timed_out = []

    for command in ai_queue:
        if command.get("status") != "delivered":
            continue

        # Check if delivered_at exists and is older than threshold
        delivered_at_str = command.get("delivered_at")
        if not delivered_at_str:
            continue

        try:
            delivered_at = datetime.fromisoformat(delivered_at_str)
            if delivered_at < timeout_threshold:
                # Mark as timed out
                command["status"] = "failed_timeout"
                command["timeout_at"] = now.isoformat()
                command["timeout_reason"] = f"Not executed within {COMMAND_TIMEOUT_MINUTES} minutes"
                timed_out.append(command)

                # Add to audit log
                if audit_log is not None:
                    audit_log.append({
                        "id": command.get("id"),
                        "action": "timeout",
                        "result": "failed_timeout",
                        "details": f"Command timed out after {COMMAND_TIMEOUT_MINUTES} minutes",
                        "timestamp": now.isoformat(),
                        "executed_by": "system_watchdog"
                    })
        except (ValueError, TypeError):
            continue

    return ai_queue, timed_out


def get_command_health(ai_queue: List[Dict]) -> Dict[str, Any]:
    """
    Analyze command queue for health status.

    Returns:
        {
            "status": "red" | "yellow" | "green",
            "reasons": ["..."],
            "pending_count": 0,
            "delivered_count": 0,
            "failed_count": 0,
            "stale_commands": []
        }
    """
    now = datetime.now()
    pending_warning_threshold = now - timedelta(minutes=COMMAND_PENDING_WARNING_MINUTES)

    pending = []
    delivered = []
    failed = []
    stale = []  # pending > 2 min

    for cmd in ai_queue:
        status = cmd.get("status", "")

        if status == "pending":
            pending.append(cmd)
            # Check if stale
            created_at_str = cmd.get("created_at") or cmd.get("timestamp")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                    if created_at < pending_warning_threshold:
                        stale.append(cmd)
                except (ValueError, TypeError):
                    pass

        elif status == "delivered":
            delivered.append(cmd)

        elif status.startswith("failed") or status == "failed_timeout":
            failed.append(cmd)

    # Determine status
    reasons = []

    if failed:
        status = "red"
        for f in failed:
            reason = f.get("timeout_reason") or f.get("execution_details") or "Command failed"
            reasons.append(f"Command failed: {f.get('command', '')[:30]}... ({reason})")
    elif stale:
        status = "yellow"
        for s in stale:
            reasons.append(f"Command pending > {COMMAND_PENDING_WARNING_MINUTES}min: {s.get('command', '')[:30]}...")
    elif delivered:
        # Delivered but not yet executed - mild warning if > 1
        if len(delivered) > 1:
            status = "yellow"
            reasons.append(f"{len(delivered)} commands awaiting execution")
        else:
            status = "green"
    else:
        status = "green"

    return {
        "status": status,
        "reasons": reasons,
        "pending_count": len(pending),
        "delivered_count": len(delivered),
        "failed_count": len(failed),
        "stale_commands": [c.get("id") for c in stale]
    }


def get_stability_health(components: List[Dict]) -> Dict[str, Any]:
    """
    Analyze component stability for health status.

    Returns:
        {
            "status": "red" | "yellow" | "green",
            "reasons": ["..."],
            "broken_count": 0,
            "blocked_count": 0
        }
    """
    broken = []
    blocked = []

    for comp in components:
        status = comp.get("status", "")
        name = comp.get("name", "Unknown")

        if status == "broken":
            broken.append(name)
        elif status == "blocked":
            blocked.append(name)

    reasons = []

    if broken:
        status = "red"
        for b in broken:
            reasons.append(f"Component broken: {b}")
    elif blocked:
        status = "yellow"
        for b in blocked:
            reasons.append(f"Component blocked: {b}")
    else:
        status = "green"

    return {
        "status": status,
        "reasons": reasons,
        "broken_count": len(broken),
        "blocked_count": len(blocked)
    }


def get_error_health(browser_errors: List[Dict], threshold: int = ERROR_THRESHOLD) -> Dict[str, Any]:
    """
    Analyze browser errors for health status.

    Returns:
        {
            "status": "red" | "yellow" | "green",
            "reasons": ["..."],
            "error_count": 0,
            "recent_errors": []
        }
    """
    # Filter to recent errors (last 10 minutes)
    now = datetime.now()
    recent_threshold = now - timedelta(minutes=10)

    recent_errors = []
    for err in browser_errors:
        timestamp_str = err.get("timestamp")
        if timestamp_str:
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                # Handle timezone-naive comparison
                if timestamp.tzinfo:
                    timestamp = timestamp.replace(tzinfo=None)
                if timestamp > recent_threshold:
                    recent_errors.append(err)
            except (ValueError, TypeError):
                recent_errors.append(err)  # Include if can't parse
        else:
            recent_errors.append(err)

    error_count = len(recent_errors)
    reasons = []

    if error_count > threshold:
        status = "red"
        reasons.append(f"{error_count} browser errors (threshold: {threshold})")
    elif error_count > 0:
        status = "yellow"
        # Add first few error messages
        for err in recent_errors[:3]:
            msg = err.get("message", "Unknown error")[:50]
            reasons.append(f"Error: {msg}")
    else:
        status = "green"

    return {
        "status": status,
        "reasons": reasons,
        "error_count": error_count,
        "recent_errors": recent_errors[:5]
    }


def get_mcp_health_status() -> Dict[str, Any]:
    """
    Get MCP health as a signal for unified health.

    Returns:
        {
            "status": "red" | "yellow" | "green",
            "reasons": ["..."],
            "mcp_state": "active" | "stale" | "configured" | "misconfigured" | "inactive"
        }
    """
    try:
        from core.mcp_health import check_mcp_health
        result = check_mcp_health()

        if result.state == "active":
            return {"status": "green", "reasons": [], "mcp_state": "active"}
        elif result.state == "stale":
            return {
                "status": "yellow",
                "reasons": [f"MCP stale: {result.reason}"],
                "mcp_state": "stale"
            }
        elif result.state == "configured":
            return {
                "status": "yellow",
                "reasons": [f"MCP inactive: {result.reason}"],
                "mcp_state": "configured"
            }
        elif result.state == "misconfigured":
            return {
                "status": "red",
                "reasons": [f"MCP misconfigured: {result.reason}"],
                "mcp_state": "misconfigured"
            }
        else:  # inactive
            return {
                "status": "red",
                "reasons": ["MCP not configured"],
                "mcp_state": "inactive"
            }
    except Exception as e:
        return {
            "status": "yellow",
            "reasons": [f"MCP health check failed: {e}"],
            "mcp_state": "unknown"
        }


def get_unified_health(
    ai_queue: List[Dict] = None,
    components: List[Dict] = None,
    browser_errors: List[Dict] = None,
    include_mcp: bool = True
) -> Dict[str, Any]:
    """
    Calculate unified health status from all signals.

    Priority:
    - RED if ANY signal is red
    - YELLOW if ANY signal is yellow
    - GREEN only if ALL signals are green

    Returns:
        {
            "status": "red" | "yellow" | "green",
            "reasons": ["..."],
            "timestamp": "...",
            "signals": {
                "commands": {...},
                "stability": {...},
                "errors": {...},
                "mcp": {...}  # NEW - MCP health
            }
        }
    """
    ai_queue = ai_queue or []
    components = components or []
    browser_errors = browser_errors or []

    # Get individual health statuses
    cmd_health = get_command_health(ai_queue)
    stability_health = get_stability_health(components)
    error_health = get_error_health(browser_errors)
    mcp_health = get_mcp_health_status() if include_mcp else {"status": "green", "reasons": []}

    # Combine reasons
    all_reasons = []

    # Priority order: red signals first
    status_priority = {"red": 0, "yellow": 1, "green": 2}

    signals = [
        ("commands", cmd_health),
        ("stability", stability_health),
        ("errors", error_health),
        ("mcp", mcp_health)
    ]

    # Sort by status severity
    signals.sort(key=lambda x: status_priority.get(x[1]["status"], 2))

    # Determine overall status (worst wins)
    overall_status = "green"
    for name, health in signals:
        if health["status"] == "red":
            overall_status = "red"
            all_reasons.extend(health["reasons"])
        elif health["status"] == "yellow" and overall_status != "red":
            overall_status = "yellow"
            all_reasons.extend(health["reasons"])

    return {
        "status": overall_status,
        "reasons": all_reasons[:10],  # Limit to 10 reasons
        "timestamp": datetime.now().isoformat(),
        "signals": {
            "commands": cmd_health,
            "stability": stability_health,
            "errors": error_health,
            "mcp": mcp_health
        }
    }
