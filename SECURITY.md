# Security policy

## Scope

LIFELINE is an alpha prototype and is not an emergency service. The current
incident-room server binds to loopback and uses local, token-authenticated
roles. Those tokens are prototype credentials, not an organizational identity
or authorization system. Never expose the server to an untrusted network or
use it to coordinate a live emergency.

## Reporting a vulnerability

Do not publish an exploitable vulnerability with reproduction details in a
public issue before it has been assessed. Contact the maintainer, Anna
Tchijova, through the contact channel associated with the repository and
include:

- the affected commit or version;
- the attacker capability and trust boundary;
- a minimal reproduction or test;
- the expected safety invariant and the observed violation; and
- whether any real personal or operational data was involved.

Do not include sensitive incident data, credentials, private addresses, or
information about real people in a report. Use synthetic fixtures whenever
possible.

## Security invariants

- No automatic dispatch is performed by the kernel or incident room.
- Unverified, conflicting, or stale inputs cannot silently become proposals.
- Plans and approvals are independently verifiable artifacts.
- The approval identity comes from the authenticated local operator, never a
  client-supplied display name.
- A model cannot select resources, routes, priorities, or recipients.
