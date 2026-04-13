# DriftSystem MC插件 - 心悦宇宙

## 概述

DriftSystem是一个**完全自然语言驱动的AI冒险游戏系统**，让玩家通过自然对话来推进剧情、修改世界、创建内容。

## 核心特性

### 1. 完全自然语言驱动 ✨
- **无需记忆命令** - 玩家只需在聊天中说话
- **智能意图识别** - AI自动理解玩家想做什么
- **多意图处理** - 一句话可以触发多个动作

示例对话:
```
玩家: 把天气改成白天然后跳到第三关
系统: ✓ 时间已设置为白天
系统: ✓ 正在传送到 level_03...
```

### 2. 剧情与世界动态共生 🌍
- **30个心悦文集关卡** - 完整的叙事体验
- **世界自动渲染** - 剧情推进时世界跟随变化
- **实时环境交互** - 方块、光源、天气、实体自动生成

### 3. 可扩展的叙事操作系统 📝
- **JSON关卡定义** - 简单的格式，易于创作
- **即时DSL注入** - 玩家可以现场创建剧情
- **热更新支持** - 无需重启服务器

示例:
```
玩家: 写一个关于月光下的冒险故事
系统: ✨ 正在创建新剧情...
系统: ✅ 剧情创建成功！关卡ID: custom_1701234567
```

### 4. 插件=前端，后端=大脑 🧠
- **清晰架构** - MC插件专注于显示和交互
- **FastAPI后端** - 处理AI、剧情逻辑、状态管理
- **模块化设计** - 可以独立升级各个组件

### 5. 玩家与剧情互相影响 🎭
- **行为反馈** - 玩家选择改变故事树
- **分支剧情** - 多条路径，多种结局
- **状态持久化** - 进度自动保存

## 架构说明

```
┌─────────────────────────────────────────────────┐
│            Minecraft 服务器 (Paper)              │
│                                                 │
│  ┌──────────────────────────────────────────┐  │
│  │         DriftSystem 插件                  │  │
│  │                                          │  │
│  │  PlayerChatListener → IntentRouter2     │  │
│  │         ↓                                │  │
│  │  IntentDispatcher2 → WorldPatchExecutor │  │
│  │         ↓                                │  │
│  │  StoryManager                            │  │
│  └──────────────────────────────────────────┘  │
│                     ↕ HTTP                     │
└─────────────────────────────────────────────────┘
                      ↕
┌─────────────────────────────────────────────────┐
│         FastAPI 后端 (Python)                    │
│                                                 │
│  /ai/intent      - 意图识别                      │
│  /story/load     - 加载关卡                      │
│  /story/inject   - 创建剧情                      │
│  /world/apply    - 世界交互                      │
│  /minimap/*      - 小地图                        │
└─────────────────────────────────────────────────┘
```

## 主要组件

### IntentRouter2
- 负责与后端通信
- 发送玩家消息到 `/ai/intent`
- 接收多意图解析结果

### IntentDispatcher2
- 分发意图到具体处理器
- 支持的意图类型:
  - `CREATE_STORY` - 创建新剧情
  - `GOTO_LEVEL` - 跳转关卡
  - `SHOW_MINIMAP` - 显示小地图
  - `SET_DAY/NIGHT` - 时间控制
  - `TELEPORT` - 传送
  - `BUILD_STRUCTURE` - 建造
  - `STORY_CONTINUE` - 推进剧情

### WorldPatchExecutor
- 执行来自后端的世界修改指令
- 支持的操作:
  - `tell` - 发送消息
  - `weather` - 天气控制
  - `time` - 时间控制
  - `teleport` - 传送玩家
  - `build` - 建造结构
  - `spawn` - 生成实体
  - `effect` - 药水效果
  - `particle` - 粒子效果
  - `sound` - 声音效果

### StoryManager
- 管理玩家剧情状态
- 跟踪当前关卡
- 同步后端状态

## 使用方法

### 安装
1. 将编译好的 jar 放入 `plugins/` 目录
2. 配置 `config.yml` 中的 `backend_url`
3. 确保后端服务运行在配置的地址
4. 重启服务器

### 玩家命令
- `/drift status` - 查看当前状态
- `/drift sync` - 同步剧情进度
- `/drift debug` - 调试信息

### 自然语言示例
```
# 查看地图
玩家: 显示地图
玩家: 我想看看小地图

# 跳转关卡
玩家: 去第5关
玩家: 跳到level_10

# 修改世界
玩家: 把天气改成下雨
玩家: 现在是白天了吗？改成晚上吧

# 创建剧情
玩家: 写一个关于星空的故事
玩家: 创建一个新关卡，内容是月下独酌

# 推进剧情
玩家: 继续
玩家: 下一步
玩家: 我选择第一个选项
```

## 配置说明

### config.yml
```yaml
# 后端地址
backend_url: "https://drift-backend-classic-production.up.railway.app"

# 系统设置
system:
  debug: false
  nlp_timeout: 30
  patch_delay: 0

# 剧情系统
story:
  start_level: "level_01"
  auto_save_interval: 300

# 世界设置
world:
  allow_world_modification: true
  allow_story_creation: true
  safe_teleport: true
```

## 开发指南

### 添加新的意图类型
1. 在 `IntentType2.java` 中添加枚举值
2. 在后端 `intent_engine.py` 中添加识别逻辑
3. 在 `IntentDispatcher2.java` 中添加处理方法

### 扩展世界patch功能
1. 在 `WorldPatchExecutor.java` 中添加新的处理方法
2. 在后端返回相应的patch结构

### 调试技巧
- 启用 `debug: true` 查看详细日志
- 使用 `/drift debug` 查看实时状态
- 检查后端日志了解AI解析结果

## 依赖
- Paper API 1.20.1
- OkHttp 4.12.0
- Gson 2.11.0
- Java 17+

## 许可
MIT License

## 作者
Xinyue - 心悦宇宙

---

**让剧情在Minecraft中自然生长 🌱**
