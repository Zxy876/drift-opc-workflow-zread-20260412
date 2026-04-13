# Drift System Architecture

## Overview

DriftSystem is an AI-powered semantic scene generation engine for Minecraft that dynamically creates immersive environments based on natural language input and player context.

---

## System Architecture (v0.1)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Player Input Layer                            │
│                    (Natural Language / Actions)                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Semantic Engine                                 │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Parse player intent                                           │   │
│  │ • Extract semantic tags (trade, travel, explore, etc.)          │   │
│  │ • Map to narrative themes                                       │   │
│  │ • Token weight: 5 | Poetic weight: 2 | Environment: 1          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Scene Prediction                                │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Score candidate scenes based on semantic match                │   │
│  │ • Select best matching scene template                           │   │
│  │ • Determine scene parameters (anchor, theme, hint)              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Theme Resolver                                  │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Load active theme pack (e.g., "desert", "forest", "ruins")    │   │
│  │ • Apply visual style rules                                      │   │
│  │ • Configure atmospheric settings                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Fragment Selection                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Query fragment library (buildings, NPCs, objects)             │   │
│  │ • Compose scene fragments based on theme + resources            │   │
│  │ • Generate spatial layout                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Scene Assembler                                 │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Combine fragments into world patch                           │   │
│  │ • Resolve entity placements (NPCs, mobs)                        │   │
│  │ • Generate loot containers with resources                       │   │
│  │ • Build event plan (spawn_camp, spawn_fire, spawn_npc, etc.)   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         World Patch                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Serializes scene data to JSON                                │   │
│  │ • Canonicalizes resource names                                 │   │
│  │ • Validates patch integrity                                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Minecraft Plugin Bridge                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ • Receives world patches via HTTP                              │   │
│  │ • Applies modifications to Minecraft world                     │   │
│  │ • Spawns structures, entities, blocks                          │   │
│  │ • Handles player interaction events                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Core Modules

### 1. Semantic Engine
**Location:** `backend/app/core/narrative/semantic_engine.py`

The Semantic Engine processes natural language input and extracts semantic meaning.

**Key Functions:**
- `infer_semantic_from_text(text)` - Main entry point for semantic inference
- `_score_domain(text, domain_rule)` - Scores text against semantic domains
- `_combo_from_scores(scores)` - Detects semantic combinations (e.g., trade+travel=caravan)

**Semantic Domains:**
- `trade` - Merchant, shop, market, commerce
- `travel` - Journey, road, wander, expedition
- `explore` - Ruin, cave, ancient, discovery

**Output Structure:**
```json
{
  "semantic": "trade",
  "predicted_root": "trade_post",
  "score": 15,
  "matched_keywords": ["merchant", "market"],
  "resolution": [...]
}
```

---

### 2. Scene Library
**Location:** `backend/app/core/narrative/scene_library.py`

Central registry for all scene templates and fragment selection logic.

**Key Functions:**
- `select_fragments_with_debug(resources, theme, scene_hint)` - Selects fragments based on context
- `build_event_plan(fragments, anchor_position)` - Generates executable event sequence

**Fragment Types:**
- `spawn_camp` - Base camp with tent and fire
- `spawn_fire` - Campfire spawn point
- `spawn_npc` - NPC character spawn
- `spawn_cooking_area` - Cooking setup with cauldron

---

### 3. Scene Assembler
**Location:** `backend/app/core/narrative/scene_assembler.py`

Orchestrates the scene generation pipeline from input to world patch.

**Key Functions:**
- `assemble_scene(inventory_state, story_theme, scene_hint, anchor_position)` - Main assembly function

**Assembly Pipeline:**
1. Normalize inventory state and resources
2. Select fragments via scene library
3. Build event plan with anchor positions
4. Generate debug trace (if enabled)
5. Return complete scene plan

**Output Structure:**
```json
{
  "scene_plan": {
    "template_version": "scene_template_v1",
    "fragments": ["camp", "fire", "npc"],
    "scene_graph": {...},
    "layout": {...}
  },
  "event_plan": [
    {"event_id": "...", "type": "spawn_camp", "offset": [0, 0, 0]},
    ...
  ]
}
```

