# DriftSystem System Functions (Command-First Reverse Map)

## 1. Scan Baseline

本文件基于以下运行时真值文件逆向整理：

- `plugin/src/main/resources/plugin.yml`（命令声明全集）
- `plugin/src/main/java/com/driftmc/DriftPlugin.java`（命令注册与监听器绑定）
- `plugin/src/main/java/com/driftmc/commands/**`（命令实现）
- `plugin/src/main/java/com/driftmc/listeners/**`（被动入口）
- `plugin/src/main/java/com/driftmc/intent2/**`（新意图链）
- `plugin/src/main/java/com/driftmc/scene/**`（规则事件桥 + 场景补丁执行）
- `backend/app/main.py`（实际挂载路由）
- `backend/app/api/world_api.py`、`backend/app/api/story_api.py`、`backend/app/routers/ai_router.py`、`backend/app/api/tutorial_api.py`、`backend/app/api/minimap_api.py`

## 2. Runtime Layering

- L1 输入层：玩家命令、聊天文本、实体交互、拾取事件、移动事件、退出意图。
- L2 语义层：`IntentRouter2 -> /ai/intent -> IntentDispatcher2`（主链），`IntentRouter`（兼容链，主要由 `/talk` 与 NPC 临近触发）。
- L3 剧情层：`/story/advance`、`/story/load`、`/story/inject`、`/world/apply`、`/world/story/rule-event`。
- L4 场景层：`story_api.build_scene_events`、`world_api.spawnfragment`、`evolve_scene_for_rule_event`。
- L5 执行层：`SceneAwareWorldPatchExecutor`、`PayloadExecutorV1`、`WorldPatchExecutor -> /world/apply/report`。
- L6 回显层：QuestLog HUD、Recommendation HUD、Dialogue/Choice Panel、TaskDebug 多视图命令。

## 3. Command-to-API Matrix (Step 1 + Step 2)

### 3.1 主命令与剧情命令

| 命令 | 插件实现 | 后端接口 | 后端处理模块 | 世界执行与反馈 |
|---|---|---|---|---|
| `/drift status` | `DriftCommand` | 无 | 本地 `StoryManager` 缓存 | 聊天输出状态 |
| `/drift sync` | `DriftCommand -> StoryManager.syncState` | `POST /story/state/{player}` | `story_api.api_story_state_post`（与 GET 同步返回） | 仅同步本地关卡缓存 |
| `/drift report` | `DriftCommand` | `GET /world/story/{player}/debug/tasks` | `world_api.story_debug_tasks` | 聊天输出 apply report |
| `/drift tutorial start` | `TutorialManager.startTutorial` | `POST /tutorial/start/{player}` | `tutorial_api.start_tutorial` | 教学 BossBar + 指令引导 |
| `/drift tutorial hint` | `TutorialManager.getHint` | `POST /tutorial/hint/{player}` | `tutorial_api.get_tutorial_hint` | 提示文本回显 |
| `/drift tutorial skip` | `TutorialManager.skipTutorial` | `POST /tutorial/skip/{player}` | `tutorial_api.skip_tutorial` | finalize + 进入主线 |
| `/talk <text>` | `TalkCommand` | `POST /story/advance/{player}`（通过 `IntentRouter`） + `POST /world/story/rule-event`（emitTalk） | `story_api.api_story_advance` + `world_api.story_rule_event` | 返回 node + world_patch，先任务事件再推进剧情 |
| `/saytoai <text>` | `SayToAICommand` | `POST /story/advance/{player}` | `story_api.api_story_advance` | 解析 node 与 world_patch 后执行 |
| `/advance [text]` | `AdvanceCommand` | `POST /story/advance/{player}` | `story_api.api_story_advance` | 推进故事并执行补丁 |
| `/storynext` | `CmdStoryNext` | `POST /story/advance/{player}` | `story_api.api_story_advance` | 固定 `say=继续` |
| `/level <id>` | `LevelCommand` | `POST /story/load/{player}/{level}` | `story_api.api_story_load` | 优先 `bootstrap_patch`，支持 payload_v1 入队 |
| `/levels` | `LevelsCommand` | 无 | 本地帮助文本 | 无 |
| `/heartmenu` | `HeartMenuCommand` | 无 | 本地帮助文本 | 无 |
| `/storycreative ...` | `StoryCreativeCommand` | 无直接后端 | `StoryCreativeManager` 本地状态管理 | 本地模式切换 |

### 3.2 实用命令与调试命令

