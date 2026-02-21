#!/usr/bin/env python3
"""
Semantic Search Setup Script

Runs all 5 steps to make semantic search production-ready:
1. Rebuild index for all existing projects
2. Verify project isolation (no cross-project leakage)
3. Verify config.json versioning
4. Check dashboard integration
5. Run smoke test
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from core.project_semantic import (
    rebuild_project_index, search_project, index_insight,
    get_project_index_stats, clear_cache
)
from core.embeddings import get_best_provider


def get_all_project_ids() -> list:
    """Get all project IDs from data/projects_v2."""
    projects_dir = Path(__file__).parent.parent / 'data' / 'projects_v2'
    project_ids = []

    for f in projects_dir.glob('*.json'):
        name = f.stem
        # Skip non-project files
        if name in ('__global__', 'live-state'):
            continue
        project_ids.append(name)

    return project_ids


def step1_rebuild_all_indexes():
    """Step 1: Rebuild semantic index for all existing projects."""
    print("\n" + "="*60)
    print("STEP 1: Rebuild indexes for all existing projects")
    print("="*60)

    project_ids = get_all_project_ids()
    print(f"Found {len(project_ids)} projects")

    results = []
    for pid in project_ids:
        print(f"\n  Rebuilding: {pid}...")
        try:
            result = rebuild_project_index(pid)
            docs = result.get('documents_indexed', 0)
            results.append((pid, docs, 'OK'))
            print(f"    -> {docs} documents indexed")
        except Exception as e:
            results.append((pid, 0, str(e)))
            print(f"    -> ERROR: {e}")

    print("\n  Summary:")
    total_docs = sum(r[1] for r in results)
    success = sum(1 for r in results if r[2] == 'OK')
    print(f"    Projects: {success}/{len(results)} successful")
    print(f"    Total documents indexed: {total_docs}")

    return results


def step2_verify_project_isolation():
    """Step 2: Verify no cross-project data leakage."""
    print("\n" + "="*60)
    print("STEP 2: Verify project isolation")
    print("="*60)

    # Create unique test data in two different projects
    test_project_a = "__test_isolation_a__"
    test_project_b = "__test_isolation_b__"

    unique_text_a = "ISOLATION_TEST_ALPHA_7291_UNIQUE"
    unique_text_b = "ISOLATION_TEST_BETA_8392_UNIQUE"

    print(f"  Creating test data...")
    index_insight(test_project_a, unique_text_a)
    index_insight(test_project_b, unique_text_b)

    # Search in project A should NOT find project B's data
    print(f"  Searching in project A for B's data...")
    results_a = search_project(test_project_a, unique_text_b, k=5, min_score=0.0)

    # Search in project B should NOT find project A's data
    print(f"  Searching in project B for A's data...")
    results_b = search_project(test_project_b, unique_text_a, k=5, min_score=0.0)

    # Verify isolation
    isolation_ok = True

    for r in results_a:
        if unique_text_b in r.text:
            print(f"    FAIL: Project A found Project B's data!")
            isolation_ok = False

    for r in results_b:
        if unique_text_a in r.text:
            print(f"    FAIL: Project B found Project A's data!")
            isolation_ok = False

    # Verify each project finds its own data
    results_a_own = search_project(test_project_a, unique_text_a, k=1, min_score=0.0)
    results_b_own = search_project(test_project_b, unique_text_b, k=1, min_score=0.0)

    if not results_a_own or unique_text_a not in results_a_own[0].text:
        print(f"    FAIL: Project A can't find its own data!")
        isolation_ok = False

    if not results_b_own or unique_text_b not in results_b_own[0].text:
        print(f"    FAIL: Project B can't find its own data!")
        isolation_ok = False

    # Cleanup
    import shutil
    data_dir = Path(__file__).parent.parent / 'data' / 'projects_v2'
    for test_dir in [test_project_a, test_project_b]:
        emb_dir = data_dir / f"{test_dir}.embeddings"
        if emb_dir.exists():
            shutil.rmtree(emb_dir)

    clear_cache()

    if isolation_ok:
        print("  -> PASS: Project isolation verified")
    else:
        print("  -> FAIL: Project isolation BROKEN!")

    return isolation_ok


def step3_verify_config_versioning():
    """Step 3: Verify config.json is saved with versioning."""
    print("\n" + "="*60)
    print("STEP 3: Verify config.json versioning")
    print("="*60)

    data_dir = Path(__file__).parent.parent / 'data' / 'projects_v2'

    # Find an existing embeddings directory
    emb_dirs = list(data_dir.glob('*.embeddings'))

    if not emb_dirs:
        print("  No embedding indexes found yet")
        print("  Creating test index...")
        index_insight("__test_config__", "Test insight for config verification")
        emb_dirs = list(data_dir.glob('*.embeddings'))

    if not emb_dirs:
        print("  -> FAIL: Could not create test index")
        return False

    emb_dir = emb_dirs[0]
    config_file = emb_dir / 'config.json'

    print(f"  Checking: {emb_dir.name}")

    if not config_file.exists():
        print("  -> FAIL: config.json not found!")
        return False

    with open(config_file, 'r') as f:
        config = json.load(f)

    required_fields = ['model_id', 'dimension', 'created_at', 'provider_type']
    missing = [f for f in required_fields if f not in config]

    if missing:
        print(f"  -> FAIL: Missing fields: {missing}")
        return False

    print(f"    model_id: {config['model_id']}")
    print(f"    dimension: {config['dimension']}")
    print(f"    provider_type: {config['provider_type']}")
    print(f"    created_at: {config['created_at']}")
    print(f"    document_count: {config.get('document_count', 'N/A')}")
    print("  -> PASS: Config versioning verified")

    # Cleanup test
    test_emb = data_dir / '__test_config__.embeddings'
    if test_emb.exists():
        import shutil
        shutil.rmtree(test_emb)

    return True


def step4_check_dashboard_integration():
    """Step 4: Check if dashboard can show semantic status."""
    print("\n" + "="*60)
    print("STEP 4: Dashboard integration check")
    print("="*60)

    # Check if the API endpoint exists
    api_file = Path(__file__).parent.parent / 'src' / 'api' / 'status.py'

    print(f"  Looking for dashboard API...")

    if not api_file.exists():
        print(f"  -> Dashboard API not found at {api_file}")
        print("  -> Need to add semantic status endpoint")
        return False

    # Check if semantic status is already integrated
    content = api_file.read_text()

    if 'semantic' in content.lower():
        print("  -> Semantic status already in dashboard API")
        return True
    else:
        print("  -> Semantic status NOT in dashboard API")
        print("  -> Will add endpoint")
        return False


def step5_smoke_test():
    """Step 5: Run smoke test with unique identifier."""
    print("\n" + "="*60)
    print("STEP 5: Smoke test")
    print("="*60)

    test_project = "__smoke_test__"
    magic_word = "tetris_collision_magicword_9173_smoketest"

    print(f"  1. Adding unique insight: {magic_word[:30]}...")

    clear_cache()  # Fresh start

    index_insight(test_project, magic_word)

    print(f"  2. Searching for it...")
    results = search_project(test_project, magic_word, k=1, min_score=0.0)

    print(f"  3. Verifying first result...")

    if not results:
        print("  -> FAIL: No results returned!")
        return False

    if results[0].text != magic_word:
        print(f"  -> FAIL: First result is not the magic word!")
        print(f"       Expected: {magic_word}")
        print(f"       Got: {results[0].text}")
        return False

    if results[0].score < 0.9:
        print(f"  -> WARN: Score lower than expected: {results[0].score}")

    print(f"  -> PASS: Magic word found with score {results[0].score:.2f}")

    # Cleanup
    import shutil
    data_dir = Path(__file__).parent.parent / 'data' / 'projects_v2'
    test_emb = data_dir / f'{test_project}.embeddings'
    if test_emb.exists():
        shutil.rmtree(test_emb)

    clear_cache()

    return True


def main():
    print("\n" + "#"*60)
    print("# SEMANTIC SEARCH PRODUCTION SETUP")
    print("#"*60)

    # Check provider first
    print("\nLoading embedding provider...")
    provider = get_best_provider()
    print(f"Provider: {provider.__class__.__name__}")
    print(f"Model: {provider.model_id}")

    results = {}

    # Run all steps
    results['step1'] = step1_rebuild_all_indexes()
    results['step2'] = step2_verify_project_isolation()
    results['step3'] = step3_verify_config_versioning()
    results['step4'] = step4_check_dashboard_integration()
    results['step5'] = step5_smoke_test()

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    print(f"  Step 1 (Rebuild all): {len([r for r in results['step1'] if r[2]=='OK'])}/{len(results['step1'])} projects")
    print(f"  Step 2 (Isolation): {'PASS' if results['step2'] else 'FAIL'}")
    print(f"  Step 3 (Versioning): {'PASS' if results['step3'] else 'FAIL'}")
    print(f"  Step 4 (Dashboard): {'EXISTS' if results['step4'] else 'NEEDS WORK'}")
    print(f"  Step 5 (Smoke test): {'PASS' if results['step5'] else 'FAIL'}")

    all_pass = (
        all(r[2] == 'OK' for r in results['step1']) and
        results['step2'] and
        results['step3'] and
        results['step5']
    )

    print()
    if all_pass:
        print("ALL CRITICAL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED - Check above for details")

    return results


if __name__ == '__main__':
    main()
