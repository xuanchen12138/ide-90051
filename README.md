# Southbank Flood Watch

Stop 116（City Rd/Kings Way）与 Route 58 的洪水风险预警原型。按照 `AGENT_IMPLEMENTATION_GUIDE.md` 实现：模拟水位 → 统一传感器接入 → 独立风险/服务状态 → 2D 地图与解释。它是 decision-support prototype，不是已验证的安全系统，也不会控制电车运营。

## 本地启动

需要 Python 3.11+、Node.js 22+ 和 npm 或 pnpm。Windows PowerShell，在项目根目录运行：

```powershell
python run.py
```

首次启动会创建 `.venv`、安装 Python/前端依赖、构建页面，再启动单个 API 进程。打开 **http://127.0.0.1:8000**。首次安装需要联网；下载完成后无需外部服务也能运行本地演示。代码修改后用 `python run.py --rebuild` 更新前端。关闭终端或 Ctrl+C 停止。

```powershell
# 只安装与构建，不启动
python run.py --setup-only
# 指定端口
python run.py --port 8001
```

如果使用当前 Codex 桌面附带的 Node/pnpm，启动脚本也会尝试自动找到它们；其他机器请安装标准 Node/npm。

## 云端免费演示部署

部署使用 Northflank Sandbox、单个 Docker 服务和 HTTPS；配置、访问密码、更新流程及临时存储限制见 [部署说明](docs/deployment.md)。`Dockerfile` 在构建时生成前端，运行时启动一个 API/SSE 进程。访问密码与后端 token 仅通过平台运行时变量设置。

## 密钥

如果根目录还没有 `.env`，复制 `.env.example` 为 `.env`。不要覆盖已有 `.env`。

| 配置 | 用途 |
| --- | --- |
| `TRANSPORT_VIC_API_KEY` | 仅后端使用的 Transport Victoria Subscription Key，以 `KeyID` header 请求；不发给浏览器 |
| `VITE_GOOGLE_MAPS_API_KEY` | 单独创建的浏览器 Maps key，限制 Maps JavaScript API 与允许的 HTTP referrer |
| `VITE_GOOGLE_MAPS_MAP_ID` | 可选 Google vector map ID；配置对应的浅色 monochrome cloud style |
| `DATABASE_URL` | 默认 `sqlite:///./data/prototype.db`，本地 SQLite |
| `SENSOR_PROVIDER` | `mock` 默认演示；`physical`/`http` 从 HTTP collector 接口接收真实设备读数 |
| `SENSOR_INGEST_TOKEN` | 可选 collector Bearer token；共享部署必须配置 |
| `ADMIN_API_TOKEN` | 可选场景管理 Bearer token；云端必须配置，浏览器通过独立演示密码认证 |
| `DEMO_ACCESS_PASSWORD` | 云端浏览器演示密码，至少 16 字符；本地可不设置 |
| `PUBLIC_DEPLOYMENT` | 云端设为 `true`，启动时强制检查访问保护配置 |
| `TRANSPORT_POLL_SECONDS` | 默认 60 秒，后端统一轮询，不随浏览器数增加 |

`.env` 已在 `.gitignore` 排除。不要提交密钥；更换 Maps key 后需要 `python run.py --rebuild`。浏览器 Maps key 按设计出现在前端资产中，必须通过 API/referrer/quota 限制保护。交通密钥不会出现在前端。请勿复用指南所指的旧密钥。

没有 Maps key 时，页面使用项目缓存的 **OpenStreetMap 墨尔本局部底图**：显示 Stop 116 周边的真实道路、建筑轮廓、桥梁、河流与公园，并叠加官方 GTFS 线路与站点。底图通过本地 `/api/v1/site/basemap` 加载，正常浏览不依赖在线地图瓦片；地图保留 © OpenStreetMap contributors / ODbL 署名。缓存只覆盖所选 Southbank 周边区域，切换到完整 Route 58 时，范围外仍是 GTFS 线路示意，不代表已下载整个墨尔本的街道。配置有效 Maps key 后可使用 Google Maps。没有交通密钥或 feed 失败时，页面保留演示能力并显示 unavailable/stale。底图来源与覆盖范围见 [底图记录](docs/basemap-data.md)。

## 哪些是真实、模拟与未验证

