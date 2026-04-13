"""
mc_schema_validator.py — Drift MC 类型系统

把 LLM 当作"编译器前端"，本模块是"类型检查器"：
  1. 验证 mc_material / mc_entity_type 是否合法
  2. 通过 alias 修正常见笔误 / LLM 幻觉
  3. 用 semantic 标签在主字段缺失时推断最佳值
  4. 记录验证决策（_mc_validated）供调试用

不会抛出异常；总是返回一个合法的结果。
"""

from typing import Any, Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# Paper MC 1.20 EntityType 合法集合
# 来源：org.bukkit.entity.EntityType 枚举，fromName() 可识别的名称
# ─────────────────────────────────────────────────────────────────────────────
VALID_HOSTILE_ENTITIES: frozenset[str] = frozenset({
    # 地面近战
    "ZOMBIE", "HUSK", "ZOMBIE_VILLAGER", "DROWNED", "GIANT",
    "SKELETON", "STRAY", "WITHER_SKELETON",
    "SPIDER", "CAVE_SPIDER",
    "CREEPER",
    "ENDERMAN", "ENDERMITE",
    "SILVERFISH",
    "WITCH",
    "BLAZE",
    "GHAST",
    "SLIME", "MAGMA_CUBE",
    "PHANTOM",
    # 1.14+
    "PILLAGER", "RAVAGER", "VINDICATOR", "EVOKER", "VEX",
    # 1.16+
    "HOGLIN", "ZOGLIN", "PIGLIN_BRUTE", "ZOMBIFIED_PIGLIN", "ZOMBIE_PIGMAN",
    # 1.19+
    "WARDEN",
    # 水下
    "GUARDIAN", "ELDER_GUARDIAN",
    "SHULKER",
    # 中性（但在本验证器里允许作为 guard）
    "IRON_GOLEM",
})

VALID_NEUTRAL_ENTITIES: frozenset[str] = frozenset({
    "VILLAGER", "WANDERING_TRADER",
    "WITCH",
    "WOLF", "LLAMA", "TRADER_LLAMA",
    "BEE", "POLAR_BEAR",
    "PIGLIN",
    "ENDERMAN",
})

VALID_ALL_ENTITIES: frozenset[str] = VALID_HOSTILE_ENTITIES | VALID_NEUTRAL_ENTITIES

# ─────────────────────────────────────────────────────────────────────────────
# MC 1.20 可捡拾物品材质白名单
# ─────────────────────────────────────────────────────────────────────────────
VALID_ITEM_MATERIALS: frozenset[str] = frozenset({
    # 宝石类
    "EMERALD", "DIAMOND", "AMETHYST_SHARD", "PRISMARINE_CRYSTALS",
    "ECHO_SHARD", "QUARTZ", "LAPIS_LAZULI", "REDSTONE",
    # 金属类
    "GOLD_INGOT", "GOLD_NUGGET", "IRON_INGOT", "COPPER_INGOT", "NETHERITE_INGOT",
    "NETHERITE_SCRAP",
    # 稀有 / 任务道具
    "NETHER_STAR", "HEART_OF_THE_SEA", "DRAGON_EGG",
    # 魔法道具
    "ENDER_PEARL", "ENDER_EYE", "BLAZE_ROD", "BLAZE_POWDER",
    "TOTEM_OF_UNDYING",
    # 文件 / 书
    "PAPER", "BOOK", "WRITABLE_BOOK", "WRITTEN_BOOK", "ENCHANTED_BOOK",
    # 工具道具
    "COMPASS", "CLOCK", "MAP", "FILLED_MAP", "LODESTONE",
    "TRIPWIRE_HOOK", "LEAD",
    # 掉落物
    "BONE", "FEATHER", "STRING", "ROTTEN_FLESH", "SPIDER_EYE",
    "LEATHER", "RABBIT_FOOT", "RABBIT_HIDE",
    # 食物
    "APPLE", "GOLDEN_APPLE", "ENCHANTED_GOLDEN_APPLE",
    "BREAD", "CAKE",
    # 环境
    "TORCH", "LANTERN", "SOUL_LANTERN",
    "OAK_SAPLING", "FLOWER_POT",
    # 蘑菇 / 自然
    "RED_MUSHROOM", "BROWN_MUSHROOM", "SWEET_BERRIES", "GLOW_BERRIES",
})

