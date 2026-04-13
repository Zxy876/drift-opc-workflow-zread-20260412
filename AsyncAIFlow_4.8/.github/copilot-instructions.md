# AsyncAIFlow Project Guidelines

## Code Style
- Keep Java changes aligned with existing Spring Boot + MyBatis-Plus patterns under `src/main/java/com/asyncaiflow`.
- Prefer small, behavior-preserving changes; avoid broad refactors unless explicitly requested.
- Put workflow/action contract changes behind existing schema and validation paths instead of ad-hoc fields.
- For payload or mapping behavior, follow documented contracts in `docs/action-schema.md` and `docs/schema-validation.md`.

## Architecture
- Treat the runtime scheduler and workers as separate boundaries:
  - Runtime server: action lifecycle, dispatch, retries, lease reclaim.
  - Java/Python workers: capability declaration, poll, execute, result callback.
- Start from these docs before modifying orchestration behavior:
  - `docs/architecture.md`
  - `docs/worker-sdk.md`
  - `docs/worker-capability-model.md`
  - `docs/planner-architecture.md`

## Build and Test
- Baseline build/test commands:
  - `mvn clean compile`
  - `mvn test`
  - `mvn spring-boot:run`
- Fast local runtime profile (H2 + Redis):
  - `mvn spring-boot:run -Dspring-boot.run.profiles=local`
- Full local stack helper scripts:
  - `scripts/dev-start.sh`
  - `scripts/dev-stop.sh`
- When touching Python workers, validate each worker in its own virtual environment under `python-workers/*/.venv`.

## Conventions
- Capability mapping drives dispatch. If actions remain `QUEUED`, verify worker capabilities and mapping before changing scheduler logic. See `docs/troubleshooting.md`.
- Repository worker enforces workspace-root-safe paths; path/scope inputs must stay under its configured root.
- The repository directory name includes a leading space (` AsyncAIFlow`), so be careful with path assumptions in scripts/globs.
- `design_gpt_worker` requires `GEMINI_API_KEY`; without it, `scripts/dev-start.sh` intentionally skips that worker and related tasks will stall.

## Documentation Map
- Quick start and run modes: `README.md`, `docs/quickstart-local.md`
- First end-to-end flow: `docs/first-workflow.md`
- Runtime observability: `docs/runtime-observability.md`
- Failure diagnosis and recovery patterns: `docs/troubleshooting.md`
- Planner and demo workflows: `docs/planner-demo.md`, `docs/first-ai-dev-demo.md`
