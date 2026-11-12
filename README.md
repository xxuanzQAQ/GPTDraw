# GPTDraw 生图

GsCore 的 GPT 生图插件，从 AstrBot 的 `astrbot_plugin_ai_video` 移植。统一走
**New API** 的 `/images/generations` 接口，模型不再写死：用 `gpt模型列表` 看当前密钥能用的
模型，用 `gpt切换模型` 选一个，之后生图默认用它；`--model` 可以单次临时指定。

## 功能

- **模型自选**：`gpt模型列表` 直接从 New API 的 `/models` 拉取当前密钥可用的模型，
  `gpt切换模型 <序号|模型名>` 保存到数据库，`gpt当前模型` 随时查看，`gpt切换模型 默认`
  恢复配置里的默认模型。
- **个人密钥绑定**：每个用户绑定自己的 New API 密钥，费用记在自己名下；同一用户可绑多把，
  可随时切换当前使用的那把。
- **密钥加密存储**：数据库里只存 Fernet 密文，密钥文件在 `data/GPTDraw/token.key`（0600）。
- **会话授权**：绑定者可以把自己的密钥授权给当前群，群成员直接生图、扣授权人的额度。
- **个人授权**：绑定者可以授权某个人私聊使用自己的密钥，可随时收回。
- **文生图 / 参考图改图**：提示词里直接写 `1:1`、`16:9`、`2k` 会自动识别；也支持
  `--model`、`--size`、`--quality`、`--background`、`--images` 等参数。
- **动态 GIF**：`--format gif`（或 `--gif`）提交 `output_format=gif`，并带上
  `complexity`、`frame_count`、`frame_duration_ms`，尺寸自动用 `auto`，直接出表情包动图。
- **异步任务**：默认带 `async=true` 提交，自动轮询 New API 的图片任务。
- **尺寸兜底**：比例或 `auto` 被上游拒绝时，在两者之间切换重试。
- **multipart 兜底**：参考图走 JSON 被上游拒绝时，自动改用 `/images/edits` 上传文件。
- **多图返回**：`--n 2` 这类请求会逐张发回全部结果。
- **预设**：本地预设存在数据库里，可增删；远程提示词库（`/api/presets`）定时同步到内存。
- **网页管理页**：密钥、预设、会话授权、个人授权、模型选择都能在网页控制台增删改查。

余额查询、消耗排行、总余额这三项没有迁入本插件，继续由 NewAPI 看板插件提供。

## 安装

把本目录放到：

```
gsuid_core/plugins/GPTDraw/
```

重启 core 后首次加载。之后改插件可以发送：

```
gpt重载插件
```

也支持 `core重载插件GPTDraw`。热重载会重新注册触发器、配置和网页管理页。

## 配置

网页控制台 → 插件 → **GPTDraw**：

