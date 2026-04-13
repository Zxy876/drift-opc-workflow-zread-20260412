package com.driftmc.commands;

import java.lang.reflect.Type;
import java.util.Map;
import java.util.UUID;

import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

import com.driftmc.backend.BackendClient;
import com.driftmc.world.PayloadExecutorV1;
import com.driftmc.world.WorldPatchExecutor;
import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.reflect.TypeToken;

/**
 * /create <关卡描述文字>
 *
 * 玩家在 MC 聊天框输入一句话描述想要的关卡，
 * 插件自动调用后端 /story/inject 生成关卡，然后调用 /story/load 加载给玩家。
 *
 * 例：/create 限时60秒逃脱迷宫，被守卫发现则失败，到达出口则胜利
 */
public class CreateLevelCommand implements CommandExecutor {

    private static final Gson GSON = new Gson();

    private final JavaPlugin plugin;
    private final BackendClient backend;
    private final WorldPatchExecutor world;
    private final PayloadExecutorV1 payloadExecutor;

    public CreateLevelCommand(
            JavaPlugin plugin,
            BackendClient backend,
            WorldPatchExecutor world,
            PayloadExecutorV1 payloadExecutor) {
        this.plugin = plugin;
        this.backend = backend;
        this.world = world;
        this.payloadExecutor = payloadExecutor;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command cmd, String label, String[] args) {
        if (!(sender instanceof Player player)) {
            sender.sendMessage(ChatColor.RED + "只有玩家可以创建关卡");
            return true;
        }

        if (args.length == 0) {
            player.sendMessage(ChatColor.GOLD + "用法: /create <关卡描述>");
            player.sendMessage(ChatColor.GRAY + "例: /create 限时60秒收集3块宝石，被守卫发现则失败");
            return true;
        }

        String text = String.join(" ", args);
        String playerId = player.getName();
        // 用玩家名+时间戳生成唯一level_id（限48字符）
        String rawLevelId = "custom_" + playerId.toLowerCase() + "_" + System.currentTimeMillis();
        final String levelId = rawLevelId.length() > 48 ? rawLevelId.substring(0, 48) : rawLevelId;

        player.sendMessage(ChatColor.YELLOW + "🎨 正在生成关卡，请稍候...");
        player.sendMessage(ChatColor.GRAY + "描述: " + text);

        UUID playerUuid = player.getUniqueId();
        String injectBody = buildInjectBody(levelId, text, playerId);

        Bukkit.getScheduler().runTaskAsynchronously(plugin, () -> {
            try {
                // Step 1: 创建关卡
                String injectResp = backend.postJson("/story/inject", injectBody);
                JsonObject injectObj = JsonParser.parseString(injectResp).getAsJsonObject();

                String status = injectObj.has("status")
                        ? injectObj.get("status").getAsString() : "error";

                if (!"ok".equals(status)) {
                    String msg = injectObj.has("msg") ? injectObj.get("msg").getAsString() : "未知错误";
                    Bukkit.getScheduler().runTask(plugin, () -> {
                        Player p = Bukkit.getPlayer(playerUuid);
                        if (p != null) p.sendMessage(ChatColor.RED + "❌ 关卡创建失败: " + msg);
                    });
                    return;
                }

                // 获取实际生成的level_id（后端可能使用不同id）
                final String actualLevelId = injectObj.has("level_id")
                        ? injectObj.get("level_id").getAsString() : levelId;

                // 顺便展示ExperienceSpec摘要
                if (injectObj.has("experience_spec_summary")) {
                    JsonObject summary = injectObj.getAsJsonObject("experience_spec_summary");
                    Bukkit.getScheduler().runTask(plugin, () -> {
                        Player p = Bukkit.getPlayer(playerUuid);
                        if (p == null) return;
                        p.sendMessage(ChatColor.AQUA + "✨ 关卡已生成: " + ChatColor.GOLD + actualLevelId);
                        if (summary.has("win_conditions")) {
                            p.sendMessage(ChatColor.GREEN + "  胜利: " + summary.get("win_conditions").getAsString());
                        }
                        if (summary.has("lose_conditions")) {
                            p.sendMessage(ChatColor.RED + "  失败: " + summary.get("lose_conditions").getAsString());
                        }
                        if (summary.has("trigger_count")) {
                            p.sendMessage(ChatColor.YELLOW + "  触发器: " + summary.get("trigger_count").getAsString() + " 个");
                        }
                    });
                }

                // Step 2: 加载关卡
                String loadResp = backend.postJson("/story/load/" + playerId + "/" + actualLevelId, "{}");
                Bukkit.getScheduler().runTask(plugin, () -> {
                    Player p = Bukkit.getPlayer(playerUuid);
                    if (p == null || !p.isOnline()) return;
                    applyLoadResponse(p, loadResp);
                    p.sendMessage(ChatColor.GREEN + "✔ 关卡已加载！开始你的冒险吧。");
                });

            } catch (Exception e) {
                Bukkit.getScheduler().runTask(plugin, () -> {
                    Player p = Bukkit.getPlayer(playerUuid);
                    if (p != null) p.sendMessage(ChatColor.RED + "❌ 关卡创建出错: " + e.getMessage());
                });
            }
        });

        return true;
    }

    private String buildInjectBody(String levelId, String text, String playerId) {
        JsonObject body = new JsonObject();
        body.addProperty("level_id", levelId);
        body.addProperty("title", text.length() > 30 ? text.substring(0, 30) : text);
        body.addProperty("text", text);
        body.addProperty("player_id", playerId);
        return body.toString();
    }

    @SuppressWarnings("unchecked")
    private void applyLoadResponse(Player player, String resp) {
        try {
            JsonElement rootEl = JsonParser.parseString(resp);
            if (!rootEl.isJsonObject()) return;
            JsonObject root = rootEl.getAsJsonObject();

            JsonObject patchObj = null;
            if (root.has("bootstrap_patch") && root.get("bootstrap_patch").isJsonObject()) {
                patchObj = root.getAsJsonObject("bootstrap_patch");
            } else if (root.has("world_patch") && root.get("world_patch").isJsonObject()) {
                patchObj = root.getAsJsonObject("world_patch");
            }
            if (patchObj == null) return;

            // PayloadV1 路径
            if (patchObj.has("version")
                    && "plugin_payload_v1".equals(patchObj.get("version").getAsString())) {
                if (payloadExecutor != null) payloadExecutor.enqueue(player, patchObj);
                return;
            }

            Type type = new TypeToken<Map<String, Object>>() {}.getType();
            Map<String, Object> patch = GSON.fromJson(patchObj, type);
            if (patch == null || patch.isEmpty()) return;

            @SuppressWarnings("rawtypes")
            Object mcObj = patch.get("mc");
            Map<String, Object> mcPatch = (mcObj instanceof Map) ? (Map<String, Object>) mcObj : patch;
            world.execute(player, mcPatch);

        } catch (Exception ignored) {
        }
    }
}
