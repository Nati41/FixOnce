"""
Tests for Project Snapshot - Single source of truth for project state.

These tests verify:
1. Superseded decisions are excluded from Snapshot counts
2. Superseded solutions are excluded from Snapshot counts
3. Snapshot and canonical active counters agree
4. fo_init and /api/snapshot return identical counts
5. Avoid patterns are counted separately from insights
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestKnowledgeCounts:
    """Test that knowledge counts properly exclude superseded items."""

    def test_knowledge_counts_includes_avoid(self):
        """KnowledgeCounts dataclass should have avoid field."""
        from core.project_snapshot import KnowledgeCounts

        counts = KnowledgeCounts(decisions=10, solutions=5, avoid=3, insights=2)
        assert counts.decisions == 10
        assert counts.solutions == 5
        assert counts.avoid == 3
        assert counts.insights == 2

    def test_knowledge_counts_default_zero(self):
        """KnowledgeCounts fields default to zero."""
        from core.project_snapshot import KnowledgeCounts

        counts = KnowledgeCounts()
        assert counts.decisions == 0
        assert counts.solutions == 0
        assert counts.avoid == 0
        assert counts.insights == 0


class TestQueryRecordedKnowledge:
    """Test _query_recorded_knowledge filters superseded items."""

    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory with .fixonce files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixonce_dir = Path(tmpdir) / ".fixonce"
            fixonce_dir.mkdir()
            yield tmpdir, fixonce_dir

    def test_filters_superseded_decisions(self, temp_project_dir):
        """Superseded decisions should NOT be counted."""
        from core.project_snapshot import _query_recorded_knowledge

        tmpdir, fixonce_dir = temp_project_dir

        # Create decisions.json with some superseded
        decisions_data = {
            "decisions": [
                {"id": "1", "text": "Active decision 1", "timestamp": "2024-01-01T10:00:00"},
                {"id": "2", "text": "Active decision 2", "timestamp": "2024-01-02T10:00:00"},
                {"id": "3", "text": "Superseded decision", "timestamp": "2024-01-03T10:00:00", "superseded": True},
                {"id": "4", "text": "Also superseded", "timestamp": "2024-01-04T10:00:00", "superseded": True},
            ]
        }
        with open(fixonce_dir / "decisions.json", "w") as f:
            json.dump(decisions_data, f)

        result = _query_recorded_knowledge(tmpdir)

        # Should only count active (non-superseded) decisions
        assert result["counts"].decisions == 2
        # Recent should also only show active
        assert len(result["recent_decisions"]) == 2

    def test_filters_superseded_solutions(self, temp_project_dir):
        """Superseded solutions should NOT be counted."""
        from core.project_snapshot import _query_recorded_knowledge

        tmpdir, fixonce_dir = temp_project_dir

        # Create solutions.json with some superseded
        solutions_data = {
            "solutions": [
                {"id": "1", "error": "Bug 1", "solution": "Fix 1", "timestamp": "2024-01-01T10:00:00"},
                {"id": "2", "error": "Bug 2", "solution": "Fix 2", "timestamp": "2024-01-02T10:00:00", "superseded": True},
                {"id": "3", "error": "Bug 3", "solution": "Fix 3", "timestamp": "2024-01-03T10:00:00"},
            ]
        }
        with open(fixonce_dir / "solutions.json", "w") as f:
            json.dump(solutions_data, f)

        result = _query_recorded_knowledge(tmpdir)

        # Should only count active (non-superseded) solutions
        assert result["counts"].solutions == 2
        # Recent should also only show active
        assert len(result["recent_solutions"]) == 2

    def test_avoid_patterns_never_superseded(self, temp_project_dir):
        """Avoid patterns are permanent and should all be counted."""
        from core.project_snapshot import _query_recorded_knowledge

        tmpdir, fixonce_dir = temp_project_dir

        # Create avoid.json
        avoid_data = {
            "patterns": [
                {"id": "1", "what": "Don't do this", "timestamp": "2024-01-01T10:00:00"},
                {"id": "2", "what": "Don't do that", "timestamp": "2024-01-02T10:00:00"},
                {"id": "3", "what": "Avoid this pattern", "timestamp": "2024-01-03T10:00:00"},
            ]
        }
        with open(fixonce_dir / "avoid.json", "w") as f:
            json.dump(avoid_data, f)

        result = _query_recorded_knowledge(tmpdir)

        # All avoid patterns should be counted
        assert result["counts"].avoid == 3
        # Recent should show most recent
        assert len(result["recent_avoid"]) == 3

    def test_avoid_separate_from_insights(self, temp_project_dir):
        """Avoid patterns and insights are counted separately."""
        from core.project_snapshot import _query_recorded_knowledge

        tmpdir, fixonce_dir = temp_project_dir

        # Create both avoid.json and insights.json
        avoid_data = {"patterns": [{"id": "1", "what": "Avoid this"}]}
        insights_data = {"insights": [{"id": "1", "text": "Insight 1"}, {"id": "2", "text": "Insight 2"}]}

        with open(fixonce_dir / "avoid.json", "w") as f:
            json.dump(avoid_data, f)
        with open(fixonce_dir / "insights.json", "w") as f:
            json.dump(insights_data, f)

        result = _query_recorded_knowledge(tmpdir)

        # Should have separate counts
        assert result["counts"].avoid == 1
        assert result["counts"].insights == 2


class TestProjectSnapshotToDict:
    """Test ProjectSnapshot serialization includes all fields."""

    def test_to_dict_includes_avoid_count(self):
        """to_dict should include avoid in knowledge_counts."""
        from core.project_snapshot import ProjectSnapshot, KnowledgeCounts

        snapshot = ProjectSnapshot(
            project_id="test_123",
            project_name="TestProject",
            knowledge_counts=KnowledgeCounts(decisions=10, solutions=5, avoid=3, insights=2)
        )

        result = snapshot.to_dict()

        assert "knowledge_counts" in result
        assert result["knowledge_counts"]["decisions"] == 10
        assert result["knowledge_counts"]["solutions"] == 5
        assert result["knowledge_counts"]["avoid"] == 3
        assert result["knowledge_counts"]["insights"] == 2

    def test_to_dict_includes_recent_avoid(self):
        """to_dict should include recent_avoid."""
        from core.project_snapshot import ProjectSnapshot

        recent_avoid = [{"id": "1", "what": "Don't do this"}]
        snapshot = ProjectSnapshot(
            project_id="test_123",
            project_name="TestProject",
            recent_avoid=recent_avoid
        )

        result = snapshot.to_dict()

        assert "recent_avoid" in result
        assert result["recent_avoid"] == recent_avoid


class TestSnapshotCountsMatchCanonical:
    """Test that Snapshot counts match the canonical counter semantics."""

    @pytest.fixture
    def temp_project_with_knowledge(self):
        """Create a project with mixed active/superseded knowledge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixonce_dir = Path(tmpdir) / ".fixonce"
            fixonce_dir.mkdir()

            # Decisions: 3 active, 2 superseded
            decisions = {
                "decisions": [
                    {"id": "1", "text": "Active 1", "timestamp": "2024-01-01"},
                    {"id": "2", "text": "Active 2", "timestamp": "2024-01-02"},
                    {"id": "3", "text": "Active 3", "timestamp": "2024-01-03"},
                    {"id": "4", "text": "Superseded 1", "timestamp": "2024-01-04", "superseded": True},
                    {"id": "5", "text": "Superseded 2", "timestamp": "2024-01-05", "superseded": True},
                ]
            }
            with open(fixonce_dir / "decisions.json", "w") as f:
                json.dump(decisions, f)

            # Solutions: 2 active, 1 superseded
            solutions = {
                "solutions": [
                    {"id": "1", "error": "Bug 1", "timestamp": "2024-01-01"},
                    {"id": "2", "error": "Bug 2", "timestamp": "2024-01-02"},
                    {"id": "3", "error": "Superseded bug", "timestamp": "2024-01-03", "superseded": True},
                ]
            }
            with open(fixonce_dir / "solutions.json", "w") as f:
                json.dump(solutions, f)

            # Avoid: 2 patterns (never superseded)
            avoid = {
                "patterns": [
                    {"id": "1", "what": "Avoid 1", "timestamp": "2024-01-01"},
                    {"id": "2", "what": "Avoid 2", "timestamp": "2024-01-02"},
                ]
            }
            with open(fixonce_dir / "avoid.json", "w") as f:
                json.dump(avoid, f)

            yield tmpdir

    def test_snapshot_counts_exclude_superseded(self, temp_project_with_knowledge):
        """Snapshot counts should exclude superseded items."""
        from core.project_snapshot import get_project_snapshot

        snapshot = get_project_snapshot("test_project", temp_project_with_knowledge)

        # Expected: 3 active decisions, 2 active solutions, 2 avoid patterns
        assert snapshot.knowledge_counts.decisions == 3
        assert snapshot.knowledge_counts.solutions == 2
        assert snapshot.knowledge_counts.avoid == 2


