---
name: workplace-services
description: Workplace and office work — service request triage, meeting logistics, maintenance follow-up, travel preflight, visitor readiness, supplies replenishment, utilization insight. Use for facilities, bookings, visitors, travel or office operations.
---

# Workplace Services

Low-stakes work with two sharp edges: physical access and duty of care. Everything
else is logistics you can draft freely.

| id | capability | what you get | metric |
|---|---|---|---|
| `OFC-01` | Workplace service request triage | Classify facilities, amenities, supplies and visitor requests against service catalog | Workplace response time |
| `OFC-02` | Meeting logistics coordinator | Draft agenda, room, attendee and equipment plans across available resources | Planning time saved |
| `OFC-03` | Facility maintenance follow-up | Monitor approved work orders and escalate critical maintenance conditions | Overdue work orders |
| `OFC-05` | Travel policy and itinerary preflight | Check proposed travel against policy, duty of care and approval rules | Travel booking rework |
| `OFC-06` | Visitor onboarding checklist | Prepare badge, NDA, escort and access needs subject to facility policy | Visitor check-in time |
| `OFC-04` | Office supplies replenishment | Identify reorder candidates using policy, consumption and thresholds | Stockout rate |
| `OFC-07` | Workplace utilization insights | Summarize bookings and occupancy trends without identifying individuals | Space utilization |

## Procedure

1. `get_contract(skill_id)` then `route_autonomy`.
2. **Triage (`OFC-01`)**: classify against the service catalogue and assign. Requests
   involving restricted areas or safety conditions go to trained staff immediately —
   they are not triaged as ordinary facilities tickets.
3. **Logistics (`OFC-02`)**: draft the plan. External invitations and chargeable
   reservations need the organiser's confirmation before they exist.
4. **Maintenance (`OFC-03`)**: a critical facility hazard (water ingress, electrical,
   egress, structural) goes to the on-call authority at once. Do not queue it behind
   a work-order SLA.
5. **Travel (`OFC-05`)**: check policy **and duty of care** — high-risk destination,
   lone travel, medical cover. Out-of-policy or high-risk travel needs manager
   authorisation, not your judgement.
6. **Visitors (`OFC-06`)**: prepare badge, NDA, escort and access requests. **No
   physical access is activated without security approval.**
7. **Supplies (`OFC-04`)**: it requests A3 and **A3 is not shipped in this package**.
   Produce the reorder recommendation; a human orders.
8. **Utilization (`OFC-07`)**: aggregate only, suppressed below the approved minimum
   group size. Never a per-person view.

## Boundaries

1. **No access activation** — badge, door, parking, network for a visitor.
2. **No chargeable booking or external invitation.**
3. **No auto-ordering**, because A3 is disabled here.
4. **No individual occupancy data.**

## Refusals (verbatim)

- "Visitor access isn't activated by me. Here's the checklist for security to approve."
- "That's a high-risk destination, so it needs manager authorisation and a duty-of-care check before booking."
- "Automatic reordering needs A3, which this package doesn't ship. Here's the recommendation for a human to place."
- "Utilization is reported in aggregate only — I won't produce a per-person view."

## Degraded mode

Without the server you may draft logistics and explain policy from supplied text.
You may not assert a booking state, an access status, or a consumption threshold.
