"""
World Patch Compiler  —  Phase 6 (World Semantics Upgrade)
============================================================
Converts payload_v2 (block_ops + entity_ops) into a world_patch dict that
WorldPatchExecutor (Java plugin) can execute directly.

Phase 5 output  →  flat blocks list
Phase 6 output  →  structure-semantic mixed patch:

{
    "mc": {
        "build": {"shape": "house", "material": "oak_planks",
                  "size": 5, "offset": {"dx": 0, "dy": 0, "dz": 0}},
        "build_multi": [...],          # secondary clumps
        "blocks": [...],               # residual / isolated blocks
        "spawn_multi": [...]           # entities (when present)
    }
}

Structure detection heuristic
------------------------------
Given the dx/dy/dz offsets of all blocks from build_plugin_payload_v2:

- Compute bounding box (width W, height H, depth D)
- height_ratio H/max(W,D):
    >= 1.5 → "wall"  (vertically dominant)
    < 0.3  → "platform"
    else   → "house"  (default room/structure)
- size  = max(W, D)  (used as WorldPatchExecutor buildmap radius)
- centroid offset used as origin
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

# ─── public constants ─────────────────────────────────────────────────────────
# Level A — Visual Only  (no world state change)
VISUAL_ONLY_KEYS = frozenset({"particle", "title", "sound", "tell", "actionbar", "music"})
# Level B — Interactive World  (runtime-interactive, not structural build)
INTERACTIVE_KEYS = frozenset({"trigger_zones", "teleport", "effect", "weather", "time"})
# Legacy combined set (kept for callers using STRUCTURE_KEYS)
STRUCTURE_KEYS   = frozenset({
    "build", "build_multi", "blocks", "structure",
    "spawn", "spawn_multi", "spawns", "trigger_zones",
})
# Level C — Structural World (block-level + entity spawn)
HARD_STRUCTURE_KEYS = frozenset({"build", "build_multi", "blocks", "structure"})
STRUCTURAL_LEVEL_KEYS = HARD_STRUCTURE_KEYS | frozenset({"spawn", "spawn_multi", "spawns"})


# ─── internal utilities ───────────────────────────────────────────────────────

def _safe_offset(raw: Any) -> Tuple[int, int, int]:
    """[x, y, z] list/tuple → (dx, dy, dz) ints."""
    if isinstance(raw, (list, tuple)) and len(raw) >= 3:
        try:
            return int(raw[0]), int(raw[1]), int(raw[2])
        except (TypeError, ValueError):
            pass
    return 0, 0, 0


def _centroid(points: List[Tuple[int, int, int]]) -> Tuple[float, float, float]:
    n = len(points)
    if n == 0:
        return 0.0, 0.0, 0.0
    return (
        sum(p[0] for p in points) / n,
        sum(p[1] for p in points) / n,
        sum(p[2] for p in points) / n,
    )


def _bounding_box(points: List[Tuple[int, int, int]]) -> Dict[str, int]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return {
        "min_x": min(xs), "max_x": max(xs),
        "min_y": min(ys), "max_y": max(ys),
        "min_z": min(zs), "max_z": max(zs),
        "width":  max(xs) - min(xs) + 1,
        "height": max(ys) - min(ys) + 1,
        "depth":  max(zs) - min(zs) + 1,
    }


# ─── structure shape detection ────────────────────────────────────────────────

def _detect_shape(bb: Dict[str, int]) -> str:
    """
    Classify a bounding box into a WorldPatchExecutor shape keyword.

    Rules (conservative — designed to map safely to handleBuild shapes):
      height >= 1.5 × max(width, depth)   → "wall"
      height <= 0.3 × max(width, depth)   → "platform"
      else                                 → "house"
    """
    w = bb["width"]
    h = bb["height"]
    d = bb["depth"]
    footprint = max(w, d)
    if footprint == 0:
        return "platform"

    hr = h / footprint
    if hr >= 1.5:
        return "wall"
    if hr <= 0.3:
        return "platform"
    return "house"


def _dominant_material(block_ops: List[Dict[str, Any]]) -> str:
    """Return the most common block id from a list of block_ops."""
    counts: Dict[str, int] = {}
    for op in block_ops:
        bid = str(op.get("block") or "oak_planks")
        counts[bid] = counts.get(bid, 0) + 1
    if not counts:
        return "oak_planks"
    return max(counts, key=lambda k: counts[k])


# ─── clustering: split ops into a "primary" group and residual ─────────────────

def _cluster_ops(
    ops: List[Dict[str, Any]],
    *,
    cluster_threshold: int = 4,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Very simple spatial clustering: the largest connected component (blocks
    within `cluster_threshold` Manhattan distance) becomes the primary cluster;
    everything else is residual.

    Returns (primary_ops, residual_ops).
    """
    if len(ops) <= 1:
        return ops, []

    # Extract positions
    pts = [_safe_offset(op.get("offset")) for op in ops]

    visited = [False] * len(ops)
    components: List[List[int]] = []

    for start in range(len(ops)):
        if visited[start]:
            continue
        comp = [start]
        visited[start] = True
        queue = [start]
        while queue:
            curr = queue.pop()
            cx, cy, cz = pts[curr]
            for nxt in range(len(ops)):
                if visited[nxt]:
                    continue
                nx, ny, nz = pts[nxt]
                dist = abs(nx - cx) + abs(ny - cy) + abs(nz - cz)
                if dist <= cluster_threshold:
                    visited[nxt] = True
                    comp.append(nxt)
                    queue.append(nxt)
        components.append(comp)

    if not components:
        return ops, []

    primary_indices = max(components, key=len)
    primary_set = set(primary_indices)
    primary = [ops[i] for i in primary_indices]
    residual = [ops[i] for i in range(len(ops)) if i not in primary_set]
    return primary, residual


