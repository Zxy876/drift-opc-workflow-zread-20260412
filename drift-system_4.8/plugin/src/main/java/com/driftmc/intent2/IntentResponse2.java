package com.driftmc.intent2;

import com.driftmc.story.LevelIds;
import com.google.gson.JsonObject;

public class IntentResponse2 {

    public final IntentType2 type;
    public final String levelId;
    public final JsonObject minimap;
    public final String rawText;
    public final String sceneTheme;
    public final String sceneHint;
    public final JsonObject worldPatch; // 世界patch
    /** 难度评分 1-5，由 intent_engine 赋值 */
    public final int difficulty;
    /**
     * Scene type 分类：CONTENT | RULE | SIMULATION
     * CONTENT  → 直接走 Drift（默认）
     * RULE     → AsyncAIFlow 生成系统级规则
     * SIMULATION → AsyncAIFlow + 持久状态
     */
    public final String sceneType;

    public IntentResponse2(IntentType2 type, String levelId, JsonObject minimap, String rawText,
                           String sceneTheme, String sceneHint, JsonObject worldPatch) {
        this(type, levelId, minimap, rawText, sceneTheme, sceneHint, worldPatch, 1, "CONTENT");
    }

    public IntentResponse2(IntentType2 type, String levelId, JsonObject minimap, String rawText,
                           String sceneTheme, String sceneHint, JsonObject worldPatch, int difficulty) {
        this(type, levelId, minimap, rawText, sceneTheme, sceneHint, worldPatch, difficulty, "CONTENT");
    }

    public IntentResponse2(IntentType2 type, String levelId, JsonObject minimap, String rawText,
                           String sceneTheme, String sceneHint, JsonObject worldPatch, int difficulty,
                           String sceneType) {
        this.type = type;
        this.levelId = levelId;
        this.minimap = minimap;
        this.rawText = rawText;
        this.sceneTheme = sceneTheme;
        this.sceneHint = sceneHint;
        this.worldPatch = worldPatch;
        this.difficulty = Math.max(1, Math.min(5, difficulty));
        this.sceneType = (sceneType != null && !sceneType.isBlank()) ? sceneType.toUpperCase() : "CONTENT";
    }

    public static IntentResponse2 fromJson(JsonObject root) {

        JsonObject intent = root.has("intent") && root.get("intent").isJsonObject()
                ? root.getAsJsonObject("intent")
                : root;

        String typeStr = intent.has("type") ? intent.get("type").getAsString() : null;
        IntentType2 type = IntentType2.fromString(typeStr);

        String levelId = intent.has("level_id") ? intent.get("level_id").getAsString() : null;
        levelId = LevelIds.canonicalizeLevelId(levelId);

        JsonObject minimap = intent.has("minimap") && intent.get("minimap").isJsonObject()
                ? intent.getAsJsonObject("minimap")
                : null;

        String raw = intent.has("raw_text") ? intent.get("raw_text").getAsString() : null;

        String sceneTheme = null;
        if (intent.has("scene_theme") && !intent.get("scene_theme").isJsonNull()) {
            sceneTheme = intent.get("scene_theme").getAsString();
        } else if (intent.has("theme") && !intent.get("theme").isJsonNull()) {
            sceneTheme = intent.get("theme").getAsString();
        }

        String sceneHint = null;
        if (intent.has("scene_hint") && !intent.get("scene_hint").isJsonNull()) {
            sceneHint = intent.get("scene_hint").getAsString();
        } else if (intent.has("hint") && !intent.get("hint").isJsonNull()) {
            sceneHint = intent.get("hint").getAsString();
        }

        JsonObject worldPatch = intent.has("world_patch") && intent.get("world_patch").isJsonObject()
                ? intent.getAsJsonObject("world_patch")
                : null;

        int difficulty = 1;
        if (intent.has("difficulty") && !intent.get("difficulty").isJsonNull()) {
            try {
                difficulty = intent.get("difficulty").getAsInt();
                difficulty = Math.max(1, Math.min(5, difficulty));
            } catch (Exception ignored) {
                difficulty = 1;
            }
        }

        // scene_type: CONTENT | RULE | SIMULATION（来自 SceneTypeClassifier）
        String sceneType = "CONTENT";
        if (intent.has("scene_type") && !intent.get("scene_type").isJsonNull()) {
            String raw2 = intent.get("scene_type").getAsString().toUpperCase().trim();
            if ("RULE".equals(raw2) || "SIMULATION".equals(raw2) || "CONTENT".equals(raw2)) {
                sceneType = raw2;
            }
        }

        return new IntentResponse2(type, levelId, minimap, raw, sceneTheme, sceneHint, worldPatch, difficulty, sceneType);
    }
}