| 配置 | 默认值 | 说明 |
|------|--------|------|
| New API 地址 | `http://localhost:3000/v1` | 生图与模型列表统一使用的地址 |
| 请求超时（秒） | 300 | 单次提交 / 查询的超时时间，最大 900 |
| 最大并发请求 | 2 | 同时向 New API 发起的生图请求数 |
| 允许私网参考图 | 开 | 关闭后只接受公网 URL 或 data:image |
| 计费请求路径 | `/images/generations` | 按需改成渠道实际路径 |
| 图片请求体模式 | `auto` | `auto` / `images_generations` / `chat_completions` |
| 启用异步任务 | 开 | 提交时带 `async=true` |
| 图片任务查询路径 | `/v1/images/generations/{task_id}` | 轮询任务状态 |
| 轮询间隔 / 超时（秒） | 8 / 360 | 图片任务轮询节奏 |
| 默认模型 | `gpt-image-2.6-sunburst` | 没切换过模型时使用 |
| 模型列表筛选词 | `image` | `gpt模型列表` 只显示名称含该词的模型；`all` 显示全部 |
| 模型列表缓存（秒） | 120 | 同一把密钥重复查模型的缓存时间 |
| 默认画幅 | `1:1` | 未指定 size 时使用，支持比例 / 像素 / 单边像素 / `auto` |
| 默认尺寸格式 | `ratio` | `ratio` / `pixels` / `single` / `auto` |
| 默认分辨率基准 | `1k` | 只用于把比例换算成像素，不再影响模型 |
| 默认输出格式 | `png` | `png` / `jpeg` / `webp` / `gif` / `auto`；留空则不发送 |
| 默认质量 | 空 | `auto` / `low` / `medium` / `high`；留空则不发送 |
| 默认背景 | 空 | `auto` / `opaque` / `transparent`；留空则不发送 |
| GIF 动画复杂度 | `low` | `low` / `medium` / `high`；留空则不发送 |
| GIF 默认帧数 | 9 | 生成 GIF 时发送，0 表示不发送 |
| GIF 默认帧间隔（毫秒） | 200 | 生成 GIF 时发送，0 表示不发送 |
| 附加请求参数 | 空 | 以 `k=v,k2=v2` 或 JSON 写进每次请求体 |
| 提示词库地址 | `http://127.0.0.1:19731` | 留空关闭远程预设同步 |
| 提示词库超时 / 刷新间隔 | 8 / 60 | 远程预设的请求超时与缓存时间 |

`附加请求参数` 用来适配不同站点的字段差异，例如 `version=flare,resolution=2K`
或 `{"response_format":"url"}`。

## 命令

默认前缀 `gpt`（也接受 `GPT`）。

| 命令 | 说明 |
|------|------|
| `gpt模型列表 [关键词\|全部]` | 查看当前密钥可用的模型；`gpt模型` 等价 |
| `gpt切换模型 <序号\|模型名>` | 切换之后生图使用的模型；`gpt切换模型 默认` 恢复配置默认 |
| `gpt当前模型` | 查看当前模型 |
| `gpt生图 <提示词> [参数]` | 文生图；别名 `gpt画图` / `gptbnn` |
| `gpt预设列表` | 查看本地与远程预设 |
| `gpt预设 <名称> [额外提示词]` | 用预设生图；额外提示词里可以继续写参数 |
| `gpt预设添加 <名称> <提示词>` | 添加本地预设；也支持 `名称 :: 提示词` |
| `gpt预设删除 <名称>` | 删除本地预设（主人） |
| `gpt重载预设库` | 立即同步远程提示词库 |
| `gpt设置密钥 <密钥>` | 绑定个人生图密钥；接口固定用配置里的 New API 地址 |
| `gpt我的密钥` | 查看已绑定的密钥与当前使用项 |
| `gpt删除密钥 [序号\|全部]` | 删除密钥；删除后相关授权自动失效 |
| `gpt全部密钥` | 查看全部用户的真实密钥（主人，仅私聊） |
| `gpt授权本群开启` / `gpt授权本群关闭` | 开启 / 关闭本群授权 |
| `gpt授权 @某人` | 授权个人私聊使用 |
| `gpt取消授权 @某人` / `gpt取消授权 本群` | 收回授权 |
| `gpt授权状态` | 查看当前会话与个人授权情况 |
| `gpt帮助` | 显示命令帮助图 |
| `gpt重载插件` | 热重载插件（主人） |

生图参数：

```text
gpt模型列表                 # 看可用模型，记住序号
gpt切换模型 3               # 切到列表第 3 个模型
gpt生图 一只橘猫在窗台晒太阳 --size 16:9 --quality high
gpt生图 赛博朋克城市 2k --size 3:2 --model gpt-image-2.5-ext-2k
gpt生图 小橘猫挥手 做成动图 --format gif --frame_count 9 --frame_duration 200
gpt生图 换成水彩风格 --images https://example.com/cat.png
```

也可以发命令时附上一张图（例如 `gpt生图 换成水彩风格` 同时带图），插件会把这张图当作参考图。

### 新站点参数差异

不同站点的图片接口字段并不一致。插件默认只发 `model`、`prompt`、`n`、`size`
和配置里开启的字段，其余按需追加：

