"""
Tests for Subject Detection V1.

Verifies that file paths and signals correctly map to subject tags.
"""

import pytest
import sys
sys.path.insert(0, 'src')

from core.subject_detection import (
    extract_subject_tags_from_path,
    derive_current_subject_tags,
    get_file_subject,
    calculate_subject_confidence,
    _normalize_work_area_to_tags,
    _extract_tags_from_query,
)


class TestExtractSubjectTagsFromPath:
    """Tests for extract_subject_tags_from_path()"""

    def test_website_index(self):
        """website/index.html -> website"""
        tags = extract_subject_tags_from_path("website/index.html")
        assert "website" in tags

    def test_website_nested(self):
        """website/assets/logo.png -> website"""
        tags = extract_subject_tags_from_path("website/assets/logo.png")
        assert "website" in tags

    def test_core_search(self):
        """src/core/search.py -> core, search"""
        tags = extract_subject_tags_from_path("src/core/search.py")
        assert "core" in tags
        assert "search" in tags

    def test_core_port_manager(self):
        """src/core/port_manager.py -> core, server, ports"""
        tags = extract_subject_tags_from_path("src/core/port_manager.py")
        assert "core" in tags
        assert "server" in tags

    def test_menubar_app(self):
        """scripts/menubar_app.py -> macos, tray"""
        tags = extract_subject_tags_from_path("scripts/menubar_app.py")
        assert "macos" in tags
        assert "tray" in tags

    def test_windows_installer(self):
        """scripts/install_windows.ps1 -> windows, installer"""
        tags = extract_subject_tags_from_path("scripts/install_windows.ps1")
        assert "windows" in tags
        assert "installer" in tags

    def test_windows_folder(self):
        """src/windows/startup.py -> windows"""
        tags = extract_subject_tags_from_path("src/windows/startup.py")
        assert "windows" in tags

    def test_mcp_server(self):
        """src/mcp_server/tools.py -> mcp"""
        tags = extract_subject_tags_from_path("src/mcp_server/tools.py")
        assert "mcp" in tags

    def test_api_folder(self):
        """src/api/status.py -> api, server"""
        tags = extract_subject_tags_from_path("src/api/status.py")
        assert "api" in tags
        assert "server" in tags

    def test_dashboard_file(self):
        """website/dashboard.html -> website, dashboard"""
        tags = extract_subject_tags_from_path("website/dashboard.html")
        assert "website" in tags
        assert "dashboard" in tags

    def test_extension(self):
        """extension/background.js -> extension"""
        tags = extract_subject_tags_from_path("extension/background.js")
        assert "extension" in tags

    def test_tests_folder(self):
        """tests/test_search.py -> tests, search"""
        tags = extract_subject_tags_from_path("tests/test_search.py")
        assert "tests" in tags
        assert "search" in tags

    def test_launchagent(self):
        """scripts/create_launchagent.sh -> macos, installer"""
        tags = extract_subject_tags_from_path("scripts/create_launchagent.sh")
        assert "macos" in tags
        assert "installer" in tags

    def test_unknown_file(self):
        """random/unknown/file.txt -> empty or safe result"""
        tags = extract_subject_tags_from_path("random/unknown/file.txt")
        # Should return empty list for unknown paths
        assert isinstance(tags, list)

    def test_empty_path(self):
        """Empty path -> empty list"""
        tags = extract_subject_tags_from_path("")
        assert tags == []

    def test_none_path(self):
        """None path -> empty list"""
        tags = extract_subject_tags_from_path(None)
        assert tags == []

    def test_absolute_path(self):
        """Absolute paths work too"""
        tags = extract_subject_tags_from_path("/Users/dev/project/website/index.html")
        assert "website" in tags

    def test_css_file(self):
        """CSS files get website tag"""
        tags = extract_subject_tags_from_path("website/styles/main.css")
        assert "website" in tags
        assert "styles" in tags


