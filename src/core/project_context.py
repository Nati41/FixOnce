"""
ProjectContext - Central project resolution and validation.

This is the SINGLE SOURCE OF TRUTH for project identification.
ALL project resolution goes through here.

HYBRID ID STRATEGY (v2):
1. Git remote exists → hash(remote_url) - Team-ready, same ID across machines
2. Git local (no remote) → hash(repo_root_path) - Stable within machine
3. No git → UUID stored in .fixonce/project.json - Explicit persistence

Key principles:
- Same repository = Same memory (across machines, CI/CD, team)
- No global active_project.json for routing (only dashboard display)
- Explicit validation: cwd must be within project_root
"""

from pathlib import Path
import hashlib
import subprocess
import json
import uuid
from typing import Optional, Tuple
from dataclasses import dataclass


# Enable verbose logging for debugging
_VERBOSE_LOGGING = True


def _log_context(message: str, project_id: str = None, source: str = None):
    """Log ProjectContext operations for debugging."""
    if not _VERBOSE_LOGGING:
        return
    parts = ["[ProjectContext]", message]
    if project_id:
        parts.append(f"project_id={project_id}")
    if source:
        parts.append(f"(source={source})")
    print(" ".join(parts))


@dataclass
class ProjectIdentity:
    """
    Full project identity information.
    Includes how the ID was resolved for debugging/display.
    """
    project_id: str
    strategy: str  # "git_remote", "git_local", "uuid", "path_fallback"
    source_value: str  # The value used to generate the ID
    project_name: str  # Human-readable name


