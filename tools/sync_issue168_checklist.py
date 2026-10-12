#!/usr/bin/env python3
"""Validate and sync issue #168 checklist YAML to Google Sheets.

The sheet is updated in one direction only. This program deliberately writes
only the managed cells listed in SHEET_SPECS; test results and evidence cells
are never included in a write request.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKLIST = ROOT / "practice" / "D" / "issue168" / "checklist.yaml"
CREDENTIALS_ENV = "ISSUE168_GOOGLE_CREDENTIALS"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SYNC_METADATA_SHEET = "00_진행현황"
SYNC_METADATA_RANGE = "A9:D9"

ERROR_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")
SHEET_CODE_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
RUNTIME_ERROR_SOURCE_GLOBS = (
    "knowledge/skills/*.jsonld",
    "ros2_ws/src/ready2go_runner/ready2go_runner/core/interpreter.py",
    "ros2_ws/src/ready2go_runner/ready2go_runner/core/run_report.py",
    "ros2_ws/src/ready2go_runner/ready2go_runner/core/step_console.py",
    "ros2_ws/src/ready2go_runner/ready2go_runner/adapters/ros_clients.py",
    "ros2_ws/src/ready2go_runner/ready2go_runner/nodes/mock_backend.py",
    "ros2_ws/src/ready2go_skills/ready2go_skills/core/skill_flow.py",
    "ros2_ws/src/ready2go_skills/ready2go_skills/nodes/skill_server.py",
    "ros2_ws/src/ready2go_vision/ready2go_vision/core/inspect_real.py",
    "ros2_ws/src/ready2go_vision/ready2go_vision/nodes/inspect_region.py",
)

SUPPORTED_SOURCE_TYPES = {
    "github_issue",
    "github_comment",
    "github_pull_request",
    "repository_file",
    "repository_files",
}
GITHUB_SOURCE_TYPES = {
    "github_issue",
    "github_comment",
    "github_pull_request",
}
GITHUB_HOST = "github.com"
GITHUB_REPOSITORY_PATH = "/Jik-Kim/ready2go"
GITHUB_NUMBERED_PATHS = {
    "github_issue": re.compile(rf"^{GITHUB_REPOSITORY_PATH}/issues/[1-9][0-9]*/?$"),
    "github_pull_request": re.compile(rf"^{GITHUB_REPOSITORY_PATH}/pull/[1-9][0-9]*/?$"),
}
GITHUB_COMMENT_PATH = re.compile(
    rf"^{GITHUB_REPOSITORY_PATH}/(?:issues|pull)/[1-9][0-9]*/?$"
)
GITHUB_COMMENT_FRAGMENT = re.compile(r"^issuecomment-[1-9][0-9]*$")
SPREADSHEET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

CONFIRMATION_TO_SHEET = {
    "B": {
        "confirmed": "확인 완료", "proposed": "확인 필요",
        "pending": "확인 필요", "not_applicable": "확인 필요",
    },
    "C": {
        "confirmed": "확인 완료", "proposed": "C 제안",
        "pending": "확인 필요", "implementation_needed": "구현 필요",
        "not_applicable": "확인 필요",
    },
    "E": {
        "confirmed": "확인 완료", "proposed": "E 조율안",
        "pending": "E 확인 필요", "not_applicable": "미입력",
    },
}

DECISION_TO_SHEET = {
    "confirmed": "확정",
    "approval_pending": "승인 대기",
    "b_card_pending": "B 카드 대기",
    "consistency_check": "정합성 확인",
    "team_decision_needed": "팀 결정 대기",
}

NODE_CARD_STATUS_TO_SHEET = {
    "draft_pending": "작성 전",
    "under_review": "검토 중",
    "confirmed": "확정",
}


@dataclass(frozen=True)
class SheetSpec:
    title: str
    header_row: int
    first_data_row: int
    last_data_row: int
    last_column: str
    managed_columns: dict[str, str]
    protected_headers: tuple[str, ...]


SHEET_SPECS = {
    "nodes": SheetSpec(
        title="01_노드카드",
        header_row=7,
        first_data_row=8,
        last_data_row=15,
        last_column="M",
        managed_columns={
            "A": "ID", "B": "노드", "C": "담당", "I": "카드 상태",
            "K": "현재 코드", "L": "B 확인",
        },
        protected_headers=(
            "시작 조건", "성공 시 끝 자세", "성공 output_json",
            "실패 코드·잔여 상태", "근거·PR", "C·E 검토",
        ),
    ),
    "scenarios": SheetSpec(
        title="02_시나리오시험",
        header_row=7,
        first_data_row=8,
        last_data_row=25,
        last_column="R",
        managed_columns={
            "A": "ID", "B": "상황", "C": "노드·오류 코드",
            "E": "C Runner 다음 행동", "O": "B 확인", "P": "C 확인",
            "Q": "E 확인", "R": "결정 상태",
        },
        protected_headers=(
            "B 로봇 상태", "사람 조치", "mock 결과", "실물 결과",
            "증적 링크", "판정", "구분", "선행 조건",
            "E pre/effect/errors", "TTS 시점·문구",
        ),
    ),
}


class ChecklistError(ValueError):
    """A validation error with an item-oriented message."""


class RuntimeCodeVisitor(ast.NodeVisitor):
    """Collect constants only from runtime locations that carry error codes."""

    def __init__(self) -> None:
        self.codes: set[str] = set()

    def _add_literals(self, node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                if ERROR_CODE_PATTERN.fullmatch(child.value):
                    self.codes.add(child.value)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id.endswith("_CODES") or target.id in {
                    "ERROR_TEXT", "NO_MOTION_BY_ACTION",
                }:
                    self._add_literals(node.value)
                elif (
                    target.id.isupper()
                    and isinstance(node.value, ast.Constant)
                    and node.value.value == target.id
                ):
                    self.codes.add(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(
                node.value, (ast.Tuple, ast.List)
            ):
                for target_item, value_item in zip(target.elts, node.value.elts):
                    if isinstance(target_item, ast.Attribute) and target_item.attr == "error_code":
                        self._add_literals(value_item)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        function_name = node.func.id if isinstance(node.func, ast.Name) else ""
        if function_name == "StepFailed":
            for argument in node.args[1:]:
                self._add_literals(argument)
        for keyword in node.keywords:
            if keyword.arg in {"error_code", "no_retry"}:
                self._add_literals(keyword.value)
        self.generic_visit(node)


def runtime_source_paths() -> list[Path]:
    paths: set[Path] = set()
    for pattern in RUNTIME_ERROR_SOURCE_GLOBS:
        paths.update(ROOT.glob(pattern))
    return sorted(path for path in paths if path.is_file())


def load_known_error_codes() -> tuple[set[str], list[str]]:
    """Read error codes from skill knowledge and executable Python sources."""
    codes: set[str] = set()
    errors: list[str] = []
    paths = runtime_source_paths()
    if not paths:
        return codes, ["runtime error-code sources were not found"]

    for path in paths:
        relative = path.relative_to(ROOT)
        try:
            if path.suffix == ".jsonld":
                payload = json.loads(path.read_text(encoding="utf-8"))
                for value in payload.get("skills", {}).values():
                    declared = value.get("errors", []) if isinstance(value, dict) else []
                    if not isinstance(declared, list):
                        errors.append(f"{relative}: skill errors must be a list")
                        continue
                    for code in declared:
                        if isinstance(code, str) and ERROR_CODE_PATTERN.fullmatch(code):
                            codes.add(code)
            else:
                visitor = RuntimeCodeVisitor()
                visitor.visit(
                    ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
                )
                codes.update(visitor.codes)
        except (OSError, UnicodeError, json.JSONDecodeError, SyntaxError) as exc:
            errors.append(f"cannot read runtime error-code source {relative}: {exc}")
    return codes, errors


def load_checklist(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        content = path.read_bytes()
        data = yaml.safe_load(content.decode("utf-8"))
    except FileNotFoundError as exc:
        raise ChecklistError(f"checklist file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise ChecklistError(f"checklist is not valid UTF-8: {path}") from exc
    except yaml.YAMLError as exc:
        raise ChecklistError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ChecklistError("checklist root must be a mapping")
    return data, content


def require_fields(item: dict[str, Any], fields: Iterable[str], label: str) -> list[str]:
    return [f"{label}.{field} is missing" for field in fields if item.get(field) in (None, "")]


def duplicate_ids(items: list[dict[str, Any]]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        item_id = str(item.get("id", ""))
        if item_id in seen:
            duplicates.add(item_id)
        seen.add(item_id)
    return duplicates


def validate_sources(item: dict[str, Any], label: str, catalog: dict[str, Any]) -> list[str]:
    sources = item.get("sources", [])
    if not isinstance(sources, list):
        return [f"{label}.sources must be a list"]
    if not sources:
        return [f"{label}.sources must not be empty"]
    errors: list[str] = []
    for source in sources:
        if not isinstance(source, str):
            errors.append(f"{label}.sources contains a non-string source")
        elif source not in catalog:
            errors.append(f"{label}.sources references unknown source: {source}")
    return errors


def validate_codes(codes: Any, label: str, known_codes: set[str]) -> list[str]:
    if not isinstance(codes, list):
        return [f"{label} must be a list"]
    errors: list[str] = []
    for code in codes:
        if not isinstance(code, str):
            errors.append(f"{label} contains a non-string code")
        elif code.startswith("[") and code.endswith("]"):
            continue
        elif code not in known_codes:
            errors.append(f"{label} contains undefined error code: {code}")
    return errors


def validate_string_fields(
    item: dict[str, Any], fields: Iterable[str], label: str
) -> list[str]:
    return [
        f"{label}.{field} must be a string"
        for field in fields
        if field in item and not isinstance(item[field], str)
    ]


def allowed_statuses(value: Any, label: str) -> tuple[set[str], list[str]]:
    if not isinstance(value, list):
        return set(), [f"{label} must be a list"]
    if not all(isinstance(status, str) for status in value):
        return set(), [f"{label} must contain only strings"]
    return set(value), []


def scenario_codes(scenario: dict[str, Any]) -> list[Any]:
    values = scenario.get("trigger_codes", [])
    codes = list(values) if isinstance(values, list) else []
    if "trigger_code" in scenario:
        codes.append(scenario["trigger_code"])
    return codes


def validate_sheet_trigger(scenario: dict[str, Any], label: str) -> list[str]:
    trigger = scenario.get("sheet_trigger")
    if not isinstance(trigger, str):
        return [f"{label}.sheet_trigger must be a string"]
    declared = {
        code for code in scenario_codes(scenario)
        if isinstance(code, str) and not (code.startswith("[") and code.endswith("]"))
    }
    displayed = set(SHEET_CODE_PATTERN.findall(trigger))
    if displayed != declared:
        return [
            f"{label}.sheet_trigger codes differ from trigger_codes: "
            f"expected {sorted(declared)}, found {sorted(displayed)}"
        ]
    return []


def validate_repository_path(source_id: str, field: str, value: Any) -> list[str]:
    label = f"source_catalog.{source_id}.{field}"
    if not isinstance(value, str) or not value:
        return [f"{label} must be a non-empty string"]
    root = ROOT.resolve()
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return [f"{label} must stay inside the repository: {value}"]
    if not candidate.is_file():
        return [f"{label} does not exist: {value}"]
    return []


def validate_github_url(source_id: str, source_type: str, value: Any) -> list[str]:
    label = f"source_catalog.{source_id}.url"
    if not isinstance(value, str) or not value:
        return [f"{label} must be a non-empty string"]

    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != GITHUB_HOST:
        return [f"{label} must use https://{GITHUB_HOST}"]
    if parsed.query or parsed.params:
        return [f"{label} must not contain query parameters"]

    if source_type == "github_comment":
        if not GITHUB_COMMENT_PATH.fullmatch(parsed.path):
            return [
                f"{label} must point to {GITHUB_REPOSITORY_PATH}/issues/<number> "
                "or /pull/<number>"
            ]
        if not GITHUB_COMMENT_FRAGMENT.fullmatch(parsed.fragment):
            return [f"{label} must include #issuecomment-<number>"]
        return []

    pattern = GITHUB_NUMBERED_PATHS[source_type]
    if not pattern.fullmatch(parsed.path) or parsed.fragment:
        kind = "issues" if source_type == "github_issue" else "pull"
        return [
            f"{label} must match https://{GITHUB_HOST}{GITHUB_REPOSITORY_PATH}/"
            f"{kind}/<number>"
        ]
    return []


def validate_sheet_config(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["root.sheet must be a mapping"]

    errors: list[str] = []
    spreadsheet_id = value.get("spreadsheet_id")
    if not isinstance(spreadsheet_id, str) or not spreadsheet_id:
        errors.append("root.sheet.spreadsheet_id must be a non-empty string")
    elif not SPREADSHEET_ID_PATTERN.fullmatch(spreadsheet_id):
        errors.append("root.sheet.spreadsheet_id contains unsupported characters")

    sheet_url = value.get("url")
    if not isinstance(sheet_url, str) or not sheet_url:
        errors.append("root.sheet.url must be a non-empty string")
    elif isinstance(spreadsheet_id, str) and spreadsheet_id:
        parsed = urlparse(sheet_url)
        expected_path = f"/spreadsheets/d/{spreadsheet_id}"
        if (
            parsed.scheme != "https"
            or parsed.netloc != "docs.google.com"
            or parsed.path.rstrip("/") not in {expected_path, f"{expected_path}/edit"}
        ):
            errors.append("root.sheet.url must match root.sheet.spreadsheet_id")

    tabs = value.get("tabs")
    expected_tabs = {
        "progress": SYNC_METADATA_SHEET,
        "nodes": SHEET_SPECS["nodes"].title,
        "scenarios": SHEET_SPECS["scenarios"].title,
    }
    if not isinstance(tabs, dict):
        errors.append("root.sheet.tabs must be a mapping")
    else:
        for key, expected in expected_tabs.items():
            actual = tabs.get(key)
            if not isinstance(actual, str):
                errors.append(f"root.sheet.tabs.{key} must be a string")
            elif actual != expected:
                errors.append(
                    f"root.sheet.tabs.{key} must be '{expected}', found '{actual}'"
                )

    sync_direction = value.get("sync_direction")
    if not isinstance(sync_direction, str):
        errors.append("root.sheet.sync_direction must be a string")
    elif sync_direction != "yaml_to_sheet":
        errors.append("root.sheet.sync_direction must be 'yaml_to_sheet'")
    return errors


def validate_source_catalog_entry(source_id: str, source: Any) -> list[str]:
    label = f"source_catalog.{source_id}"
    if not isinstance(source, dict):
        return [f"{label} must be a mapping"]

    source_type = source.get("type")
    if not isinstance(source_type, str) or source_type not in SUPPORTED_SOURCE_TYPES:
        return [f"{label}.type is unsupported: {source_type}"]

    errors: list[str] = []
    if source_type in GITHUB_SOURCE_TYPES:
        errors += validate_github_url(source_id, source_type, source.get("url"))
    elif source_type == "repository_file":
        errors += validate_repository_path(source_id, "path", source.get("path"))
    elif source_type == "repository_files":
        source_paths = source.get("paths")
        if not isinstance(source_paths, list) or not source_paths:
            errors.append(f"{label}.paths must be a non-empty list")
        else:
            for index, source_path in enumerate(source_paths):
                errors += validate_repository_path(
                    source_id, f"paths[{index}]", source_path
                )

    if "value" in source or "values" in source:
        errors.append(f"{label} must reference a path/key, not copy raw values")
    return errors


def validate_checklist(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    known_codes, source_errors = load_known_error_codes()
    errors += source_errors
    errors += require_fields(
        data,
        ("schema_version", "checklist_id", "phase", "owner", "source_catalog", "status_legend"),
        "root",
    )
    errors += validate_sheet_config(data.get("sheet"))
    nodes = data.get("node_cards")
    scenarios = data.get("scenarios")
    failures = data.get("node_failure_cases")
    if not isinstance(nodes, list):
        errors.append("root.node_cards must be a list")
        nodes = []
    if not isinstance(scenarios, list):
        errors.append("root.scenarios must be a list")
        scenarios = []
    if not isinstance(failures, list):
        errors.append("root.node_failure_cases must be a list")
        failures = []

    node_items = [item for item in nodes if isinstance(item, dict)]
    scenario_items = [item for item in scenarios if isinstance(item, dict)]
    failure_items = [item for item in failures if isinstance(item, dict)]
    for index, item in enumerate(nodes):
        if not isinstance(item, dict):
            errors.append(f"root.node_cards[{index}] must be a mapping")
    for index, item in enumerate(scenarios):
        if not isinstance(item, dict):
            errors.append(f"root.scenarios[{index}] must be a mapping")
    for index, item in enumerate(failures):
        if not isinstance(item, dict):
            errors.append(f"root.node_failure_cases[{index}] must be a mapping")

    if len(nodes) != 8:
        errors.append(f"root.node_cards must contain 8 items, found {len(nodes)}")
    if len(scenarios) != 18:
        errors.append(f"root.scenarios must contain 18 items, found {len(scenarios)}")
    for duplicate in sorted(duplicate_ids(node_items) | duplicate_ids(scenario_items)):
        errors.append(f"duplicate id: {duplicate}")

    expected_nodes = {f"N-{i:02d}" for i in range(1, 9)}
    expected_scenarios = {f"S-{i:02d}" for i in range(1, 19)}
    actual_nodes = {str(item.get("id", "")) for item in node_items}
    actual_scenarios = {str(item.get("id", "")) for item in scenario_items}
    if actual_nodes != expected_nodes:
        errors.append(f"node IDs differ: expected {sorted(expected_nodes)}, found {sorted(actual_nodes)}")
    if actual_scenarios != expected_scenarios:
        errors.append(
            f"scenario IDs differ: expected {sorted(expected_scenarios)}, found {sorted(actual_scenarios)}"
        )

    raw_catalog = data.get("source_catalog")
    catalog = raw_catalog if isinstance(raw_catalog, dict) else {}
    if not isinstance(raw_catalog, dict):
        errors.append("root.source_catalog must be a mapping")
    raw_legend = data.get("status_legend")
    status_legend = raw_legend if isinstance(raw_legend, dict) else {}
    if not isinstance(raw_legend, dict):
        errors.append("root.status_legend must be a mapping")
    allowed_confirmation, legend_errors = allowed_statuses(
        status_legend.get("confirmation"), "root.status_legend.confirmation"
    )
    errors += legend_errors
    allowed_implementation, legend_errors = allowed_statuses(
        status_legend.get("implementation"), "root.status_legend.implementation"
    )
    errors += legend_errors
    allowed_decision, legend_errors = allowed_statuses(
        status_legend.get("decision"), "root.status_legend.decision"
    )
    errors += legend_errors

    for node in node_items:
        label = str(node.get("id", "node<?>"))
        errors += require_fields(
            node,
            ("id", "name", "owner", "action", "card_status", "owner_confirmation", "sources"),
            label,
        )
        errors += validate_string_fields(
            node,
            ("id", "name", "owner", "action"),
            label,
        )
        owner_confirmation = node.get("owner_confirmation")
        if not isinstance(owner_confirmation, str):
            errors.append(f"{label}.owner_confirmation must be a string")
        elif owner_confirmation not in allowed_confirmation:
            errors.append(f"{label}.owner_confirmation has an invalid status")
        elif owner_confirmation not in CONFIRMATION_TO_SHEET["B"]:
            errors.append(f"{label}.owner_confirmation cannot be projected for B")
        card_status = node.get("card_status")
        if not isinstance(card_status, str):
            errors.append(f"{label}.card_status must be a string")
        elif card_status not in NODE_CARD_STATUS_TO_SHEET:
            errors.append(f"{label}.card_status has an invalid status")
        errors += validate_sources(node, label, catalog)

    for scenario in scenario_items:
        label = str(scenario.get("id", "scenario<?>"))
        errors += require_fields(
            scenario,
            ("id", "title", "sheet_trigger", "next_action", "confirmation", "implementation", "decision", "sources"),
            label,
        )
        errors += validate_string_fields(
            scenario,
            ("id", "title", "next_action"),
            label,
        )
        confirmation = scenario.get("confirmation", {})
        implementation = scenario.get("implementation", {})
        if not isinstance(confirmation, dict):
            errors.append(f"{label}.confirmation must be a mapping")
            confirmation = {}
        if not isinstance(implementation, dict):
            errors.append(f"{label}.implementation must be a mapping")
            implementation = {}
        for owner in ("B", "C", "E"):
            if owner not in confirmation:
                errors.append(f"{label}.confirmation.{owner} is missing")
            elif not isinstance(confirmation[owner], str):
                errors.append(f"{label}.confirmation.{owner} must be a string")
            elif confirmation[owner] not in allowed_confirmation:
                errors.append(f"{label}.confirmation.{owner} has an invalid status")
            elif confirmation[owner] not in CONFIRMATION_TO_SHEET[owner]:
                errors.append(
                    f"{label}.confirmation.{owner} cannot be projected to the sheet"
                )
        for owner, status in implementation.items():
            if owner not in {"B", "C", "E"}:
                errors.append(f"{label}.implementation.{owner} has an invalid owner")
            if not isinstance(status, str):
                errors.append(f"{label}.implementation.{owner} must be a string")
            elif status not in allowed_implementation:
                errors.append(f"{label}.implementation.{owner} has an invalid status")
        decision = scenario.get("decision")
        if not isinstance(decision, str):
            errors.append(f"{label}.decision must be a string")
        elif decision not in allowed_decision:
            errors.append(f"{label}.decision has an invalid status")
        errors += validate_codes(
            scenario.get("trigger_codes", []), f"{label}.trigger_codes", known_codes
        )
        if "trigger_code" in scenario:
            errors += validate_codes(
                [scenario["trigger_code"]], f"{label}.trigger_code", known_codes
            )
        errors += validate_sheet_trigger(scenario, label)
        errors += validate_sources(scenario, label, catalog)

    for index, failure in enumerate(failure_items):
        label = f"node_failure_cases[{index}]"
        errors += require_fields(failure, ("node_id", "error_code", "segment"), label)
        errors += validate_string_fields(failure, ("node_id", "error_code", "segment"), label)
        errors += validate_codes(
            [failure.get("error_code")], f"{label}.error_code", known_codes
        )
        errors += validate_codes(failure.get("aliases", []), f"{label}.aliases", known_codes)
        errors += validate_sources(failure, label, catalog)

    for source_id, source in catalog.items():
        errors += validate_source_catalog_entry(source_id, source)
    return errors


def action_text(node: dict[str, Any]) -> str:
    action = str(node["action"])
    reference = node.get("action_reference")
    if reference in (None, ""):
        return action
    if reference == "계약 승인 전":
        return f"{action} ({reference})"
    if action == "move_to_named_pose":
        return f"{action}({reference})"
    return f"{action} {reference}"


def desired_rows(data: dict[str, Any]) -> dict[str, dict[str, dict[str, str]]]:
    nodes: dict[str, dict[str, str]] = {}
    for node in data["node_cards"]:
        nodes[node["id"]] = {
            "A": node["id"],
            "B": node["name"],
            "C": node["owner"],
            "I": NODE_CARD_STATUS_TO_SHEET[node["card_status"]],
            "K": action_text(node),
            "L": CONFIRMATION_TO_SHEET["B"][node["owner_confirmation"]],
        }
    scenarios: dict[str, dict[str, str]] = {}
    for scenario in data["scenarios"]:
        confirmation = scenario["confirmation"]
        scenarios[scenario["id"]] = {
            "A": scenario["id"],
            "B": scenario["title"],
            "C": scenario["sheet_trigger"],
            "E": scenario["next_action"],
            "O": CONFIRMATION_TO_SHEET["B"][confirmation["B"]],
            "P": CONFIRMATION_TO_SHEET["C"][confirmation["C"]],
            "Q": CONFIRMATION_TO_SHEET["E"][confirmation["E"]],
            "R": DECISION_TO_SHEET[scenario["decision"]],
        }
    return {"nodes": nodes, "scenarios": scenarios}


def column_number(column: str) -> int:
    value = 0
    for char in column:
        value = value * 26 + ord(char.upper()) - ord("A") + 1
    return value


def read_live_tables(session: requests.Session, spreadsheet_id: str) -> dict[str, list[list[str]]]:
    ranges = [
        f"'{spec.title}'!A{spec.header_row}:{spec.last_column}{spec.last_data_row}"
        for spec in SHEET_SPECS.values()
    ]
    ranges.append(f"'{SYNC_METADATA_SHEET}'!{SYNC_METADATA_RANGE}")
    response = session.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchGet",
        params=[("ranges", value) for value in ranges] + [("valueRenderOption", "FORMATTED_VALUE")],
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    tables = {
        key: payload["valueRanges"][index].get("values", [])
        for index, key in enumerate(SHEET_SPECS)
    }
    tables["sync_metadata"] = payload["valueRanges"][len(SHEET_SPECS)].get("values", [])
    return tables


def verify_sync_metadata(rows: list[list[str]]) -> list[str]:
    first_cell = str(rows[0][0]).strip() if rows and rows[0] else ""
    if first_cell not in {"", "SHA"}:
        return [
            f"{SYNC_METADATA_SHEET}!A9:D9 is not an empty or managed metadata row "
            f"(A9='{first_cell}')"
        ]
    return []


def verify_headers(key: str, rows: list[list[str]]) -> list[str]:
    spec = SHEET_SPECS[key]
    if not rows:
        return [f"{spec.title}: header row is missing"]
    header = rows[0]
    errors: list[str] = []
    for column, expected in spec.managed_columns.items():
        index = column_number(column) - 1
        actual = header[index] if index < len(header) else ""
        if actual != expected:
            errors.append(f"{spec.title}!{column}{spec.header_row}: expected '{expected}', found '{actual}'")
    for expected in spec.protected_headers:
        if expected not in header:
            errors.append(f"{spec.title}: protected header is missing: {expected}")
    return errors


def live_row_map(key: str, rows: list[list[str]]) -> tuple[dict[str, int], list[str]]:
    spec = SHEET_SPECS[key]
    mapping: dict[str, int] = {}
    errors: list[str] = []
    for offset, row in enumerate(rows[1:], start=spec.first_data_row):
        item_id = str(row[0]).strip() if row else ""
        if not item_id:
            continue
        if item_id in mapping:
            errors.append(f"{spec.title}: duplicate sheet ID {item_id}")
        mapping[item_id] = offset
    return mapping, errors


def build_changes(
    desired: dict[str, dict[str, dict[str, str]]],
    live: dict[str, list[list[str]]],
) -> tuple[list[dict[str, str]], list[str]]:
    changes: list[dict[str, str]] = []
    errors: list[str] = []
    for key, desired_items in desired.items():
        spec = SHEET_SPECS[key]
        rows = live.get(key, [])
        errors += verify_headers(key, rows)
        row_map, row_errors = live_row_map(key, rows)
        errors += row_errors
        for item_id, columns in desired_items.items():
            row_number = row_map.get(item_id)
            if row_number is None:
                errors.append(f"{spec.title}: required ID is missing: {item_id}")
                continue
            live_index = row_number - spec.header_row
            live_row = rows[live_index] if live_index < len(rows) else []
            for column, after in columns.items():
                column_index = column_number(column) - 1
                before = str(live_row[column_index]) if column_index < len(live_row) else ""
                if before != after:
                    changes.append({
                        "sheet": spec.title,
                        "cell": f"{column}{row_number}",
                        "item_id": item_id,
                        "field": spec.managed_columns[column],
                        "before": before,
                        "after": after,
                    })
    return changes, errors


def authorized_session(credentials_path: Path) -> requests.Session:
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials
    except ImportError as exc:
        raise ChecklistError(
            "Google auth dependency is missing; install requirements.txt before live dry-run/apply"
        ) from exc
    credentials = Credentials.from_service_account_file(
        str(credentials_path), scopes=[SHEETS_SCOPE]
    )
    return AuthorizedSession(credentials)


def apply_changes(
    session: requests.Session,
    spreadsheet_id: str,
    changes: list[dict[str, str]],
    source_sha: str,
    synced_at: str,
) -> None:
    data = [
        {
            "range": f"'{change['sheet']}'!{change['cell']}",
            "majorDimension": "ROWS",
            "values": [[change["after"]]],
        }
        for change in changes
    ]
    data.append(
        {
            "range": f"'{SYNC_METADATA_SHEET}'!{SYNC_METADATA_RANGE}",
            "majorDimension": "ROWS",
            "values": [["SHA", source_sha, f"동기화 {synced_at} KST", ""]],
        }
    )
    payload = {
        "valueInputOption": "RAW",
        "data": data,
    }
    response = session.post(
        f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values:batchUpdate",
        json=payload,
        timeout=30,
    )
    response.raise_for_status()


def print_changes(changes: list[dict[str, str]]) -> None:
    if not changes:
        print("NO CHANGES")
        return
    for change in changes:
        print(f"UPDATE {change['item_id']}.{change['field']} ({change['sheet']}!{change['cell']}):")
        print(f"  before: {change['before'] or '<empty>'}")
        print(f"  after: {change['after'] or '<empty>'}")


def print_preserved_columns() -> None:
    for spec in SHEET_SPECS.values():
        print(f"PRESERVE {spec.title}: {', '.join(spec.protected_headers)}")


def print_offline_plan(desired: dict[str, dict[str, dict[str, str]]]) -> None:
    print("OFFLINE DRY-RUN: Google credentials are not configured; no sheet was read or changed.")
    for key, items in desired.items():
        spec = SHEET_SPECS[key]
        columns = ", ".join(f"{column}({header})" for column, header in spec.managed_columns.items())
        print(f"PLAN {spec.title}: {len(items)} rows; managed columns: {columns}")
    print_preserved_columns()


def git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def verified_apply_sha(checklist_path: Path, checklist_content: bytes) -> str:
    root = ROOT.resolve()
    resolved_path = checklist_path.expanduser().resolve()
    try:
        relative_path = resolved_path.relative_to(root)
    except ValueError as exc:
        raise ChecklistError(
            "--apply requires a checklist tracked in the current repository"
        ) from exc

    source_sha = git_sha()
    if source_sha == "unknown":
        raise ChecklistError("cannot resolve the source commit for --apply")
    committed = subprocess.run(
        ["git", "show", f"{source_sha}:{relative_path.as_posix()}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if committed.returncode != 0:
        raise ChecklistError(
            f"--apply requires a checklist tracked at {source_sha}: {relative_path}"
        )
    if committed.stdout != checklist_content:
        raise ChecklistError(
            "--apply requires checklist content committed at HEAD; commit or revert "
            f"changes to {relative_path}"
        )
    return source_sha


def sync_timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate", action="store_true", help="validate YAML only")
    mode.add_argument("--dry-run", action="store_true", help="preview managed-cell changes; never writes")
    mode.add_argument("--apply", action="store_true", help="apply managed-cell changes")
    parser.add_argument("--checklist", type=Path, default=DEFAULT_CHECKLIST)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data, checklist_content = load_checklist(args.checklist)
        errors = validate_checklist(data)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print(f"PASS: {len(data['node_cards'])} node cards, {len(data['scenarios'])} scenarios")
        if args.validate:
            return 0

        desired = desired_rows(data)
        source_sha = (
            verified_apply_sha(args.checklist, checklist_content)
            if args.apply
            else git_sha()
        )
        credentials_value = os.environ.get(CREDENTIALS_ENV)
        if not credentials_value:
            if args.apply:
                raise ChecklistError(f"{CREDENTIALS_ENV} is required for --apply")
            print_offline_plan(desired)
            return 0

        credentials_path = Path(credentials_value).expanduser()
        if not credentials_path.is_file():
            raise ChecklistError(f"credentials file not found: {credentials_path}")
        spreadsheet_id = str(data["sheet"]["spreadsheet_id"])
        session = authorized_session(credentials_path)
        live = read_live_tables(session, spreadsheet_id)
        changes, sheet_errors = build_changes(desired, live)
        sheet_errors += verify_sync_metadata(live.get("sync_metadata", []))
        if sheet_errors:
            for error in sheet_errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print_changes(changes)
        print_preserved_columns()
        if args.dry_run:
            print(f"METADATA {SYNC_METADATA_SHEET}!{SYNC_METADATA_RANGE}: source SHA {source_sha}")
            return 0

        synced_at = sync_timestamp()
        apply_changes(session, spreadsheet_id, changes, source_sha, synced_at)
        print(f"APPLIED: {len(changes)} managed cells (source commit {source_sha}, {synced_at})")
        return 0
    except (
        ChecklistError, KeyError, TypeError, AttributeError, requests.RequestException
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