| 字段 | 命令参数 | 说明 |
|------|----------|------|
| `output_format` | `--format gif` / `--output_format webp` | `png` / `jpeg` / `webp` / `gif` |
| `complexity` | `--complexity low` | GIF 动画复杂度 |
| `frame_count` | `--frame_count 9` | GIF 帧数，1-60 |
| `frame_duration_ms` | `--frame_duration 200` | GIF 帧间隔，0-2000 |
| `quality` | `--quality high` | `auto` / `low` / `medium` / `high` |
| `background` | `--background transparent` | `auto` / `opaque` / `transparent` |
| `resolution` / `version` | `--resolution 2k` / `--version flare` | 仅在显式写了才发送 |
| 其它 | `--extra k=v,k2=v2` | 原样写进请求体，可覆盖上面的默认值 |

`--n` 支持 1-10，返回几张就发几张（最多发 4 张，其余以链接补发）。

生成 GIF 时如果没显式写 `--size`，插件会把 `size` 设为 `auto`（上游一般给 512x512），
避免「帧数 × 尺寸」超出上游像素预算；显式写了大尺寸又报
`GIF frames exceed the total request pixel budget` 时，减小 `--size` 或降低
`--frame_count` 即可。

### New API 渠道要求

部分上传字段（`image_urls`、`complexity`、`frame_count`、`frame_duration_ms`、`resolution`、
`version`、`quality`、`output_format` 等）不是 OpenAI 标准图片字段，New API 默认会把它们丢掉：
它不是原样转发，而是把请求重新解析成固定结构再序列化。

所以这些字段必须在渠道上打开「透传请求体」（`setting.pass_through_body_enabled: true`）才会到上游。
判断办法：如果 GIF 帧数不生效、参考图被忽略（但插件日志里明明带了 `image_urls`），就是这个开关没开。

打开后 New API 会把原始 body 直接转给上游，但会先剥掉它自己的 `async` 字段，所以异步任务照常可用，
上游收到的正好是插件发出的那套参数。

参考图还有个额外兜底：上游抓不到图片链接（QQ 图片链接带 rkey，会过期）时，插件会把图片下载下来
转成 `data:image` 再提交一次；仍然失败才回退到 `/images/edits` 表单上传。

## 数据结构

运行时数据在 `data/GPTDraw/`：

```
data/GPTDraw/
├── config.json   # 插件配置
├── token.key     # Fernet 密钥（0600）
└── images/       # 预留的图片缓存目录
```

密钥以 Fernet 密文存在数据库；`token.key` 丢失后所有已绑定密钥都要重新绑定。
数据库里还会存会话授权、个人授权、本地预设与每个用户当前选择的模型。

## 与 AstrBot 原项目的差异

- **去掉余额相关能力**：`查余额`、`用户消耗排行`、`总余额` 及对应密钥配置都没有迁入。
- **预设网站没有迁入**：原项目内嵌的提示词库网站（`preset_server.py` + `index.html`）
  不随插件发布；远程预设只作为 `/api/presets` 的只读缓存同步。
- **本地预设始终可增删**：原项目在配置了提示词库地址时会禁用本地增删，本插件不做这个限制。
- **数据库存储**：原项目的 `users.json` / `custom_image_presets.json` 换成 SQLModel 表，
  密钥按 `bot_id + user_id` 隔离。

## 已知限制

- 模型名以 New API 的 `/models` 为准；切换时模型不在列表里会报错。上游渠道没映射的模型
  即使出现在列表里也可能生成失败。
- 不同站点支持的字段不同，插件不认识的字段请用 `--extra` 或配置里的「附加请求参数」透传。
- 参考图只支持公网 URL、`data:image`、`base64://` 或机器人能读到的本地文件；单张超过
  20MB 会被拒绝。
- 生成图超过 50MB 或下载失败时，改为发送图片链接文本。
- 远程提示词库不可用时只影响远程预设，本地预设和生图不受影响。
- 群里发送密钥会留在聊天记录里，建议私聊绑定。
