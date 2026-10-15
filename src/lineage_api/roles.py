"""Demo roles (X-Role header) and identifier masking. ponytail: no real auth, add SSO when leaving demo."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from lineage_store.masking import mask_counterparty, mask_key  # noqa: F401  (re-exported)

ROLES = {"analyst", "supervisor", "data_owner", "head_of_reg"}
CAN_REVEAL = {"analyst"}


@dataclass(frozen=True)
class Caller:
    role: str
    actor: str

    @property
    def can_reveal(self) -> bool:
        return self.role in CAN_REVEAL


def caller(x_role: str = Header("analyst"), x_actor: str = Header("[Analyst B]")) -> Caller:
    if x_role not in ROLES:
        raise HTTPException(400, f"unknown role {x_role!r}; expected one of {sorted(ROLES)}")
    return Caller(x_role, x_actor)
