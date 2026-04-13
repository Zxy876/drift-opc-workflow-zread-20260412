[![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=plastic&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/Zxy876/drift-system-classic)# DriftSystem v0.1
https://youtu.be/Bswtq8UmK88?si=lW0bWa0HcN_R1jJF

## Semantic Scene Generation Engine for Minecraft

DriftSystem is an AI-powered semantic scene generation engine that dynamically creates immersive Minecraft environments based on natural language input and player context.

---

## Architecture Overview

```
Player Input (Natural Language)
           ↓
    Semantic Engine
    - Parse player intent
    - Extract semantic tags
    - Map to narrative themes
           ↓
    Scene Prediction
    - Score candidate scenes
    - Select best match
    - Determine scene parameters
           ↓
    Theme Resolver
    - Load active theme pack
    - Apply visual style rules
    - Configure atmospheric settings
           ↓
    Fragment Selection
    - Query fragment library
    - Compose scene fragments
    - Generate spatial layout
           ↓
    Scene Assembler
    - Combine fragments into patch
    - Resolve entity placements
    - Generate loot containers
           ↓
    World Patch
    - Serializes to JSON
    - Transmits to plugin
           ↓
    Minecraft Plugin
    - Applies world modifications
    - Spawns entities
    - Triggers cutscene events
```

---

## Project Structure

```
drift-system/
├── backend/              # Python backend server
│   ├── app/
│   │   ├── api/         # REST API endpoints
│   │   ├── content/     # Scene and fragment definitions
│   │   ├── core/        # Core narrative engine
│   │   │   ├── narrative/
│   │   │   │   ├── scene_library.py      # Scene registry
│   │   │   │   ├── scene_assembler.py    # Fragment composition
│   │   │   │   └── semantic_engine.py    # Semantic processing
│   │   │   └── runtime/
│   │   │       └── resource_canonical.py # Resource canonicalization
│   │   └── routers/    # API route handlers
│   └── requirements.txt
│
├── plugin/              # Minecraft plugin (Java)
│   └── mc_plugin/
│       └── src/main/java/com/driftmc/
│           ├── DriftPlugin.java           # Main plugin class
│           ├── commands/                  # Plugin commands
│           ├── listeners/                 # Event listeners
│           └── scene/                     # Scene patch execution
│
├── content/            # Content definitions (exported from backend)
│   ├── scenes/
│   │   ├── fragments/   # Reusable scene fragments
│   │   └── presets/     # Scene scoring presets
│   └── semantic/        # Semantic mapping rules
│
├── docs/               # Documentation
│   ├── DRIFTSYSTEM_ARCHITECTURE_V0.5.md
│   ├── DRIFTSYSTEM_ROADMAP.md
│   └── SCENE_SCORING_PRESETS.md
│
└── scripts/            # Utility scripts
    ├── switch_scene_scoring_preset.sh
    └── scene_influence_15min_validation.sh
```

---

## Core Modules

### Semantic Engine (`backend/app/core/narrative/semantic_engine.py`)
- Processes natural language input
- Extracts semantic tags and intent
- Maps player input to scene themes

### Scene Library (`backend/app/core/narrative/scene_library.py`)
- Central registry of all scenes
- Scene metadata management
- Scene query and filtering

### Fragment Loader (`backend/app/content/scenes/`)
- Loads fragment definitions
- Manages fragment composition rules
- Handles fragment inheritance

### Scene Assembler (`backend/app/core/narrative/scene_assembler.py`)
- Composes scenes from fragments
- Generates world patch data
- Resolves entity and block placements

### World Patch Generator (`backend/app/core/runtime/resource_canonical.py`)
- Serializes scene data to JSON
- Canonicalizes resource names
- Validates patch integrity

### Minecraft Plugin Bridge (`plugin/mc_plugin/`)
- Receives world patches via HTTP
- Applies modifications to Minecraft world
- Handles player interaction events

---

## Hosted Backend

```
https://drift-backend-classic-production.up.railway.app
```

DriftSystem uses a hosted backend. Install the plugin and start the server. No backend setup required.

> Local development: edit `backend_url` in `plugins/DriftSystem/config.yml` to point at your local instance.

---

## Quick Start

### Plugin (Hosted Backend — No Setup Required)
1. Download `drift-plugin.jar` from the [v1 Release](https://github.com/Zxy876/drift-system-classic/releases/tag/drift-v1)
2. Drop into your server's `plugins/` folder
3. Start the server — connects to `https://drift-backend-classic-production.up.railway.app` automatically

### Backend Setup (Self-hosted / Development)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Plugin Build from Source
```bash
cd plugin
mvn clean package
# Copy target/mc_plugin-1.0-SNAPSHOT.jar to Minecraft plugins/
```

---

## Version

**v1.0 — drift-v1** · [GitHub Release](https://github.com/Zxy876/drift-system-classic/releases/tag/drift-v1)

Initial production release of DriftSystem / 心悦宇宙.
- Plugin: [drift-plugin-classic](https://github.com/Zxy876/drift-plugin-classic)
- Backend: [drift-backend-classic](https://github.com/Zxy876/drift-backend-classic)

---

## License

See LICENSE file for details.
