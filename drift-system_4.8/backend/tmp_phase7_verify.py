import sys, os, json
os.environ.setdefault("PYTEST_CURRENT_TEST", "phase7_verify")
sys.path.insert(0, ".")

from app.core.runtime.world_patch_compiler import (
    compile_to_world_patch,
    validate_world_patch,
    classify_world_evidence_level,
    is_visual_only,
)
from app.core.ai.intent_engine import classify_scene


def make_content_payload(name):
    block_ops = []
    n = 0
    for x in range(13):
        for z in range(10):
            block_ops.append({"anchor": [0, 0, 0], "offset": [x * 2, n % 5, z * 2],
                               "block": "OAK_PLANKS" if n % 3 != 0 else "STONE"})
            n += 1
    for y in range(8):
        block_ops.append({"anchor": [0, 0, 0], "offset": [0, y, 0], "block": "STONE_BRICKS"})
    return {"block_ops": block_ops, "entity_ops": [
        {"entity_type": "villager", "offset": [5, 1, 5], "name": f"{name}_guide"}
    ]}


def make_rule_patch():
    return {"trigger_zones": [{"id": "vote_zone", "quest_event": "vote_cast",
                                "radius": 3.0, "repeat": True}]}


def make_simulation_patch():
    return {"tell": "§6[模拟器] 潜伏阶段已激活",
            "title": {"title": "§6观察模式", "subtitle": "§7记录中...",
                      "fadeIn": 10, "stay": 100, "fadeOut": 20}}


results = []

# ── CONTENT × 3 ──────────────────────────────────────────────────────────────
for name, text in [("城堡", "帮我建造一个城堡"), ("地牢", "生成一个地牢关卡"),
                   ("火山", "创建火山场景")]:
    scene_type = classify_scene(text, "CREATE_STORY")
    payload = make_content_payload(name)
    patch = compile_to_world_patch(payload)
    evl = classify_world_evidence_level(patch)
    val = validate_world_patch(patch)
    results.append({
        "scenario": name, "input_class": "CONTENT",
        "scene_type_routed": scene_type, "route_correct": scene_type == "CONTENT",
        "world_evidence_level": evl, "structural_world": evl == "STRUCTURAL_WORLD",
        "block_count": val["block_count"], "compiler_mode": val["compiler_mode"],
        "build_shape_summary": val["build_shape_summary"],
        "entity_count": val["entity_count"], "fallback_triggered": False,
        "regression": scene_type != "CONTENT" or evl != "STRUCTURAL_WORLD",
    })

# ── RULE × 2 ─────────────────────────────────────────────────────────────────
for name, text in [("投票", "发起一次投票表决"), ("谁是卧底", "开始谁是卧底游戏")]:
    scene_type = classify_scene(text, "CREATE_STORY")
    patch = make_rule_patch()
    evl = classify_world_evidence_level(patch)
    val = validate_world_patch(patch)
    results.append({
        "scenario": name, "input_class": "RULE",
        "scene_type_routed": scene_type, "route_correct": scene_type == "RULE",
        "world_evidence_level": evl, "structural_world": False,
        "block_count": val["block_count"], "compiler_mode": val["compiler_mode"],
        "build_shape_summary": None, "entity_count": 0, "fallback_triggered": False,
        "regression": scene_type != "RULE",
    })

# ── SIMULATION × 2 ───────────────────────────────────────────────────────────
for name, text in [("潜伏模拟", "开始长期潜伏行为实验"), ("状态跟踪", "持续追踪玩家行为状态")]:
    scene_type = classify_scene(text, "CREATE_STORY")
    patch = make_simulation_patch()
    evl = classify_world_evidence_level(patch)
    val = validate_world_patch(patch)
    results.append({
        "scenario": name, "input_class": "SIMULATION",
        "scene_type_routed": scene_type, "route_correct": scene_type == "SIMULATION",
        "world_evidence_level": evl, "structural_world": False,
        "block_count": val["block_count"], "compiler_mode": val["compiler_mode"],
        "build_shape_summary": None, "entity_count": 0, "fallback_triggered": False,
        "regression": scene_type != "SIMULATION",
    })

