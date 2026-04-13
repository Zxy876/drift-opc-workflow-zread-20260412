# Drift + AsyncAIFlow (OPC Workflow Demo)

## What is this?

This project demonstrates a hybrid narrative-AI system combining two components:

- **Drift**: narrative/state engine — converts story text → structured game world state (`state_graph`)
- **AsyncAIFlow**: action scheduling + worker orchestration — manages async AI task pipelines end-to-end

Together they form a closed-loop OPC (Orchestrated Player Content) workflow:
`story premise → inject → evaluate → iterate (beam search) → structured state`

---

## Core Capabilities

### 1. Beam Search Experiment (`drift_experiment_v3`)
- Multi-path exploration: `beam_width` paths × N variants per round
- Global competitive ranking across all candidates
- Hypothesis generator: LLM (or rule-based fallback) proposes novel design directions — not patches

### 2. LLM Hypothesis Generation
- Input: best variant + weakness analysis
- Output: entirely new design direction (new premise)
- Falls back to rule-based templates when LLM unavailable

### 3. Structured State Graph (`drift_arc_v3`)
- `state_chain` (string) → `state_graph` (structured list of state objects)
- Each state object: `{completed_level, inventory[], flags[], progress, beats_count}`
- Inventory and flags carry over across levels — enables conditional branches in next level

---

## Repository Structure

```
AsyncAIFlow_4.8/
  src/                         Java backend (Spring Boot, action scheduler, Redis queue)
  python-workers/              Python worker implementations
    drift_arc_worker/          Arc orchestrator — state_graph generation
    drift_experiment_worker/   Beam Search experiment worker
    drift_plan_worker/         Planner worker
    drift_code_worker/         Code patch worker
    ...
  scripts/                     Dev/demo launch scripts
  docs/                        Architecture and schema docs

drift-system-clean（very important）_4.8/
  backend/                     Drift Python backend (FastAPI, narrative engine)
  plugin/                      Minecraft plugin (world patch executor)
  content/                     Story content and presets
  docs/                        Drift system documentation

deploy/
  docker-compose.cloud.yml     Cloud deployment config
  systemd/                     Systemd service units for production
```

---

## How to Run (minimal)

### 1. Start AsyncAIFlow backend
```bash
cd AsyncAIFlow_4.8
mvn spring-boot:run
# or: java -jar target/asyncaiflow-*.jar
```

### 2. Start Drift backend
```bash
cd drift-system-clean*/backend
pip install -r requirements.txt
uvicorn world_api:app --port 8000
```

### 3. Run Python workers
```bash
cd AsyncAIFlow_4.8/python-workers

# Arc worker (state_graph)
export DRIFT_ARC_ACTION_TYPE=drift_arc_v3
export ASYNCAIFLOW_URL=http://localhost:8080
export DRIFT_URL=http://localhost:8000
python3 drift_arc_worker/worker.py

# Experiment worker (beam search)
export DRIFT_EXPERIMENT_ACTION_TYPE=drift_experiment_v3
python3 drift_experiment_worker/worker.py
```

---

## Example Workflow

```bash
# 1. Create a workflow
curl -X POST http://localhost:8080/workflow/create \
  -H "Content-Type: application/json" \
  -d '{"name": "demo", "description": "arc test"}'

# 2. Submit an arc action
curl -X POST http://localhost:8080/action/create \
  -H "Content-Type: application/json" \
  -d '{
    "workflowId": <id>,
    "type": "drift_arc_v3",
    "name": "arc_test",
    "payload": "{\"player_id\":\"demo\",\"arc_title\":\"神庙三部曲\"}"
  }'

# 3. Poll result
curl http://localhost:8080/action/<action_id>
```

---

## Key API Endpoints

| Service | Endpoint | Description |
|---------|----------|-------------|
| AsyncAIFlow | `POST /workflow/create` | Create a workflow |
| AsyncAIFlow | `POST /action/create` | Submit an action |
| AsyncAIFlow | `GET /action/{id}` | Poll action result |
| AsyncAIFlow | `POST /action/{id}/renew-lease` | Extend action lease |
| Drift | `POST /story/inject` | Inject story text → world state |
| Drift | `POST /story/load/{player}/{level}` | Load level for player |
| Drift | `POST /world/story/rule-event` | Fire narrative event |

---

## Notes

This repo is prepared for:
- **zread** analysis — architecture readable from directory structure + this README
- **OPC workflow evaluation** — closed-loop story → state pipeline demonstration
- **Local + remote hybrid testing** — workers run locally, APIs point to remote VM via env vars

Worker action types use env-var overrides (`DRIFT_ARC_ACTION_TYPE`, `DRIFT_EXPERIMENT_ACTION_TYPE`)
to allow local v3 workers to coexist with VM v1/v2 workers without queue collision.
