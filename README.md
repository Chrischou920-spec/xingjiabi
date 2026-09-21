# 行价比 · 第一版 Demo

版本：`v0.1.0-demo` · 归档日期：2026-09-21。

本版本保存国内行程规划后端、票务 Provider、测试、接口文档和 UI 概念设计稿。设计稿位于 `design/`，尚未实现为可交互的网站。

已验证真实 12306 查询；国内航班 Provider 已接入，但当前网络下携程 WhaleGuard 会拦截查询，尚未完成真实航班结果的端到端验收。默认使用演示数据。

项目的票务能力集中在 `services/`，应用层通过统一 Provider 接口调用火车和国内航班数据。

已完成：

- 仅允许中国大陆城市，国际线路在产品入口和规划器两层均被阻止。
- 去程与返程联合组合，不再只推荐单程。
- 火车和国内航班使用统一数据结构。
- 按省钱、均衡、最快三种偏好排序。
- 预算过滤、跨夜住宿成本、返校/门禁超时风险。
- 无需网络的演示数据与自动化测试。
- 一次中转与空铁组合计算框架；三段复杂路线不进入 MVP。
- 可供新 UI 调用的 `POST /plan` 本地 HTTP 接口。
- 不包含国际节点、三段跨洲查询和开发者启动面板。

## 运行

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

接口地址为 `http://127.0.0.1:8765`，健康检查为 `GET /health`，规划接口为 `POST /plan`。当前返回演示票务数据，后续替换 Provider 即可接真实票务源，UI 合同无需变化。

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

当前航班 Provider 只接受中国大陆城市，并只把直达航班作为单个行程段；跨模式中转仍由规划器统一计算。如果携程返回 WhaleGuard 拦截页或验证码，接口会返回 HTTP 503 和可诊断错误，不会把反爬拦截误报为“没有航班”。可通过 `FLIGHT_BROWSER_PATH` 指定本机 Chrome/Chromium 可执行文件。

## 下一阶段

`TicketProvider` 是真实数据接入边界。`TrainMcpProvider` 和 `DomesticFlightMcpProvider` 都已实现；火车数据已通过真实 12306 查询验证，航班 MCP 协议、浏览器启动和反爬错误边界也已验证。新 UI 只调用 `POST /plan` 或 `DomesticTripPlanner.plan()`，无需知道 MCP、浏览器验证码或票务源细节。

下一阶段建议先实现全新 UI 的搜索页和方案列表，再根据比赛环境决定是否接入第二个国内航班数据源或增加带时效标记的缓存降级。

UI 字段见 [docs/UI_INPUTS.md](docs/UI_INPUTS.md)。