- **真实静态交通数据**：官方 2026-09-18 GTFS；Route `aus:vic:vic-03-58:`；两个方向站点 `18233` / `22612`；线路顶点来自 `shapes.txt`，不是手绘。详见 [GTFS 核验记录](docs/gtfs-provenance.md)。
- **真实地理背景**：OpenStreetMap 的道路、建筑、桥梁、水域与绿地数据，按局部范围缓存并以 SVG 绘制；遵循 [ODbL](https://opendatacommons.org/licenses/odbl/1-0/) 并保留 [OpenStreetMap 署名](https://www.openstreetmap.org/copyright)。它是静态地理背景，不是实时道路状态、建筑测绘或洪水范围。
- **真实实时交通数据**：后端请求并解码车辆位置、班次更新、官方服务公告，按已核验 ID 筛选。每个 feed 保留独立源时间、抓取时间、freshness 和失败信息。没有匹配车辆不意味着停运。
- **模拟 hazard**：0–100 的 `scenarioLevel` 和地图上的局部水纹；不是毫米积水深度或真实淹没范围。阈值 25/50/75、滞回 3、上升 dwell 3 秒、恢复 dwell 5 秒均为演示配置。
- **官方公告 fixture**：仅用于演示服务状态分类，始终标明 fixture，不是真实官方停运信息。退出该场景就恢复真实交通快照。
- **未验证部分**：物理传感器、实测水深阈值、洪水水动力学、生产运营与真实设备时钟同步；Google Maps 需使用有效 key 后另行验证；人工 reviewer 评估不会用自动测试替代。

## 操作

默认 Simulation mode。选择 Water rising，可观看 NORMAL → WATCH → WARNING → CRITICAL。暂停保持演示水位，传感器心跳继续；Resume 继续场景；Reset 回到正常场景与局部范围。Manual slider 可固定 0–100 的演示水平，状态仍遵循 dwell/hysteresis。Full route demo 仅用于演示，并显示 “Simulated impact — not an official service status.”

Normal operation 使用 physical collector 独立读数；没有设备数据时显示 UNKNOWN。它不会把 mock 读数当成真实观察。

完整演示步骤：[demo-guide.md](docs/demo-guide.md)。评估与限制：[validation.md](docs/validation.md)。

## 开发与验证

```powershell
# Python 单元、适配器、API 集成测试
.\.venv\Scripts\python.exe -m pytest -q
# 前端呈现逻辑 / 类型检查与构建
npm --prefix web test
npm --prefix web run build
# 浏览器测试，先启动 python run.py
npm --prefix web exec -- playwright install chromium
npm --prefix web run test:e2e
# 验证真实交通接口，仅输出脱敏后的健康信息
.\.venv\Scripts\python.exe scripts/check_live_transport.py
# 检查配置的后端密钥未进入源码或构建资产
.\.venv\Scripts\python.exe scripts/scan_secrets.py
# 测量默认1Hz数据流、截图与渲染延迟（保持平台运行）
node scripts/evaluate_browser.mjs
# 独立故障注入实验，按默认60秒轮询周期测量恢复
.\.venv\Scripts\python.exe scripts/evaluate_transport_recovery.py
```

pnpm 用户可使用 `pnpm --dir web test` / `pnpm --dir web build`。浏览器测试脚本的具体端口/命令见 `web/playwright.config.ts`。真实接口返回 stale/empty 是正常的可报告结果，不等于 adapter 测试失败。

开发前端运行 `npm --prefix web run dev`，Vite 将 `/api` 转发到 `127.0.0.1:8000`。后端单独运行 `.venv/Scripts/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000`。

## 结构与交付物

| 路径 | 内容 |
| --- | --- |
| `web/` | React/TypeScript、缓存 OSM / 可选 Google 底图、GTFS 叠加、状态面板、场景控制、移动端、浏览器测试 |
| `api/` | FastAPI、SSE、场景 runtime、SQLite 持久化 |
| `domain/` | 传感器模型、纯状态引擎 |
| `adapters/` | 官方 GTFS 静态/实时适配器、mock 与 HTTP collector |
| `config/` | 核验站点、线路与局部底图 GeoJSON、trip ID 索引、演示阈值、预设评估目标 |
| `contracts/` | Sensor JSON Schema；在线 OpenAPI 在 `/docs` 与 `/openapi.json` |
| `docs/` | 架构、状态表、数据来源、演示、验证与限制、可选部署说明 |
| `artifacts/` | 本地验证输出和截图，忽略于 Git；失败记录同样保留 |
| `gtfs_tram_test/` | 原有独立接口测试脚本，保留不改动 |

静态数据可用 `python -m adapters.gtfs_static --download` 刷新；更新后核对 provenance，再重启 API。不要把 passenger stop number `116` 当成 GTFS stop ID。