# ─── public API ───────────────────────────────────────────────────────────────

def compile_to_world_patch(payload_v2: dict) -> dict:
    """
    Phase 6: semantics-aware compile.

    block_ops  →  primary shape (build) + secondary clumps (build_multi) + residual (blocks)
    entity_ops →  spawn_multi
    """
    if not isinstance(payload_v2, dict):
        return {}

    raw_block_ops: List[Any] = payload_v2.get("block_ops") or []
    raw_entity_ops: List[Any] = payload_v2.get("entity_ops") or []

    # ── validate inputs ───────────────────────────────────────────────────────
    block_ops = [op for op in raw_block_ops if isinstance(op, dict)]
    entity_ops = [op for op in raw_entity_ops if isinstance(op, dict)]

    if not block_ops and not entity_ops:
        return {}

    mc_patch: Dict[str, Any] = {}

    if block_ops:
        # --- primary cluster → build directive ----------------------------
        primary, residual = _cluster_ops(block_ops)

        primary_pts = [_safe_offset(op.get("offset")) for op in primary]
        bb = _bounding_box(primary_pts)
        shape = _detect_shape(bb)
        material = _dominant_material(primary)

        # size = max(footprint, 1); capped at 20 to avoid explosions
        size = max(1, min(20, max(bb["width"], bb["depth"])))

        cx, cy, cz = _centroid(primary_pts)
        build_dir: Dict[str, Any] = {
            "shape": shape,
            "material": material.upper(),
            "size": size,
            "offset": {
                "dx": int(round(cx)),
                "dy": int(round(cy)),
                "dz": int(round(cz)),
            },
        }
        mc_patch["build"] = build_dir

        # --- secondary build_multi (residual grouped by material) ---------
        if residual:
            build_multi: List[Dict[str, Any]] = []
            # group residual by material
            by_mat: Dict[str, List[Dict[str, Any]]] = {}
            for op in residual:
                bid = str(op.get("block") or "oak_planks")
                by_mat.setdefault(bid, []).append(op)

            for mat, ops in by_mat.items():
                sub_pts = [_safe_offset(op.get("offset")) for op in ops]
                sub_bb = _bounding_box(sub_pts)
                sub_shape = _detect_shape(sub_bb)
                sub_size = max(1, min(10, max(sub_bb["width"], sub_bb["depth"])))
                sub_cx, sub_cy, sub_cz = _centroid(sub_pts)
                build_multi.append({
                    "shape": sub_shape,
                    "material": mat.upper(),
                    "size": sub_size,
                    "offset": {
                        "dx": int(round(sub_cx)),
                        "dy": int(round(sub_cy)),
                        "dz": int(round(sub_cz)),
                    },
                })
            if build_multi:
                mc_patch["build_multi"] = build_multi

        # --- always keep flat blocks list for precise execution -----------
        blocks_list: List[Dict[str, Any]] = []
        for op in block_ops:
            block_id = str(op.get("block") or "oak_planks")
            dx, dy, dz = _safe_offset(op.get("offset"))
            blocks_list.append({"block": block_id, "dx": dx, "dy": dy, "dz": dz})
        mc_patch["blocks"] = blocks_list

    # ── entity_ops → spawn_multi ──────────────────────────────────────────────
    if entity_ops:
        spawn_multi: List[Dict[str, Any]] = []
        for op in entity_ops:
            entity_type = str(op.get("entity_type") or "villager")
            name = str(op.get("name") or "")
            dx, dy, dz = _safe_offset(op.get("offset"))
            entry: Dict[str, Any] = {"type": entity_type, "dx": dx, "dy": dy, "dz": dz}
            if name:
                entry["name"] = name
            spawn_multi.append(entry)
        mc_patch["spawn_multi"] = spawn_multi

    if not mc_patch:
        return {}

    return {"mc": mc_patch}


