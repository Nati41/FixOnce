"""
FixOnce Error Routes
Error logging and live error retrieval endpoints.

Phase 0: Added project_id tagging to prevent cross-project leakage.
Phase 0.1: Use X-Project-Root header for explicit project context.
"""

from flask import jsonify, request
from datetime import datetime

from . import errors_bp, get_project_from_request
from core.notifications import send_desktop_notification
from core.error_store import get_error_log, get_log_lock, add_error, get_errors, clear_errors

# Get references to shared state (legacy compatibility)
error_log = get_error_log()
log_lock = get_log_lock()


def _get_active_project_id() -> str:
    """
    Get the project ID for error attribution.

    Priority:
    1. X-Project-Root header (if present)
    2. Active project fallback (for backward compatibility)
    3. __global__ fallback
    """
    # Try X-Project-Root header first
    project_id, _ = get_project_from_request()
    if project_id:
        return project_id

    # Fallback to active project (backward compatibility)
    try:
        from managers.multi_project_manager import get_active_project_id
        pid = get_active_project_id()
        return pid if pid else "__global__"
    except:
        return "__global__"


@errors_bp.route("/log", methods=["POST"])
def receive_log():
    """Receive error log from browser snippet."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    entry = {
        "type": data.get("type", "unknown"),
        "message": data.get("message", ""),
        "url": data.get("url", ""),
        "source": data.get("source", ""),
        "line": data.get("line", ""),
        "column": data.get("column", ""),
        "stack": data.get("stack", ""),
        "timestamp": data.get("timestamp", datetime.now().isoformat()),
    }

    # Phase 0: Add error with project_id tagging
    project_id = _get_active_project_id()
    add_error(entry, project_id=project_id)

    print(
        f"\n🔥 [{entry['type']}] {entry['timestamp']}\n"
        f"   URL:     {entry['url']}\n"
        f"   Message: {entry['message']}"
    )

    return jsonify({"status": "ok"})


@errors_bp.route("/api/log_error", methods=["POST"])
def api_log_error():
    """V3.1: New endpoint for extension to log errors.
    Now also updates Project Memory for AI context persistence.
    """
    # Anti-loop guard: Skip errors from FixOnce hooks to prevent infinite loops
    if request.headers.get('X-FixOnce-Origin'):
        origin = request.headers.get('X-FixOnce-Origin')
        print(f"[FixOnce] Received error from hook: {origin}")

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    # Extract error info
    error_data = data.get("data", {})
    entry = {
        "type": data.get("type", "unknown"),
        "message": error_data.get("message", data.get("message", "")),
        "severity": error_data.get("severity", "error"),
        "url": data.get("url", data.get("tabUrl", "")),
        "file": error_data.get("file", ""),
        "line": error_data.get("line", ""),
        "timestamp": data.get("timestamp", datetime.now().isoformat()),
    }

    # Check for existing solution using semantic engine
    try:
        from core.semantic_engine import get_engine
        from config import PERSONAL_DB_PATH

        if entry["message"]:
            engine = get_engine(PERSONAL_DB_PATH)
            match = engine.find_similar(entry["message"])
            if match:
                solution_id, score, _ = match
                solution = engine.get_solution_by_id(solution_id)
                if solution:
                    entry["matched_solution"] = {
                        "id": solution_id,
                        "score": score,
                        "solution": solution["solution_text"],
                        "success_count": solution.get("success_count", 0)
                    }

                    # 🔥 AUTO-APPLY: Add to pending fixes queue
                    try:
                        from core.pending_fixes import add_pending_fix
                        # High similarity = high confidence (AUTO-FIX behavior)
                        # score >= 0.85 → AUTO (90+)
                        # score >= 0.70 → SUGGEST (70-89)
                        base_confidence = int(score * 100)  # 0.9 → 90
                        success_bonus = solution.get("success_count", 0) * 3
                        confidence = min(95, base_confidence + success_bonus)
                        similarity = int(score * 100)

                        result = add_pending_fix(
                            error_message=entry["message"],
                            solution_text=solution["solution_text"],
                            confidence=confidence,
                            similarity=similarity,
                            source="semantic",
                            error_id=f"err_{datetime.now().timestamp()}"
                        )

                        if result["action"] == "auto":
                            print(f"[AUTO-APPLY] 🔧 Ready to auto-fix: {entry['message'][:50]}...")
                        elif result["action"] == "suggest":
                            print(f"[SUGGEST] 💡 Solution found: {entry['message'][:50]}...")
                    except Exception as pf_err:
                        print(f"[PendingFix] Error: {pf_err}")
    except Exception as e:
        print(f"[V3.1] Match error: {e}")

    # Check for committed solutions in .fixonce/solutions.json
    if not entry.get("matched_solution"):
        try:
            from core.committed_knowledge import read_committed_knowledge
            from managers.multi_project_manager import get_active_project_path

            working_dir = get_active_project_path()
            if working_dir:
                committed = read_committed_knowledge(working_dir)
                solutions = committed.get("solutions", [])

                # Simple keyword matching for now
                error_msg_lower = entry["message"].lower()
                for sol in solutions:
                    problem_lower = sol.get("problem", "").lower()
                    symptoms = [s.lower() for s in sol.get("symptoms", [])]

                    # Check if error matches problem or symptoms
                    problem_words = set(problem_lower.split())
                    error_words = set(error_msg_lower.split())
                    overlap = problem_words & error_words

                    if len(overlap) >= 3 or any(symptom in error_msg_lower for symptom in symptoms):
                        entry["committed_solution"] = {
                            "problem": sol.get("problem", ""),
                            "solution": sol.get("solution", ""),
                            "root_cause": sol.get("root_cause", ""),
                            "files_changed": sol.get("files_changed", []),
                            "source": "repo"
                        }
                        print(f"[CommittedSolution] Found match: {sol.get('problem', '')[:50]}")

                        # 🔥 AUTO-APPLY: Committed solutions have high confidence
                        try:
                            from core.pending_fixes import add_pending_fix
                            result = add_pending_fix(
                                error_message=entry["message"],
                                solution_text=sol.get("solution", ""),
                                confidence=92,  # Committed solutions are trusted
                                similarity=75,
                                source="committed",
                                files=sol.get("files_changed", []),
                                error_id=f"committed_{datetime.now().timestamp()}"
                            )
                            if result["action"] == "auto":
                                print(f"[AUTO-APPLY] 🔧 Committed fix ready: {entry['message'][:50]}...")
                        except Exception as pf_err:
                            print(f"[PendingFix] Error: {pf_err}")

                        break
        except Exception as e:
            print(f"[CommittedSolution] Error: {e}")

    # Phase 0: Add error with project_id tagging
    project_id = _get_active_project_id()
    add_error(entry, project_id=project_id)

    # Update Project Memory
    try:
        from managers.project_memory_manager import add_or_update_issue

        snippet = data.get("snippet", error_data.get("snippet", []))
        locals_data = data.get("locals", error_data.get("locals", {}))
        func_name = data.get("function", error_data.get("function", ""))
        stack_trace = data.get("stack", error_data.get("stack", ""))

        memory_result = add_or_update_issue(
            error_type=entry["type"],
            message=entry["message"],
            url=entry["url"],
            severity=entry["severity"],
            file=entry["file"],
            line=str(entry["line"]),
            function=func_name,
            snippet=snippet if isinstance(snippet, list) else [],
            locals_data=locals_data if isinstance(locals_data, dict) else {},
            stack=stack_trace,
            extra_data={"matched_solution": entry.get("matched_solution")}
        )
        print(f"[ProjectMemory] {memory_result['status']}: {memory_result['issue_id']} (count: {memory_result['count']})")

        # Desktop notifications disabled - errors show in dashboard
        # if memory_result['status'] == 'new':
        #     send_desktop_notification(...)
    except Exception as e:
        print(f"[ProjectMemory] Error: {e}")

    print(f"[V3.1] {entry['severity'].upper()}: {entry['message'][:80]}")

    return jsonify({
        "status": "ok",
        "has_solution": "matched_solution" in entry,
        "solution_score": entry.get("matched_solution", {}).get("score", 0)
    })


@errors_bp.route("/api/log_errors_batch", methods=["POST"])
def api_log_errors_batch():
    """V3.2: Batch endpoint for logging multiple errors in one request."""
    data = request.get_json(silent=True)
    if not data or "errors" not in data:
        return jsonify({"status": "error", "message": "No errors array"}), 400

    errors = data.get("errors", [])
    processed = 0

    # Phase 0: Get project_id once for the batch
    project_id = _get_active_project_id()

    for error_data in errors:
        try:
            entry = {
                "type": error_data.get("type", "unknown"),
                "message": error_data.get("message", ""),
                "severity": error_data.get("severity", "error"),
                "url": error_data.get("url", error_data.get("tabUrl", "")),
                "file": error_data.get("file", ""),
                "line": error_data.get("line", ""),
                "timestamp": error_data.get("timestamp", datetime.now().isoformat()),
            }

            # Phase 0: Add error with project_id tagging
            add_error(entry, project_id=project_id)

            # Update Project Memory
            try:
                from managers.project_memory_manager import add_or_update_issue

                snippet = error_data.get("snippet", [])
                locals_data = error_data.get("locals", {})
                func_name = error_data.get("function", "")
                stack_trace = error_data.get("stack", "")

                memory_result = add_or_update_issue(
                    error_type=entry["type"],
                    message=entry["message"],
                    url=entry["url"],
                    severity=entry["severity"],
                    file=entry["file"],
                    line=str(entry["line"]),
                    function=func_name,
                    snippet=snippet if isinstance(snippet, list) else [],
                    locals_data=locals_data if isinstance(locals_data, dict) else {},
                    stack=stack_trace,
                    extra_data={}
                )

                # Desktop notifications disabled - errors show in dashboard
            except Exception as e:
                print(f"[ProjectMemory] Batch error: {e}")

            processed += 1
        except Exception as e:
            print(f"[Batch] Error processing item: {e}")

    print(f"[V3.2] Batch processed: {processed}/{len(errors)} errors")

    return jsonify({
        "status": "ok",
        "processed": processed,
        "total": len(errors)
    })


@errors_bp.route("/api/live-errors")
def api_live_errors():
    """API endpoint to get live errors with matched solutions.

    Query params:
        since: Filter to errors from the last N seconds (optional)
    """
    from core.db_solutions import find_solution_hybrid

    # Check for 'since' parameter (seconds)
    since_seconds = request.args.get('since', type=int)

    with log_lock:
        errors = list(error_log)

    # Filter by time if 'since' is provided
    if since_seconds:
        cutoff = datetime.now().timestamp() - since_seconds
        filtered_errors = []
        for error in errors:
            try:
                error_time = datetime.fromisoformat(error.get('timestamp', '')).timestamp()
                if error_time >= cutoff:
                    filtered_errors.append(error)
            except:
                # If timestamp parsing fails, include the error
                filtered_errors.append(error)
        errors = filtered_errors

    # Enrich each error with previous solution if available
    for error in errors:
        error_msg = error.get("message", "")
        if error_msg:
            try:
                from core.semantic_engine import get_engine
                from config import PERSONAL_DB_PATH
                engine = get_engine(PERSONAL_DB_PATH)
                previous = find_solution_hybrid(error_msg, engine)
            except:
                previous = find_solution_hybrid(error_msg)

            if previous:
                error["previous_solution"] = previous

    return jsonify({"errors": errors, "count": len(errors)})


@errors_bp.route("/api/clear-logs", methods=["POST"])
def api_clear_logs():
    """API endpoint to clear all live error logs."""
    with log_lock:
        error_log.clear()
    return jsonify({"status": "ok", "message": "Logs cleared"})


@errors_bp.route("/api/clear_errors", methods=["POST"])
def api_clear_errors():
    """Clear all stored browser errors and pending fixes.

    Used by fo_errors to clear test/noise errors automatically.
    Uses the unified error_store for consistency with fo_errors.
    """
    count = clear_errors()

    # Also clear pending fixes (they're linked to errors)
    try:
        from core.pending_fixes import clear_pending
        clear_pending()
    except Exception:
        pass

    return jsonify({"status": "cleared", "count": count})


@errors_bp.route("/api/page-load-success", methods=["POST"])
def api_page_load_success():
    """
    Called by extension when a page loads with no errors.
    Clears all errors older than 60 seconds.

    This implements "Clear on Success" - when a page loads cleanly,
    old errors from previous (fixed) sessions are automatically cleared.
    """
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")

    # Clear errors older than 60 seconds
    cutoff = datetime.now().timestamp() - 60
    cleared_count = 0

    with log_lock:
        to_keep = []
        for error in error_log:
            try:
                error_time = datetime.fromisoformat(error.get('timestamp', '')).timestamp()
                if error_time >= cutoff:
                    to_keep.append(error)
                else:
                    cleared_count += 1
            except:
                # If timestamp parsing fails, keep the error
                to_keep.append(error)

        error_log.clear()
        error_log.extend(to_keep)

    if cleared_count > 0:
        print(f"[PageLoadSuccess] Cleared {cleared_count} old errors (page: {url[:50]})")

    return jsonify({
        "status": "ok",
        "cleared": cleared_count,
        "remaining": len(error_log)
    })


