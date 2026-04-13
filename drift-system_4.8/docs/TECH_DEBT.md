# Technical Debt Register

Date: 2026-03-13

## Debt Items

TD-001 StoryManager concurrency model
- Priority: High
- Area: plugin runtime state handling
- Current risk: race condition possibility
- Exit criteria:
  - all StoryManager state writes happen on main thread, or
  - thread-safe model is implemented with tests proving correctness.

TD-002 Intent ingress unification
- Priority: High
- Area: plugin intent routing
- Current risk: split behavior between old and new intent paths
- Exit criteria:
  - single intent ingress contract for chat and NPC-triggered flows
  - regression tests for both trigger types.

TD-003 Narrative config source and reload contract
- Priority: Medium
- Area: backend narrative config lifecycle
- Current risk: partial reload semantics and operator confusion
- Exit criteria:
  - single source-of-truth config path
  - explicit reload API/hook that refreshes all narrative config caches.

TD-004 Test state isolation
- Priority: Medium
- Area: backend test architecture
- Current risk: persistent/global state leakage across runs
- Exit criteria:
  - deterministic setup/teardown for quest, scene, inventory state
  - no dependence on shared player IDs across tests.

TD-005 Docs drift and compatibility warnings
- Priority: Low
- Area: docs/release hygiene
- Current risk: onboarding friction and future Python compatibility warning
- Exit criteria:
  - path references validated in CI docs lint
  - deprecated datetime usage replaced with timezone-aware call.