# ─── validation ───────────────────────────────────────────────────────────────

def _collect_all_keys(world_patch: dict) -> set:
    """Flatten top-level + mc content into a unified key set (excluding 'mc' container)."""
    mc = world_patch.get("mc")
    if isinstance(mc, dict):
        return set(world_patch.keys()) | set(mc.keys())
    if isinstance(mc, list):
        nested_keys: set = set()
        for item in mc:
            if isinstance(item, dict):
                nested_keys |= set(item.keys())
        return set(world_patch.keys()) | nested_keys
    return set(world_patch.keys())


def classify_world_evidence_level(world_patch: dict) -> str:
    """
    Phase 7: Classify a world_patch into one of 4 evidence levels:

      STRUCTURAL_WORLD  — build / build_multi / blocks / structure /
                          spawn / spawn_multi / spawns present
      INTERACTIVE_WORLD — trigger_zones / teleport / effect / weather / time present
      VISUAL_ONLY       — only particle / title / sound / tell / actionbar / music
      EMPTY             — no recognizable op at all

    This is the single authoritative evidence classifier for Phase 7.
    """
    if not isinstance(world_patch, dict) or not world_patch:
        return "EMPTY"
    effective_keys = _collect_all_keys(world_patch) - {"mc"}
    if STRUCTURAL_LEVEL_KEYS & effective_keys:
        return "STRUCTURAL_WORLD"
    if INTERACTIVE_KEYS & effective_keys:
        return "INTERACTIVE_WORLD"
    if VISUAL_ONLY_KEYS & effective_keys:
        return "VISUAL_ONLY"
    return "EMPTY"


