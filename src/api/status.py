"""
FixOnce Status Routes
System status, health, and configuration endpoints.

Phase 0: Supports X-Project-Root header for explicit project context.
Dashboard requests can use X-Dashboard: true to fallback to active project.
"""

from flask import jsonify, request, current_app
from datetime import datetime
from pathlib import Path
import sys
import json
import os
import subprocess
import getpass

from . import status_bp, get_project_from_request
from config import PROJECT_ROOT, VERSION
from core.system_mode import get_system_mode, set_system_mode, VALID_MODES

# Global state (will be set by main app)
EXTENSION_CONNECTED = False
EXTENSION_LAST_SEEN = None
ACTUAL_PORT = 5000


def set_extension_connected(connected: bool, last_seen: str = None):
    """Update extension connection state."""
    global EXTENSION_CONNECTED, EXTENSION_LAST_SEEN
    EXTENSION_CONNECTED = connected
    EXTENSION_LAST_SEEN = last_seen or datetime.now().isoformat()


@status_bp.route("/ping")
def api_ping():
    """Simple ping endpoint for service discovery.

    Used by Chrome extension to find which port FixOnce is running on.
    Also used by installer to validate server ownership (cross-user isolation).
    Returns service identifier + ownership info for multi-user safety.
    """
    return jsonify({
        "service": "fixonce",
        "status": "ok",
        "port": ACTUAL_PORT,
        "user": getpass.getuser(),
        "install_path": str(PROJECT_ROOT)
    })


def set_actual_port(port: int):
    """Set the actual port being used."""
    global ACTUAL_PORT
    ACTUAL_PORT = port


@status_bp.route("/version")
def api_version():
    """Return current version information.

    Used by dashboard to display version and check for updates.
    Future: Will check GitHub releases for latest version.
    """
    return jsonify({
        "current": VERSION,
        "latest": None,  # TODO: Check GitHub releases
        "update_available": False,
        "release_url": "https://github.com/anthropics/fixonce/releases"
    })


def _detect_running_editors():
    """
    Best-effort process probe for local editors.
    Used as fallback signal when MCP heartbeat is stale.
    """
    checks = [
        ("codex", ["pgrep", "-f", "codex"]),
        ("claude", ["pgrep", "-f", "/claude"]),
        ("cursor", ["pgrep", "-f", "Cursor"]),
    ]
    running = []
    for name, cmd in checks:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.5)
            if res.returncode == 0 and (res.stdout or "").strip():
                running.append(name)
        except Exception:
            pass
    return running


def _is_dev_mode() -> bool:
    """Allow test endpoints only in explicit dev/test environments."""
    env_flag = os.getenv("FIXONCE_DEV_MODE") == "1" or os.getenv("FIXONCE_ALLOW_TEST_API") == "1"
    flask_env = os.getenv("FLASK_ENV", "").lower() == "development"
    runtime_flag = bool(current_app.debug or current_app.testing)
    host = (request.host or "").lower()
    loopback_host = host.startswith("127.0.0.1") or host.startswith("localhost")
    return env_flag or flask_env or runtime_flag or loopback_host


def _paths_share_project_scope(path_a: str, path_b: str) -> bool:
    """Return True when two paths are the same project root or nested within each other."""
    if not path_a or not path_b:
        return False

    try:
        resolved_a = os.path.realpath(path_a)
        resolved_b = os.path.realpath(path_b)
        common = os.path.commonpath([resolved_a, resolved_b])
        return common == resolved_a or common == resolved_b
    except Exception:
        return False


def _dev_only_guard():
    if _is_dev_mode():
        return None
    return jsonify({
        "status": "error",
        "message": "Test endpoint is disabled outside dev mode. Set FIXONCE_DEV_MODE=1."
    }), 403


@status_bp.route("/handshake", methods=["POST"])
def api_handshake():
    """Called by Chrome Extension on install/startup to signal connection."""
    global EXTENSION_CONNECTED, EXTENSION_LAST_SEEN
    EXTENSION_CONNECTED = True
    EXTENSION_LAST_SEEN = datetime.now().isoformat()
    print(f"🤝 Extension handshake received at {EXTENSION_LAST_SEEN}")
    return jsonify({"status": "connected", "timestamp": EXTENSION_LAST_SEEN})


@status_bp.route("/status")
def api_status():
    """Return system health status for the dashboard wizard."""
    # Count today's events from error store
    events_today = 0
    try:
        from core.error_store import get_all_errors
        today_str = datetime.now().strftime('%Y-%m-%d')
        all_errors = get_all_errors()
        events_today = sum(1 for e in all_errors if e.get('timestamp', '').startswith(today_str) or e.get('_added_at', '').startswith(today_str))
    except Exception:
        pass

    return jsonify({
        "extension_connected": EXTENSION_CONNECTED,
        "extension_last_seen": EXTENSION_LAST_SEEN,
        "events_today": events_today,
        "server_running": True,
        "port": ACTUAL_PORT
    })


