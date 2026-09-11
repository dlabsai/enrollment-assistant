from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EntraIdentity:
    tenant_id: str
    object_id: str
    email: str
    name: str
