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

    assert state["approved_phase"] == 2
    assert state["active_candidate"] is None


def test_invalid_approved_sha_is_rejected(governance_root):
    path = governance_root / "project/state.json"
    state = load_json(path)
    state["approved_head"] = "invalid"
    write_json(path, state)

    with pytest.raises(GovernanceError, match="approved_head"):
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


def test_phase_base_must_match_approved_head(governance_root):
    path = governance_root / "project/phases/03-orders.json"
    phase = load_json(path)
    phase["base_sha"] = "0" * 40
    write_json(path, phase)

    with pytest.raises(GovernanceError, match="base differs"):
        GovernanceRepository(governance_root).validate_phase(3)


def test_invalid_manifest_is_rejected(governance_root):
    path = governance_root / "project/phases/03-orders.json"
    phase = load_json(path)
    del phase["expected_models"]
    write_json(path, phase)

    with pytest.raises(GovernanceError, match="missing fields"):
        GovernanceRepository(governance_root).validate_phase(3)


def test_incomplete_handoff_is_rejected(governance_root):
    path = governance_root / "project/handoffs/phase-02.json"
    handoff = load_json(path)
    del handoff["tests"]
    write_json(path, handoff)

    with pytest.raises(GovernanceError, match="missing fields"):
        GovernanceRepository(governance_root).validate_handoff("project/handoffs/phase-02.json")


def test_implementation_requires_approved_plan(repository):
    with pytest.raises(GovernanceError, match="before human plan approval"):
        repository.render("implementation", 3)


def test_agent_cannot_self_approve_phase(governance_root):
    path = governance_root / "project/phases/03-orders.json"
    phase = load_json(path)
    phase["human_approval_status"] = "approved"
    write_json(path, phase)

    with pytest.raises(GovernanceError, match="cannot approve"):
        GovernanceRepository(governance_root).validate_phase(3)


def test_rendering_is_deterministic(repository):
    first = repository.render("planning", 3)
    second = repository.render("planning", 3)

    assert first == second
    assert "Planning Agent" in first
    assert "b28a019871274e9da1ca1cb65043c5e208b0e727" in first


def test_environment_secrets_are_never_rendered(repository, monkeypatch):
    sensitive_value = "gh" + "p_" + ("a" * 24)
    monkeypatch.setenv("UNRELATED_CREDENTIAL", sensitive_value)

    output = repository.render("planning", 3)

    assert sensitive_value not in output


def test_checkpoint_templates_render_only_after_prerequisites(governance_root):
    path = governance_root / "project/phases/03-orders.json"
    phase = load_json(path)
    phase["plan_status"] = "approved"
    phase["implementation_status"] = "pending"
    write_json(path, phase)
    repository = GovernanceRepository(governance_root)

    implementation = repository.render("implementation", 3)

    phase["status"] = "in_progress"
    phase["implementation_status"] = "complete"
    phase["review_status"] = "pending"
    write_json(path, phase)
    review = repository.render("review", 3)

    phase["review_status"] = "complete"
    phase["qa_status"] = "pending"
    write_json(path, phase)
    qa = repository.render("qa-security", 3)

    assert "Implementation Agent" in implementation
    assert "Review Agent" in review
    assert "QA and Security Agent" in qa


def test_approval_template_cannot_be_rendered_by_agent(repository):
    with pytest.raises(GovernanceError, match="Human Approver"):
        repository.render("approval", 3)


def test_cli_errors_return_nonzero(capsys):
    assert main(["render", "implementation", "03"]) == 1
    assert "before human plan approval" in capsys.readouterr().err

    assert main(["render", "approval", "03"]) == 1
    assert "Human Approver" in capsys.readouterr().err


def test_handoff_path_cannot_escape_repository(repository):
    with pytest.raises(GovernanceError, match="handoff must be"):
        repository.validate_handoff("project/state.json")
