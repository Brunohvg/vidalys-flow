import json
import shutil
from pathlib import Path

import pytest

from scripts.agent_orchestrator import GovernanceError, GovernanceRepository, main

ROOT = Path(__file__).resolve().parent.parent


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def governance_root(tmp_path):
    shutil.copy(ROOT / "AGENTS.md", tmp_path / "AGENTS.md")
    shutil.copytree(ROOT / "project", tmp_path / "project")
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    return tmp_path


@pytest.fixture
def repository(governance_root):
    return GovernanceRepository(governance_root)


def test_valid_state_and_all_artifacts(repository):
    state = repository.validate_state()

    repository.validate_all()

    assert state["approved_phase"] == 6
    assert state["approved_phase_head"] == "e2140eb25cc10f1a79dad05a0507ba9141003ac9"
    assert state["baseline_branch"] == "main"
    assert state["next_phase"] == 7
    assert state["active_candidate"] == {
        "phase": 7,
        "branch": "phase/07-integrations",
        "base_ref": "main",
        "actual_base_sha": "09d73050f1df9d52b13e61ae87a26db4b26f365c",
        "dependency_head": "e2140eb25cc10f1a79dad05a0507ba9141003ac9",
    }


def test_invalid_approved_sha_is_rejected(governance_root):
    path = governance_root / "project/state.json"
    state = load_json(path)
    state["approved_phase_head"] = "invalid"
    write_json(path, state)

    with pytest.raises(GovernanceError, match="approved_phase_head"):
        GovernanceRepository(governance_root).validate_state()


def test_missing_phase_is_rejected(repository):
    with pytest.raises(GovernanceError, match="does not exist"):
        repository.validate_phase(99)


def test_unapproved_dependency_is_rejected(governance_root):
    path = governance_root / "project/roadmap.json"
    roadmap = load_json(path)
    roadmap["phases"][2]["status"] = "planned"
    roadmap["phases"][2]["human_approval_status"] = "pending"
    write_json(path, roadmap)

    with pytest.raises(GovernanceError, match="confirmed approval"):
        GovernanceRepository(governance_root).validate_phase(3)


def test_dependency_head_must_match_approved_dependency(governance_root):
    path = governance_root / "project/phases/03-orders.json"
    phase = load_json(path)
    phase["dependency_head"] = "0" * 40
    write_json(path, phase)

    with pytest.raises(GovernanceError, match="dependency_head differs"):
        GovernanceRepository(governance_root).validate_phase(3)


def test_phase_uses_main_as_unresolved_baseline(repository):
    phase = repository.validate_phase(3)

    assert phase["base_ref"] == "main"
    assert "base_sha" not in phase


def test_active_candidate_does_not_invalidate_historical_phase(repository):
    phase = repository.validate_phase(3)

    assert phase["status"] == "approved"


def test_active_candidate_dependency_must_match_manifest(governance_root):
    path = governance_root / "project/state.json"
    state = load_json(path)
    state["active_candidate"] = {
        "phase": 7,
        "branch": "phase/07-integrations",
        "base_ref": "main",
        "actual_base_sha": "09d73050f1df9d52b13e61ae87a26db4b26f365c",
        "dependency_head": "0" * 40,
    }
    write_json(path, state)

    with pytest.raises(GovernanceError, match="active_candidate dependency_head differs"):
        GovernanceRepository(governance_root).validate_phase(7)


def test_render_implementation_requires_plan_approval(repository):
    with pytest.raises(GovernanceError, match="plan approval"):
        repository.render("implementation", 7)


def test_render_review_requires_complete_implementation(governance_root):
    phase_path = governance_root / "project/phases/07-integrations.json"
    phase = load_json(phase_path)
    phase["plan_status"] = "approved"
    phase["implementation_status"] = "in_progress"
    phase["status"] = "in_progress"
    write_json(phase_path, phase)

    repository = GovernanceRepository(governance_root)
    with pytest.raises(GovernanceError, match="implementation is complete"):
        repository.render("review", 7)


def test_render_qa_requires_complete_review(governance_root):
    phase_path = governance_root / "project/phases/07-integrations.json"
    phase = load_json(phase_path)
    phase["plan_status"] = "approved"
    phase["implementation_status"] = "complete"
    phase["review_status"] = "in_progress"
    phase["status"] = "candidate"
    write_json(phase_path, phase)

    repository = GovernanceRepository(governance_root)
    with pytest.raises(GovernanceError, match="review is complete"):
        repository.render("qa-security", 7)


def test_approval_prompt_is_human_only(repository):
    with pytest.raises(GovernanceError, match="Human Approver"):
        repository.render("approval", 7)


def test_unknown_checkpoint_is_rejected(repository):
    with pytest.raises(GovernanceError, match="unknown checkpoint"):
        repository.render("unknown", 7)


def test_cli_validate_state(governance_root, capsys):
    exit_code = main(["--root", str(governance_root), "validate-state"])

    assert exit_code == 0
    assert "OK: official state is valid." in capsys.readouterr().out


def test_cli_validate_all(governance_root, capsys):
    exit_code = main(["--root", str(governance_root), "validate-all"])

    assert exit_code == 0
    assert "OK: all governance artifacts are valid." in capsys.readouterr().out