| 命令 | 插件实现 | 后端接口 | 后端处理模块 | 世界执行与反馈 |
|---|---|---|---|---|
| `/minimap` | `MiniMapCommand` | `GET /minimap/png/{player}` | `minimap_api.get_png` | 下载 PNG 转地图物品 |
| `/recommend` | `RecommendCommand -> RecommendationHud` | `GET /world/story/{player}/recommendations?limit=3` | `world_api.story_recommendations` | ActionBar + 可点击 `/level` |
| `/questlog` | `QuestLogCommand -> QuestLogHud` | `GET /world/story/{player}/quest-log` | `world_api.story_quest_log` | 结构化任务日志展示 |
| `/taskdebug` | `TaskDebugCommand(TASKS)` | `GET /world/story/{player}/debug/tasks` | `world_api.story_debug_tasks` | 任务快照 + 场景调试总览 |
| `/worldstate` | `TaskDebugCommand(WORLDSTATE)` | `GET /world/story/{player}/debug/tasks` | 同上 | 阶段/资源摘要 |
| `/leveldebug` | `TaskDebugCommand(LEVELDEBUG)` | `GET /world/story/{player}/debug/tasks` | 同上 | 关卡状态机调试 |
| `/eventdebug` | `TaskDebugCommand(EVENTDEBUG)` | `GET /world/story/{player}/debug/tasks` | 同上 | recent_rule_events + scene scoring |
| `/debugscene` | `TaskDebugCommand(SCENE)` | `GET /world/story/{player}/debug/tasks` | 同上 | scene/event_plan 可视化文本 |
| `/debuginventory` | `TaskDebugCommand(INVENTORY)` | `GET /world/story/{player}/debug/tasks` | 同上 | 资源聚合与候选影响 |
| `/predictscene` | `TaskDebugCommand(PREDICTION)` | `GET /world/story/{player}/predict_scene` | `world_api.story_predict_scene` | 场景预测榜单 |
| `/explainscene` | `TaskDebugCommand(EXPLAIN)` | `GET /world/story/{player}/explain_scene` | `world_api.story_explain_scene` | 解释 selected_root 与原因 |
| `/debugpatch` | `TaskDebugCommand(PATCH)` | `GET /world/story/{player}/debug/tasks` | `world_api.story_debug_tasks` | 最近 apply report |
| `/spawnfragment` | `StoryRuntimeToolCommand(SPAWN_FRAGMENT)` | `POST /world/story/{player}/spawnfragment` | `world_api.story_spawn_fragment` | 生成并执行 scene world_patch |
| `/storyreset` | `StoryRuntimeToolCommand(STORY_RESET)` | `POST /world/story/{player}/reset` | `world_api.story_reset` | 清空运行态并返回 reset 摘要 |
| `/cinematic test` | `CinematicCommand` | 无 | 本地 `CinematicController` | 本地过场动作序列 |

### 3.3 本地命令（无后端调用）

- `/npc summon`：`NpcMasterCommand -> NpcSummonCommand`，本地 `NPCManager.spawnRabbit`。
- `/tp2`：本地传送。
- `/time2`：本地时间调整。
- `/sayc`：本地全服广播。

## 4. Passive Entry Points (非命令入口)

### 4.1 聊天主链（生产主入口）

`PlayerChatListener.onAsyncChat`：

1. 拦截聊天并回显。
2. `ruleEvents.emitTalk` 上报 `POST /world/story/rule-event`。
3. `IntentRouter2.askIntent` 请求 `POST /ai/intent`。
4. `IntentDispatcher2.dispatch` 根据意图分发：
   - `CREATE_STORY` -> `POST /story/inject` -> `POST /story/load/{player}/{level}`
   - `GOTO_LEVEL/GOTO_NEXT_LEVEL` -> `POST /story/load/...`
   - `SHOW_MINIMAP` -> `GET /minimap/give/{player}`
   - `SAY_ONLY/STORY_CONTINUE/UNKNOWN` -> `POST /world/apply`
   - `SET_DAY/SET_NIGHT/SET_WEATHER/TELEPORT/SPAWN_ENTITY/BUILD_STRUCTURE` -> 直接本地 world patch 执行

### 4.2 NPC 与世界交互链

- `NearbyNPCListener`：
  - 临近/交互 NPC 会触发 `ruleEvents.emit*` 到 `POST /world/story/rule-event`。
  - 部分路径会调用旧 `IntentRouter.handlePlayerSpeak` -> `POST /story/advance/{player}`。
