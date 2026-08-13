"""Versioned, model-agnostic Agentic Compatibility Contracts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from .sandboxes import INITIAL_STATES

CONTRACT_SCHEMA_VERSION = "1.0"


class ContractBehavior(BaseModel):
    clarification: Literal["required", "not_required"] = "not_required"


class ContractBudgets(BaseModel):
    max_tool_calls: int = Field(default=5, ge=0, le=30)


class ContractAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    equals: Any | None = None
    not_equals: Any | None = None
    exists: bool | None = None
    unchanged: bool | None = None

    @model_serializer(mode="wrap")
    def omit_unselected_operators(self, handler: Any) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for operator in {"equals", "not_equals", "exists", "unchanged"}:
            if operator not in self.model_fields_set:
                data.pop(operator, None)
        return data

    @model_validator(mode="after")
    def one_operator(self) -> ContractAssertion:
        operators = {"equals", "not_equals", "exists", "unchanged"}
        if len(operators.intersection(self.model_fields_set)) != 1:
            raise ValueError("Each assertion must define exactly one operator")
        return self

    def evaluator_assertion(self) -> dict[str, Any]:
        if "not_equals" in self.model_fields_set:
            return {"type": "not_equals", "path": self.path, "value": self.not_equals}
        if "exists" in self.model_fields_set:
            return {"type": "exists" if self.exists else "not_exists", "path": self.path}
        if "unchanged" in self.model_fields_set:
            if not self.unchanged:
                raise ValueError("unchanged: false is not a supported deterministic assertion")
            return {"type": "unchanged", "path": self.path}
        return {"type": "equals", "path": self.path, "value": self.equals}


class InitialState(BaseModel):
    fixture: str | None = None
    state: dict[str, Any] | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> InitialState:
        if (self.fixture is None) == (self.state is None):
            raise ValueError("initial_state must provide exactly one of fixture or state")
        return self


class AgenticCompatibilityContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONTRACT_SCHEMA_VERSION
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    intent: str = Field(min_length=1)
    initial_state: InitialState
    assertions: list[ContractAssertion] = Field(min_length=1)
    invariants: list[ContractAssertion] = []
    forbidden_actions: list[str] = []
    required_actions: list[str] = []
    behavior: ContractBehavior = ContractBehavior()
    budgets: ContractBudgets = ContractBudgets()
    related_tools: list[str] = Field(min_length=1)
    capabilities: list[str] = Field(min_length=1)
    categories: list[str] = Field(default_factory=lambda: ["compatibility"])
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    evaluator_version: str = "agentseo-contract-evaluator-1"

    @model_validator(mode="after")
    def supported_version(self) -> AgenticCompatibilityContract:
        if self.schema_version != CONTRACT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported contract schema version: {self.schema_version}")
        overlap = set(self.required_actions) & set(self.forbidden_actions)
        if overlap:
            raise ValueError(f"Actions cannot be both required and forbidden: {sorted(overlap)}")
        return self

    def resolved_initial_state(self) -> dict[str, Any]:
        if self.initial_state.state is not None:
            return self.initial_state.state
        fixture = str(self.initial_state.fixture)
        if fixture not in INITIAL_STATES:
            raise ValueError(f"Unknown built-in fixture: {fixture}")
        return INITIAL_STATES[fixture]

    def canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def sha256(self) -> str:
        payload = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()


def load_contract(path: Path) -> AgenticCompatibilityContract:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Contract root must be an object: {path}")
    return AgenticCompatibilityContract.model_validate(raw)


def load_contract_suite(path: Path) -> list[AgenticCompatibilityContract]:
    files = (
        [path]
        if path.is_file()
        else sorted((*path.glob("*.yaml"), *path.glob("*.yml"), *path.glob("*.json")))
    )
    if not files:
        raise ValueError(f"No contract files found at {path}")
    contracts = [load_contract(file) for file in files]
    names = [contract.name for contract in contracts]
    if len(set(names)) != len(names):
        raise ValueError("Contract names must be unique within a task suite")
    return contracts


def contract_suite_hash(contracts: list[AgenticCompatibilityContract]) -> str:
    payload = json.dumps(
        [contract.canonical_dict() for contract in sorted(contracts, key=lambda item: item.name)],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def write_contract_schema(path: Path) -> None:
    path.write_text(
        json.dumps(AgenticCompatibilityContract.model_json_schema(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