# ─────────────────────────────────────────────────────────────────────────────
# 实体别名：修正 LLM 常见错误 / 非英文语义名
# ─────────────────────────────────────────────────────────────────────────────
_ENTITY_ALIASES: Dict[str, str] = {
    # 常见拼写变体
    "ZOMBIE_PIG": "ZOMBIFIED_PIGLIN",
    "PIG_ZOMBIE": "ZOMBIFIED_PIGLIN",
    "ZOMBIE_PIGMAN": "ZOMBIFIED_PIGLIN",
    "SKELETON_ARCHER": "SKELETON",
    "SKELETON_WARRIOR": "WITHER_SKELETON",
    "ARCHER": "SKELETON",
    "WITHER_ARCHER": "WITHER_SKELETON",
    "FIRE_SLIME": "MAGMA_CUBE",
    "FIRE_MOB": "BLAZE",
    "FIRE_DEMON": "BLAZE",
    "DARK_WITCH": "WITCH",
    "EVIL_VILLAGER": "ZOMBIE_VILLAGER",
    "GHOST": "PHANTOM",
    "WRAITH": "PHANTOM",
    "BANSHEE": "VEX",
    "DEMON": "BLAZE",
    "GOLEM": "IRON_GOLEM",
    "GUARDIAN_BOSS": "ELDER_GUARDIAN",
    "CAVE_MONSTER": "CAVE_SPIDER",
    "GUARD": "ZOMBIE",
    "PATROL": "PILLAGER",
    "SOLDIER": "ZOMBIE",
    # 英文语义近义
    "SPECTER": "PHANTOM",
    "REVENANT": "ZOMBIE",
    "SHADE": "VEX",
    "HORROR": "WARDEN",
    "TITAN": "GIANT",
}

# ─────────────────────────────────────────────────────────────────────────────
# 材质别名
# ─────────────────────────────────────────────────────────────────────────────
_MATERIAL_ALIASES: Dict[str, str] = {
    # LLM 常见幻觉名 → 真实 MC 材质
    "AMETHYST": "AMETHYST_SHARD",
    "CRYSTAL": "AMETHYST_SHARD",
    "MOON_CRYSTAL": "AMETHYST_SHARD",
    "MOONSTONE": "AMETHYST_SHARD",
    "STARSTONE": "AMETHYST_SHARD",
    "MAGIC_CRYSTAL": "AMETHYST_SHARD",
    "QUARTZ_CRYSTAL": "QUARTZ",
    "RED_CRYSTAL": "REDSTONE",
    "REDSTONE_DUST": "REDSTONE",
    "FIRE_CRYSTAL": "BLAZE_ROD",
    "FIRE_GEM": "BLAZE_ROD",
    "ORB": "ENDER_PEARL",
    "SOUL_ORB": "HEART_OF_THE_SEA",
    "SPIRIT_ORB": "HEART_OF_THE_SEA",
    "SOUL_CRYSTAL": "HEART_OF_THE_SEA",
    "OCEAN_HEART": "HEART_OF_THE_SEA",
    "ECHO_CRYSTAL": "ECHO_SHARD",
    "DARK_GEM": "NETHER_STAR",
    "VOID_GEM": "NETHER_STAR",
    "CHAOS_GEM": "NETHER_STAR",
    "STAR_FRAGMENT": "NETHER_STAR",
    "GEM": "EMERALD",
    "RUBY": "REDSTONE",
    "SAPPHIRE": "LAPIS_LAZULI",
    "TOPAZ": "GOLD_NUGGET",
    "OPAL": "AMETHYST_SHARD",
    "RUNE": "AMETHYST_SHARD",
    "KEY": "TRIPWIRE_HOOK",
    "SCROLL": "PAPER",
    "ARTIFACT": "NETHER_STAR",
    "CORE": "HEART_OF_THE_SEA",
    "COIN": "GOLD_NUGGET",
    "GOLD": "GOLD_INGOT",
    "GOLDEN_NUGGET": "GOLD_NUGGET",
    "IRON": "IRON_INGOT",
    "DIAMOND_SHARD": "DIAMOND",
    "EMERALD_GEM": "EMERALD",
}

