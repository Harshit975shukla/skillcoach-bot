# Lab: VPC subnet sizing and route tables

Goal: size subnets correctly and reason about route-table decisions the way a VPC does.
Pure Python (`ipaddress`) — no AWS account needed.

Edit only `solution.py`:

1. `usable_hosts(cidr)` returns usable IPv4 addresses in a VPC subnet. AWS reserves 5 addresses in every
   subnet (network, VPC router, DNS, future use, and broadcast). Only prefixes `/16` to `/28` are valid; raise
   `ValueError` otherwise, and for CIDRs with host bits set.
2. `split(cidr, new_prefix)` returns the subnet CIDR strings, in order, for a larger block. Raise `ValueError`
   when `new_prefix` is smaller than the block prefix or larger than `/28`.
3. `route_target(routes, ip)` returns the `target` of the most specific matching route (longest prefix wins),
   or `None` when nothing matches. Each route is `{"destination": "<cidr>", "target": "<id>"}`.
4. `is_public(routes)` is `True` only when the table routes `0.0.0.0/0` to an internet gateway (`igw-...`).
   A NAT gateway (`nat-...`) default route makes a subnet private-with-egress, not public.

Run: `python -m pytest -c pytest.ini labs/vpc-subnet-routing`

Official references:

- https://docs.aws.amazon.com/vpc/latest/userguide/subnet-sizing.html
- https://docs.aws.amazon.com/vpc/latest/userguide/route-table-priority.html
- https://docs.aws.amazon.com/vpc/latest/userguide/configure-subnets.html
