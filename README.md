# 行价比 · 本地出行规划网站

当前版本：完整本地网站 · 更新日期：2026-10-04。第一版 `v0.1.0-demo` 的归档说明保留在 [历史版本记录](docs/RELEASE_v0.1.0-demo.md)。

本仓库保存中文前端网站、国内行程规划后端、12306 / 国内航班 MCP 服务、票务 Provider、自动化测试、接口与调试文档和 UI 设计资料。网站由同一个 Python 服务在 `127.0.0.1:8765` 提供，无需单独启动前端服务。

已验证真实 12306 查询，以及通过 Safari 已登录携程页面取得真实机票并显示在网站。国内航班 Provider 已接入，修复了浏览器并发冲突、验证异常空返回、超时重试重叠及前 10 条截断。Safari 模式目前读取已加载的航班列表，仍可能需要人工验证或重新登录；验收情况见 [航班调试记录](docs/FLIGHT_DEBUG.md)。直接运行后端时默认使用演示数据，使用本地网站启动脚本时默认查询真实来源。

项目的票务能力集中在 `services/`，应用层通过统一 Provider 接口调用火车和国内航班数据。

已完成：

- 仅允许中国大陆城市，国际线路在产品入口和规划器两层均被阻止。
- 去程与返程联合组合，不再只推荐单程。
- 火车和国内航班使用统一数据结构。
- 按省钱、均衡、最快三种偏好排序。
- 预算过滤、跨夜住宿成本、返校/门禁超时风险。
- 无需网络的演示数据与自动化测试。
- 一次中转与空铁组合计算框架；三段复杂路线不进入 MVP。
- 可供网站调用的 `POST /plan` 本地 HTTP 接口，以及 `GET /cities` 城市选项接口。
- 参考 `design/concepts/02-planning-ice-dashboard.png` 实现的中文搜索页和方案页。
- 不包含国际节点、三段跨洲查询和开发者启动面板。

公开仓库不包含本地虚拟环境、依赖目录、运行日志、登录 Cookie、浏览器会话、临时构建文件和路演交付稿。克隆后需要按下方说明安装依赖；真实机票查询需要在本机 Safari 登录携程，不能从仓库获取其他人的登录状态。网站目前用于本地运行，不是已部署的公网订票平台。

自动化验证：Python 62 项、前端 22 项测试通过。Safari 航班查询和 Chrome 网站展示已完成真实机票验收，记录见 [航班调试记录](docs/FLIGHT_DEBUG.md)。

## 运行

### 本地网站与真实票务查询

先按下方说明安装并构建 12306 MCP、航班 MCP 所需依赖，然后在项目根目录运行：

```bash
bash scripts/start-local.sh
```

浏览器打开 `http://127.0.0.1:8765`。此启动方式默认使用 `live_all`：网页经 `/plan` 请求本地后端，后端通过 stdio 调用 12306 和国内航班 MCP；无需另开前端端口。搜索时会按所选日期实时打开携程航班列表页，网页结果页单独列出本次抓取的航班，不只显示前三个规划方案。若航班源被携程 WhaleGuard 拦截，网页会明确显示错误；只要 12306 有可用方案，仍会展示已查到的真实火车结果，不会自动混入演示机票。

若 8765 已被旧版服务占用，可用 `STUDENT_TRIP_PORT=8766 bash scripts/start-local.sh` 在另一端口启动，不会停止旧进程。

macOS 启动脚本默认使用 `FLIGHT_BROWSER_ENGINE=safari`。先在 Safari 打开已登录的携程机票页面；查询程序会在同一窗口创建带 `#xingjiabi-live` 标记的专用标签页，读取页面已加载的直达航班文字和最低报价。每次查询会自动选中专用标签所在窗口的该标签，避免携程在未选中的后台标签延迟加载列表；不会把 Safari 应用强制置前。首次运行可能需要在 macOS 授权本地程序自动化访问 Safari。无需导出 Cookie，也无需启用“允许 Apple Events 执行 JavaScript”。该模式读取已加载的列表，尚不保证覆盖携程的全部滚动分页结果；查询时请保留专用标签页。未登录的空列表会报告登录问题；点选、拼图、滑块等验证优先于底层无航班提示和旧列表，需由用户手动完成，未完成时返回 `VERIFICATION_REQUIRED`。设置 `FLIGHT_BROWSER_ENGINE=chromium` 可使用原有独立浏览器。

