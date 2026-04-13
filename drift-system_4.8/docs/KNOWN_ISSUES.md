# Known Issues (v1)

Date: 2026-03-13
Scope: Non-blocking issues accepted in v1 freeze

## Classification

- Blocker: none confirmed
- High risk (future): limited set
- Architecture debt: present
- Documentation drift: present

## High Risk (Future)

1. StoryManager concurrency risk
- Symptom: async HTTP callback may write player state while main thread reads/writes local maps.
- Impact: intermittent race conditions under load.
- v1 decision: accepted as non-blocking.
- v2 action: enforce main-thread state mutation or use a strict concurrency model.

## Architecture Debt

1. Dual intent pipeline
- Chat path and nearby/interact NPC path are not fully unified.
- Impact: behavior divergence and higher maintenance cost.
- v1 decision: accepted.
- v2 action: consolidate to one intent ingress contract.

2. Narrative config source and hot-reload asymmetry
- Runtime config cache and generated-level refresh boundaries are not fully unified.
- Impact: operational confusion during live content updates.
- v1 decision: accepted.
- v2 action: single source of truth plus explicit reload contract.

3. Test isolation consistency
- Some tests still rely on process-global singletons/persistent stores.
- Impact: potential flaky behavior in repeated/parallel runs.
- v1 decision: accepted.
- v2 action: isolated state fixtures and deterministic teardown policy.

## Documentation Drift

- Some path references and structure notes are outdated.
- One datetime API call has deprecation warning in generated-level helper.
- v1 decision: accepted as non-blocking.
- v2 action: docs lint and compatibility cleanup.
