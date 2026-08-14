#!/usr/bin/env python3
"""Read-only validator and prompt renderer for Vidalys Flow governance."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SENSITIVE_OUTPUT_PATTERNS = (
    re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile("gh" + r"[pousr]_[A-Za-z0-9]{20,}"),
    re.compile("AK" + r"IA[0-9A-Z]{16}"),
    re.compile("xo" + r"x[baprs]-[A-Za-z0-9-]{10,}"),
)

PHASE_STATUSES = {"planned", "in_progress", "candidate", "approved", "rejected"}
PLAN_STATUSES = {"pending", "approved", "rejected"}
IMPLEMENTATION_STATUSES = {"blocked", "pending", "in_progress", "complete"}
REVIEW_STATUSES = {"blocked", "pending", "in_progress", "complete", "changes_requested"}
QA_STATUSES = {"blocked", "pending", "in_progress", "go", "no_go"}
HUMAN_STATUSES = {"pending", "approved", "rejected"}
CHECKPOINTS = {"planning", "implementation", "review", "qa-security", "approval"}
ROLES = {
    "planning": "Planning Agent",
    "implementation": "Implementation Agent",
    "review": "Review Agent",
    "qa-security": "QA and Security Agent",
}
DEFAULT_HANDOFF_FIELDS = {
    "schema_version", "phase_id", "phase_name", "status", "branch", "base_sha", "head_sha", "commits",
    "delivered_scope", "models", "migrations", "tests", "scans", "ci", "organization_isolation",
    "legacy_reuse", "deferred", "risks", "blockers", "human_approval",
}
PHASE_REQUIRED_FIELDS = {
    "schema_version", "id", "name", "dependency_phase", "dependency_head", "base_ref", "branch", "status",
    "plan_status", "implementation_status", "review_status", "qa_status", "human_approval_status",
    "allowed_status_values", "allowed_apps", "forbidden_apps", "expected_models", "expected_features",
    "deferred_features", "states", "snapshots", "idempotency", "money_rules", "authorization", "migrations",
    "tests", "coverage", "ci", "documentation", "acceptance_criteria", "checks", "report_format",
    "handoff_format", "allowed_scope", "forbidden_scope",
}
TEMPLATE_TOKENS = {
    "planning": {"CHECKPOINT", "ROLE", "PHASE_ID", "PHASE_NAME", "DEPENDENCY_HEAD", "BASE_REF", "BRANCH", "ALLOWED_SCOPE", "FORBIDDEN_SCOPE", "CHECKS", "REPORT_FORMAT"},
    "implementation": {"CHECKPOINT", "ROLE", "PHASE_ID", "PHASE_NAME", "DEPENDENCY_HEAD", "BASE_REF", "BRANCH", "ALLOWED_SCOPE", "FORBIDDEN_SCOPE", "CHECKS", "REPORT_FORMAT"},
    "review": {"CHECKPOINT", "ROLE", "PHASE_ID", "PHASE_NAME", "DEPENDENCY_HEAD", "BASE_REF", "BRANCH", "ALLOWED_SCOPE", "FORBIDDEN_SCOPE", "CHECKS", "REPORT_FORMAT"},
    "qa-security": {"CHECKPOINT", "ROLE", "PHASE_ID", "PHASE_NAME", "DEPENDENCY_HEAD", "BASE_REF", "BRANCH", "ALLOWED_SCOPE", "FORBIDDEN_SCOPE", "CHECKS", "REPORT_FORMAT"},
    "approval": {"PHASE_ID", "PHASE_NAME", "DEPENDENCY_HEAD", "BASE_REF", "BRANCH"},
}


class GovernanceError(Exception):
    """A governance artifact or requested transition is invalid."""


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GovernanceError(f"{label} must be a JSON object")
    return value


def _require_fields(data: dict[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(fields - data.keys())
    if missing:
        raise GovernanceError(f"{label} is missing fields: {', '.join(missing)}")


def _require_sha(value: Any, label: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not SHA_PATTERN.fullmatch(value):
        raise GovernanceError(f"{label} must be a lowercase 40-character SHA")


def _require_string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise GovernanceError(f"{label} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise GovernanceError(f"{label} must not be empty")
    return value


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


class GovernanceRepository:
    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()

    def _path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if path != self.root and self.root not in path.parents:
            raise GovernanceError(f"path escapes repository: {relative}")
        return path

    def load_json(self, relative: str) -> dict[str, Any]:
        path = self._path(relative)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GovernanceError(f"cannot read {relative}: {exc}") from exc
        try:
            return _require_mapping(json.loads(content), relative)
        except json.JSONDecodeError as exc:
            raise GovernanceError(f"invalid JSON in {relative}: {exc}") from exc

    def state(self) -> dict[str, Any]:
        return self.load_json("project/state.json")

    def roadmap(self) -> dict[str, Any]:
        return self.load_json("project/roadmap.json")

    def phase_path(self, phase_id: int) -> Path:
        matches = sorted(self._path("project/phases").glob(f"{phase_id:02d}-*.json"))
        if not matches:
            raise GovernanceError(f"phase {phase_id:02d} does not exist")
        if len(matches) != 1:
            raise GovernanceError(f"phase {phase_id:02d} has multiple manifests")
        return matches[0]

    def phase(self, phase_id: int) -> dict[str, Any]:
        path = self.phase_path(phase_id)
        return self.load_json(str(path.relative_to(self.root)))

    def validate_state(self) -> dict[str, Any]:
        state = self.state()
        _require_fields(state, {"schema_version", "product", "repository", "approved_phase", "approved_phase_name", "approved_phase_head", "baseline_branch", "next_phase", "next_phase_name", "active_candidate", "human_approval_required"}, "project/state.json")
        if state["schema_version"] != 2:
            raise GovernanceError("unsupported state schema_version")
        if state["product"] != "Vidalys Flow" or state["repository"] != "Brunohvg/vidalys-flow":
            raise GovernanceError("state identifies a different product or repository")
        if "approved_head" in state or "default_branch" in state:
            raise GovernanceError("state contains an obsolete ambiguous baseline field")
        _require_sha(state["approved_phase_head"], "state approved_phase_head")
        if not isinstance(state["approved_phase"], int) or state["approved_phase"] < 0:
            raise GovernanceError("approved_phase must be a non-negative integer")
        if state["next_phase"] != state["approved_phase"] + 1:
            raise GovernanceError("next_phase must immediately follow approved_phase")
        if state["baseline_branch"] != "main":
            raise GovernanceError("baseline_branch must be main")
        if state["active_candidate"] is not None:
            candidate = _require_mapping(state["active_candidate"], "active_candidate")
            _require_fields(candidate, {"phase", "branch", "base_ref", "actual_base_sha", "dependency_head"}, "active_candidate")
            _require_sha(candidate["actual_base_sha"], "active_candidate actual_base_sha")
            _require_sha(candidate["dependency_head"], "active_candidate dependency_head")
            if candidate["phase"] != state["next_phase"] or candidate["base_ref"] != state["baseline_branch"]:
                raise GovernanceError("active_candidate must describe the next phase on the baseline branch")
        if state["human_approval_required"] is not True:
            raise GovernanceError("human_approval_required must be true")
        return state

    def validate_roadmap(self) -> dict[str, Any]:
        state = self.validate_state()
        roadmap = self.roadmap()
        _require_fields(roadmap, {"schema_version", "phases"}, "project/roadmap.json")
        if roadmap["schema_version"] != 1 or not isinstance(roadmap["phases"], list):
            raise GovernanceError("invalid roadmap schema")
        phases: dict[int, dict[str, Any]] = {}
        required = {"id", "name", "status", "dependencies", "approved_sha", "branch", "handoff", "domains", "human_approval_status", "known_risks"}
        for phase_value in roadmap["phases"]:
            phase = _require_mapping(phase_value, "roadmap phase")
            _require_fields(phase, required, "roadmap phase")
            phase_id = phase["id"]
            if not isinstance(phase_id, int) or phase_id < 0 or phase_id in phases:
                raise GovernanceError("roadmap phase ids must be unique non-negative integers")
            if phase["status"] not in PHASE_STATUSES:
                raise GovernanceError(f"roadmap phase {phase_id} has invalid status")
            if phase["human_approval_status"] not in HUMAN_STATUSES:
                raise GovernanceError(f"roadmap phase {phase_id} has invalid human approval status")
            if not isinstance(phase["dependencies"], list) or any(not isinstance(dependency, int) for dependency in phase["dependencies"]):
                raise GovernanceError(f"roadmap phase {phase_id} has invalid dependencies")
            _require_sha(phase["approved_sha"], f"roadmap phase {phase_id} approved_sha", nullable=True)
            phases[phase_id] = phase
        if sorted(phases) != list(range(0, 11)):
            raise GovernanceError("roadmap must contain phases 0 through 10 exactly once")
        for phase_id, phase in phases.items():
            for dependency in phase["dependencies"]:
                if dependency not in phases or dependency >= phase_id:
                    raise GovernanceError(f"roadmap phase {phase_id} has an invalid dependency")
            if phase_id <= state["approved_phase"]:
                if phase["status"] != "approved" or phase["human_approval_status"] != "approved":
                    raise GovernanceError(f"roadmap phase {phase_id} must reflect confirmed approval")
            elif phase["approved_sha"] is not None or phase["human_approval_status"] == "approved":
                raise GovernanceError(f"future roadmap phase {phase_id} cannot be approved")
        approved = phases[state["approved_phase"]]
        if approved["approved_sha"] != state["approved_phase_head"]:
            raise GovernanceError("roadmap approved SHA differs from state approved_phase_head")
        if approved["name"] != state["approved_phase_name"]:
            raise GovernanceError("roadmap approved phase name differs from state")
        if phases[state["next_phase"]]["name"] != state["next_phase_name"]:
            raise GovernanceError("roadmap next phase name differs from state")
        return roadmap

    def validate_source_reference(self) -> dict[str, Any]:
        source = self.load_json("project/source_reference.json")
        _require_fields(source, {"schema_version", "repository", "branch", "frozen_sha", "mode", "runtime_access", "database_access", "domains_no_longer_consulted", "domains_still_consultable", "rules"}, "project/source_reference.json")
        _require_sha(source["frozen_sha"], "source frozen_sha")
        if source["mode"] != "read_only" or source["runtime_access"] is not False:
            raise GovernanceError("source reference must be read-only with no runtime access")
        if source["database_access"] is not False:
            raise GovernanceError("source reference database access must be false")
        return source

    def validate_phase(self, phase_id: int) -> dict[str, Any]:
        state = self.validate_state()
        roadmap = self.validate_roadmap()
        manifest = self.phase(phase_id)
        _require_fields(manifest, PHASE_REQUIRED_FIELDS, f"phase {phase_id:02d}")
        if manifest["schema_version"] != 2 or manifest["id"] != phase_id:
            raise GovernanceError(f"phase {phase_id:02d} identity or schema is invalid")
        if "base_sha" in manifest:
            raise GovernanceError(f"phase {phase_id:02d} must not invent an actual baseline SHA")
        _require_sha(manifest["dependency_head"], f"phase {phase_id:02d} dependency_head")
        if not isinstance(manifest["dependency_phase"], int):
            raise GovernanceError(f"phase {phase_id:02d} dependency_phase must be an integer")
        if manifest["base_ref"] != state["baseline_branch"]:
            raise GovernanceError(f"phase {phase_id:02d} base_ref differs from baseline_branch")

        status_sets = {"status": PHASE_STATUSES, "plan_status": PLAN_STATUSES, "implementation_status": IMPLEMENTATION_STATUSES, "review_status": REVIEW_STATUSES, "qa_status": QA_STATUSES, "human_approval_status": HUMAN_STATUSES}
        allowed_values = _require_mapping(manifest["allowed_status_values"], "allowed_status_values")
        for field, canonical in status_sets.items():
            if manifest[field] not in canonical:
                raise GovernanceError(f"phase {phase_id:02d} has invalid {field}")
            declared = allowed_values.get(field)
            if not isinstance(declared, list) or set(declared) != canonical:
                raise GovernanceError(f"phase {phase_id:02d} declares divergent values for {field}")

        roadmap_phases = {phase["id"]: phase for phase in roadmap["phases"]}
        roadmap_phase = roadmap_phases.get(phase_id)
        dependency = manifest["dependency_phase"]
        dependency_phase = roadmap_phases.get(dependency)
        if roadmap_phase is None or roadmap_phase["dependencies"] != [dependency]:
            raise GovernanceError(f"phase {phase_id:02d} dependency differs from roadmap")
        if roadmap_phase["branch"] != manifest["branch"]:
            raise GovernanceError(f"phase {phase_id:02d} branch differs from roadmap")
        if state["active_candidate"] is not None and state["active_candidate"]["phase"] == phase_id:
            if state["active_candidate"]["branch"] != manifest["branch"]:
                raise GovernanceError("active_candidate branch differs from phase manifest")
        if dependency_phase is None or dependency_phase["status"] != "approved" or dependency_phase["human_approval_status"] != "approved" or dependency_phase["approved_sha"] is None:
            raise GovernanceError(f"phase {phase_id:02d} dependency {dependency} is not approved")
        if manifest["dependency_head"] != dependency_phase["approved_sha"]:
            raise GovernanceError(f"phase {phase_id:02d} dependency_head differs from roadmap approved SHA")
        if state["active_candidate"] is not None and state["active_candidate"]["phase"] == phase_id:
            candidate = state["active_candidate"]
            if candidate["dependency_head"] != manifest["dependency_head"]:
                raise GovernanceError("active_candidate dependency_head differs from phase manifest")
        if phase_id > state["approved_phase"] and (manifest["status"] == "approved" or manifest["human_approval_status"] == "approved"):
            raise GovernanceError("an agent cannot approve a future phase")
        if manifest["status"] == "planned":
            if manifest["implementation_status"] not in {"blocked", "pending"}:
                raise GovernanceError("a planned phase cannot have implementation progress")
            if manifest["review_status"] != "blocked" or manifest["qa_status"] != "blocked":
                raise GovernanceError("review and QA must be blocked for a planned phase")
        for field in ("allowed_apps", "forbidden_apps", "allowed_scope", "forbidden_scope", "checks"):
            _require_string_list(manifest[field], f"phase {phase_id:02d} {field}")
        if set(manifest["allowed_apps"]) & set(manifest["forbidden_apps"]):
            raise GovernanceError(f"phase {phase_id:02d} app scope overlaps")
        if manifest["coverage"].get("minimum_total_percent") != 85:
            raise GovernanceError(f"phase {phase_id:02d} coverage minimum must be 85")
        if manifest["migrations"].get("legacy_reuse") is not False:
            raise GovernanceError(f"phase {phase_id:02d} cannot reuse legacy migrations")
        return manifest

    def validate_handoff(self, relative: str) -> dict[str, Any]:
        path = self._path(relative)
        handoff_root = self._path("project/handoffs")
        if handoff_root not in path.parents or path.suffix != ".json":
            raise GovernanceError("handoff must be a JSON file under project/handoffs")
        handoff = self.load_json(str(path.relative_to(self.root)))
        _require_fields(handoff, DEFAULT_HANDOFF_FIELDS, relative)
        if handoff["schema_version"] != 1:
            raise GovernanceError("unsupported handoff schema_version")
        phase_id = handoff["phase_id"]
        if not isinstance(phase_id, int) or phase_id < 1:
            raise GovernanceError("handoff phase_id must be a positive integer")
        _require_sha(handoff["base_sha"], "handoff base_sha", nullable=phase_id == 1)
        _require_sha(handoff["head_sha"], "handoff head_sha")
        if not isinstance(handoff["commits"], list) or not handoff["commits"]:
            raise GovernanceError("handoff commits must not be empty")
        for commit in handoff["commits"]:
            commit_data = _require_mapping(commit, "handoff commit")
            _require_fields(commit_data, {"sha", "subject"}, "handoff commit")
            _require_sha(commit_data["sha"], "handoff commit SHA")
        human = _require_mapping(handoff["human_approval"], "handoff human_approval")
        _require_fields(human, {"status", "evidence"}, "handoff human_approval")
        if human["status"] not in HUMAN_STATUSES:
            raise GovernanceError("handoff has invalid human approval status")
        state = self.validate_state()
        roadmap = self.validate_roadmap()
        roadmap_phases = {phase["id"]: phase for phase in roadmap["phases"]}
        roadmap_phase = roadmap_phases.get(phase_id)
        if roadmap_phase is None:
            raise GovernanceError("handoff phase does not exist in roadmap")
        if handoff["status"] == "approved":
            if human["status"] != "approved" or phase_id > state["approved_phase"]:
                raise GovernanceError("handoff approval is not backed by official human approval")
            if handoff["head_sha"] != roadmap_phase["approved_sha"]:
                raise GovernanceError("approved handoff HEAD differs from roadmap")
        return handoff

    def validate_templates(self) -> None:
        for checkpoint, required_tokens in TEMPLATE_TOKENS.items():
            relative = f"prompts/templates/{checkpoint}.md"
            try:
                content = self._path(relative).read_text(encoding="utf-8")
            except OSError as exc:
                raise GovernanceError(f"cannot read {relative}: {exc}") from exc
            found = set(re.findall(r"\{\{([A-Z_]+)\}\}", content))
            if found != required_tokens:
                raise GovernanceError(f"{relative} has divergent tokens: expected {sorted(required_tokens)}, found {sorted(found)}")
        generated = self._path("prompts/generated")
        if generated.exists() and any(path.is_file() for path in generated.rglob("*")):
            raise GovernanceError("generated prompts must not be versioned")

    def validate_all(self) -> None:
        self.validate_state()
        self.validate_roadmap()
        self.validate_source_reference()
        constraints = self.load_json("project/constraints.json")
        if constraints.get("minimum_coverage_percent") != 85:
            raise GovernanceError("constraints minimum coverage must be 85")
        self.validate_templates()
        phase_paths = sorted(self._path("project/phases").glob("*.json"))
        if not phase_paths:
            raise GovernanceError("at least one phase manifest is required")
        for path in phase_paths:
            phase = self.load_json(str(path.relative_to(self.root)))
            if not isinstance(phase.get("id"), int):
                raise GovernanceError(f"{path.relative_to(self.root)} has no integer id")
            self.validate_phase(phase["id"])
        for path in sorted(self._path("project/handoffs").glob("*.json")):
            self.validate_handoff(str(path.relative_to(self.root)))

    def render(self, checkpoint: str, phase_id: int) -> str:
        if checkpoint not in CHECKPOINTS:
            raise GovernanceError(f"unknown checkpoint: {checkpoint}")
        if checkpoint == "approval":
            raise GovernanceError("approval prompts are exclusive to the Human Approver")
        manifest = self.validate_phase(phase_id)
        if checkpoint == "implementation" and manifest["plan_status"] != "approved":
            raise GovernanceError("implementation cannot be rendered before human plan approval")
        if checkpoint == "review" and manifest["implementation_status"] != "complete":
            raise GovernanceError("review cannot be rendered before implementation is complete")
        if checkpoint == "qa-security" and manifest["review_status"] != "complete":
            raise GovernanceError("QA cannot be rendered before review is complete")
        template = self._path(f"prompts/templates/{checkpoint}.md").read_text(encoding="utf-8")
        report_fields = manifest["report_format"].get("required_sections")
        _require_string_list(report_fields, "report required sections")
        values = {
            "CHECKPOINT": checkpoint, "ROLE": ROLES[checkpoint], "PHASE_ID": f"{phase_id:02d}",
            "PHASE_NAME": manifest["name"], "DEPENDENCY_HEAD": manifest["dependency_head"],
            "BASE_REF": manifest["base_ref"], "BRANCH": manifest["branch"],
            "ALLOWED_SCOPE": _bullets(manifest["allowed_scope"]), "FORBIDDEN_SCOPE": _bullets(manifest["forbidden_scope"]),
            "CHECKS": _bullets(manifest["checks"]), "REPORT_FORMAT": _bullets(report_fields),
        }
        for name, value in values.items():
            template = template.replace(f"{{{{{name}}}}}", value)
        if re.search(r"\{\{[A-Z_]+\}\}", template):
            raise GovernanceError("rendered template contains unresolved tokens")
        contract = self._path("AGENTS.md").read_text(encoding="utf-8").strip()
        manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        output = f"{template.strip()}\n\n## Contrato global obrigatório\n\n{contract}\n\n## Manifesto canônico da fase\n\n```json\n{manifest_json}\n```\n"
        for pattern in SENSITIVE_OUTPUT_PATTERNS:
            if pattern.search(output):
                raise GovernanceError("rendered output contains a possible secret")
        return output

    def status_text(self) -> str:
        state = self.validate_state()
        values = (("product", state["product"]), ("repository", state["repository"]), ("approved_phase", state["approved_phase"]), ("approved_phase_name", state["approved_phase_name"]), ("approved_phase_head", state["approved_phase_head"]), ("baseline_branch", state["baseline_branch"]), ("next_phase", state["next_phase"]), ("next_phase_name", state["next_phase_name"]), ("active_candidate", state["active_candidate"]), ("human_approval_required", state["human_approval_required"]))
        return "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in values)


def _phase_id(value: str) -> int:
    if not re.fullmatch(r"\d{1,2}", value):
        raise argparse.ArgumentTypeError("phase must be a one- or two-digit id")
    return int(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("validate-state")
    subparsers.add_parser("validate-roadmap")
    subparsers.add_parser("validate-templates")
    subparsers.add_parser("validate-all")
    validate_phase = subparsers.add_parser("validate-phase")
    validate_phase.add_argument("phase", type=_phase_id)
    validate_handoff = subparsers.add_parser("validate-handoff")
    validate_handoff.add_argument("file")
    render = subparsers.add_parser("render")
    render.add_argument("checkpoint", choices=sorted(CHECKPOINTS))
    render.add_argument("phase", type=_phase_id)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repository = GovernanceRepository()
    try:
        if args.command == "status":
            print(repository.status_text())
        elif args.command == "validate-state":
            repository.validate_state(); print("OK: official state is valid.")
        elif args.command == "validate-roadmap":
            repository.validate_roadmap(); print("OK: roadmap is valid.")
        elif args.command == "validate-templates":
            repository.validate_templates(); print("OK: prompt templates are valid and no generated prompts are stored.")
        elif args.command == "validate-all":
            repository.validate_all(); print("OK: all governance artifacts are valid.")
        elif args.command == "validate-phase":
            repository.validate_phase(args.phase); print(f"OK: phase {args.phase:02d} is valid.")
        elif args.command == "validate-handoff":
            repository.validate_handoff(args.file); print(f"OK: handoff {args.file} is valid.")
        elif args.command == "render":
            print(repository.render(args.checkpoint, args.phase), end="")
        else:
            raise GovernanceError(f"unsupported command: {args.command}")
    except GovernanceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
