"""
FixOnce Memory Routes
Project memory API endpoints for AI context persistence.

Phase 0: Supports X-Project-Root header for explicit project context.
Dashboard requests can use X-Dashboard: true to fallback to active project.
"""

from flask import jsonify, request, send_file
from datetime import datetime
import json
import io
import re

from . import memory_bp, get_project_from_request
from core.system_mode import get_system_mode, MODE_OFF, MODE_PASSIVE


@memory_bp.route("", methods=["GET"])
def api_get_memory():
    """Get full project memory JSON."""
    try:
        from managers.project_memory_manager import get_project_context
        return jsonify(get_project_context())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/summary", methods=["GET"])
def api_get_memory_summary():
    """Get markdown summary of project memory (for AI consumption)."""
    try:
        from managers.project_memory_manager import get_context_summary
        return get_context_summary(), 200, {'Content-Type': 'text/markdown'}
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Decisions API ============

@memory_bp.route("/decisions", methods=["GET"])
def api_get_decisions():
    """Get all logged decisions."""
    try:
        from managers.project_memory_manager import get_decisions
        decisions = get_decisions()
        return jsonify({"count": len(decisions), "decisions": decisions})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/decisions", methods=["POST"])
def api_add_decision():
    """Add a new decision."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    decision = data.get("decision", "")
    reason = data.get("reason", "")

    if not decision or not reason:
        return jsonify({"status": "error", "message": "Decision and reason required"}), 400

    try:
        from managers.project_memory_manager import log_decision
        result = log_decision(decision, reason, data.get("context", ""))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Avoid Patterns API ============

@memory_bp.route("/avoid", methods=["GET"])
def api_get_avoid():
    """Get all avoid patterns."""
    try:
        from managers.project_memory_manager import get_avoid_list
        avoid = get_avoid_list()
        return jsonify({"count": len(avoid), "avoid": avoid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/avoid", methods=["POST"])
def api_add_avoid():
    """Add a new avoid pattern."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    what = data.get("what", "")
    reason = data.get("reason", "")

    if not what or not reason:
        return jsonify({"status": "error", "message": "What and reason required"}), 400

    try:
        from managers.project_memory_manager import log_avoid
        result = log_avoid(what, reason)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Project Rules API ============