class TestRenderSnapshotOpenerV1:
    """Test the V1 opener renderer includes avoid patterns."""

    def test_opener_shows_avoid_patterns(self):
        """render_snapshot_opener_v1 should show Avoid Patterns count."""
        from core.project_snapshot import render_snapshot_opener_v1, ProjectSnapshot, KnowledgeCounts

        snapshot = ProjectSnapshot(
            project_id="test_123",
            project_name="TestProject",
            knowledge_counts=KnowledgeCounts(decisions=10, solutions=5, avoid=3, insights=0)
        )

        opener = render_snapshot_opener_v1(snapshot)

        assert "10 Decisions" in opener
        assert "5 Solved Bugs" in opener
        assert "3 Avoid Patterns" in opener
        assert "Insights" not in opener  # No insights = not shown

    def test_opener_shows_all_categories(self):
        """render_snapshot_opener_v1 should show all non-zero categories."""
        from core.project_snapshot import render_snapshot_opener_v1, ProjectSnapshot, KnowledgeCounts

        snapshot = ProjectSnapshot(
            project_id="test_123",
            project_name="TestProject",
            knowledge_counts=KnowledgeCounts(decisions=10, solutions=5, avoid=3, insights=2)
        )

        opener = render_snapshot_opener_v1(snapshot)

        assert "10 Decisions" in opener
        assert "5 Solved Bugs" in opener
        assert "3 Avoid Patterns" in opener
        assert "2 Insights" in opener