class TestDeriveCurrentSubjectTags:
    """Tests for derive_current_subject_tags()"""

    def test_single_file_signal(self):
        """Single file signal extracts tags"""
        tags = derive_current_subject_tags({
            "activity.file": "website/index.html"
        })
        assert "website" in tags

    def test_multiple_file_signals(self):
        """Multiple signals combine (union mode)"""
        tags = derive_current_subject_tags({
            "activity.file": "website/index.html",
            "intent.last_file": "src/core/search.py"
        })
        assert "website" in tags
        assert "core" in tags
        assert "search" in tags

    def test_files_changed_list(self):
        """files_changed list extracts from all files"""
        tags = derive_current_subject_tags({
            "solutions.files_changed": [
                "src/core/search.py",
                "src/core/memory.py"
            ]
        })
        assert "core" in tags
        assert "search" in tags
        assert "memory" in tags

    def test_work_area_explicit(self):
        """Explicit work_area adds tags"""
        tags = derive_current_subject_tags({
            "intent.work_area": "website dashboard"
        })
        assert "website" in tags
        assert "dashboard" in tags

    def test_empty_signals(self):
        """Empty signals -> empty tags"""
        tags = derive_current_subject_tags({})
        assert tags == []

    def test_intersection_mode(self):
        """Intersection mode returns common tags"""
        tags = derive_current_subject_tags({
            "activity.file": "src/core/search.py",
            "intent.last_file": "src/core/memory.py"
        }, combine_mode="intersection")
        # Both have "core"
        assert "core" in tags

    def test_combined_signals(self):
        """Real-world signal combination"""
        tags = derive_current_subject_tags({
            "activity.file": "website/dashboard.html",
            "intent.last_file": "website/styles.css",
            "intent.work_area": "dashboard UX"
        })
        assert "website" in tags
        assert "dashboard" in tags


class TestNormalizeWorkAreaToTags:
    """Tests for _normalize_work_area_to_tags()"""

    def test_simple_area(self):
        """Simple work area"""
        tags = _normalize_work_area_to_tags("website")
        assert "website" in tags

    def test_compound_area(self):
        """Compound work area"""
        tags = _normalize_work_area_to_tags("core search")
        assert "core" in tags
        assert "search" in tags

    def test_platform_area(self):
        """Platform in work area"""
        tags = _normalize_work_area_to_tags("Windows installer")
        assert "windows" in tags
        assert "installer" in tags

    def test_empty_area(self):
        """Empty work area"""
        tags = _normalize_work_area_to_tags("")
        assert tags == []


class TestExtractTagsFromQuery:
    """Tests for _extract_tags_from_query() - extracts tags from task_hint."""

    def test_file_path_in_query(self):
        """Extracts tags from file path in query."""
        tags = _extract_tags_from_query("work on website/index.html")
        assert "website" in tags

    def test_nested_file_path(self):
        """Extracts tags from nested file path."""
        tags = _extract_tags_from_query("edit src/core/search.py")
        assert "core" in tags
        assert "search" in tags

    def test_dashboard_path(self):
        """Extracts dashboard tag from path."""
        tags = _extract_tags_from_query("fix website/dashboard.html")
        assert "website" in tags
        assert "dashboard" in tags

    def test_keyword_only(self):
        """Extracts tags from keywords without path."""
        tags = _extract_tags_from_query("dashboard improvements")
        assert "dashboard" in tags

    def test_mixed_path_and_keyword(self):
        """Extracts from both path and keywords."""
        tags = _extract_tags_from_query("update website/styles.css for dashboard")
        assert "website" in tags
        assert "dashboard" in tags

    def test_empty_query(self):
        """Empty query returns empty list."""
        tags = _extract_tags_from_query("")
        assert tags == []

    def test_no_recognizable_content(self):
        """Unrecognizable content returns empty or minimal tags."""
        tags = _extract_tags_from_query("do something random")
        assert isinstance(tags, list)


