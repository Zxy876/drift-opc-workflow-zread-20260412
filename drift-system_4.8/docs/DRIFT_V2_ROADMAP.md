# Drift v2 Roadmap

Date: 2026-03-13
Status: Planned

## v2 Goal

Reduce operational risk and maintenance cost while preserving v1 gameplay behavior.

## Workstream A: Runtime Safety

- Fix StoryManager concurrency boundaries.
- Add plugin tests for state mutation paths.

Milestone A done when:
- no async callback writes to shared state without synchronization policy
- tests cover concurrent callback scenarios.

## Workstream B: Intent Pipeline Consolidation

- Unify chat and NPC-triggered intent ingress.
- Keep one compatibility adapter layer only if needed.

Milestone B done when:
- one canonical intent contract is used by all player action entrypoints.

## Workstream C: Narrative Config Lifecycle

- Consolidate to one narrative config source.
- Introduce full reload contract for graph + policy + dependent caches.

Milestone C done when:
- content update path has deterministic runtime refresh behavior.

## Workstream D: Test Reliability

- Enforce isolated state fixtures for quest/scene/inventory stores.
- Remove hidden dependence on global singletons in tests.

Milestone D done when:
- repeated and parallel test runs stay deterministic.

## Workstream E: Docs and Release Hygiene

- Fix structural path drift in docs.
- Add docs lint in CI.
- Replace deprecated datetime UTC API usage.

Milestone E done when:
- docs checks pass in CI and no deprecation warnings remain in tested paths.