class TestProjectResolutionAlignment:
    """Test that fo_init and /api/snapshot resolve the same project_id."""

    def test_snapshot_api_uses_project_context_from_path(self):
        """When working_dir is available, should use ProjectContext.from_path."""
        from core.project_context import ProjectContext

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create .fixonce/metadata.json to simulate a project
            fixonce_dir = Path(tmpdir) / ".fixonce"
            fixonce_dir.mkdir()

            metadata = {"project_id": "test_project_from_path"}
            with open(fixonce_dir / "metadata.json", "w") as f:
                json.dump(metadata, f)

            # ProjectContext.from_path should return consistent ID
            project_id = ProjectContext.from_path(tmpdir)

            assert project_id is not None
            # Should use the stored project_id from metadata
            assert project_id == "test_project_from_path"

    def test_fo_init_and_snapshot_use_same_resolution(self):
        """fo_init and /api/snapshot should use ProjectContext.from_path."""
        # This is a structural test - both code paths should call ProjectContext.from_path
        # fo_init: _get_project_id -> ProjectContext.from_path
        # /api/snapshot: _resolve_project_and_working_dir -> ProjectContext.from_path

        # Verify the import paths exist
        from core.project_context import ProjectContext
        assert hasattr(ProjectContext, 'from_path')

        # The _resolve_project_and_working_dir should import and use ProjectContext.from_path
        from api.snapshot import _resolve_project_and_working_dir
        import inspect
        source = inspect.getsource(_resolve_project_and_working_dir)
        assert "ProjectContext.from_path" in source


