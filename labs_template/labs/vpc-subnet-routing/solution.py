"""Lab: VPC subnet sizing and route-table decisions. Edit only this file."""


def usable_hosts(cidr: str) -> int:
    """Usable addresses after the 5 AWS reserves in a /16-/28 subnet."""
    raise NotImplementedError


def split(cidr: str, new_prefix: int) -> list[str]:
    """Split a block into equal subnets of new_prefix, in address order."""
    raise NotImplementedError


def route_target(routes: list[dict], ip: str) -> str | None:
    """Target of the longest-prefix matching route, or None."""
    raise NotImplementedError


def is_public(routes: list[dict]) -> bool:
    """True only when 0.0.0.0/0 routes to an internet gateway."""
    raise NotImplementedError
