"""
FixOnce Auto Discovery
Automatically detect components from codebase structure.
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime


# Component detection patterns
COMPONENT_PATTERNS = {
    # Python patterns
    "api_route": {
        "pattern": r"@\w+_bp\.route|@app\.route|@mcp\.tool",
        "type": "API/Tool",
        "extensions": [".py"]
    },
    "flask_blueprint": {
        "pattern": r"Blueprint\s*\(",
        "type": "API Module",
        "extensions": [".py"]
    },
    "class_definition": {
        "pattern": r"^class\s+(\w+)(?:\([^)]*\))?:",
        "type": "Class",
        "extensions": [".py"]
    },
    # JavaScript patterns
    "react_component": {
        "pattern": r"function\s+([A-Z]\w+)|const\s+([A-Z]\w+)\s*=",
        "type": "UI Component",
        "extensions": [".js", ".jsx", ".tsx"]
    },
    "chrome_extension": {
        "pattern": r"chrome\.(runtime|tabs|storage|action)",
        "type": "Extension",
        "extensions": [".js"]
    },
}

# Folders that indicate major components (skip generic ones)
COMPONENT_FOLDERS = {
    # "api": "API Layer",  # Too generic
    # "core": "Core Logic",  # Too generic
    # "managers": "Business Logic",  # Too generic
    # "mcp_server": "MCP Server",  # Already in default components
    # "extension": "Chrome Extension",  # Already in default components
    # "data": "Data/Dashboard",  # Already in default components
}

# Keywords to skip in component names (too generic or internal)
SKIP_KEYWORDS = [
    "api", "layer", "logic", "util", "helper", "base", "abstract",
    "config", "init", "test", "mock", "fixture"
]

# Files that are likely standalone components
COMPONENT_FILES = {
    "server.py": ("Flask Server", "Main Flask application"),
    "mcp_memory_server_v2.py": ("MCP Server", "FastMCP tools"),
    "background.js": ("Extension Background", "Chrome extension service worker"),
    "element-picker.js": ("Element Picker", "Browser element selection"),
    "dashboard_vnext.html": ("Dashboard", "Main dashboard UI"),
    "semantic_engine.py": ("Semantic Engine", "Embedding-based search"),
    "boundary_detector.py": ("Boundary Detector", "Auto project switching"),
    "safe_file.py": ("Safe File", "Atomic writes with backup"),
    "auto_discovery.py": ("Auto Discovery", "Component detection"),
}


def scan_directory(root_path: str, max_depth: int = 3) -> Dict:
    """
    Scan a directory for components.

    Returns:
        {
            "components": [...],
            "summary": {...},
            "scan_time": "..."
        }
    """
    root = Path(root_path)
    if not root.exists():
        return {"error": f"Path not found: {root_path}"}

    discovered = []
    seen_names = set()

    # Scan for folder-based components
    for folder_name, component_type in COMPONENT_FOLDERS.items():
        folder_path = root / "src" / folder_name
        if not folder_path.exists():
            folder_path = root / folder_name

        if folder_path.exists() and folder_path.is_dir():
            # Count files in folder
            py_files = list(folder_path.glob("*.py"))
            js_files = list(folder_path.glob("*.js"))
            file_count = len(py_files) + len(js_files)

            if file_count > 0:
                comp_name = component_type
                if comp_name not in seen_names:
                    discovered.append({
                        "name": comp_name,
                        "source": str(folder_path.relative_to(root)),
                        "type": "folder",
                        "file_count": file_count,
                        "confidence": "high"
                    })
                    seen_names.add(comp_name)

    # Scan for file-based components
    for file_pattern, (comp_name, desc) in COMPONENT_FILES.items():
        matches = list(root.rglob(file_pattern))
        for match in matches[:1]:  # Take first match only
            if comp_name not in seen_names:
                discovered.append({
                    "name": comp_name,
                    "source": str(match.relative_to(root)),
                    "type": "file",
                    "description": desc,
                    "confidence": "high"
                })
                seen_names.add(comp_name)

    # Scan for pattern-based components in key files
    key_dirs = ["src/api", "src/core", "src/managers", "extension"]
    for key_dir in key_dirs:
        dir_path = root / key_dir
        if not dir_path.exists():
            continue

        for py_file in dir_path.glob("*.py"):
            try:
                content = py_file.read_text(errors='ignore')

                # Check for blueprints
                if "Blueprint(" in content:
                    bp_match = re.search(r'(\w+)_bp\s*=\s*Blueprint', content)
                    if bp_match:
                        bp_raw = bp_match.group(1).lower()
                        # Skip generic blueprint names
                        if bp_raw in SKIP_KEYWORDS or bp_raw in ['main', 'app', 'root']:
                            continue
                        bp_name = bp_match.group(1).title() + " API"
                        if bp_name not in seen_names:
                            discovered.append({
                                "name": bp_name,
                                "source": str(py_file.relative_to(root)),
                                "type": "blueprint",
                                "confidence": "medium"
                            })
                            seen_names.add(bp_name)

                # Check for major classes
                classes = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)
                for cls in classes:
                    # Skip private/internal classes
                    if cls.startswith('_') or cls in ['Config', 'Meta']:
                        continue
                    # Skip generic-sounding class names
                    if any(kw in cls.lower() for kw in SKIP_KEYWORDS):
                        continue
                    # Skip if already covered by a file-based component
                    cls_normalized = cls.lower().replace('_', '')
                    if any(cls_normalized in name.lower().replace(' ', '') for name in seen_names):
                        continue
                    # Only include significant-sounding classes
                    if any(kw in cls for kw in ['Manager', 'Engine', 'Provider', 'Handler', 'Service']):
                        if cls not in seen_names:
                            discovered.append({
                                "name": cls,
                                "source": str(py_file.relative_to(root)),
                                "type": "class",
                                "confidence": "medium"
                            })
                            seen_names.add(cls)
            except Exception:
                continue

    # Calculate summary
    summary = {
        "total_discovered": len(discovered),
        "high_confidence": sum(1 for c in discovered if c.get("confidence") == "high"),
        "medium_confidence": sum(1 for c in discovered if c.get("confidence") == "medium"),
        "by_type": {}
    }

    for comp in discovered:
        comp_type = comp.get("type", "unknown")
        summary["by_type"][comp_type] = summary["by_type"].get(comp_type, 0) + 1

    return {
        "components": discovered,
        "summary": summary,
        "scan_time": datetime.now().isoformat(),
        "root_path": str(root)
    }


def compare_with_existing(discovered: List[Dict], existing: List[Dict]) -> Dict:
    """
    Compare discovered components with existing ones.

    Returns:
        {
            "new": [...],      # Not in existing
            "matched": [...],  # Already exists
            "missing": [...]   # In existing but not found
        }
    """
    existing_names = {c.get("name", "").lower() for c in existing}
    discovered_names = {c.get("name", "").lower() for c in discovered}

    new = [c for c in discovered if c.get("name", "").lower() not in existing_names]
    matched = [c for c in discovered if c.get("name", "").lower() in existing_names]
    missing = [c for c in existing if c.get("name", "").lower() not in discovered_names]

    return {
        "new": new,
        "matched": matched,
        "missing": missing,
        "summary": {
            "new_count": len(new),
            "matched_count": len(matched),
            "missing_count": len(missing)
        }
    }


def suggest_components(project_path: str, existing_components: List[Dict]) -> Dict:
    """
    Main function: scan project and suggest new components.
    """
    scan_result = scan_directory(project_path)

    if "error" in scan_result:
        return scan_result

    comparison = compare_with_existing(
        scan_result["components"],
        existing_components
    )

    # Format suggestions
    suggestions = []
    for comp in comparison["new"]:
        suggestions.append({
            "name": comp["name"],
            "source": comp.get("source", ""),
            "type": comp.get("type", "unknown"),
            "confidence": comp.get("confidence", "low"),
            "suggested_status": "done",  # Assume done if code exists
            "suggested_desc": comp.get("description", f"Auto-discovered from {comp.get('source', 'codebase')}")
        })

    return {
        "suggestions": suggestions,
        "scan_summary": scan_result["summary"],
        "comparison": comparison["summary"],
        "scan_time": scan_result["scan_time"]
    }
