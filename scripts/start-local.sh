#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -f services/12306-mcp/build/index.js ]]; then
  echo "缺少 12306 MCP 构建文件。请先在 services/12306-mcp 执行 npm install && npm run build。" >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "缺少 .venv/bin/python。请先按 README 安装航班 MCP 依赖。" >&2
  exit 1
fi

export FLIGHT_MCP_PYTHON="${FLIGHT_MCP_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
export STUDENT_TRIP_DATA_MODE="${STUDENT_TRIP_DATA_MODE:-live_all}"
if [[ "$(uname -s)" == "Darwin" ]]; then
  export FLIGHT_BROWSER_ENGINE="${FLIGHT_BROWSER_ENGINE:-safari}"
fi

echo "本地网站：http://127.0.0.1:${STUDENT_TRIP_PORT:-8765}"
echo "数据模式：$STUDENT_TRIP_DATA_MODE"
exec .venv/bin/python -m student_trip.server
