from app.dependencies.auth import (
    ensure_programme_in_scope,
    get_current_identity,
    require_admin,
    require_authenticated,
    require_external_resident,
    require_master_admin,
    require_programme_pc,
    require_resident,
    require_secretary,
)
from app.dependencies.staff_actor import StaffActorContext, require_staff_actor

__all__ = [
    "StaffActorContext",
    "ensure_programme_in_scope",
    "get_current_identity",
    "require_admin",
    "require_authenticated",
    "require_external_resident",
    "require_master_admin",
    "require_programme_pc",
    "require_resident",
    "require_secretary",
    "require_staff_actor",
]
