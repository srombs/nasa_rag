# 04: Deploy the private service through Railway's dashboard

**What to build:** The user has a healthy private API running on Railway from a
verified source revision, with persistent cache reuse demonstrated after restart.

**Blocked by:** 02: Successful container/CI checks; 03: Dashboard deployment
guide; implementation committed and available on GitHub.

**Status:** ready-for-human

Source: [Deployment specification](../spec.md).

## Acceptance criteria

- [ ] The implementation is available on the connected GitHub branch and its
  required CI checks pass. Link the exact deployed source revision and CI run.
- [ ] Through Railway's dashboard, connect the repository and configure the
  source branch, Docker build, runtime secret, persistent `/data` volume, single
  replica, readiness check, crash restart policy, and **Wait for CI**.
- [ ] Choose and record the region, resource limits/headroom, hosting sleep
  behavior, and any compute alerts/usage limits. Never record credential values.
- [ ] Keep public domains and TCP proxies absent. Confirm a healthy deployment
  and a private in-container `/health` response without temporarily publishing
  the API. Record the service identity and deployment result.
- [ ] First-start embedding usage is understood before starting the service.
  Restart against the same volume and verify compatible cache reuse. Ordinary
  health checks make no model requests.
- [ ] Observe hosted memory and startup behavior and compare them with the
  provisional Linux evidence. Adjust resources based on observed requirements;
  distinguish deployment health from a successful live answer benchmark.
- [ ] Confirm **Wait for CI** is enabled and review its gate against the linked
  workflow checks; if deployment blocking by a failed run is not exercised,
  record that behavioral check as pending rather than claim it was demonstrated.
- [ ] Record any live answer check only if separately authorized; otherwise
  report provider-answer/latency verification pending. Website integration and
  public access remain future work even when deployment succeeds.

## Handoff

Tickets 01–03 prepare everything the repository can provide. The user will perform
this ticket in the Railway UI. Creating this ticket is not an instruction for an
agent to sign in, provision resources, push code, deploy, or make paid requests.
Record the actual result when the user performs the deployment; do not resolve
this ticket based only on packaging or documentation being complete.

## Comments

2026-10-30: Assigned to the human deployment path requested by the user. Blocked
on implementation and handoff; no account connection or deployment performed.
