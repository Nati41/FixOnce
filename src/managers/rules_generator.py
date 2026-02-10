"""
Rules Generator for FixOnce
Syncs memory data to editor rules files (.cursorrules, .windsurfrules)
Makes AI memory "live" for editors that don't support MCP

Key Features:
- Safe write: Preserves user's custom rules using FIXONCE tags
- Smart triggers: Only syncs on meaningful changes
- Fresh content: Timestamp shows AI this is current data
"""

import os
import json
import threading
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path

# Import config for paths
try:
    from config import DATA_DIR, MEMORY_FILE
except ImportError:
    DATA_DIR = Path(__file__).parent.parent.parent / "data"
    MEMORY_FILE = DATA_DIR / "project_memory.json"

# Thread lock for file operations
_lock = threading.Lock()

# Markers for safe write
FIXONCE_START = "<!-- FIXONCE-START -->"
FIXONCE_END = "<!-- FIXONCE-END -->"


def get_memory_data() -> Dict:
    """Load memory data from project_memory.json"""
    try:
        if MEMORY_FILE.exists():
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[RulesGenerator] Error loading memory: {e}")
    return {}


def generate_fixonce_block(memory: Dict) -> str:
    """
    Generate the FixOnce rules block content.
    This is what gets inserted between FIXONCE-START and FIXONCE-END tags.
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Get data
    project_info = memory.get('project_info', {})
    project_name = project_info.get('name', 'Unknown Project')
    stack = project_info.get('stack', '')

    avoid_patterns = memory.get('avoid_patterns', [])
    decisions = memory.get('decisions', [])
    handover = memory.get('handover', {})
    solutions = memory.get('solutions_history', [])

    lines = []

    # === HEADER ===
    lines.append(FIXONCE_START)
    lines.append("")
    lines.append("# FixOnce Project Memory")
    lines.append("")
    lines.append("Command: `/fixonce` - loads context (no file searches)")
    lines.append("")
    lines.append(f"## Project: {project_name}")
    lines.append(f"## Stack: {stack}")
    lines.append(f"## Updated: {now}")
    lines.append("")

    # === HANDOVER (Current Context) ===
    if handover and handover.get('summary'):
        lines.append("## 📍 Where We Left Off")
        lines.append("")
        summary = handover.get('summary', '')[:800]  # Limit size
        lines.append(summary)
        created = handover.get('created_at', '')
        if created:
            lines.append(f"\n_Last session: {created}_")
        lines.append("")

    # === CRITICAL: NEVER REPEAT ===
    if avoid_patterns:
        lines.append("## 🚫 Critical: Never Repeat")
        lines.append("")
        lines.append("These caused problems before. **Do NOT use these approaches:**")
        lines.append("")
        for pattern in avoid_patterns[-7:]:  # Last 7
            what = pattern.get('pattern', pattern.get('what', ''))
            why = pattern.get('reason', pattern.get('why', ''))
            if what:
                lines.append(f"- ❌ **{what}**")
                if why:
                    lines.append(f"  - Why: {why}")
        lines.append("")

    # === HOUSE RULES (Decisions) ===
    if decisions:
        lines.append("## ✅ House Rules")
        lines.append("")
        lines.append("Follow these decisions made for this project:")
        lines.append("")
        for decision in decisions[-7:]:  # Last 7
            what = decision.get('decision', '')
            reason = decision.get('reason', '')
            if what:
                lines.append(f"- ✓ **{what}**")
                if reason:
                    lines.append(f"  - Reason: {reason}")
        lines.append("")

    # === PROVEN SOLUTIONS ===
    worked_solutions = [s for s in solutions if s.get('status') == 'worked']
    if worked_solutions:
        lines.append("## 💡 Proven Solutions")
        lines.append("")
        lines.append("These fixes worked before - reuse them:")
        lines.append("")
        for sol in worked_solutions[-5:]:  # Last 5
            problem = sol.get('problem', sol.get('title', ''))[:100]
            solution = sol.get('solution', '')[:200]
            keywords = sol.get('keywords', [])
            if problem and solution:
                kw_str = f" `{', '.join(keywords[:3])}`" if keywords else ""
                lines.append(f"- **{problem}**{kw_str}")
                lines.append(f"  - Fix: {solution}")
        lines.append("")

    # === COMMAND ===
    lines.append("---")
    lines.append("")
    lines.append("## WHEN USER TYPES: /fixonce")
    lines.append("")
    lines.append("Respond EXACTLY like this:")
    lines.append("")
    lines.append("```")
    lines.append(f"היי! מחובר ל-{project_name}.")
    lines.append("")
    if handover and handover.get('summary'):
        # Extract short summary
        summary_lines = handover.get('summary', '').strip().split('\n')
        short_summary = summary_lines[0][:80] if summary_lines else 'אין סיכום'
        lines.append(f"🎯 איפה עצרנו: {short_summary}")
    else:
        lines.append("🎯 הקשר: פרויקט חדש")
    lines.append("")
    lines.append("מה עושים?")
    lines.append("```")
    lines.append("")
    lines.append("NO searches. NO commands. Just this response.")
    lines.append("")
    lines.append(FIXONCE_END)

    return "\n".join(lines)


def safe_write_rules(file_path: str, fixonce_content: str) -> Dict:
    """
    Safely write FixOnce content to rules file.
    Preserves any user content outside the FIXONCE tags.

    Args:
        file_path: Path to .cursorrules or .windsurfrules
        fixonce_content: The generated FixOnce block

    Returns:
        Result dict with status
    """
    try:
        existing_content = ""

        # Read existing file if it exists
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_content = f.read()

        # Check if FIXONCE tags exist
        has_tags = FIXONCE_START in existing_content and FIXONCE_END in existing_content

        if has_tags:
            # Replace content between tags
            start_idx = existing_content.find(FIXONCE_START)
            end_idx = existing_content.find(FIXONCE_END) + len(FIXONCE_END)

            new_content = (
                existing_content[:start_idx] +
                fixonce_content +
                existing_content[end_idx:]
            )
        else:
            # No tags - append at the end (or create new file)
            if existing_content.strip():
                # File has content - add separator and append
                new_content = existing_content.rstrip() + "\n\n" + fixonce_content
            else:
                # Empty or new file
                new_content = fixonce_content

        # Write the file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return {
            "success": True,
            "file": file_path,
            "mode": "updated" if has_tags else "appended",
            "preserved_user_content": has_tags
        }

    except Exception as e:
        return {
            "success": False,
            "file": file_path,
            "error": str(e)
        }


def sync_rules_to_project(project_path: str = None) -> Dict:
    """
    Sync FixOnce memory to project's rules files.

    Args:
        project_path: Path to project root. If None, uses memory's root_path.

    Returns:
        Result dict with sync status
    """
    with _lock:
        memory = get_memory_data()

        if not memory:
            return {"success": False, "error": "No memory data"}

        # Determine project path
        if not project_path:
            project_path = memory.get('project_info', {}).get('root_path', '')

        if not project_path or not os.path.isdir(project_path):
            return {"success": False, "error": f"Invalid project path: {project_path}"}

        # Generate content
        fixonce_content = generate_fixonce_block(memory)

        results = {}

        # Sync to .cursorrules
        cursor_path = os.path.join(project_path, '.cursorrules')
        results['cursor'] = safe_write_rules(cursor_path, fixonce_content)

        # Sync to .windsurfrules
        windsurf_path = os.path.join(project_path, '.windsurfrules')
        results['windsurf'] = safe_write_rules(windsurf_path, fixonce_content)

        success_count = sum(1 for r in results.values() if r.get('success'))

        return {
            "success": success_count > 0,
            "synced_at": datetime.now().isoformat(),
            "project_path": project_path,
            "results": results
        }


def trigger_sync():
    """
    Trigger a sync in background thread.
    Call this after handover creation or avoid_pattern addition.
    """
    def _do_sync():
        result = sync_rules_to_project()
        if result.get('success'):
            print(f"[RulesGenerator] Synced rules to {result.get('project_path')}")
        else:
            print(f"[RulesGenerator] Sync failed: {result.get('error')}")

    threading.Thread(target=_do_sync, daemon=True).start()


# ============ Integration Hooks ============
# Call these from project_memory_manager.py

def on_handover_created():
    """Hook: Call when handover is created"""
    trigger_sync()


def on_avoid_pattern_added():
    """Hook: Call when avoid pattern is added"""
    trigger_sync()


def on_decision_logged():
    """Hook: Call when decision is logged"""
    trigger_sync()


def on_solution_saved():
    """Hook: Call when solution is saved"""
    trigger_sync()


# ============ Manual Sync (for Dashboard) ============

def manual_sync(project_path: str = None) -> Dict:
    """
    Manual sync triggered from dashboard.
    Returns detailed result for UI feedback.
    """
    return sync_rules_to_project(project_path)


def get_sync_status() -> Dict:
    """Get current sync status for dashboard"""
    memory = get_memory_data()

    if not memory:
        return {"status": "no_memory", "message": "No memory data found"}

    project_path = memory.get('project_info', {}).get('root_path', '')

    if not project_path:
        return {"status": "no_project", "message": "No project path set"}

    cursor_exists = os.path.exists(os.path.join(project_path, '.cursorrules'))
    windsurf_exists = os.path.exists(os.path.join(project_path, '.windsurfrules'))

    return {
        "status": "ready",
        "project_path": project_path,
        "files": {
            ".cursorrules": "exists" if cursor_exists else "missing",
            ".windsurfrules": "exists" if windsurf_exists else "missing"
        },
        "memory_stats": {
            "avoid_patterns": len(memory.get('avoid_patterns', [])),
            "decisions": len(memory.get('decisions', [])),
            "solutions": len(memory.get('solutions_history', []))
        }
    }