@status_bp.route("/health")
def api_health():
    """
    Comprehensive health check endpoint.
    Checks: server, MCP, memory writable, dashboard reachable.
    """
    import os
    import subprocess
    from config import DATA_DIR, SRC_DIR

    health = {
        "status": "healthy",
        "checks": {},
        "timestamp": datetime.now().isoformat()
    }

    issues = []

    # Check 1: Server running (obviously true if we got here)
    health["checks"]["server"] = {"status": "ok", "port": ACTUAL_PORT}

    # Check 2: Data directory writable
    try:
        test_file = DATA_DIR / "health_check.tmp"
        test_file.write_text("test")
        test_file.unlink()
        health["checks"]["memory_writable"] = {"status": "ok", "path": str(DATA_DIR)}
    except Exception as e:
        health["checks"]["memory_writable"] = {"status": "error", "error": str(e)}
        issues.append("Cannot write to data directory")

    # Check 3: MCP server file exists
    mcp_server = SRC_DIR / "mcp_server" / "mcp_memory_server_v2.py"
    if mcp_server.exists():
        health["checks"]["mcp_server"] = {"status": "ok", "path": str(mcp_server)}
    else:
        health["checks"]["mcp_server"] = {"status": "error", "error": "MCP server file not found"}
        issues.append("MCP server file missing")

    # Check 4: Projects directory
    projects_dir = DATA_DIR / "projects_v2"
    if projects_dir.exists():
        project_count = len(list(projects_dir.glob("*.json")))
        health["checks"]["projects"] = {"status": "ok", "count": project_count}
    else:
        health["checks"]["projects"] = {"status": "warning", "message": "No projects yet"}

    # Check 5: Extension connection
    health["checks"]["extension"] = {
        "status": "ok" if EXTENSION_CONNECTED else "warning",
        "connected": EXTENSION_CONNECTED,
        "last_seen": EXTENSION_LAST_SEEN
    }
    if not EXTENSION_CONNECTED:
        issues.append("Chrome extension not connected")

    # Check 6: Active project (no project is a valid state)
    try:
        from core.system_status import _check_project
        project_status = _check_project()

        if project_status.has_project:
            health["checks"]["active_project"] = {
                "status": "ok",
                "project_id": project_status.project_id,
                "project_name": project_status.project_name,
                "working_dir": project_status.working_dir
            }
        else:
            # No active project is valid - not a warning
            health["checks"]["active_project"] = {
                "status": "info",
                "message": "No active project",
                "project_count": project_status.project_count
            }
    except Exception as e:
        health["checks"]["active_project"] = {"status": "error", "error": str(e)}

    # Overall status
    if issues:
        health["status"] = "degraded"
        health["issues"] = issues

    return jsonify(health)


@status_bp.route("/system/status", methods=["GET"])
def api_system_status():
    """
    Unified system status - single source of truth.

    This endpoint returns the complete system status in one call.
    Use this for dashboard initialization and status checks.
    """
    from core.system_status import get_status_for_dashboard
    return jsonify(get_status_for_dashboard())


@status_bp.route("/mcp/health", methods=["GET"])
def api_mcp_health():
    """
    TRUE MCP health check - not just config existence.

    Returns real state:
    - active: MCP tools are callable and recently used
    - stale: Config exists, had recent activity, may need restart
    - configured: Config exists but not active
    - misconfigured: Config has errors
    - inactive: No config

    This endpoint should be used instead of checking "configured" status.
    """
    try:
        from core.mcp_health import get_mcp_health_for_dashboard
        return jsonify(get_mcp_health_for_dashboard())
    except Exception as e:
        return jsonify({
            "status": "error",
            "state": "unknown",
            "message": f"Health check failed: {e}",
            "is_active": False,
            "is_usable": False,
            "needs_fix": True
        }), 500


