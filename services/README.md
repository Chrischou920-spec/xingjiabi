# 票务服务

本目录包含项目所需的火车票和国内航班 MCP 服务。应用主程序通过统一 Provider 边界调用这些服务。

## 12306-mcp

提供车站代码、直达票、余票和中转票等查询能力。

## FlightTicketMCP

提供国内航班搜索、日期和航班详情能力。项目范围不包含：

- 国际三地中转工具；
- OpenSky 全球航班跟踪工具；
- 与 MVP 无关的天气工具；
- 国际航线产品入口。

服务层 `searchFlightRoutes` 还增加了中国大陆城市白名单。产品内核层会再次校验，因此即使 UI 传入国外城市也会被拒绝。

## 注意

当前默认运行模式仍是 `demo`，所以无需安装依赖也能验证新 UI 和路线算法。火车票可通过 `STUDENT_TRIP_DATA_MODE=live_train` 使用 `TrainMcpProvider`；国内机票可通过 `live_flight` 使用 `DomesticFlightMcpProvider`。机票源可能触发 WhaleGuard 或浏览器验证码，这些情况会被当作数据源不可用报错，不会返回空票务列表。现场演示仍必须准备带查询时间的缓存结果。
