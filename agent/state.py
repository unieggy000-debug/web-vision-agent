"""Simple in-memory state for one research run."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    """Holds progress for a single agent run."""

    goal: str = ""
    current_goal: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    final_result: dict[str, Any] | None = None
    step: int = 0
    step_count: int = 0
    last_tool: str = ""
    researched_urls: list[str] = field(default_factory=list)
    saved_case_ids: list[str] = field(default_factory=list)
    skipped_urls: list[str] = field(default_factory=list)
    last_novelty: str = ""
    last_decision: str = ""
    stop_status: str | None = None
    finish_validation_attempts: int = 0
    last_finish_validation: dict[str, Any] | None = None
    report_paths: list[str] = field(default_factory=list)
    # Ticket 17 — Run packaging
    run_id: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    report_errors: list[dict[str, Any]] = field(default_factory=list)
    artifact_path: str | None = None