当前网站只提供直达路线搜索。概念图中的中转次数和最短换乘时间暂不做成可操作入口，因为当前本地服务没有配置实际中转枢纽。网站不提供订票或支付。

需要稳定演示界面时可改用固定数据：

```bash
STUDENT_TRIP_DATA_MODE=demo bash scripts/start-local.sh
```

演示数据只覆盖 2026 年 10 月 1 日上海去北京、10 月 3 日北京返上海，页面会明确标记“演示数据 · 非实时票价”。

### 命令行与接口

```bash
python -m student_trip.cli
```

或指定条件：

```bash
python -m student_trip.cli --origin 上海 --destination 北京 --budget 1300 --preference cheapest
```

启动本地接口：

```bash
python -m student_trip.server
```

接口地址为 `http://127.0.0.1:8765`，健康检查为 `GET /health`，城市列表为 `GET /cities`，规划接口为 `POST /plan`。直接运行 `python -m student_trip.server` 时默认使用演示数据；通过上述脚本运行时默认使用真实票务来源。`POST /plan` 返回方案、查询时间、数据模式及按交通方式区分的来源错误。

### 使用真实 12306 数据

首次安装并编译依赖：

```bash
cd services/12306-mcp
npm install
npm run build
cd ../..
```

启动真实火车票模式：

```bash
STUDENT_TRIP_DATA_MODE=live_train python3 -m student_trip.server
```

此模式只返回火车方案。若 12306 网络或服务不可用，`POST /plan` 返回 HTTP 503，不会伪装成“没有票”。

### 使用真实国内航班数据

航班服务使用独立 Python 虚拟环境和 Chromium：

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r services/FlightTicketMCP/requirements.txt
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
FLIGHT_MCP_PYTHON="$PWD/.venv/bin/python" \
STUDENT_TRIP_DATA_MODE=live_flight \
python3 -m student_trip.server
```

火车和国内航班同时启用：

```bash
FLIGHT_MCP_PYTHON="$PWD/.venv/bin/python" \
STUDENT_TRIP_DATA_MODE=live_all \
python3 -m student_trip.server
```

当前航班 Provider 只接受中国大陆城市，并只把直达航班作为单个行程段。本地查询默认使用可见浏览器；检测到验证码或登录弹窗时，在当前携程窗口等待人工处理（最多 120 秒），请不要关闭该窗口。未完成验证、页面未加载或解析失败时，接口返回 HTTP 503 和可诊断错误，不会把这些异常当成“没有航班”。火车和航班同时查询时，有可用火车方案则返回部分结果并标明航班失败。可通过 `FLIGHT_BROWSER_PATH` 指定本机 Chrome/Chromium 可执行文件；无桌面环境部署时可设置 `FLIGHT_BROWSER_VISIBLE=0`，但验证码仍需要可见窗口人工处理。

网站取消按钮通过 `POST /cancel` 向后端发送本次 `query_id`，停止后续规划并向航班 MCP 发送取消信号。浏览器会在当前短操作结束后释放资源，不会中断其他查询。单次航班搜索总预算为 240 秒，MCP 等待上限为 300 秒；超时不会立即重发仍在运行的任务。

## UI 规范与验收

前端仍为原生 HTML / CSS / JavaScript，无新增框架或外部 UI 依赖。界面按中文出行工作台组织，包含联动行程摘要、门禁/住宿渐进展开、票券式方案比较、航班列表展开、来源诊断、字段错误定位、查询等待与取消反馈。

设计规范见 [design-system/xingjiabi/MASTER.md](design-system/xingjiabi/MASTER.md)，八项自检与验收记录见 [docs/UI_REFINEMENT.md](docs/UI_REFINEMENT.md)。前端合约测试运行 `node --test tests/test_web_ui.cjs`。

## 下一阶段

`TicketProvider` 是真实数据接入边界。`TrainMcpProvider` 和 `DomesticFlightMcpProvider` 都已实现；火车数据已通过真实 12306 查询验证，航班 MCP 协议、浏览器启动和反爬错误边界也已验证。网站只调用 `GET /health`、`GET /cities` 和 `POST /plan`，无需直接处理 MCP 协议或浏览器验证码。

下一阶段可根据比赛环境决定是否接入第二个国内航班数据源或增加带时效标记的缓存降级。

UI 字段见 [docs/UI_INPUTS.md](docs/UI_INPUTS.md)。