@status_bp.route("/system/mode", methods=["GET"])
def api_get_system_mode():
    """Get global FixOnce operating mode."""
    try:
        return jsonify({"status": "ok", **get_system_mode()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@status_bp.route("/system/mode", methods=["POST"])
def api_set_system_mode():
    """Set global FixOnce operating mode."""
    try:
        payload = request.get_json(silent=True) or {}
        mode = payload.get("mode", "")
        updated_by = payload.get("updated_by", "dashboard")

        if str(mode).strip().lower() not in VALID_MODES:
            return jsonify({
                "status": "error",
                "message": f"Invalid mode '{mode}'. Valid modes: {sorted(VALID_MODES)}"
            }), 400

        data = set_system_mode(mode, updated_by=updated_by)
        return jsonify({"status": "ok", **data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Dashboard Snapshot (Unified API for Widgets) ============

@status_bp.route("/dashboard_snapshot", methods=["GET"])
def api_dashboard_snapshot():
    """
    Unified dashboard snapshot - all data for widgets in one call.

    Returns:
        {
            "active_ais": [...],
            "ai_handoffs": [...],
            "roi": {...},
            "projects": [...],
            "knowledge": {...},
            "environment": {...},
            "activity": [...],
            "timestamp": "..."
        }
    """
    from config import DATA_DIR
    from datetime import datetime, timedelta

    snapshot = {
        "active_ais": [],
        "ai_handoffs": [],
        "roi": {
            "solutions_reused": 0,
            "decisions_referenced": 0,
            "errors_prevented": 0,
            "time_saved_minutes": 0,
            "tokens_saved": 0
        },
        "projects": [],
        "knowledge": {
            "total_insights": 0,
            "total_decisions": 0,
            "total_avoids": 0,
            "total_rules": 0,
            "indexed_docs": 0,
            "top_learnings": [],
            "project_rules": [],
            "decisions": [],
            "avoids": []
        },
        "environment": {
            "env": "dev",
            "ports": [],
            "urls": [],
            "working_dir": None,
            "stage": None
        },
        "policy": {
            "mode": None,
            "persona": None,
            "compliance_percent": None,
            "reason": None
        },
        "protocol_watchdog": {
            "out_of_protocol": False,
            "reason": "",
            "active_project_path": None,
            "observed_working_dir": None,
            "observed_project_id": None,
            "timestamp": None,
            "actor": None
        },
        "system_mode": {
            "mode": "full",
            "updated_at": None,
            "updated_by": "unknown"
        },
        "identity": None,
        "activity": [],
        "timestamp": datetime.now().isoformat()
    }

    try:
        # === Global system mode ===
        try:
            snapshot["system_mode"] = get_system_mode()
        except Exception:
            pass

        # === Active AIs & Handoffs ===
        try:
            # Get from active project memory (where MCP stores it)
            from managers.multi_project_manager import get_active_project_id, load_project_memory

            active_project_id = get_active_project_id()
            if active_project_id:
                project_memory = load_project_memory(active_project_id) or {}

                # Active AIs
                active_ais = project_memory.get("active_ais", {}) or {}
                normalized_ais = []
                now = datetime.now()
                ACTIVE_STALE_SECONDS = 1800  # 30m: avoid false "No AI" during long coding stretches
                for ai_name, ai_data in active_ais.items():
                    last_activity = ai_data.get("last_activity")
                    if last_activity:
                        try:
                            last_dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                            if last_dt.tzinfo:
                                last_dt = last_dt.replace(tzinfo=None)
                            # Hide stale AI rows from dashboard view.
                            if (now - last_dt).total_seconds() > ACTIVE_STALE_SECONDS:
                                continue
                        except Exception:
                            pass
                    normalized_ais.append({
                        "id": ai_name,
                        "editor": ai_name,  # ai_name IS the editor name
                        "started_at": ai_data.get("started_at"),
                        "last_activity": ai_data.get("last_activity"),
                        "is_primary": ai_data.get("is_primary", False),
                        "actor_source": ai_data.get("actor_source", "unknown"),
                        "actor_confidence": ai_data.get("actor_confidence", 0.0),
                        "tool_calls": ai_data.get("tool_calls", 0),
                    })

                # Conservative fallback: include ai_session only when it was produced by
                # an MCP call source and has very recent activity.
                ai_session = project_memory.get("ai_session", {}) or {}
                session_editor = ai_session.get("editor")
                session_source = ai_session.get("actor_source", "unknown")
                session_last_activity = ai_session.get("last_activity")
                is_recent_session = False
                if session_last_activity:
                    try:
                        sess_dt = datetime.fromisoformat(session_last_activity.replace('Z', '+00:00'))
                        if sess_dt.tzinfo:
                            sess_dt = sess_dt.replace(tzinfo=None)
                        is_recent_session = (now - sess_dt).total_seconds() <= ACTIVE_STALE_SECONDS
                    except Exception:
                        is_recent_session = False
                if (
                    session_editor
                    and session_source in {"client_actor", "runtime_env", "parent_process"}
                    and is_recent_session
                    and not any(ai.get("editor") == session_editor for ai in normalized_ais)
                ):
                    normalized_ais.append({
                        "id": session_editor,
                        "editor": session_editor,
                        "started_at": ai_session.get("started_at"),
                        "last_activity": session_last_activity,
                        "is_primary": bool(ai_session.get("active", False)),
                        "actor_source": session_source,
                        "actor_confidence": ai_session.get("actor_confidence", 0.0),
                    })

                # Ensure at least one primary for UI ordering if any AI exists
                if normalized_ais and not any(ai.get("is_primary") for ai in normalized_ais):
                    normalized_ais[0]["is_primary"] = True

                # Last-resort fallback: detect running editor process if no active AI rows.
                if not normalized_ais:
                    running_editors = _detect_running_editors()
                    for i, editor_name in enumerate(running_editors):
                        normalized_ais.append({
                            "id": editor_name,
                            "editor": editor_name,
                            "started_at": None,
                            "last_activity": None,
                            "is_primary": i == 0,
                            "actor_source": "process_probe",
                            "actor_confidence": 0.35,
                            "tool_calls": 0,
                        })

                snapshot["active_ais"] = normalized_ais

                # AI Handoffs (last 10)
                handoffs = project_memory.get("ai_handoffs", [])
                snapshot["ai_handoffs"] = handoffs[-10:] if handoffs else []
        except Exception:
            pass

        # === ROI Stats ===
        try:
            from managers.project_memory_manager import get_roi_stats
            roi = get_roi_stats()
            snapshot["roi"] = {
                "solutions_reused": roi.get("solutions_reused", 0),
                "decisions_referenced": roi.get("decisions_referenced", 0),
                "errors_prevented": roi.get("errors_prevented", 0),
                "errors_caught_live": roi.get("errors_caught_live", 0),
                "sessions_with_context": roi.get("sessions_with_context", 0),
                "insights_used": roi.get("insights_used", 0),
                "time_saved_minutes": roi.get("time_saved_minutes", 0),
                "tokens_saved": roi.get("tokens_saved", 0)
            }
        except Exception:
            pass

        # === Projects List ===
        try:
            from managers.multi_project_manager import (
                get_active_project_id, load_project_memory
            )

            active_id = get_active_project_id()
            all_projects = []

            # Scan projects_v2 directory
            projects_dir = DATA_DIR / "projects_v2"
            if projects_dir.exists():
                for f in projects_dir.glob("*.json"):
                    name = f.stem
                    if name not in ('__global__', 'live-state'):
                        all_projects.append(name)

            now = datetime.now()
            for pid in all_projects[:20]:  # Limit to 20 projects
                try:
                    memory = load_project_memory(pid) or {}
                    project_info = memory.get("project_info", {})
                    live_record = memory.get("live_record", {})

                    # Determine status based on last activity
                    last_updated = memory.get("last_updated") or live_record.get("updated_at")
                    status = "stale"
                    if pid == active_id:
                        status = "active"
                    elif last_updated:
                        try:
                            last_dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00').replace('+00:00', ''))
                            if (now - last_dt).days < 7:
                                status = "recent"
                        except:
                            pass

                    # Get counts
                    lessons = live_record.get("lessons", {})
                    insights_count = len(lessons.get("insights", []))
                    decisions_count = len(memory.get("decisions", []))
                    avoids_count = len(memory.get("avoid", []))

                    # Check semantic index
                    semantic_info = {"indexed": False, "doc_count": 0}
                    emb_dir = DATA_DIR / "projects_v2" / f"{pid}.embeddings"
                    if emb_dir.exists():
                        config_file = emb_dir / "config.json"
                        if config_file.exists():
                            with open(config_file, 'r', encoding='utf-8') as cf:
                                emb_config = json.load(cf)
                            semantic_info = {
                                "indexed": True,
                                "doc_count": emb_config.get("document_count", 0)
                            }

                    snapshot["projects"].append({
                        "project_id": pid,
                        "name": project_info.get("name") or pid.split("_")[0],
                        "working_dir": project_info.get("working_dir", ""),
                        "status": status,
                        "last_updated": last_updated,
                        "archived": project_info.get("archived", False),
                        "counts": {
                            "insights": insights_count,
                            "decisions": decisions_count,
                            "avoids": avoids_count
                        },
                        "semantic": semantic_info
                    })
                except Exception:
                    continue

            # Sort: active first, then recent, then stale
            status_order = {"active": 0, "recent": 1, "stale": 2}
            snapshot["projects"].sort(key=lambda p: status_order.get(p["status"], 3))

        except Exception:
            pass

        # === Knowledge Base Stats ===
        try:
            from managers.multi_project_manager import get_active_project_id, load_project_memory

            active_id = get_active_project_id()
            if active_id:
                memory = load_project_memory(active_id) or {}
                lessons = memory.get("live_record", {}).get("lessons", {})
                insights = lessons.get("insights", [])
                decisions = memory.get("decisions", [])
                avoids = memory.get("avoid", [])
                project_rules = memory.get("project_rules", [])

                snapshot["knowledge"]["total_insights"] = len(insights)
                snapshot["knowledge"]["total_decisions"] = len(decisions)
                snapshot["knowledge"]["total_avoids"] = len(avoids)
                snapshot["knowledge"]["total_rules"] = len([r for r in project_rules if r.get("enabled", True)])
                snapshot["knowledge"]["project_rules"] = project_rules
                snapshot["knowledge"]["decisions"] = decisions[-10:]  # Last 10
                snapshot["knowledge"]["avoids"] = avoids[-10:]  # Last 10

                # Try semantic top learnings
                try:
                    from core.project_semantic import get_project_index_stats
                    stats = get_project_index_stats(active_id)
                    snapshot["knowledge"]["indexed_docs"] = stats.get("document_count", 0)
                except:
                    pass

                # Get top learnings with metadata
                top_learnings = []
                for insight in insights[-10:]:
                    if isinstance(insight, dict):
                        top_learnings.append({
                            "text": insight.get("text", str(insight))[:200],
                            "importance": insight.get("importance", 1),
                            "use_count": insight.get("use_count", 0)
                        })
                    else:
                        top_learnings.append({
                            "text": str(insight)[:200],
                            "importance": 1,
                            "use_count": 0
                        })

                # Sort by importance/use_count
                top_learnings.sort(key=lambda x: (x["importance"], x["use_count"]), reverse=True)
                snapshot["knowledge"]["top_learnings"] = top_learnings[:5]

        except Exception:
            pass

        # === Environment / GPS ===
        try:
            from managers.multi_project_manager import get_active_project_id, load_project_memory

            active_id = get_active_project_id()
            if active_id:
                memory = load_project_memory(active_id) or {}
                project_info = memory.get("project_info", {})
                live_record = memory.get("live_record", {})
                gps = live_record.get("gps", {})
                arch = live_record.get("architecture", {})
                intent = live_record.get("intent", {})

                # Get working_dir from gps or project_info
                working_dir = gps.get("working_dir") or project_info.get("working_dir")

                # Infer stage from intent or default
                stage = intent.get("stage") or project_info.get("stage") or "development"

                snapshot["environment"] = {
                    "env": gps.get("environment", "dev"),
                    "ports": gps.get("active_ports", []),
                    "urls": [gps.get("url")] if gps.get("url") else [],
                    "working_dir": working_dir,
                    "stage": stage,
                    "stack": arch.get("stack") or project_info.get("stack"),
                    "key_flows": arch.get("key_flows", [])
                }
        except Exception:
            pass

        # === Project Identity (human-readable snapshot) ===
        try:
            from managers.multi_project_manager import get_active_project_id, load_project_memory

            active_id = get_active_project_id()
            if active_id:
                memory = load_project_memory(active_id) or {}
                project_info = memory.get("project_info", {})
                live_record = memory.get("live_record", {})
                arch = live_record.get("architecture", {})
                intent = live_record.get("intent", {})
                lessons = live_record.get("lessons", {})
                decisions = memory.get("decisions", [])
                avoids = memory.get("avoid", [])

                last_decision = decisions[-1] if decisions else None
                last_insight_raw = (lessons.get("insights") or [])
                last_insight = last_insight_raw[-1] if last_insight_raw else None
                last_avoid = avoids[-1] if avoids else None

                snapshot["identity"] = {
                    "name": project_info.get("name") or active_id.split("_")[0],
                    "stack": arch.get("stack") or project_info.get("stack") or "",
                    "summary": arch.get("summary") or "",
                    "current_goal": intent.get("current_goal") or "",
                    "next_step": intent.get("next_step") or "",
                    "last_decision": {
                        "text": (last_decision.get("decision") or last_decision.get("text") or "")[:120],
                        "reason": (last_decision.get("reason") or "")[:120],
                    } if last_decision else None,
                    "last_insight": (
                        (last_insight.get("text") or last_insight.get("insight") or str(last_insight))[:120]
                        if isinstance(last_insight, dict) else str(last_insight)[:120]
                    ) if last_insight else None,
                    "last_avoid": (
                        (last_avoid.get("what") or last_avoid.get("text") or "")[:120]
                    ) if last_avoid else None,
                    "counts": {
                        "decisions": len(decisions),
                        "insights": len(last_insight_raw),
                        "avoids": len(avoids),
                    }
                }

                # Architecture for system tree
                snapshot["architecture"] = {
                    "summary": arch.get("summary") or "",
                    "stack": arch.get("stack") or "",
                    "key_flows": arch.get("key_flows") or [],
                    "components": arch.get("components") or []
                }

                # Policy profile (non-invasive): read explicit fields if present,
                # otherwise derive safe defaults from existing snapshot signals.
                def first_present(*values):
                    for value in values:
                        if value is not None and value != "":
                            return value
                    return None

                mode = first_present(
                    intent.get("mode"),
                    intent.get("project_mode"),
                    project_info.get("mode"),
                    project_info.get("project_mode"),
                    snapshot["environment"].get("stage")
                )

                persona = first_present(
                    intent.get("persona"),
                    intent.get("ai_persona"),
                    project_info.get("persona"),
                    project_info.get("ai_persona")
                )

                explicit_compliance = first_present(
                    intent.get("compliance_percent"),
                    intent.get("policy_compliance"),
                    project_info.get("compliance_percent"),
                    project_info.get("policy_compliance")
                )
                explicit_reason = first_present(
                    intent.get("policy_reason"),
                    intent.get("reason"),
                    project_info.get("policy_reason"),
                    project_info.get("reason")
                )

                compliance_percent = None
                reason = explicit_reason
                if explicit_compliance is not None:
                    try:
                        compliance_percent = max(0, min(100, int(round(float(explicit_compliance)))))
                        if not reason:
                            reason = "From stored policy profile."
                    except (TypeError, ValueError):
                        compliance_percent = None

                if compliance_percent is None:
                    try:
                        from mcp_server.mcp_memory_server_v2 import get_compliance_for_api
                        compliance = get_compliance_for_api()
                        checks = [
                            bool(compliance.get("session_initialized")),
                            bool(compliance.get("decisions_displayed")),
                            bool(compliance.get("goal_updated"))
                        ]
                        compliance_percent = int(round((sum(checks) / len(checks)) * 100))
                        reason = "Derived from protocol compliance checks."
                    except Exception:
                        compliance_percent = None
                        reason = "Policy data unavailable."

                if not persona:
                    active_ais = snapshot.get("active_ais") or []
                    if active_ais:
                        persona = active_ais[0].get("editor")

                snapshot["policy"] = {
                    "mode": mode,
                    "persona": persona,
                    "compliance_percent": compliance_percent,
                    "reason": reason
                }
        except Exception:
            pass

        # === Activity Stream ===
        try:
            activity_file = DATA_DIR / "activity_log.json"
            if activity_file.exists():
                with open(activity_file, 'r', encoding='utf-8') as f:
                    activity_data = json.load(f)

                activities = activity_data.get("activities", [])[:50]  # First 50 (newest first)
                latest_observed = None

                # Get active project ID for filtering
                active_project_id = None
                try:
                    from managers.multi_project_manager import get_active_project_id
                    active_project_id = get_active_project_id()
                except Exception:
                    pass

                for act in activities:
                    act_project_id = act.get("project_id", "__global__")
                    observed_cwd = (act.get("cwd") or "").strip()
                    observed_file = (act.get("file") or "").strip()
                    observed_path = observed_cwd or (os.path.dirname(observed_file) if observed_file else "")

                    if not latest_observed and observed_path:
                        latest_observed = {
                            "path": observed_path,
                            "project_id": act_project_id,
                            "timestamp": act.get("timestamp"),
                            "actor": act.get("editor") or act.get("actor") or "unknown"
                        }

                    # Include activity if:
                    # 1. It's from the active project, OR
                    # 2. It's a global activity (fallback), OR
                    # 3. It's an MCP tool activity (memory operations)
                    is_active_project = (act_project_id == active_project_id) if active_project_id else False
                    is_mcp_activity = act.get("type") == "mcp_tool" or act.get("file_context") == "memory"
                    is_global = act_project_id == "__global__"

                    if is_active_project or is_mcp_activity or (is_global and len(snapshot["activity"]) < 10):
                        snapshot["activity"].append({
                            "timestamp": act.get("timestamp"),
                            "tool": act.get("tool"),
                            "file": act.get("file"),
                            "human_name": act.get("human_name"),
                            "project_id": act_project_id,
                            "actor": act.get("editor", "unknown"),
                            "diff": act.get("diff"),  # {added, removed} if available
                            "type": act.get("type", "file_change"),  # Include type for MCP detection
                            "file_context": act.get("file_context", "")  # Include context
                        })

                # Limit to 30 activities (already in newest-first order)
                snapshot["activity"] = snapshot["activity"][:30]

                active_path = snapshot["environment"].get("working_dir")
                if latest_observed:
                    snapshot["protocol_watchdog"].update({
                        "observed_working_dir": latest_observed["path"],
                        "observed_project_id": latest_observed["project_id"],
                        "timestamp": latest_observed["timestamp"],
                        "actor": latest_observed["actor"],
                        "active_project_path": active_path
                    })

                    if not active_path:
                        snapshot["protocol_watchdog"]["out_of_protocol"] = True
                        snapshot["protocol_watchdog"]["reason"] = "no_active_project"
                    elif not _paths_share_project_scope(latest_observed["path"], active_path):
                        snapshot["protocol_watchdog"]["out_of_protocol"] = True
                        snapshot["protocol_watchdog"]["reason"] = "working_dir_mismatch"
        except Exception:
            pass

        # === MCP Health (TRUE state, not just config) ===
        try:
            from core.mcp_health import get_mcp_health_for_dashboard
            snapshot["mcp_health"] = get_mcp_health_for_dashboard()
        except Exception as e:
            snapshot["mcp_health"] = {
                "status": "error",
                "state": "unknown",
                "message": f"Health check failed: {e}",
                "is_active": False,
                "is_usable": False,
                "needs_fix": True
            }

        # === Unified Orb Health ===
        try:
            from core.unified_health import get_unified_health, check_command_timeouts
            from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory

            active_id = get_active_project_id()
            if active_id:
                memory = load_project_memory(active_id) or {}

                # Get command queue and run timeout watchdog
                ai_queue = memory.get("ai_queue", [])
                audit_log = memory.get("command_audit", [])
                ai_queue, timed_out = check_command_timeouts(ai_queue, audit_log)

                # Save if any timed out
                if timed_out:
                    memory["ai_queue"] = ai_queue
                    memory["command_audit"] = audit_log[-50:]
                    save_project_memory(active_id, memory)

                # Get components
                components = memory.get("live_record", {}).get("architecture", {}).get("components", [])

                # Get browser errors from core.error_store (shared state)
                try:
                    from core.error_store import get_error_log, get_log_lock
                    _error_log = get_error_log()
                    _log_lock = get_log_lock()
                    with _log_lock:
                        browser_errors = list(_error_log)  # Copy the list
                except Exception as e:
                    print(f"[Dashboard] Error getting browser errors: {e}")
                    browser_errors = []

                # Calculate unified health
                snapshot["orb"] = get_unified_health(ai_queue, components, browser_errors)

                # Add browser_errors for minimal dashboard
                snapshot["browser_errors"] = browser_errors
                snapshot["error_count"] = len(browser_errors)
        except Exception:
            snapshot["orb"] = {"status": "green", "reasons": [], "timestamp": None}

        # === Top-level convenience fields for minimal dashboard ===
        try:
            # Project name and goal
            if snapshot.get("identity"):
                snapshot["project_name"] = snapshot["identity"].get("name")
                snapshot["current_goal"] = snapshot["identity"].get("current_goal")
                snapshot["next_step"] = snapshot["identity"].get("next_step")

            # Intent (last_change, next_step) from live_record
            from managers.multi_project_manager import get_active_project_id, load_project_memory
            active_id = get_active_project_id()
            if active_id:
                memory = load_project_memory(active_id) or {}
                intent = memory.get("live_record", {}).get("intent", {})
                snapshot["intent"] = intent

            # Active AI name
            if snapshot.get("active_ais") and len(snapshot["active_ais"]) > 0:
                primary = next((ai for ai in snapshot["active_ais"] if ai.get("is_primary")), snapshot["active_ais"][0])
                snapshot["active_ai"] = primary.get("editor", "Unknown")

            # Auto-fix available
            try:
                from core.pending_fixes import get_auto_fixes
                auto_fixes = get_auto_fixes()
                snapshot["has_auto_fix"] = bool(auto_fixes)
                snapshot["auto_fix_count"] = len(auto_fixes) if auto_fixes else 0
            except:
                snapshot["has_auto_fix"] = False
                snapshot["auto_fix_count"] = 0

        except Exception:
            pass

        # === System Status (real sources only) ===
        try:
            system_status = {
                "fixonce": {"connected": True, "source": "api_responding"},  # If we got here, server is up
                "ai": {"name": None, "source": None, "connected": False},
                "extension": {"connected": False, "last_seen": None, "source": "unknown"},
                "memory": {"loaded": False, "project_id": None, "source": "unknown"}
            }

            # AI status from real session data
            if snapshot.get("active_ais") and len(snapshot["active_ais"]) > 0:
                primary = next((ai for ai in snapshot["active_ais"] if ai.get("is_primary")), snapshot["active_ais"][0])
                system_status["ai"] = {
                    "name": primary.get("editor"),
                    "source": primary.get("actor_source", "unknown"),
                    "connected": True,
                    "last_activity": primary.get("last_activity")
                }

            # Extension status from real heartbeat
            if EXTENSION_CONNECTED:
                system_status["extension"] = {
                    "connected": True,
                    "last_seen": EXTENSION_LAST_SEEN,
                    "source": "heartbeat"
                }
            else:
                system_status["extension"] = {
                    "connected": False,
                    "last_seen": None,
                    "source": "no_heartbeat"
                }

            # Memory status from active project
            from managers.multi_project_manager import get_active_project_id
            active_id = get_active_project_id()
            if active_id and snapshot.get("identity"):
                system_status["memory"] = {
                    "loaded": True,
                    "project_id": active_id,
                    "source": "active_project"
                }
            else:
                system_status["memory"] = {
                    "loaded": False,
                    "project_id": None,
                    "source": "no_active_project"
                }

            snapshot["system_status"] = system_status

        except Exception:
            pass

        return jsonify({"status": "ok", "snapshot": snapshot})

    except Exception as e:
        snapshot["error"] = str(e)
        return jsonify({"status": "error", "snapshot": snapshot, "message": str(e)}), 500


# ============ Sessions API (Multi-AI Isolation) ============

@status_bp.route("/stability/report", methods=["GET"])
def api_stability_report():
    """
    Get component stability summary.

    Returns:
        {
            "total": 10,
            "stable": 5,
            "building": 3,
            "broken": 2,
            "with_checkpoints": 4,
            "components": [...]
        }
    """
    try:
        from core.component_stability import get_stability_summary
        from managers.multi_project_manager import get_active_project_id, load_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"error": "No active project"}), 400

        memory = load_project_memory(project_id) or {}
        components = memory.get("live_record", {}).get("architecture", {}).get("components", [])

        summary = get_stability_summary(components)
        summary["components"] = components

        return jsonify(summary)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@status_bp.route("/stability/mark-all", methods=["POST"])
def api_mark_all_stable():
    """
    Mark all components as stable (Safety Point).
    Creates a checkpoint of current state.
    """
    try:
        from core.component_stability import mark_component_stable, get_current_commit
        from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory
        from datetime import datetime

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"error": "No active project"}), 400

        memory = load_project_memory(project_id) or {}
        repo_path = memory.get("live_record", {}).get("gps", {}).get("working_dir", "")

        arch = memory.get("live_record", {}).get("architecture", {})
        components = arch.get("components", [])

        if not components:
            return jsonify({"status": "ok", "message": "No components to mark", "marked": 0})

        # Get current commit
        commit = get_current_commit(repo_path) if repo_path else None
        marked_count = 0

        for comp in components:
            comp["status"] = "stable"
            comp["stable_since"] = datetime.now().isoformat()
            if commit:
                comp["stable_commit"] = commit
            marked_count += 1

        # Update stable count
        arch["stable_count"] = len(components)
        memory["live_record"]["architecture"] = arch
        save_project_memory(project_id, memory)

        return jsonify({
            "status": "ok",
            "message": f"Safety Point created",
            "marked": marked_count,
            "commit": commit
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@status_bp.route("/stability/mark/<name>", methods=["POST"])
def api_mark_stable(name):
    """
    Mark a component as stable via API.

    Request body (optional):
        {
            "files": ["src/file1.py", "src/file2.py"]
        }
    """
    try:
        from core.component_stability import mark_component_stable, add_files_to_component, get_current_commit
        from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"error": "No active project"}), 400

        memory = load_project_memory(project_id) or {}
        repo_path = memory.get("live_record", {}).get("gps", {}).get("working_dir", "")

        arch = memory.get("live_record", {}).get("architecture", {})
        components = arch.get("components", [])

        # Find component
        found_idx = None
        for i, comp in enumerate(components):
            if comp.get("name", "").lower() == name.lower():
                found_idx = i
                break

        if found_idx is None:
            return jsonify({"error": f"Component '{name}' not found"}), 404

        component = components[found_idx]

        # Add files if provided
        data = request.get_json(silent=True) or {}
        if data.get("files"):
            component = add_files_to_component(component, data["files"])

        # Mark stable
        component = mark_component_stable(component, repo_path, "dashboard")

        # Save
        components[found_idx] = component
        arch["components"] = components
        arch["updated_at"] = datetime.now().isoformat()
        memory["live_record"]["architecture"] = arch

        # Log as decision
        commit_short = component.get("last_stable", {}).get("commit_short", "unknown")
        decision = {
            "type": "decision",
            "decision": f"Checkpoint created for {name}",
            "reason": f"Saved at commit {commit_short} - can rollback to this state",
            "timestamp": datetime.now().isoformat(),
            "importance": "permanent"
        }
        if "decisions" not in memory:
            memory["decisions"] = []
        memory["decisions"].append(decision)

        save_project_memory(project_id, memory)

        return jsonify({
            "success": True,
            "component": component,
            "decision_logged": True
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