def validate_world_patch(world_patch: dict) -> Dict[str, Any]:
    """
    Validate a world_patch for structural content.

    Returns (backward-compatible Phase 6 fields + Phase 7 evidence extension):
        {
            # ── Phase 6 (backward-compat) ──────────────────
            "valid": bool,
            "has_structure": bool,
            "block_count": int,
            "is_visual_only": bool,
            "failure_reason": str | None,
            "structure_keys_found": list[str],
            # ── Phase 7 world evidence extension ────────────
            "world_evidence_level": "STRUCTURAL_WORLD"
                                    | "INTERACTIVE_WORLD"
                                    | "VISUAL_ONLY" | "EMPTY",
            "visual_keys_found": list[str],
            "interactive_keys_found": list[str],
            "build_shape_summary": dict | None,
            "entity_count": int,
            "compiler_mode": "grouped_build" | "mixed_patch" | "raw_blocks"
                              | "entity_only" | "empty",
        }
    """
    _EMPTY_RESULT: Dict[str, Any] = {
        "valid": False,
        "has_structure": False,
        "block_count": 0,
        "is_visual_only": False,
        "failure_reason": "world_patch is not a dict",
        "structure_keys_found": [],
        "world_evidence_level": "EMPTY",
        "visual_keys_found": [],
        "interactive_keys_found": [],
        "build_shape_summary": None,
        "entity_count": 0,
        "compiler_mode": "empty",
    }
    if not isinstance(world_patch, dict):
        return _EMPTY_RESULT

    mc = world_patch.get("mc")
    effective_keys = _collect_all_keys(world_patch) - {"mc"}

    # ── 3-level evidence classification ──────────────────────────────────────
    world_evidence_level = classify_world_evidence_level(world_patch)

    # ── per-level key inventory ───────────────────────────────────────────────
    visual_keys_found      = sorted(VISUAL_ONLY_KEYS  & effective_keys)
    interactive_keys_found = sorted(INTERACTIVE_KEYS  & effective_keys)
    struct_found           = sorted(HARD_STRUCTURE_KEYS & effective_keys)
    has_structure          = len(struct_found) > 0
    is_visual_only_flag    = world_evidence_level in ("VISUAL_ONLY", "EMPTY")

    # ── block count (from mc.blocks list) ─────────────────────────────────────
    block_count = 0
    if isinstance(mc, dict):
        bl = mc.get("blocks") or []
        if isinstance(bl, list):
            block_count = len(bl)
    elif isinstance(mc, list):
        for item in mc:
            if isinstance(item, dict):
                _bl = item.get("blocks")
                if isinstance(_bl, list):
                    block_count += len(_bl)

    # ── build shape summary ────────────────────────────────────────────────────
    build_shape_summary: Dict[str, Any] | None = None
    if isinstance(mc, dict) and "build" in mc:
        b = mc["build"]
        build_shape_summary = {
            "shape": b.get("shape"),
            "material": b.get("material"),
            "size": b.get("size"),
            "build_multi_count": len(mc.get("build_multi") or []),
        }

    # ── entity count ──────────────────────────────────────────────────────────
    entity_count = 0
    if isinstance(mc, dict):
        sm = mc.get("spawn_multi") or []
        if isinstance(sm, list):
            entity_count = len(sm)

    # ── compiler mode ─────────────────────────────────────────────────────────
    if isinstance(mc, dict):
        _has_build  = "build" in mc
        _has_blocks = bool(mc.get("blocks"))
        _has_spawn  = bool(mc.get("spawn_multi"))
        if _has_build and _has_blocks:
            compiler_mode = "mixed_patch"
        elif _has_build:
            compiler_mode = "grouped_build"
        elif _has_blocks:
            compiler_mode = "raw_blocks"
        elif _has_spawn:
            compiler_mode = "entity_only"
        else:
            compiler_mode = "empty"
    else:
        compiler_mode = "empty"

    # ── validity decision ─────────────────────────────────────────────────────
    failure_reason: str | None = None
    is_valid = True
    if world_evidence_level == "EMPTY":
        failure_reason = "world_patch is empty or has no recognizable operations"
        is_valid = False
    elif world_evidence_level == "VISUAL_ONLY":
        failure_reason = "world_patch contains only visual-effect keys (no structural/interactive ops)"
        is_valid = False
    elif not has_structure:
        # INTERACTIVE_WORLD: valid from evidence standpoint, but not structural
        failure_reason = "world_patch has no block-level structural keys (build/blocks/structure)"
        is_valid = False
    elif block_count > 0 and block_count < 10:
        failure_reason = f"block_count={block_count} is below minimum threshold (10)"
        is_valid = False

    return {
        # ── Phase 6 (backward-compat) ─────────────────────────────────────────
        "valid": is_valid,
        "has_structure": has_structure,
        "block_count": block_count,
        "is_visual_only": is_visual_only_flag,
        "failure_reason": failure_reason,
        "structure_keys_found": struct_found,
        # ── Phase 7 world evidence extension ──────────────────────────────────
        "world_evidence_level": world_evidence_level,
        "visual_keys_found": visual_keys_found,
        "interactive_keys_found": interactive_keys_found,
        "build_shape_summary": build_shape_summary,
        "entity_count": entity_count,
        "compiler_mode": compiler_mode,
    }


def is_visual_only(world_patch: dict) -> bool:
    """Return True if the patch is VISUAL_ONLY or EMPTY (no structural/interactive ops)."""
    return classify_world_evidence_level(world_patch) in ("VISUAL_ONLY", "EMPTY")

