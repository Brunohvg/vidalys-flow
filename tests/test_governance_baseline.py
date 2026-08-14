import json
import shutil
import subprocess

import pytest

from scripts.check_governance_baseline import BaselineError, GovernanceBaselineGate


def git(root, *args):
    result = subprocess.run(
        ("git", "-C", str(root), *args),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def baseline_repository(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("Git CLI is not installed in this test environment")
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "governance@example.invalid")
    git(tmp_path, "config", "user.name", "Governance Test")
    (tmp_path / "README.md").write_text("# Product\n", encoding="utf-8")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-m", "product phase")
    approved_phase_head = git(tmp_path, "rev-parse", "HEAD")

    write_json(
        tmp_path / "project/state.json",
        {
            "schema_version": 2,
            "approved_phase_head": approved_phase_head,
            "baseline_branch": "main",
        },
    )
    write_json(
        tmp_path / "project/constraints.json",
        {
            "governance_baseline_allowed_paths": [
                "AGENTS.md",
                "project/",
                "docs/PROJECT_STATUS.md",
                "scripts/check_governance_baseline.py",
            ]
        },
    )
    (tmp_path / "AGENTS.md").write_text("# Governance\n", encoding="utf-8")
    git(tmp_path, "add", "AGENTS.md", "project")
    git(tmp_path, "commit", "-m", "governance baseline")
    return tmp_path, approved_phase_head


def test_approved_phase_head_may_differ_from_governance_baseline(baseline_repository):
    root, approved_phase_head = baseline_repository
    baseline_head = git(root, "rev-parse", "HEAD")

    GovernanceBaselineGate(root).validate(head=baseline_head, ref_name="main")

    assert baseline_head != approved_phase_head


def test_baseline_accepts_only_governance_paths(baseline_repository):
    root, _ = baseline_repository

    GovernanceBaselineGate(root).validate(head="HEAD", ref_name="chore/agent-orchestration")


def test_baseline_accepts_exact_project_status_document(baseline_repository):
    root, _ = baseline_repository
    path = root / "docs/PROJECT_STATUS.md"
    path.parent.mkdir()
    path.write_text("# Project status\n", encoding="utf-8")
    git(root, "add", "docs/PROJECT_STATUS.md")
    git(root, "commit", "-m", "update project status")

    GovernanceBaselineGate(root).validate(head="HEAD", ref_name="main")


def test_baseline_rejects_other_docs_path(baseline_repository):
    root, _ = baseline_repository
    path = root / "docs/unapproved.md"
    path.parent.mkdir()
    path.write_text("# Product documentation\n", encoding="utf-8")
    git(root, "add", "docs/unapproved.md")
    git(root, "commit", "-m", "unapproved documentation")

    with pytest.raises(BaselineError, match="unapproved product paths"):
        GovernanceBaselineGate(root).validate(head="HEAD", ref_name="main")


def test_baseline_rejects_unapproved_product_path(baseline_repository):
    root, _ = baseline_repository
    path = root / "apps/unapproved.py"
    path.parent.mkdir()
    path.write_text("UNAPPROVED = True\n", encoding="utf-8")
    git(root, "add", "apps/unapproved.py")
    git(root, "commit", "-m", "unapproved product code")

    with pytest.raises(BaselineError, match="unapproved product paths"):
        GovernanceBaselineGate(root).validate(head="HEAD", ref_name="main")


def test_baseline_must_descend_from_approved_phase(baseline_repository):
    root, approved_phase_head = baseline_repository
    git(root, "switch", "--orphan", "unrelated")
    write_json(
        root / "project/state.json",
        {
            "schema_version": 2,
            "approved_phase_head": approved_phase_head,
            "baseline_branch": "main",
        },
    )
    write_json(
        root / "project/constraints.json",
        {"governance_baseline_allowed_paths": ["AGENTS.md", "project/"]},
    )
    (root / "AGENTS.md").write_text("# Unrelated\n", encoding="utf-8")
    git(root, "add", "AGENTS.md", "project")
    git(root, "commit", "-m", "unrelated root")

    with pytest.raises(BaselineError, match="not an ancestor"):
        GovernanceBaselineGate(root).validate(head="HEAD", ref_name="main")


def test_phase_branch_must_descend_from_recorded_baseline(baseline_repository):
    root, approved_phase_head = baseline_repository
    baseline_head = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-c", "phase/03-orders", approved_phase_head)
    git(root, "checkout", baseline_head, "--", "AGENTS.md", "project")
    git(root, "commit", "-m", "copy governance without baseline ancestry")

    with pytest.raises(BaselineError, match="baseline ref is not an ancestor"):
        GovernanceBaselineGate(root).validate(
            head="HEAD",
            ref_name="phase/03-orders",
            baseline_ref=baseline_head,
        )