class TestCanonicalKnowledgeCounts:
    """Test the canonical knowledge counts provider."""

    @pytest.fixture
    def temp_project_with_knowledge(self):
        """Create a project with mixed active/superseded knowledge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixonce_dir = Path(tmpdir) / ".fixonce"
            fixonce_dir.mkdir()

            # Decisions: 3 active, 2 superseded
            decisions = {
                "decisions": [
                    {"id": "1", "text": "Active 1", "timestamp": "2024-01-01"},
                    {"id": "2", "text": "Active 2", "timestamp": "2024-01-02"},
                    {"id": "3", "text": "Active 3", "timestamp": "2024-01-03"},
                    {"id": "4", "text": "Superseded 1", "timestamp": "2024-01-04", "superseded": True},
                    {"id": "5", "text": "Superseded 2", "timestamp": "2024-01-05", "superseded": True},
                ]
            }
            with open(fixonce_dir / "decisions.json", "w") as f:
                json.dump(decisions, f)

            # Solutions: 4 active, 2 superseded
            solutions = {
                "solutions": [
                    {"id": "1", "error": "Bug 1", "timestamp": "2024-01-01"},
                    {"id": "2", "error": "Bug 2", "timestamp": "2024-01-02"},
                    {"id": "3", "error": "Bug 3", "timestamp": "2024-01-03"},
                    {"id": "4", "error": "Bug 4", "timestamp": "2024-01-04"},
                    {"id": "5", "error": "Superseded", "timestamp": "2024-01-05", "superseded": True},
                    {"id": "6", "error": "Also Superseded", "timestamp": "2024-01-06", "superseded": True},
                ]
            }
            with open(fixonce_dir / "solutions.json", "w") as f:
                json.dump(solutions, f)

            # Avoid: 2 patterns
            avoid = {
                "patterns": [
                    {"id": "1", "what": "Avoid 1", "timestamp": "2024-01-01"},
                    {"id": "2", "what": "Avoid 2", "timestamp": "2024-01-02"},
                ]
            }
            with open(fixonce_dir / "avoid.json", "w") as f:
                json.dump(avoid, f)

            yield tmpdir

    def test_canonical_provider_returns_correct_counts(self, temp_project_with_knowledge):
        """Canonical provider should return active (non-superseded) counts only."""
        from core.knowledge_counters import get_canonical_knowledge_counts

        canonical = get_canonical_knowledge_counts(temp_project_with_knowledge)

        # Expected: 3 active decisions, 4 active solutions, 2 avoid patterns
        assert canonical.decisions == 3
        assert canonical.solutions == 4
        assert canonical.avoid == 2

    def test_canonical_provider_matches_snapshot(self, temp_project_with_knowledge):
        """Canonical provider should return same counts as project snapshot."""
        from core.knowledge_counters import get_canonical_knowledge_counts
        from core.project_snapshot import get_project_snapshot

        canonical = get_canonical_knowledge_counts(temp_project_with_knowledge)
        snapshot = get_project_snapshot("test_project", temp_project_with_knowledge)

        assert canonical.decisions == snapshot.knowledge_counts.decisions
        assert canonical.solutions == snapshot.knowledge_counts.solutions
        assert canonical.avoid == snapshot.knowledge_counts.avoid

    def test_canonical_to_legacy_dict(self, temp_project_with_knowledge):
        """to_legacy_dict should use 'solved' key for backward compatibility."""
        from core.knowledge_counters import get_canonical_knowledge_counts

        canonical = get_canonical_knowledge_counts(temp_project_with_knowledge)
        legacy = canonical.to_legacy_dict()

        assert "solved" in legacy
        assert legacy["solved"] == canonical.solutions
        assert "decisions" in legacy
        assert "avoid" in legacy

    def test_canonical_empty_project(self):
        """Canonical provider should return zeros for empty/nonexistent project."""
        from core.knowledge_counters import get_canonical_knowledge_counts

        with tempfile.TemporaryDirectory() as tmpdir:
            canonical = get_canonical_knowledge_counts(tmpdir)

            assert canonical.decisions == 0
            assert canonical.solutions == 0
            assert canonical.avoid == 0
            assert canonical.insights == 0
