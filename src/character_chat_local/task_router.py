from __future__ import annotations

import os

from .models import TaskAssignment, TaskRole
from .providers import AIProvider, ProviderRegistry

_TASK_ROLES: tuple[TaskRole, ...] = (
    "main_chat",
    "knowledge_extractor",
    "draft_analyzer",
    "knowledge_orchestrator",
    "guardian",
    "repair",
)


class TaskRouter:
    """Maps logical task roles to provider/model assignments."""

    def __init__(
        self,
        registry: ProviderRegistry,
        assignments: dict[TaskRole, TaskAssignment] | None = None,
    ):
        self.registry = registry
        self._assignments = dict(assignments or {})

    def set_assignment(self, role: TaskRole, assignment: TaskAssignment | None) -> None:
        if assignment is None:
            self._assignments.pop(role, None)
            return
        self.registry.get(assignment.provider_id)
        self._assignments[role] = assignment

    def assignment(self, role: TaskRole) -> TaskAssignment | None:
        return self._assignments.get(role)

    def resolve(self, role: TaskRole) -> tuple[AIProvider, TaskAssignment] | None:
        assignment = self.assignment(role)
        if assignment is None:
            return None
        return self.registry.get(assignment.provider_id), assignment

    @classmethod
    def from_env(cls, registry: ProviderRegistry) -> TaskRouter:
        router = cls(registry)
        for role in _TASK_ROLES:
            stem = role.upper()
            provider_id = os.getenv(f"CHARACTER_CHAT_TASK_{stem}_PROVIDER")
            model = os.getenv(f"CHARACTER_CHAT_TASK_{stem}_MODEL")
            temperature_raw = os.getenv(
                f"CHARACTER_CHAT_TASK_{stem}_TEMPERATURE", "0.1"
            )
            if not provider_id and not model:
                continue
            if not provider_id or not model:
                raise RuntimeError(f"task role {role} requires both provider and model")
            try:
                temperature = float(temperature_raw)
            except ValueError as exc:
                raise RuntimeError(f"task role {role} has invalid temperature") from exc
            router.set_assignment(
                role,
                TaskAssignment(
                    provider_id=provider_id,
                    model=model,
                    temperature=temperature,
                ),
            )
        return router
