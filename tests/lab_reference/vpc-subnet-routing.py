"""Private reference solution for the vpc-subnet-routing code lab. Never publish."""

import ipaddress


def network(cidr):
    value = ipaddress.ip_network(cidr)
    if value.version != 4:
        raise ValueError("IPv4 only")
    return value


def usable_hosts(cidr: str) -> int:
    value = network(cidr)
    if not 16 <= value.prefixlen <= 28:
        raise ValueError("VPC subnets must be /16 to /28")
    return value.num_addresses - 5


def split(cidr: str, new_prefix: int) -> list[str]:
    value = network(cidr)
    if not value.prefixlen <= new_prefix <= 28:
        raise ValueError("invalid new prefix")
    return [str(subnet) for subnet in value.subnets(new_prefix=new_prefix)]


def route_target(routes: list[dict], ip: str) -> str | None:
    address = ipaddress.ip_address(ip)
    matches = [(network(r["destination"]), r["target"]) for r in routes]
    matches = [item for item in matches if address in item[0]]
    return max(matches, key=lambda item: item[0].prefixlen)[1] if matches else None


def is_public(routes: list[dict]) -> bool:
    return any(r["destination"] == "0.0.0.0/0" and r["target"].startswith("igw-") for r in routes)