class ProjectContext:
    """
    CENTRAL project resolution and validation.
    ALL project identification goes through here.

    HYBRID STRATEGY:
    1. Git remote → hash(remote_url)
    2. Git local → hash(repo_root)
    3. No git → UUID from .fixonce/project.json
    """

    # Cache for resolved projects (avoid repeated git calls)
    _cache: dict = {}

    @classmethod
    def _get_git_info(cls, project_root: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Get git remote URL and repo root.

        IMPORTANT: Works from ANY subdirectory within the repo.
        Uses `git rev-parse` to find the actual repo root first.

        Returns:
            (remote_url, repo_root) - Either can be None
        """
        try:
            root_path = Path(project_root).resolve()

            # First, try to find the repo root from this path
            # This works from ANY subdirectory
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                cwd=str(root_path),
                capture_output=True, text=True, timeout=5
            )

            if result.returncode != 0:
                # Not inside a git repo
                return (None, None)

            repo_root = result.stdout.strip()

            # Get remote URL (prefer origin, fall back to first remote)
            result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=str(root_path),
                capture_output=True, text=True, timeout=5
            )

            if result.returncode == 0 and result.stdout.strip():
                remote_url = result.stdout.strip()
                # Normalize URL (remove .git suffix, handle SSH vs HTTPS)
                remote_url = cls._normalize_git_url(remote_url)
                return (remote_url, repo_root)

            # No origin, try any remote
            result = subprocess.run(
                ['git', 'remote'],
                cwd=str(root_path),
                capture_output=True, text=True, timeout=5
            )

            if result.returncode == 0 and result.stdout.strip():
                first_remote = result.stdout.strip().split('\n')[0]
                result = subprocess.run(
                    ['git', 'remote', 'get-url', first_remote],
                    cwd=str(root_path),
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    remote_url = cls._normalize_git_url(result.stdout.strip())
                    return (remote_url, repo_root)

            # Git repo but no remote
            return (None, repo_root)

        except Exception as e:
            _log_context(f"Git info error: {e}", source="git_check")
            return (None, None)

    @staticmethod
    def _normalize_git_url(url: str) -> str:
        """
        Normalize git URL to consistent format.

        git@github.com:user/repo.git → github.com/user/repo
        https://github.com/user/repo.git → github.com/user/repo
        """
        url = url.strip()

        # Remove .git suffix
        if url.endswith('.git'):
            url = url[:-4]

        # Handle SSH format: git@github.com:user/repo
        if url.startswith('git@'):
            url = url[4:]  # Remove git@
            url = url.replace(':', '/', 1)  # Replace first : with /

        # Handle HTTPS format
        if url.startswith('https://'):
            url = url[8:]
        if url.startswith('http://'):
            url = url[7:]

        return url

    @classmethod
    def _get_or_create_uuid(cls, project_root: str) -> str:
        """
        Get or create UUID for projects without git.
        Stored in .fixonce/project.json
        """
        root_path = Path(project_root).resolve()
        fixonce_dir = root_path / ".fixonce"
        project_file = fixonce_dir / "project.json"

        # Try to read existing UUID
        if project_file.exists():
            try:
                with open(project_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data.get('project_uuid'):
                        return data['project_uuid']
            except Exception:
                pass

        # Create new UUID
        project_uuid = str(uuid.uuid4())

        try:
            fixonce_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "project_uuid": project_uuid,
                "created_at": __import__('datetime').datetime.now().isoformat(),
                "project_name": root_path.name
            }
            with open(project_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            _log_context(f"Created UUID for {root_path.name}", project_uuid, "uuid_create")
        except Exception as e:
            _log_context(f"Failed to save UUID: {e}", source="uuid_create")

        return project_uuid

    @classmethod
    def resolve(cls, project_root: str) -> ProjectIdentity:
        """
        Resolve full project identity using hybrid strategy.

        Priority:
        1. Git remote URL → hash(normalized_url)
        2. Git local (no remote) → hash(repo_root_path)
        3. No git → UUID from .fixonce/project.json

        Args:
            project_root: Path to project directory

        Returns:
            ProjectIdentity with full resolution details
        """
        root_path = Path(project_root).resolve()
        cache_key = str(root_path)

        # Check cache
        if cache_key in cls._cache:
            cached = cls._cache[cache_key]
            _log_context("Using cached", cached.project_id, f"cache/{cached.strategy}")
            return cached

        project_name = root_path.name

        # Strategy 1: Git remote
        remote_url, repo_root = cls._get_git_info(str(root_path))

        if remote_url:
            # Git remote exists - team-ready ID
            url_hash = hashlib.md5(remote_url.encode()).hexdigest()[:12]
            # Extract repo name from URL for readability
            url_parts = remote_url.rstrip('/').split('/')
            repo_name = url_parts[-1] if url_parts else project_name
            project_id = f"{repo_name}_{url_hash}"

            identity = ProjectIdentity(
                project_id=project_id,
                strategy="git_remote",
                source_value=remote_url,
                project_name=repo_name
            )
            _log_context("Resolved", project_id, f"git_remote:{remote_url[:40]}")

        elif repo_root:
            # Git local (no remote) - stable within machine
            path_hash = hashlib.md5(repo_root.encode()).hexdigest()[:12]
            project_id = f"{project_name}_{path_hash}"

            identity = ProjectIdentity(
                project_id=project_id,
                strategy="git_local",
                source_value=repo_root,
                project_name=project_name
            )
            _log_context("Resolved", project_id, "git_local")

        else:
            # No git - use UUID
            project_uuid = cls._get_or_create_uuid(str(root_path))
            uuid_hash = hashlib.md5(project_uuid.encode()).hexdigest()[:12]
            project_id = f"{project_name}_{uuid_hash}"

            identity = ProjectIdentity(
                project_id=project_id,
                strategy="uuid",
                source_value=project_uuid,
                project_name=project_name
            )
            _log_context("Resolved", project_id, "uuid")

        # Cache result
        cls._cache[cache_key] = identity
        return identity

    @classmethod
    def from_path(cls, project_root: str, log_source: str = "working_dir") -> str:
        """
        Generate project_id from path using hybrid strategy.

        This is the CANONICAL way to get a project ID.

        Args:
            project_root: Absolute path to the project root directory
            log_source: Source of the call for logging

        Returns:
            Deterministic project ID
        """
        identity = cls.resolve(project_root)
        return identity.project_id

    @classmethod
    def clear_cache(cls):
        """Clear the resolution cache (for testing/debugging)."""
        cls._cache.clear()
        _log_context("Cache cleared", source="cache")

    @staticmethod
    def validate(cwd: str, project_root: str) -> bool:
        """
        Validate that cwd is within project_root.

        This is a GUARD to prevent cross-project contamination.
        Raises ValueError if cwd is not within project_root.

        Args:
            cwd: Current working directory (where the request came from)
            project_root: The project root directory

        Returns:
            True if valid

        Raises:
            ValueError: If cwd is not within project_root
        """
        cwd_path = Path(cwd).resolve()
        root_path = Path(project_root).resolve()

        # CORRECT check - avoids /project-a matching /project-a-test
        # Must be either equal to root OR a subdirectory of root
        if root_path not in cwd_path.parents and cwd_path != root_path:
            _log_context(f"BLOCKED! cwd={cwd} not in project_root={project_root}", source="validation")
            raise ValueError(
                f"Project mismatch! cwd={cwd} is not within project_root={project_root}"
            )

        _log_context("Validated OK", source="validation")
        return True

    @staticmethod
    def get_project_file(project_id: str) -> Path:
        """
        Get path to project memory file.

        Args:
            project_id: The project ID (from from_path())

        Returns:
            Path to the project's memory JSON file
        """
        # Find data directory
        src_dir = Path(__file__).parent.parent
        project_dir = src_dir.parent
        data_dir = project_dir / "data"

        return data_dir / "projects_v2" / f"{project_id}.json"

    @staticmethod
    def get_embeddings_dir(project_id: str) -> Path:
        """
        Get path to project embeddings directory (for semantic index).

        Args:
            project_id: The project ID

        Returns:
            Path to the project's embeddings directory
        """
        src_dir = Path(__file__).parent.parent
        project_dir = src_dir.parent
        data_dir = project_dir / "data"

        return data_dir / "projects_v2" / f"{project_id}.embeddings"

    @staticmethod
    def is_valid_project_root(path: str) -> bool:
        """
        Check if a path could be a valid project root.

        Args:
            path: Path to check

        Returns:
            True if path exists and is a directory
        """
        try:
            p = Path(path).resolve()
            return p.exists() and p.is_dir()
        except Exception:
            return False

    @staticmethod
    def extract_project_name(project_root: str) -> str:
        """
        Extract a human-readable project name from path.

        Args:
            project_root: Path to project

        Returns:
            The folder name as project name
        """
        return Path(project_root).resolve().name


# Convenience function for common use case
def resolve_project_id(working_dir: str) -> str:
    """
    Convenience function to get project ID from working directory.

    This is the ONLY way to resolve a project ID.
    Uses hybrid strategy: git_remote > git_local > uuid

    Args:
        working_dir: The working directory path

    Returns:
        The project ID
    """
    return ProjectContext.from_path(working_dir)


def resolve_project_identity(working_dir: str) -> ProjectIdentity:
    """
    Get full project identity including resolution strategy.

    Useful for debugging and display.

    Args:
        working_dir: The working directory path

    Returns:
        ProjectIdentity with full details
    """
    return ProjectContext.resolve(working_dir)