# ─────────────────────────────────────────────────────────────────────────────
# Semantic tag → 实体类型候选（按匹配度排序）
# ─────────────────────────────────────────────────────────────────────────────
_SEMANTIC_ENTITY_MAP: Dict[str, List[str]] = {
    "flying": ["PHANTOM", "BLAZE", "VEX", "GHAST"],
    "ground": ["ZOMBIE", "SKELETON", "SPIDER", "PILLAGER"],
    "ranged": ["SKELETON", "STRAY", "PILLAGER", "WITCH"],
    "melee": ["ZOMBIE", "HUSK", "VINDICATOR", "PIGLIN_BRUTE"],
    "night": ["PHANTOM", "ZOMBIE", "SKELETON"],
    "hostile": ["ZOMBIE", "SKELETON", "SPIDER", "PILLAGER"],
    "neutral": ["VILLAGER", "IRON_GOLEM", "WANDERING_TRADER"],
    "magical": ["WITCH", "EVOKER", "VEX", "BLAZE"],
    "undead": ["ZOMBIE", "SKELETON", "WITHER_SKELETON", "DROWNED"],
    "water": ["DROWNED", "GUARDIAN", "ELDER_GUARDIAN"],
    "fire": ["BLAZE", "MAGMA_CUBE", "GHAST"],
    "cave": ["CAVE_SPIDER", "SILVERFISH", "ZOMBIE", "SKELETON"],
    "boss": ["ELDER_GUARDIAN", "WARDEN", "EVOKER", "RAVAGER"],
    "patrol": ["PILLAGER", "ZOMBIE", "SKELETON"],
    "ghost": ["PHANTOM", "VEX"],
    "fast": ["CAVE_SPIDER", "VEX", "BLAZE"],
    "slow": ["WARDEN", "ZOMBIE", "GIANT"],
    "stealth": ["ENDERMAN", "CREEPER"],
}

# Semantic tag → 材质候选
_SEMANTIC_MATERIAL_MAP: Dict[str, str] = {
    "gem": "EMERALD",
    "crystal": "AMETHYST_SHARD",
    "gold": "GOLD_INGOT",
    "coin": "GOLD_NUGGET",
    "iron": "IRON_INGOT",
    "fire": "BLAZE_ROD",
    "magic": "ENDER_PEARL",
    "dark": "NETHER_STAR",
    "water": "HEART_OF_THE_SEA",
    "earth": "EMERALD",
    "wind": "FEATHER",
    "key": "TRIPWIRE_HOOK",
    "scroll": "PAPER",
    "book": "BOOK",
    "artifact": "NETHER_STAR",
    "star": "NETHER_STAR",
    "soul": "HEART_OF_THE_SEA",
    "plant": "OAK_SAPLING",
    "food": "GOLDEN_APPLE",
}

# ─────────────────────────────────────────────────────────────────────────────
# 核心验证函数
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(name: str) -> str:
    return name.strip().upper().replace("-", "_").replace(" ", "_")


