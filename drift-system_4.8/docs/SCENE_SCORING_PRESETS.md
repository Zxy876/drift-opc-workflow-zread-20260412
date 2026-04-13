# DriftSystem 场景评分预设（high_control / balanced / emergent）

本页只涉及**配置层**，不改算法：

- `high_control`：玩家刷资源的控制力更强。
- `balanced`：平衡默认。
- `emergent`：更强调系统涌现与多样性。

## 文件位置

- 当前生效配置：`backend/app/content/scenes/semantic_scoring.json`
- 预设目录：`backend/app/content/scenes/presets/`
  - `semantic_scoring.high_control.json`
  - `semantic_scoring.balanced.json`
  - `semantic_scoring.emergent.json`

## 一键切换

```bash
./scripts/switch_scene_scoring_preset.sh high_control --restart
./scripts/switch_scene_scoring_preset.sh balanced --restart
./scripts/switch_scene_scoring_preset.sh emergent --restart
```

查看状态：

```bash
./scripts/switch_scene_scoring_preset.sh status
```

列出可用预设：

```bash
./scripts/switch_scene_scoring_preset.sh list
```

## 15分钟游戏内验证脚本

执行：

```bash
./scripts/scene_influence_15min_validation.sh high_control
```

可选自动切换并重启：

```bash
./scripts/scene_influence_15min_validation.sh high_control --switch --restart --player vivn
```

该脚本是**交互式内测脚本**，会逐步提示你在游戏里执行每条命令（可自动复制到剪贴板），并在每轮要求录入 `selected_root`，最后自动输出通过/失败与报告文件。

- 报告目录：`logs/playtest/`
- 判定规则：
  - `high_control`：每个导向阶段至少命中 `2/2`
  - `balanced` / `emergent`：每个导向阶段至少命中 `1/2`