@memory_bp.route("/rules", methods=["GET"])
def api_get_project_rules():
    """Get all project rules."""
    try:
        from managers.project_memory_manager import get_all_project_rules
        rules = get_all_project_rules()
        return jsonify({"rules": rules, "count": len(rules)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/rules", methods=["POST"])
def api_add_project_rule():
    """Add a custom project rule."""
    data = request.get_json(silent=True)
    if not data or not data.get("text"):
        return jsonify({"status": "error", "message": "Rule text required"}), 400

    try:
        from managers.project_memory_manager import add_project_rule
        result = add_project_rule(data["text"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/rules/<rule_id>", methods=["PUT"])
def api_toggle_project_rule(rule_id):
    """Enable or disable a project rule."""
    data = request.get_json(silent=True)
    if data is None or "enabled" not in data:
        return jsonify({"status": "error", "message": "enabled field required"}), 400

    try:
        from managers.project_memory_manager import toggle_project_rule
        result = toggle_project_rule(rule_id, data["enabled"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/rules/<rule_id>", methods=["DELETE"])
def api_delete_project_rule(rule_id):
    """Delete a custom project rule."""
    try:
        from managers.project_memory_manager import delete_project_rule
        result = delete_project_rule(rule_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ AI Queue API ============

@memory_bp.route("/ai-queue", methods=["GET"])
def api_get_ai_queue():
    """Get pending commands for AI."""
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"commands": []})

        memory = load_project_memory(project_id)
        ai_queue = memory.get("ai_queue", []) if memory else []
        pending = [cmd for cmd in ai_queue if cmd.get("status") == "pending"]

        return jsonify({"commands": pending})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/queue-for-ai", methods=["POST"])
def api_queue_for_ai():
    """Add a command to the AI queue."""
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory, save_project_memory
        import uuid

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"status": "error", "message": "No active project"}), 400

        data = request.get_json() or {}
        message = data.get("message", "").strip()
        cmd_type = data.get("type", "refresh_rules")

        if not message and cmd_type != "refresh_rules":
            return jsonify({"status": "error", "message": "Message required"}), 400

        memory = load_project_memory(project_id) or {}
        ai_queue = memory.get("ai_queue", [])

        # Remove existing pending commands of same type (prevent duplicates)
        ai_queue = [cmd for cmd in ai_queue
                    if not (cmd.get("type") == cmd_type and cmd.get("status") == "pending")]

        # Create command
        command = {
            "id": str(uuid.uuid4())[:8],
            "type": cmd_type,
            "message": message or "Refresh rules - user updated rules in dashboard",
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "source": data.get("source", "dashboard")
        }

        ai_queue.append(command)
        memory["ai_queue"] = ai_queue
        save_project_memory(project_id, memory)

        return jsonify({"status": "ok", "command_id": command["id"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/command-status/<command_id>", methods=["GET"])
def api_get_command_status(command_id):
    """Get the status of a specific command."""
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"status": "unknown"}), 404

        memory = load_project_memory(project_id) or {}
        ai_queue = memory.get("ai_queue", [])

        for cmd in ai_queue:
            if cmd.get("id") == command_id:
                return jsonify({
                    "status": cmd.get("status", "pending"),
                    "executed_at": cmd.get("executed_at")
                })

        return jsonify({"status": "not_found"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Debug Sessions API ============

@memory_bp.route("/debug-sessions", methods=["GET"])
def api_get_debug_sessions():
    """Get all debug sessions."""
    try:
        from managers.multi_project_manager import get_active_project, load_project_memory
        active = get_active_project()
        if not active:
            return jsonify({"debug_sessions": []})
        # get_active_project returns a dict with active_id
        project_id = active.get('active_id') if isinstance(active, dict) else active
        if not project_id:
            return jsonify({"debug_sessions": []})
        memory = load_project_memory(project_id)
        sessions = memory.get('debug_sessions', [])
        return jsonify({"count": len(sessions), "debug_sessions": sessions})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Handover API ============

@memory_bp.route("/handover", methods=["GET"])
def api_get_handover():
    """Get the last handover summary."""
    try:
        from managers.project_memory_manager import get_handover
        handover = get_handover()
        return jsonify({"handover": handover or {}})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/handover", methods=["POST"])
def api_save_handover():
    """Save a handover summary."""
    data = request.get_json(silent=True)
    if not data or not data.get("summary"):
        return jsonify({"status": "error", "message": "Summary required"}), 400

    try:
        from managers.project_memory_manager import save_handover
        result = save_handover(data["summary"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/handover", methods=["DELETE"])
def api_clear_handover():
    """Clear the handover."""
    try:
        from managers.project_memory_manager import get_project_context, save_memory
        memory = get_project_context()
        memory['handover'] = {}
        save_memory(memory)
        return jsonify({"status": "ok", "message": "Handover cleared"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Export/Import API ============

@memory_bp.route("/export", methods=["GET"])
def api_export_memory():
    """Export full memory as JSON file."""
    try:
        from managers.project_memory_manager import get_project_context
        memory = get_project_context()

        output = io.BytesIO()
        output.write(json.dumps(memory, ensure_ascii=False, indent=2).encode('utf-8'))
        output.seek(0)

        return send_file(
            output,
            mimetype='application/json',
            as_attachment=True,
            download_name=f"fixonce_memory_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/import", methods=["POST"])
def api_import_memory():
    """Import memory from JSON."""
    try:
        from managers.project_memory_manager import save_memory, _create_default_memory

        data = request.get_json(silent=True)
        if not data:
            return jsonify({"status": "error", "message": "No JSON body"}), 400

        default = _create_default_memory()
        required_keys = ["project_info", "active_issues", "solutions_history"]

        for key in required_keys:
            if key not in data:
                return jsonify({"status": "error", "message": f"Missing required key: {key}"}), 400

        for key in default:
            if key not in data:
                data[key] = default[key]

        save_memory(data)
        return jsonify({"status": "ok", "message": "Memory imported successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Live Record API ============

@memory_bp.route("/live-record", methods=["GET"])
def api_get_live_record():
    """Get the full Live Record for warm start."""
    try:
        from managers.project_memory_manager import get_live_record
        return jsonify(get_live_record())
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@memory_bp.route("/live-record/<section>", methods=["PUT"])
def api_update_live_record(section):
    """
    Update a Live Record section.

    Sections: gps, architecture, lessons, intent
    Mode: APPEND for lessons (accumulates), REPLACE for others (overwrites)
    """
    valid_sections = {'gps', 'architecture', 'lessons', 'intent'}
    if section not in valid_sections:
        return jsonify({
            "status": "error",
            "message": f"Invalid section. Must be one of: {', '.join(valid_sections)}"
        }), 400

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body"}), 400

    try:
        from managers.project_memory_manager import update_live_record
        result = update_live_record(section, data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Active Project API ============

@memory_bp.route("/active-project", methods=["GET"])
def api_get_active_project():
    """Get the active project info including connected server for hooks.

    Returns:
        - active_id: The current project ID
        - working_dir: Project root directory
        - connected_server: Server info with port (if active)
        - display_name: Human readable project name
    """
    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory
        from pathlib import Path
        import json

        # Load active project info
        active_project_file = Path(__file__).parent.parent.parent / 'data' / 'active_project.json'
        if active_project_file.exists():
            with open(active_project_file, 'r', encoding='utf-8') as f:
                active_info = json.load(f)
        else:
            active_info = {}

        project_id = active_info.get('active_id') or get_active_project_id()

        if not project_id:
            return jsonify({
                "active_id": None,
                "working_dir": None,
                "connected_server": None,
                "display_name": None
            })

        # Get full project memory for connected_server info
        memory = load_project_memory(project_id)

        result = {
            "active_id": project_id,
            "working_dir": active_info.get('working_dir') or (
                memory.get('project_info', {}).get('working_dir') if memory else None
            ),
            "display_name": active_info.get('display_name') or (
                memory.get('project_info', {}).get('name') if memory else None
            ),
            "connected_server": memory.get('connected_server') if memory else None
        }

        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ============ Search API ============

@memory_bp.route("/search", methods=["GET"])
def api_search_solutions():
    """Search insights and past solutions.

    Query params:
        q: Search query (required)
        limit: Max results (default 5)
    """
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 5))

    if not query:
        return jsonify({"status": "error", "message": "Query required"}), 400

    try:
        from managers.multi_project_manager import get_active_project_id, load_project_memory

        project_id = get_active_project_id()
        if not project_id:
            return jsonify({"results": []})

        memory = load_project_memory(project_id)
        if not memory:
            return jsonify({"results": []})

        # Get insights
        lessons = memory.get('live_record', {}).get('lessons', {})
        insights = lessons.get('insights', [])

        # Smart keyword matching with noise filtering
        query_lower = query.lower()
        query_words = set(query_lower.split())

        # Filter out common noise words from query
        NOISE_WORDS = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                       'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                       'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                       'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
                       'it', 'its', 'this', 'that', 'these', 'those', 'more', 'words', 'noise'}
        significant_query_words = query_words - NOISE_WORDS

        results = []
        for insight in insights:
            # Handle both string and dict formats
            if isinstance(insight, str):
                text = insight
            else:
                text = insight.get('text', insight.get('insight', ''))

            text_lower = text.lower()
            text_words = set(text_lower.split())
            significant_text_words = text_words - NOISE_WORDS

            # Calculate similarity based on significant word overlap
            common_words = significant_query_words & significant_text_words
            if len(common_words) == 0:
                # Fallback: check if ANY query word appears in text
                common_words = query_words & text_words
                if len(common_words) == 0:
                    continue

            # Use significant words for similarity if available
            if significant_query_words:
                similarity = int((len(common_words) / max(len(significant_query_words), 1)) * 100)
            else:
                similarity = int((len(common_words) / max(len(query_words), 1)) * 100)

            # Bonus for exact substring match
            if query_lower in text_lower:
                similarity = min(100, similarity + 30)

            # Bonus for unique tokens (long words are likely meaningful)
            for word in common_words:
                if len(word) > 15:  # Likely a unique token/ID
                    similarity = min(100, similarity + 40)
                    break

            if similarity >= 20:  # Lower threshold - noise filtering makes it more precise
                results.append({
                    "text": text,
                    "similarity": similarity,
                    "type": "insight"
                })

        # Sort by similarity descending
        results.sort(key=lambda x: x['similarity'], reverse=True)

        return jsonify({"results": results[:limit]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _to_text(item) -> str:
    """Normalize mixed insight/handover structures into plain text."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "insight", "summary", "message", "content"):
            if item.get(key):
                return str(item.get(key))
    return ""


def _is_test_artifact(text: str) -> bool:
    """Detect synthetic brutal-test artifacts to keep UI clean."""
    if not text:
        return False
    return bool(
        re.search(
            r"(BRUTAL_|brutal_|CACHE_BUST_TOKEN_|avoid-pattern-|Brutal spam|Brutal dedup|Brutal link error|critical handoff \d+|verify regeneration)",
            text,
            re.IGNORECASE,
        )
    )


def _short_text(text: str, limit: int = 140) -> str:
    """Normalize whitespace and clamp long text for compact UI labels."""
    if not text:
        return ""
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _extract_signals(text: str) -> dict:
    """
    Parse free-text summaries into structured signals.
    Emoji is a boost signal, not a hard dependency.
    """
    lines = [
        ln.strip("-• \t")
        for ln in re.split(r"[\n\r]+", text or "")
        if ln.strip() and not _is_test_artifact(ln)
    ]

    out = {
        "solved": [],
        "decisions": [],
        "insights": [],
        "risks": [],
        "changes": []
    }

    if not lines:
        return out

    decision_re = re.compile(r"(החלט|decision|decided|נבחר|בחרנו)", re.IGNORECASE)
    solved_re = re.compile(r"(תוקנ|נפתר|fixed|resolved|הושלם|✅|closed)", re.IGNORECASE)
    insight_re = re.compile(r"(תובנה|learned|insight|lesson|💡)", re.IGNORECASE)
    risk_re = re.compile(r"(סיכון|רגיש|risk|warning|avoid|להימנע|⚠️|⚠)", re.IGNORECASE)
    change_re = re.compile(r"(שינוי|refactor|migration|עדכון מבני|🔄)", re.IGNORECASE)

    for ln in lines:
        # Boost from emoji markers, but also support plain text
        has_decision = "🔒" in ln or bool(decision_re.search(ln))
        has_solved = "🐛" in ln or "✅" in ln or bool(solved_re.search(ln))
        has_insight = "💡" in ln or bool(insight_re.search(ln))
        has_risk = "⚠" in ln or bool(risk_re.search(ln))
        has_change = "🔄" in ln or bool(change_re.search(ln))

        if has_decision:
            out["decisions"].append(ln)
        if has_solved:
            out["solved"].append(ln)
        if has_insight:
            out["insights"].append(ln)
        if has_risk:
            out["risks"].append(ln)
        if has_change:
            out["changes"].append(ln)

    # De-duplicate while preserving order
    for key in out:
        seen = set()
        uniq = []
        for item in out[key]:
            if item not in seen:
                uniq.append(item)
                seen.add(item)
        out[key] = uniq
    return out


def _infer_stage(memory: dict) -> str:
    intent = memory.get("live_record", {}).get("intent", {}) or {}
    blockers = intent.get("blockers") or []
    if blockers:
        return "חסום"
    if intent.get("current_goal"):
        if intent.get("next_step"):
            return "בביצוע"
        return "מוגדר"
    if memory.get("active_issues"):
        return "דורש ייצוב"
    return "אתחול"


def _extract_semantic_identity(project_id: str) -> dict:
    """
    Use semantic search to extract project identity from insights.

    Returns:
        {
            "signature": ["key theme 1", "key theme 2", ...],
            "top_learnings": ["most important insight 1", ...],
            "semantic_enabled": True/False
        }
    """
    result = {
        "signature": [],
        "top_learnings": [],
        "semantic_enabled": False,
        "document_count": 0
    }

    try:
        from core.project_semantic import search_project, get_project_index_stats

        # Check if we have indexed documents
        stats = get_project_index_stats(project_id)
        doc_count = stats.get("document_count", 0)
        result["document_count"] = doc_count

        if doc_count == 0:
            return result

        result["semantic_enabled"] = True

        # Search for identity-related concepts
        identity_queries = [
            "what this project does main purpose",
            "important decision architecture choice",
            "key learning insight discovered",
            "problem solved fixed bug",
            "avoid mistake pattern"
        ]

        all_results = []
        seen_texts = set()

        for query in identity_queries:
            try:
                results = search_project(project_id, query, k=3, min_score=0.3)
                for r in results:
                    if r.text not in seen_texts:
                        all_results.append({
                            "text": r.text,
                            "score": r.score,
                            "type": r.metadata.get("doc_type", "insight"),
                            "query": query
                        })
                        seen_texts.add(r.text)
            except:
                continue

        # Sort by score and extract top learnings
        all_results.sort(key=lambda x: x["score"], reverse=True)
        result["top_learnings"] = [r["text"] for r in all_results[:5]]

        # Extract signature themes (key concepts from top results)
        signature_words = set()
        tech_keywords = {
            # Languages/Frameworks
            "python", "javascript", "typescript", "react", "vue", "angular",
            "node", "flask", "django", "fastapi", "express", "nextjs",
            # Concepts
            "api", "auth", "authentication", "database", "cache", "redis",
            "frontend", "backend", "fullstack", "microservice", "serverless",
            "test", "testing", "deploy", "ci", "docker", "kubernetes",
            "security", "performance", "async", "websocket", "graphql", "rest",
            "mcp", "semantic", "embedding", "vector", "index", "search",
            "memory", "session", "state", "context", "ai", "llm", "claude"
        }

        for r in all_results[:10]:
            # Extract meaningful words
            text_lower = r["text"].lower()
            words = text_lower.replace("-", " ").replace("_", " ").split()
            for word in words:
                clean_word = ''.join(c for c in word if c.isalnum())
                if len(clean_word) > 2 and clean_word in tech_keywords:
                    signature_words.add(clean_word)

        # Also extract doc types as signature elements
        doc_types = set(r["type"] for r in all_results[:5] if r.get("type"))
        for dt in doc_types:
            if dt not in ["insight"]:  # Skip generic ones
                signature_words.add(dt)

        result["signature"] = list(signature_words)[:8]

    except ImportError:
        # Semantic search not available
        pass
    except Exception as e:
        result["error"] = str(e)

    return result