def _resolve_entity(raw: str, semantics: List[str]) -> tuple[str, str]:
    """
    把原始字符串解析为合法实体类型。
    返回 (result, source) 其中 source 是 "ok|alias|semantic|default"
    """
    name = _normalize(raw)

    # 1. 直接命中白名单
    if name in VALID_ALL_ENTITIES:
        return name, "ok"

    # 2. alias 修正
    aliased = _ENTITY_ALIASES.get(name)
    if aliased and aliased in VALID_ALL_ENTITIES:
        return aliased, f"alias:{raw}→{aliased}"

    # 3. 前缀/后缀模糊匹配（处理 ZOMBIE_GUARD 等带前缀变体）
    for valid in VALID_ALL_ENTITIES:
        if name.startswith(valid) or name.endswith(valid):
            return valid, f"fuzzy:{raw}→{valid}"

    # 4. semantic 推断
    for tag in (semantics or []):
        candidates = _SEMANTIC_ENTITY_MAP.get(tag.lower().replace("-", "_"), [])
        if candidates:
            best = candidates[0]
            return best, f"semantic:{tag}→{best}"

    # 5. ultimate fallback
    return "ZOMBIE", f"default:{raw}"


def _resolve_material(raw: str, semantics: List[str]) -> tuple[str, str]:
    """
    把原始字符串解析为合法物品材质。
    返回 (result, source)
    """
    name = _normalize(raw)

    # 1. 直接命中
    if name in VALID_ITEM_MATERIALS:
        return name, "ok"

    # 2. alias 修正
    aliased = _MATERIAL_ALIASES.get(name)
    if aliased and aliased in VALID_ITEM_MATERIALS:
        return aliased, f"alias:{raw}→{aliased}"

    # 3. 包含子串匹配（EMERALD_GEM → EMERALD）
    for valid in sorted(VALID_ITEM_MATERIALS):
        if valid in name:
            return valid, f"contains:{raw}→{valid}"

    # 4. semantic 推断
    for tag in (semantics or []):
        mat = _SEMANTIC_MATERIAL_MAP.get(tag.lower().replace("-", "_"))
        if mat:
            return mat, f"semantic:{tag}→{mat}"

    # 5. ultimate fallback
    return "EMERALD", f"default:{raw}"


def validate_trigger(trigger: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证并修正 trigger 中的 mc_material / mc_entity_type 字段（原地修改）。
    在 _mc_validated 字段中记录决策路径供调试。
    返回修改后的 trigger（即使没有变化也返回）。
    不抛出任何异常。
    """
    try:
        ttype = str(trigger.get("type") or "").strip().lower()
        semantics: List[str] = list(trigger.get("semantic") or [])

        if ttype == "item_collect":
            raw_mat = str(trigger.get("mc_material") or "").strip()
            if raw_mat:
                fixed, source = _resolve_material(raw_mat, semantics)
                trigger["mc_material"] = fixed
                trigger["_mc_validated"] = source
            else:
                # LLM 没给 mc_material，用 semantic 推断
                inferred, source = _resolve_material("", semantics)
                trigger["mc_material"] = inferred
                trigger["_mc_validated"] = source

        elif ttype in ("guard_detect", "npc_detect", "guard", "enemy_detect",
                       "proximity") and (
            trigger.get("mc_entity_type") or (
                str(trigger.get("target") or "").lower() in {
                    "guard", "守卫", "patrol", "soldier", "enemy", "archer",
                    "skeleton", "spider", "creeper", "zombie", "villain",
                    "phantom", "ghost", "wraith", "banshee", "demon",
                }
            )
        ):
            raw_ent = str(trigger.get("mc_entity_type") or "").strip()
            if raw_ent:
                fixed, source = _resolve_entity(raw_ent, semantics)
                trigger["mc_entity_type"] = fixed
                trigger["_mc_validated"] = source
            else:
                # LLM 没给实体类型，用 target + semantic 推断
                target = str(trigger.get("target") or "")
                inferred, source = _resolve_entity(target, semantics)
                trigger["mc_entity_type"] = inferred
                trigger["_mc_validated"] = source

    except Exception:
        # 验证器本身不应影响主流程
        pass

    return trigger


def validate_exp_spec_triggers(triggers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    验证 exp_spec.triggers 列表中每个触发器的 MC 字段。
    在副本上操作，不修改原始 exp_spec。
    """
    result = []
    for t in (triggers or []):
        if isinstance(t, dict):
            result.append(validate_trigger(dict(t)))  # 副本
        else:
            result.append(t)
    return result
