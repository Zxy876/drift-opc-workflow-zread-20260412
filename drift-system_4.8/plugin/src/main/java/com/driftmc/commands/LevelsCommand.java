package com.driftmc.commands;

import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;

import com.driftmc.backend.BackendClient;
import com.driftmc.intent.IntentRouter;
import com.driftmc.session.PlayerSessionManager;
import com.driftmc.world.WorldPatchExecutor;

/**
 * /levels
 * 目前做成一个「心悦宇宙帮助面板」，不强依赖后端。
 */
public class LevelsCommand implements CommandExecutor {

    @SuppressWarnings("unused")
    private final BackendClient backend;
    @SuppressWarnings("unused")
    private final IntentRouter router;
    @SuppressWarnings("unused")
    private final WorldPatchExecutor world;
    @SuppressWarnings("unused")
    private final PlayerSessionManager sessions;

    public LevelsCommand(
            BackendClient backend,
            IntentRouter router,
            WorldPatchExecutor world,
            PlayerSessionManager sessions
    ) {
        this.backend = backend;
        this.router = router;
        this.world = world;
        this.sessions = sessions;
    }

    @Override
    public boolean onCommand(CommandSender sender, Command cmd, String label, String[] args) {

        if (!(sender instanceof Player player)) {
            sender.sendMessage(ChatColor.RED + "只有玩家可以查看心悦宇宙关卡~");
            return true;
        }

        player.sendMessage(ChatColor.LIGHT_PURPLE + "====== 心悦宇宙 · Levels ======");
        player.sendMessage(ChatColor.AQUA + "/level flagship_tutorial " + ChatColor.GRAY + "→ 心悦文集 · 第 1 章");
        player.sendMessage(ChatColor.AQUA + "/storynext " + ChatColor.GRAY + "→ 让故事向前推进一步");
        player.sendMessage(ChatColor.AQUA + "直接在聊天里说话 " + ChatColor.GRAY + "→ 让世界根据你的自然语言变化");
        player.sendMessage(ChatColor.LIGHT_PURPLE + "================================");

        return true;
    }
}