"""
FixOnce Component Mapping API
Maps file paths to human-readable component names.
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import json
import re
from pathlib import Path

components_bp = Blueprint('components', __name__)

# Data directory
DATA_DIR = Path(__file__).parent.parent.parent / "data"
COMPONENTS_FILE = DATA_DIR / "component_map.json"

# Default mappings (Hebrew)
DEFAULT_MAPPINGS = {
    # Common component names
    "header": "תפריט עליון",
    "footer": "תחתית העמוד",
    "navbar": "סרגל ניווט",
    "sidebar": "תפריט צד",
    "nav": "ניווט",

    # Pages
    "login": "דף כניסה",
    "signup": "דף הרשמה",
    "register": "דף הרשמה",
    "home": "דף הבית",
    "index": "עמוד ראשי",
    "dashboard": "דשבורד",
    "profile": "פרופיל",
    "settings": "הגדרות",
    "admin": "ניהול",

    # Components
    "button": "כפתור",
    "form": "טופס",
    "input": "שדה קלט",
    "modal": "חלון קופץ",
    "dialog": "דיאלוג",
    "card": "כרטיס",
    "list": "רשימה",
    "table": "טבלה",
    "menu": "תפריט",
    "dropdown": "תפריט נפתח",
    "tabs": "טאבים",
    "accordion": "אקורדיון",
    "carousel": "קרוסלה",
    "slider": "סליידר",
    "toast": "התראה",
    "notification": "התראה",
    "alert": "התרעה",
    "badge": "תג",
    "avatar": "אווטר",
    "icon": "אייקון",
    "image": "תמונה",
    "video": "וידאו",
    "audio": "אודיו",
    "chart": "גרף",
    "graph": "גרף",
    "map": "מפה",
    "calendar": "לוח שנה",
    "datepicker": "בורר תאריך",
    "timepicker": "בורר שעה",
    "search": "חיפוש",
    "filter": "סינון",
    "sort": "מיון",
    "pagination": "עימוד",
    "breadcrumb": "נתיב",
    "stepper": "צעדים",
    "progress": "התקדמות",
    "spinner": "טעינה",
    "loader": "טעינה",
    "skeleton": "שלד",
    "placeholder": "מציין מקום",
    "error": "שגיאה",
    "empty": "ריק",
    "not-found": "לא נמצא",
    "404": "דף לא נמצא",

    # Features
    "auth": "אימות",
    "checkout": "תשלום",
    "cart": "עגלה",
    "payment": "תשלום",
    "order": "הזמנה",
    "product": "מוצר",
    "item": "פריט",
    "user": "משתמש",
    "comment": "תגובה",
    "review": "ביקורת",
    "rating": "דירוג",
    "share": "שיתוף",
    "like": "לייק",
    "follow": "עקוב",
    "subscribe": "הרשמה",
    "upload": "העלאה",
    "download": "הורדה",
    "export": "ייצוא",
    "import": "ייבוא",

    # Python special files
    "__init__": "קובץ אתחול",
    "__main__": "נקודת כניסה",
    "setup": "הגדרות חבילה",
    "requirements": "תלויות",
    "conftest": "הגדרות בדיקות",
    "manage": "ניהול Django",
    "wsgi": "שרת WSGI",
    "asgi": "שרת ASGI",
    "settings": "הגדרות",
    "urls": "נתיבים",
    "views": "תצוגות",
    "models": "מודלים",
    "admin": "ממשק ניהול",
    "forms": "טפסים",
    "serializers": "סריאליזרים",

    # Config files
    "package": "הגדרות חבילה",
    "tsconfig": "הגדרות TypeScript",
    "webpack": "הגדרות Webpack",
    "vite": "הגדרות Vite",
    "babel": "הגדרות Babel",
    "eslint": "הגדרות Linting",
    "prettier": "הגדרות עיצוב קוד",
    "jest": "הגדרות בדיקות",
    "docker": "הגדרות Docker",
    "nginx": "הגדרות Nginx",
    "env": "משתני סביבה",
    "gitignore": "קבצים מוסתרים מ-Git",
    "readme": "תיעוד",
    "changelog": "יומן שינויים",
    "license": "רישיון",
    "makefile": "פקודות Build",

    # Technical
    "api": "API",
    "server": "שרת",
    "client": "לקוח",
    "config": "הגדרות",
    "utils": "עזרים",
    "helpers": "עזרים",
    "hooks": "הוקים",
    "context": "קונטקסט",
    "store": "מאגר",
    "reducer": "רדיוסר",
    "action": "פעולה",
    "middleware": "ביניים",
    "service": "שירות",
    "controller": "בקר",
    "model": "מודל",
    "schema": "סכמה",
    "migration": "מיגרציה",
    "seed": "נתוני בסיס",
    "test": "בדיקות",
    "spec": "בדיקות",
    "mock": "מוק",
    "fixture": "פיקסצ'ר",
    "style": "עיצוב",
    "theme": "ערכת נושא",
    "layout": "פריסה",
    "template": "תבנית",
    "component": "רכיב",
    "widget": "ווידג'ט",
    "plugin": "תוסף",
    "extension": "הרחבה",
}


def _load_mappings():
    """Load component mappings."""
    if COMPONENTS_FILE.exists():
        try:
            with open(COMPONENTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Merge with defaults
                merged = DEFAULT_MAPPINGS.copy()
                merged.update(data.get('mappings', {}))
                return merged, data.get('custom', {})
        except:
            pass
    return DEFAULT_MAPPINGS.copy(), {}


def _save_mappings(custom_mappings):
    """Save custom mappings."""
    DATA_DIR.mkdir(exist_ok=True)
    data = {
        "custom": custom_mappings,
        "updated_at": datetime.now().isoformat()
    }
    with open(COMPONENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_component_name(file_path: str) -> str:
    """
    Get human-readable name for a file path.

    Args:
        file_path: Full or partial file path

    Returns:
        Human-readable component name in Hebrew
    """
    if not file_path:
        return ""

    mappings, custom = _load_mappings()
    all_mappings = {**mappings, **custom}

    # Get file name without extension
    path = Path(file_path)
    file_name = path.stem.lower()

    # Remove common prefixes/suffixes
    clean_name = re.sub(r'^(use|get|set|fetch|create|update|delete|handle)', '', file_name)
    clean_name = re.sub(r'(component|container|page|view|screen|modal|dialog|form|list|item|card|button|input|wrapper|provider|context|hook|util|helper|service|api|controller|model|schema|style|test|spec)$', '', clean_name)
    clean_name = clean_name.strip('-_')

    # Check exact match first
    if file_name in all_mappings:
        return all_mappings[file_name]

    if clean_name in all_mappings:
        return all_mappings[clean_name]

    # Check partial matches
    for key, value in all_mappings.items():
        if key in file_name or key in clean_name:
            return value

    # Check parent directory
    if len(path.parts) > 1:
        parent = path.parts[-2].lower()
        if parent in all_mappings:
            return f"{all_mappings[parent]} - {file_name}"

    # Return cleaned file name
    return file_name.replace('-', ' ').replace('_', ' ').title()


@components_bp.route("/map", methods=["GET"])
def get_mappings():
    """Get all component mappings."""
    mappings, custom = _load_mappings()
    return jsonify({
        "defaults": DEFAULT_MAPPINGS,
        "custom": custom,
        "total": len(mappings) + len(custom)
    })


@components_bp.route("/map", methods=["POST"])
def add_mapping():
    """
    Add a custom component mapping.

    Body:
        file_pattern: Pattern to match (e.g., "header", "src/components/Nav")
        display_name: Human-readable name in Hebrew
    """
    try:
        data = request.get_json(silent=True) or {}
        pattern = data.get('file_pattern', '').lower().strip()
        display_name = data.get('display_name', '').strip()

        if not pattern or not display_name:
            return jsonify({"status": "error", "message": "file_pattern and display_name required"}), 400

        _, custom = _load_mappings()
        custom[pattern] = display_name
        _save_mappings(custom)

        return jsonify({
            "status": "ok",
            "mapping": {pattern: display_name}
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@components_bp.route("/map/<pattern>", methods=["DELETE"])
def delete_mapping(pattern):
    """Delete a custom mapping."""
    try:
        _, custom = _load_mappings()

        if pattern in custom:
            del custom[pattern]
            _save_mappings(custom)
            return jsonify({"status": "ok", "deleted": pattern})
        else:
            return jsonify({"status": "error", "message": "Mapping not found"}), 404

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@components_bp.route("/resolve", methods=["POST"])
def resolve_name():
    """
    Resolve a file path to component name.

    Body:
        file_path: The file path to resolve
    """
    try:
        data = request.get_json(silent=True) or {}
        file_path = data.get('file_path', '')

        name = get_component_name(file_path)

        return jsonify({
            "file_path": file_path,
            "component_name": name
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@components_bp.route("/suggest", methods=["POST"])
def suggest_mappings():
    """
    Get AI-suggested mappings for unmapped files.

    Body:
        files: List of file paths to get suggestions for
    """
    try:
        data = request.get_json(silent=True) or {}
        files = data.get('files', [])

        suggestions = []
        for file_path in files:
            current_name = get_component_name(file_path)
            file_name = Path(file_path).stem

            # Only suggest if we don't have a good mapping
            if current_name == file_name or current_name == file_name.replace('-', ' ').replace('_', ' ').title():
                suggestions.append({
                    "file": file_path,
                    "current": current_name,
                    "suggested": None  # AI would fill this
                })

        return jsonify({
            "suggestions": suggestions,
            "count": len(suggestions)
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