---

### 4. Resource Canonicalizer
**Location:** `backend/app/core/runtime/resource_canonical.py`

Normalizes resource names across Minecraft items and internal canonical names.

**Key Mappings:**
- Minecraft items → Canonical resources
- Variant handling (oak_log → wood, stone → stone)
- Inventory state normalization

---

### 5. Minecraft Plugin Bridge
**Location:** `plugin/mc_plugin/src/main/java/com/driftmc/`

Java plugin that receives world patches and executes them in Minecraft.

**Key Classes:**
- `DriftPlugin.java` - Main plugin entry point
- `WorldPatchExecutor.java` - Executes world modifications
- `PlayerChatListener.java` - Captures player chat for semantic input
- `RuleEventBridge.java` - Bridges rule events to backend

**API Endpoints:**
- `POST /world/apply` - Receive and execute world patches
- `POST /world/apply/report` - Report execution results

---

## Data Flow

### 1. Player Input → Semantic Engine
```
Player: "I want to find a merchant"
    ↓
Semantic Engine: {semantic: "trade", predicted_root: "trade_post"}
```

### 2. Semantic → Scene Selection
```
{semantic: "trade"} + inventory: {gold: 10}
    ↓
Scene Library: Selects trade_post fragments with merchant NPC
```

### 3. Scene → World Patch
```
fragments: ["trade_post", "merchant_cart", "caravan_camp"]
    ↓
Scene Assembler: event_plan with spawn structures
```

### 4. World Patch → Minecraft
```
event_plan → WorldPatchExecutor
    ↓
Minecraft World: Trade post appears at player location
```

---

## Content Structure

### Fragment Definitions
**Location:** `content/scenes/fragments/`

Reusable scene components that can be combined:
- `arena.json` - Combat training arena
- `inn.json` - Rest location with common room
- `mine.json` - Resource extraction site
- `temple.json` - Spiritual/mystical location
- `trade_post.json` - Commerce hub

### Presets
**Location:** `content/scenes/presets/`

Pre-configured scene scoring profiles for different gameplay styles.

### Semantic Mappings
**Location:** `content/semantic/`

Rules mapping player input to scene themes.

---

## API Contract

### Scene Injection
**Endpoint:** `POST /story/inject`

**Request:**
```json
{
  "inventory_state": {
    "player_id": "uuid",
    "resources": {"wood": 5, "gold": 10}
  },
  "story_theme": "desert",
  "scene_hint": "A merchant caravan rests here"
}
```

**Response:**
```json
{
  "scene_plan": {...},
  "event_plan": [...],
  "selected_assets": [...]
}
```

### World Application
**Endpoint:** `POST /world/apply`

**Request:**
```json
{
  "patch_id": "uuid",
  "world_patch": {...}
}
```

---

## Determinism Guarantees

The system maintains deterministic output for identical inputs:
- Same resources + theme + hint → Same fragments
- Same fragments → Same event plan
- Same event plan → Same world patch

This enables reproducible testing and debugging.

---

## Extension Points

### Adding New Semantic Domains
Edit `semantic_engine.py`:
```python
SEMANTIC_FIELDS: Dict[str, Dict[str, Any]] = {
    "your_domain": {
        "tokens": ["keyword1", "keyword2"],
        "poetic": ["evocative1", "evocative2"],
        "environment": ["env1", "env2"],
        "root": "your_scene_root"
    }
}
```

### Adding New Fragments
Create fragment JSON in `content/scenes/fragments/`:
```json
{
  "fragment_id": "your_fragment",
  "display_name": "Your Fragment",
  "semantic_tags": ["your_domain"],
  "required_resources": {},
  "structure_templates": [...],
  "events": [...]
}
```

---

## Version Information

**Current Version:** v0.1-semantic-scene-engine

This is the initial stable release of DriftSystem's semantic scene generation engine.
