# DriftSystem Module Test Cases

## 1. Command -> API Contract Tests

| ID | 目标 | 操作 | 预期 |
|---|---|---|---|
| CMD-001 | `/saytoai` 推进故事 | 执行 `/saytoai 继续前进` | 插件请求 `POST /story/advance/{player}`，收到 `node/world_patch` 后执行补丁 |
| CMD-002 | `/advance` 默认文案 | 执行 `/advance` | 请求体 `action.say=继续` |
| CMD-003 | `/storynext` 固定推进 | 执行 `/storynext` | 等价于 `/advance 继续` |
| CMD-004 | `/level` 加载关卡 | 执行 `/level flagship_tutorial` | 请求 `POST /story/load/{player}/flagship_tutorial` 并优先执行 `bootstrap_patch` |
| CMD-005 | `/spawnfragment` 运行态场景投放 | 执行 `/spawnfragment` | 请求 `POST /world/story/{player}/spawnfragment`，返回 `world_patch` 时被执行 |
| CMD-006 | `/storyreset` 状态重置 | 执行 `/storyreset` | 请求 `POST /world/story/{player}/reset`，返回 reset 清理计数 |
| CMD-007 | `/taskdebug` 可观测性 | 执行 `/taskdebug` | 请求 `GET /world/story/{player}/debug/tasks`，输出任务+场景快照 |
| CMD-008 | `/predictscene` 预测能力 | 执行 `/predictscene` | 请求 `GET /world/story/{player}/predict_scene`，返回候选评分 |
| CMD-009 | `/explainscene` 解释能力 | 执行 `/explainscene` | 请求 `GET /world/story/{player}/explain_scene`，返回 semantic/reason |
| CMD-010 | `/recommend` 推荐链路 | 执行 `/recommend` | 请求 `GET /world/story/{player}/recommendations`，显示可点击 `/level` |
| CMD-011 | `/questlog` 任务日志 | 执行 `/questlog` | 请求 `GET /world/story/{player}/quest-log`，展示 active_tasks |
| CMD-012 | `/minimap` 地图渲染 | 执行 `/minimap` | 请求 `GET /minimap/png/{player}`，背包收到地图 |

## 2. Chat Intent Pipeline Tests

| ID | 目标 | 输入语句 | 预期意图与行为 |
|---|---|---|---|
| INT-001 | 单意图 SAY_ONLY | `我想继续` | `/ai/intent` 返回 `SAY_ONLY` 或 `STORY_CONTINUE`，分发至 `/world/apply` |
| INT-002 | 多意图拆分 | `跳到第三关并切到白天` | 返回至少两个 intents：`GOTO_LEVEL` + `SET_DAY` |
| INT-003 | CREATE_STORY 主题解析 | `创建剧情 雨夜灯塔` | intent 含 `scene_theme=雨夜灯塔` |
| INT-004 | CREATE_STORY 场景提示解析 | `创建剧情 雨夜灯塔 在海边` | intent 含 `scene_hint=海边` |
| INT-005 | minimap 语义触发 | `我在哪，给我看地图` | 触发 `SHOW_MINIMAP` -> `/minimap/give/{player}` |
| INT-006 | 退出语义触发 | `我要退出剧情` | `ExitIntentDetector` 命中，触发 `POST /world/story/end` |

## 3. Scene Reliability & Policy Tests

| ID | 目标 | 前置 | 操作 | 预期 |
|---|---|---|---|---|
| SCN-001 | verified candidate 门控 | 玩家无有效种子 | 连续聊天触发 | 不应把 `talk_text_v3` hint-only 候选当作可执行 root |
| SCN-002 | auto bootstrap 阈值 | 默认阈值启用 | 低语义置信输入 | 不触发自动 bootstrap |
| SCN-003 | candidate cap | 默认策略 | 高频行为后调试预测 | 候选数量不超过 `max_scene_candidates=5` |
| SCN-004 | fallback hint_only | 无可执行片段 | `/spawnfragment` | 返回 fallback reason 为 `hint_only` 或无补丁提示 |
| SCN-005 | cooldown 防抖 | 短时间重复同类行为 | 重复触发场景 | 观测到 cooldown 信息，避免根节点抖动 |
| SCN-006 | inventory override 生效 | 指定 `inventory_state_override` | 调用 `build_scene_events` 路径 | 生成依赖 override 的 scene 输出 |

