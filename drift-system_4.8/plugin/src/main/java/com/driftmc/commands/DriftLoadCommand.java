package com.driftmc.commands;

import java.io.IOException;
import java.lang.reflect.Type;
import java.util.Map;

import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.plugin.java.JavaPlugin;

import com.driftmc.backend.BackendClient;
import com.driftmc.world.WorldPatchExecutor;
import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.reflect.TypeToken;

import okhttp3.Call;
import okhttp3.Callback;
import okhttp3.Response;

/**
 * /driftload <player_name> <level_id>
 *
 * 可由控制台 / RCON 执行，后端通过 RCON 调用此命令来把已 publish 的关卡
 * 推送给在线玩家。等同于：后端调 /story/load，然后把 bootstrap_patch 应用给玩家。
 *
 * 用法示例（RCON）：
 *   driftload demo_player gem_test_v10
 */
public class DriftLoadCommand implements CommandExecutor {

    private static final Gson GSON = new Gson();
    private static final Type MAP_TYPE = new TypeToken<Map<String, Object>>() {}.getType();

    private final JavaPlugin plugin;
    private final BackendClient backend;
    private final WorldPatchExecutor world;

    public DriftLoadCommand(JavaPlugin plugin, BackendClient backend, WorldPatchExecutor world) {
        this.plugin = plugin;
        this.backend = backend;
        this.world = world;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command cmd, String label, String[] args) {
        if (args.length < 2) {
            sender.sendMessage(ChatColor.GOLD + "用法: /driftload <player_name> <level_id>");
            return true;
        }

        String playerName = args[0];
        String levelId = args[1];

        Player target = Bukkit.getPlayerExact(playerName);
        if (target == null || !target.isOnline()) {
            sender.sendMessage(ChatColor.RED
                    + "[DriftLoad] 玩家 " + playerName + " 不在线，无法加载关卡。");
            return true;
        }

        final Player fp = target;
        sender.sendMessage(ChatColor.YELLOW + "[DriftLoad] 正在为 " + playerName + " 加载关卡 " + levelId + "...");

        backend.postJsonAsync("/story/load/" + playerName + "/" + levelId, "{}", new Callback() {

            @Override
            public void onFailure(Call call, IOException e) {
                plugin.getLogger().warning("[DriftLoadCommand] 后端请求失败: " + e.getMessage());
                Bukkit.getScheduler().runTask(plugin, () ->
                        fp.sendMessage(ChatColor.RED + "[Drift] 关卡加载失败：" + e.getMessage()));
            }

            @Override
            public void onResponse(Call call, Response resp) throws IOException {
                final String body = resp.body() != null ? resp.body().string() : "{}";
                resp.close();

                Bukkit.getScheduler().runTask(plugin, () -> {
                    try {
                        JsonObject root = JsonParser.parseString(body).getAsJsonObject();

                        JsonObject patchObj = null;
                        if (root.has("bootstrap_patch") && root.get("bootstrap_patch").isJsonObject()) {
                            patchObj = root.getAsJsonObject("bootstrap_patch");
                        } else if (root.has("world_patch") && root.get("world_patch").isJsonObject()) {
                            patchObj = root.getAsJsonObject("world_patch");
                        }

                        if (patchObj != null && patchObj.size() > 0) {
                            Map<String, Object> patch = GSON.fromJson(patchObj, MAP_TYPE);
                            @SuppressWarnings("unchecked")
                            Object mcObj = patch.get("mc");
                            @SuppressWarnings("unchecked")
                            Map<String, Object> mcPatch = (mcObj instanceof Map)
                                    ? (Map<String, Object>) mcObj
                                    : patch;
                            world.execute(fp, mcPatch);
                            fp.sendMessage(ChatColor.GREEN + "✨ 关卡 " + levelId + " 已加载！");
                            plugin.getLogger().info("[DriftLoadCommand] bootstrap_patch 应用完成: player="
                                    + playerName + " level=" + levelId);
                        } else {
                            fp.sendMessage(ChatColor.RED + "[Drift] 关卡 " + levelId + " 未找到或无场景数据。");
                            plugin.getLogger().warning("[DriftLoadCommand] bootstrap_patch 为空: " + body.substring(0, Math.min(200, body.length())));
                        }
                    } catch (Exception e) {
                        plugin.getLogger().warning("[DriftLoadCommand] 解析响应失败: " + e.getMessage());
                        fp.sendMessage(ChatColor.RED + "[Drift] 关卡加载出错：" + e.getMessage());
                    }
                });
            }
        });

        return true;
    }
}
