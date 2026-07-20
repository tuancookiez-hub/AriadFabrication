"""Idempotency-aware admission through the trusted target registry.

This coordinator can persist a queued no-hardware record.  It cannot launch a
worker, publish Journey evidence, expose HTTP, or contact hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import AdmissionDecision, ExecutionRequest
from .registry import ResolvedTarget, TrustedTargetRegistry
from .store import ExecutionControlStore, StoreAdmissionResult


@dataclass(frozen=True)
class RegisteredAdmissionResult:
    store_result: StoreAdmissionResult
    resolved_target: ResolvedTarget | None
    current_target_checked: bool
    hardware_actions: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.store_result, StoreAdmissionResult):
            raise ValueError("store_result must be a StoreAdmissionResult")
        if self.hardware_actions:
            raise ValueError("registered admission cannot enable hardware actions")
        accepted = self.store_result.decision is AdmissionDecision.ACCEPT
        if accepted != (self.resolved_target is not None):
            raise ValueError("only a newly accepted request may retain a resolved target")
        if accepted and not self.current_target_checked:
            raise ValueError("accepted requests require a current target identity check")

    @property
    def decision(self) -> AdmissionDecision:
        return self.store_result.decision


class RegisteredTargetAdmission:
    """Resolve only new requests, then atomically admit their immutable plan."""

    def __init__(
        self,
        store: ExecutionControlStore,
        registry: TrustedTargetRegistry,
    ) -> None:
        if not isinstance(store, ExecutionControlStore):
            raise TypeError("store must be an ExecutionControlStore")
        if not isinstance(registry, TrustedTargetRegistry):
            raise TypeError("registry must be a TrustedTargetRegistry")
        self.store = store
        self.registry = registry

    def admit(
        self,
        request: ExecutionRequest,
        *,
        accepted_at: str | datetime,
    ) -> RegisteredAdmissionResult:
        if not isinstance(request, ExecutionRequest):
            raise TypeError("request must be an ExecutionRequest")
        existing = self.store.lookup_request(request)
        resolved: ResolvedTarget | None = None
        current_target_checked = False
        if existing is None:
            resolved = self.registry.resolve(request.target)
            current_target_checked = True
            plan = resolved.plan
        else:
            # Records cannot be deleted or have their accepted plan replaced.
            # Reusing it here preserves replay/conflict behavior even if today's
            # local toolchain is unavailable.
            plan = existing.record.plan
        store_result = self.store.admit(request, plan, accepted_at=accepted_at)
        accepted_target = (
            resolved if store_result.decision is AdmissionDecision.ACCEPT else None
        )
        return RegisteredAdmissionResult(
            store_result=store_result,
            resolved_target=accepted_target,
            current_target_checked=current_target_checked,
        )


__all__ = ["RegisteredAdmissionResult", "RegisteredTargetAdmission"]