## 4. Rule Event & Quest Runtime Tests

| ID | 目标 | 操作 | 预期 |
|---|---|---|---|
| RUL-001 | talk 事件桥接 | 聊天一句普通文本 | `RuleEventBridge` 发送 `event_type=talk` 到 `/world/story/rule-event` |
| RUL-002 | collect 事件桥接 | 玩家拾取物品 | 发送 `event_type=collect` 且 payload 含 `resource/item_type/amount` |
| RUL-003 | NPC 互动桥接 | 右键 NPC | 发送 `npc_talk/npc_trigger/interact_entity` 组合事件 |
| RUL-004 | Quest 节点回显 | 触发任务里程碑 | 插件显示 `task_milestone/task_complete` 并更新 QuestLog |
| RUL-005 | scene_evolution 合并 | 触发规则事件后 | 查看返回体 | `scene_diff` 与 `world_patch` 被合并回插件执行 |
| RUL-006 | 命令回放 | 后端返回 commands | 观察服务器控制台执行 | 指令应按 player 占位符替换后执行 |

## 5. Tutorial Lifecycle Tests

| ID | 目标 | 操作 | 预期 |
|---|---|---|---|
| TUT-001 | 新玩家自动进教学 | 新号首次加入 | `PlayerJoinListener` 延迟触发 `startTutorial` |
| TUT-002 | 教学进度推进 | 在教学中聊天 | `POST /tutorial/check` 返回下一步并更新 BossBar |
| TUT-003 | 教学提示 | `/drift tutorial hint` | `POST /tutorial/hint/{player}` 返回 hint |
| TUT-004 | 教学跳过 | `/drift tutorial skip confirm` | finalize 并进入主线关卡加载 |
| TUT-005 | 教学完成迁移 | 与教程向导关键互动 | 标记完成后自动 `load flagship_03` |

## 6. Patch Execution & Report Tests

| ID | 目标 | 操作 | 预期 |
|---|---|---|---|
| PAT-001 | 常规 patch 执行 | 任一返回含 `world_patch` 的操作 | `WorldPatchExecutor.execute` 正常应用 time/weather/build/spawn |
| PAT-002 | payload_v1 入队执行 | 返回 `version=plugin_payload_v1` | `PayloadExecutorV1.enqueue` 接收并分帧执行 |
| PAT-003 | apply report 回传 | 完成一次 patch/payload | 插件调用 `POST /world/apply/report`，后端 debug 可见 |
| PAT-004 | report 调试展示 | `/debugpatch` | 显示 `last_apply_report` 与 fallback 字段 |

## 7. Negative & Recovery Tests

| ID | 目标 | 注入故障 | 预期 |
|---|---|---|---|
| NEG-001 | 后端不可达 | 关闭 backend | 命令失败有明确提示，不崩插件主线程 |
| NEG-002 | debug token 不匹配 | 开启 `DRIFT_TASK_DEBUG_TOKEN` 且不给 token | `taskdebug/predictscene/explainscene` 返回 403 |
| NEG-003 | 空 patch 防护 | 返回空 `world_patch` | 插件不抛异常、给出软提示 |
| NEG-004 | 在线模式 bot 拒绝 | `online-mode=true` 下离线 bot 登录 | 预期被 kicked，系统安全配置不被破坏 |
| NEG-005 | reset 恢复能力 | 运行态混乱后 `/storyreset` | 调试快照回到可控初始状态 |

## 8. 建议执行顺序

1. 先跑 `CMD-*` 与 `INT-*` 验证主链路。
2. 再跑 `SCN-*` 与 `RUL-*` 验证稳定性与闭环。
3. 最后跑 `NEG-*` 验证容错与恢复。
