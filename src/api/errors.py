"""
FixOnce Error Routes
Error logging and live error retrieval endpoints.
"""

from flask import jsonify, request
from datetime import datetime

from . import errors_bp
from core.notifications import send_desktop_notification
from core.error_store import get_error_log, get_log_lock, add_error, get_errors, clear_errors

# Get references to shared state
error_log = get_error_log()
log_lock = get_log_lock()


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

    with log_lock:
        error_log.append(entry)

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
    except Exception as e:
        print(f"[V3.1] Match error: {e}")

    with log_lock:
        error_log.append(entry)

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

        # Send desktop notification for new errors
        if memory_result['status'] == 'new':
            is_critical = entry['severity'] == 'critical'
            short_msg = entry['message'][:100] + '...' if len(entry['message']) > 100 else entry['message']
            send_desktop_notification(
                title=f"🔴 FixOnce: {entry['type']}" if is_critical else f"⚠️ FixOnce: {entry['type']}",
                message=short_msg,
                sound=is_critical
            )
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

            with log_lock:
                error_log.append(entry)

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

                if memory_result.get('status') == 'new':
                    is_critical = entry['severity'] == 'critical'
                    short_msg = entry['message'][:100] + '...' if len(entry['message']) > 100 else entry['message']
                    send_desktop_notification(
                        title=f"🔴 FixOnce: {entry['type']}" if is_critical else f"⚠️ FixOnce: {entry['type']}",
                        message=short_msg,
                        sound=is_critical
                    )
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
    """API endpoint to get live errors with matched solutions."""
    from core.db_solutions import find_solution_hybrid

    with log_lock:
        errors = list(error_log)

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


@errors_bp.route("/api/feedback", methods=["POST"])
def api_feedback():
    """V3.1: User feedback on solution matches."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error"}), 400

    solution_id = data.get("solution_id")
    feedback = data.get("feedback")

    if not solution_id or feedback not in ["verified", "incorrect"]:
        return jsonify({"status": "error", "message": "Invalid feedback"}), 400

    try:
        from core.semantic_engine import get_engine
        from config import PERSONAL_DB_PATH

        engine = get_engine(PERSONAL_DB_PATH)
        if feedback == "verified":
            engine.increment_success_count(solution_id)
        return jsonify({"status": "ok", "message": f"Feedback recorded: {feedback}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
