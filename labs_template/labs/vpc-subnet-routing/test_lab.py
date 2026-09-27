"""Protected SkillCoach tests. Do not edit: SkillCoach verifies this file's Git hash."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("lab_vpc_solution", Path(__file__).with_name("solution.py"))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)

ROUTES = [
    {"destination": "10.0.0.0/16", "target": "local"},
    {"destination": "10.0.8.0/24", "target": "pcx-11112222"},
    {"destination": "0.0.0.0/0", "target": "nat-0abc"},
]


@pytest.mark.parametrize("cidr,expected", [("10.0.0.0/24", 251), ("10.0.0.0/28", 11), ("10.0.0.0/16", 65531)])
def test_usable_hosts_subtracts_five_reserved(cidr, expected):
    assert solution.usable_hosts(cidr) == expected


@pytest.mark.parametrize("cidr", ["10.0.0.0/29", "10.0.0.0/15", "10.0.0.1/24", "not-a-cidr"])
def test_invalid_subnets_are_rejected(cidr):
    with pytest.raises(ValueError):
        solution.usable_hosts(cidr)


def test_split_returns_ordered_subnets():
    assert solution.split("10.0.0.0/22", 24) == ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
    assert len(solution.split("10.0.0.0/16", 20)) == 16
    for prefix in (21, 29):
        with pytest.raises(ValueError):
            solution.split("10.0.0.0/22", prefix)


def test_longest_prefix_wins():
    assert solution.route_target(ROUTES, "10.0.8.9") == "pcx-11112222"
    assert solution.route_target(ROUTES, "10.0.1.9") == "local"
    assert solution.route_target(ROUTES, "8.8.8.8") == "nat-0abc"
    assert solution.route_target(ROUTES[:2], "8.8.8.8") is None


def test_public_means_default_route_to_internet_gateway():
    assert solution.is_public(ROUTES) is False
    public = ROUTES[:2] + [{"destination": "0.0.0.0/0", "target": "igw-0def"}]
    assert solution.is_public(public) is True
    assert solution.is_public([{"destination": "0.0.0.0/1", "target": "igw-0def"}]) is False
    assert solution.is_public([{"destination": "10.0.0.0/16", "target": "local"}]) is False
