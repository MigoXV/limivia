# SDK 拆分验证记录（2026-10-22）

## 环境与依赖

- Python 3.12.3；Poetry 2.1.4。
- SDK 独立环境：`limivia/.venv`；server 独立环境：`limivia-server/.venv`。
- 原 `limivia-rt3MOzg4-py3.10` 缓存环境在目录迁移前移除。
- SDK 初始实现提交：`439bdab`；server 接入提交：`751f6c4`。
- server 从 `../limivia/src/limivia` 导入 SDK，从自身 `src/limivia_server` 导入服务代码。
- SDK 环境不包含 FastAPI；wheel 的依赖仅包括 Pydantic、Bleak、pySerial、AnyIO 和 Typer。

## 已执行结果

| 检查 | 结果 |
|---|---|
| SDK `poetry run pytest -q` | 59 项通过 |
| SDK Ruff | src、tests、examples 通过 |
| SDK `poetry run mypy` | 15 个源文件检查通过，含公开 API 类型收窄用例 |
| Server `poetry run pytest -q` | 22 项通过 |
| Server Ruff | src/limivia_server、tests 通过 |
| 前端 lint | 通过 |
| 前端 Vitest | 8 项通过 |
| 前端生产构建 | 通过 |
| Playwright E2E | 15 项通过，新 CLI 启动的 server 提供页面 |
| 两项目 `poetry check --lock` | 通过 |
| 两项目 `poetry build` | wheel 和 sdist 均生成 |
| SDK wheel 独立导入 | 临时目录安装 wheel，通过隔离子进程导入，确认 py.typed 存在且未依赖 FastAPI |
| Server wheel 元数据 | Python >=3.12,<3.13；limivia >=0.1.0,<0.2.0，未嵌入本机 file:// 依赖 |
| CLI / 示例 | scan、同步 GPIO 与异步 ADC 示例的 --help 通过；server doctor 通过 |

## 关键覆盖

- 全部 13 个命令资源的同步／异步一致性，响应类型与请求 ID 关联。
- 自动握手、协议／板型不兼容、UTF-8 分片与超长行恢复。
- 固件拒绝、命令超时、迟到响应、八条等待队列与事件缓冲溢出。
- 部分写入超时关闭通道，避免下一条命令拼接到半帧。
- 事件消费取消、单消费者限制、扫描和连接互斥。
- 连接打开期间取消、客户端关闭期间取消打开、断线后重连，以及同步线程退出。
- server 内部握手 ID 与浏览器 ID 隔离；主动事件和固件错误保持原网页格式。
- 同源检查、独占占用、非法参数、连接／握手期间关闭页面、ASGI 请求取消时硬件清理。
- SPA 深层路径、未知 API、静态资源及缺少前端构建时的启动失败。

## 验证边界

SDK 与 server 的设备测试使用可控模拟传输，浏览器控制用例使用模拟后端。本次未扫描、连接或操纵真实 USB/BLE 开发板，也未修改、烧录固件；真实硬件兼容性仍需单独验收。