# ── 3-Level Classification Probes ────────────────────────────────────────────
level_probes = [
    ({"tell": "hello", "title": {"title": "x"}, "sound": {"sound": "x"}}, "VISUAL_ONLY"),
    ({"trigger_zones": [{"id": "z"}]}, "INTERACTIVE_WORLD"),
    ({"mc": {"build": {"shape": "house", "material": "STONE", "size": 7,
                       "offset": {"dx": 0, "dy": 0, "dz": 0}}}}, "STRUCTURAL_WORLD"),
    ({}, "EMPTY"),
    ({"tell": "hi", "trigger_zones": [{"id": "z"}]}, "INTERACTIVE_WORLD"),
    ({"mc": {"blocks": [{"block": "STONE", "dx": 0, "dy": 0, "dz": 0}]},
      "tell": "hi"}, "STRUCTURAL_WORLD"),
]

print("\n═══════ 3-Level Classification Probes ═══════")
probe_pass = 0
for patch, expected in level_probes:
    got = classify_world_evidence_level(patch)
    ok = got == expected
    probe_pass += ok
    print(f"  {'OK' if ok else 'FAIL'} expected={expected:<20} got={got:<20} keys={list(patch.keys())}")

print(f"\nProbes: {probe_pass}/{len(level_probes)} PASS")

# ── is_visual_only fix verification ──────────────────────────────────────────
print("\n═══════ is_visual_only Fix Verification ═══════")
fallback_patch = {
    "tell": "AI 能力已部署",
    "title": {"title": "能力已更新"},
    "sound": {"sound": "ENTITY_PLAYER_LEVELUP"},
    "particle": {"type": "VILLAGER_HAPPY"},
    "trigger_zones": [{"id": "ai_cap_123"}],
}
ivo_result = is_visual_only(fallback_patch)
evl_fallback = classify_world_evidence_level(fallback_patch)
print(f"  Fallback patch: is_visual_only={ivo_result}  evidence_level={evl_fallback}")
print(f"  Expected: is_visual_only=False, evidence_level=INTERACTIVE_WORLD")
fallback_ok = not ivo_result and evl_fallback == "INTERACTIVE_WORLD"
print(f"  Result: {'OK' if fallback_ok else 'FAIL'}")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n═══════ Scenario Results ═══════")
for r in results:
    flag = "OK  " if not r["regression"] else "FAIL"
    print(f"  [{flag}] [{r['input_class']:<12}] {r['scenario']:<10} "
          f"route={r['scene_type_routed']:<14} "
          f"evidence={r['world_evidence_level']:<20} "
          f"blocks={r['block_count']:3}  "
          f"mode={r['compiler_mode']}")

passed = sum(1 for r in results if not r["regression"])
all_content_structural = all(
    r["world_evidence_level"] == "STRUCTURAL_WORLD"
    for r in results if r["input_class"] == "CONTENT"
)
rule_sim_routed = all(
    r["route_correct"]
    for r in results if r["input_class"] in ("RULE", "SIMULATION")
)
content_routed = all(
    r["route_correct"]
    for r in results if r["input_class"] == "CONTENT"
)
all_probes_pass = probe_pass == len(level_probes)

verdict_data = {
    "phase": "Phase 7",
    "world_runtime": "ON",
    "content_world_first": content_routed and all_content_structural,
    "rule_simulation_routed": rule_sim_routed,
    "structural_world_verified": all_content_structural,
    "evidence_classification_correct": all_probes_pass,
    "fallback_guard_fixed": fallback_ok,
    "regression": passed < len(results) or not all_probes_pass or not fallback_ok,
    "verdict": "PHASE_7_READY" if (
        passed == len(results) and all_probes_pass and fallback_ok
    ) else "NEEDS_MORE_WORK",
}
print("\n═══════ Phase 7 Verdict ═══════")
print(json.dumps(verdict_data, indent=2, ensure_ascii=False))