class TestGetFileSubject:
    """Tests for get_file_subject() convenience function"""

    def test_website(self):
        """Get primary subject for website file"""
        subject = get_file_subject("website/index.html")
        assert subject == "website"

    def test_core(self):
        """Get primary subject for core file"""
        subject = get_file_subject("src/core/search.py")
        assert subject == "core"

    def test_unknown(self):
        """Unknown file returns None"""
        subject = get_file_subject("random/file.txt")
        assert subject is None


class TestCalculateSubjectConfidence:
    """Tests for calculate_subject_confidence()"""

    def test_no_tags_zero_confidence(self):
        """No tags => 0.0 confidence"""
        confidence = calculate_subject_confidence([], {})
        assert confidence == 0.0

        # Even with signals, no tags = no confidence
        confidence = calculate_subject_confidence(
            [],
            {"activity.file": "website/index.html"}
        )
        assert confidence == 0.0

    def test_file_path_gives_high_confidence(self):
        """File path signal => >= 0.5"""
        # activity.file
        confidence = calculate_subject_confidence(
            ["website"],
            {"activity.file": "website/index.html"}
        )
        assert confidence >= 0.5

        # intent.last_file
        confidence = calculate_subject_confidence(
            ["core"],
            {"intent.last_file": "src/core/search.py"}
        )
        assert confidence >= 0.5

        # solutions.files_changed
        confidence = calculate_subject_confidence(
            ["api"],
            {"solutions.files_changed": ["src/api/status.py"]}
        )
        assert confidence >= 0.5

    def test_work_area_gives_medium_confidence(self):
        """work_area signal => >= 0.4"""
        confidence = calculate_subject_confidence(
            ["website"],
            {"intent.work_area": "website dashboard"}
        )
        assert confidence >= 0.4

    def test_query_gives_medium_confidence(self):
        """query signal => >= 0.4"""
        confidence = calculate_subject_confidence(
            ["search"],
            {"query": "search tokenization"}
        )
        assert confidence >= 0.4

    def test_task_hint_gives_high_confidence(self):
        """task_hint signal => >= 0.5"""
        confidence = calculate_subject_confidence(
            ["website"],
            {"task_hint": "work on website"}
        )
        assert confidence >= 0.5

    def test_combined_signals_max_confidence(self):
        """file + work_area + multiple tags => 1.0 max"""
        confidence = calculate_subject_confidence(
            ["website", "dashboard"],  # 2 tags
            {
                "activity.file": "website/dashboard.html",
                "intent.work_area": "dashboard UX"
            }
        )
        assert confidence == 1.0

    def test_multiple_tags_bonus(self):
        """Multiple tags add 0.1 bonus"""
        # Single tag with file signal = 0.5
        single = calculate_subject_confidence(
            ["website"],
            {"activity.file": "website/index.html"}
        )

        # Two tags with file signal = 0.6
        multiple = calculate_subject_confidence(
            ["website", "dashboard"],
            {"activity.file": "website/dashboard.html"}
        )

        assert multiple == single + 0.1

    def test_empty_signals_low_confidence(self):
        """Empty signals with tags = very low confidence"""
        confidence = calculate_subject_confidence(
            ["website"],
            {}
        )
        # Has tags but no signals, should be below threshold
        assert confidence < 0.5

    def test_threshold_requirement(self):
        """Verify signals needed to pass 0.5 threshold"""
        # Tags only, no signals - below threshold
        confidence = calculate_subject_confidence(
            ["website", "dashboard"],
            {}
        )
        assert confidence < 0.5

        # File signal - passes threshold
        confidence = calculate_subject_confidence(
            ["website"],
            {"activity.file": "website/index.html"}
        )
        assert confidence >= 0.5

    def test_capped_at_one(self):
        """Confidence never exceeds 1.0"""
        # All possible signals
        confidence = calculate_subject_confidence(
            ["website", "dashboard", "ux"],  # 3 tags
            {
                "activity.file": "website/dashboard.html",
                "intent.last_file": "website/styles.css",
                "intent.work_area": "dashboard",
                "query": "dashboard UX",
                "solutions.files_changed": ["website/x.html"]
            }
        )
        assert confidence == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