- `RuleEventListener`：
  - 方块交互、实体交互、拾取物品 -> `ruleEvents.emit*` -> `POST /world/story/rule-event`。

### 4.3 退出剧情链

`ExitIntentDetector`：

- profile 拉取：`GET /world/state/{player}`
- 匹配退出语义后：`POST /world/story/end`
- 执行返回 `world_patch`，并触发 Recommendation + QuestLog 退出刷新。

## 5. Backend Endpoint Capability Map (实际挂载)

| 接口 | 核心能力 |
|---|---|
| `POST /ai/intent` | 多意图解析，返回 `intents[]`，含 `raw_text/minimap/world_patch` 补全 |
| `POST /world/apply` | 世界动作 + 文本意图 + 剧情推进融合执行 |
| `POST /story/load/{player}/{level}` | 加载关卡并返回 `bootstrap_patch` |
| `POST /story/advance/{player}` | StoryEngine 推进，返回 `node/world_patch` |
| `POST /story/inject` | 动态创建关卡，支持 payload_v1/v2 与 scene 注入 |
| `POST /world/story/rule-event` | QuestRuntime 规则事件处理 + 场景增量演化 |
| `GET /world/story/{player}/debug/tasks` | 任务、场景、候选、补丁、fallback、事件总调试快照 |
| `GET /world/story/{player}/predict_scene` | 场景候选预测 |
| `GET /world/story/{player}/explain_scene` | 场景选择可解释性输出 |
| `POST /world/story/{player}/spawnfragment` | 运行态生成并投放场景片段（含 fallback 策略） |
| `POST /world/story/{player}/reset` | 清空玩家剧情运行态/缓存 |
| `GET /world/story/{player}/quest-log` | 当前活跃任务快照 |
| `GET /world/story/{player}/recommendations` | StoryGraph 推荐章节 |
| `POST /world/apply/report` | 插件执行回传（build_id/status/failure） |
| `GET /minimap/png/{player}` | 渲染 PNG 小地图 |
| `GET /minimap/give/{player}` | 以 base64 map_image 形式返回给插件发图 |
| `POST /tutorial/start/{player}` | 启动教学流程 |
| `POST /tutorial/check` | 教学进度检查 |
| `POST /tutorial/hint/{player}` | 教学提示 |
| `POST /tutorial/skip/{player}` | 跳过教学 |

## 6. Function Modules (Reverse Inference)

- 模块 A：自然语言意图编排
  - 输入：聊天文本。
  - 组件：`/ai/intent` + `IntentDispatcher2`。
  - 输出：剧情创建、跳关、地图、推进、世界指令。
- 模块 B：剧情推进与节点呈现
  - 输入：`/story/advance`、`/world/apply`。
  - 输出：`story_node`、`world_patch`、分支对话节点。
- 模块 C：场景生成与增量演化
  - 输入：`/story/inject`、`/spawnfragment`、`/world/story/rule-event`。
  - 输出：`scene_plan/event_plan/scene_diff/world_patch`。
- 模块 D：规则事件任务运行时
  - 输入：talk/interact/collect/npc_trigger。
  - 输出：任务节点、里程碑、commands、patch。
- 模块 E：世界补丁执行与回传
  - 输入：`world_patch`（含 `mc`）。
  - 输出：实体/方块/时间/天气/特效执行 + `/world/apply/report`。
- 模块 F：HUD 可视化
  - QuestLog、Recommendation、Dialogue/Choice、TaskDebug 多模式。
- 模块 G：教学闭环
  - start/check/hint/skip + tutorial finalize + 自动切主线。

## 7. Known Gaps / Risks

- `plugin/plugin.yml` 为旧版子集，运行时应以 `plugin/src/main/resources/plugin.yml` 为准。
- `/drift sync` 与后端 `POST /story/state/{player}` 已对齐；仍需在回归测试中覆盖 GET/POST 双动词兼容性。
- 插件同时保留新旧双意图链：聊天主链走 `IntentRouter2`，NPC 临近仍可触发旧 `IntentRouter`，可能导致路径行为差异。
- `DRIFT_TASK_DEBUG_TOKEN` 启用后，`taskdebug/predictscene/explainscene` 需带 token 才可访问。

## 8. Step-6 前置条件（Bot 实测）

- MC 服务端可达（host/port）。
- 若 `online-mode=true`，需真实微软账号登录流；离线 bot 默认无法加入。
- 若仅做本地集成链路回归，可在受控窗口临时离线模式测试，并在测试后恢复安全配置。
