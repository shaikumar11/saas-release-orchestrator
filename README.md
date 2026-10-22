# SaaS Release Orchestrator

An operations tool, `releasectl`, that automates change-managed software upgrades across a SaaS fleet. It replaces the manual runbook of raising a change, getting approval, picking a window, upgrading servers and checking health.

## What it does
- Change requests with risk from the version jump: patch is low, minor is medium, major is high.
- Approval rules: production and high risk changes need approval, and the requester cannot approve their own change.
- Pre-flight gates: approved status, inside the change window, no freeze day, no version drift, fleet healthy.
- Rolling deployment: one canary node first, then percentage batches, with a health check after each batch.
- Automatic rollback of every upgraded node when a batch fails its health check.
- Audit trail for every step, printed with `releasectl report`.

## Run it
    python -m releasectl seed production 8 2.4.0
    python -m releasectl request production 2.5.0 --by asha --start "2026-10-24 01:00" --end "2026-10-24 04:00"
    python -m releasectl approve 1 --by ravi
    python -m releasectl deploy 1 --now "2026-10-24 02:00"
    python -m releasectl report 1

Failure drill:

    python -m releasectl fault production production-app-06 2.5.0
    python -m releasectl deploy 1 --now "2026-10-24 02:00"   # exits 2 and rolls back

## Test
    python -m unittest discover -s tests -v

Python 3.10 or newer, standard library only. The fleet is simulated in SQLite, so no cloud account is needed.
