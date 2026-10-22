# SDK 与示例验证记录（2026-10-22）

前半部分记录 SDK 初始拆分的验收；后文“示例体系整理验证”记录新增自动化检查和独立的 BLE 实机结果。

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

## 初始拆分的验证边界

SDK 与 server 初始拆分时的设备测试使用可控模拟传输，浏览器控制用例使用模拟后端。当时未扫描、连接或操纵真实 USB/BLE 开发板，也未修改、烧录固件；不将这些结果当作实机验收。

## 示例体系整理验证

实现分批提交：`7715431`（基础与同步资源）、`3628949`（异步事件与采样）、`082a3d9`（实机发现的有限定时器释放修复）。SDK 公开 API、协议、server 与固件均未改动。

### 自动化检查

| 检查 | 最终结果 |
|---|---|
| `poetry run pytest -q` | 134 项通过，包含 75 项示例检查 |
| `poetry run ruff check src tests examples` | 通过 |
| `poetry run mypy` | 27 个源文件通过，默认范围已包含 examples |
| `poetry check --lock` | 通过 |
| `poetry build` | wheel 和 sdist 构建成功 |
| 10 个示例的 `--help` | 全部通过，确认不会扫描或连接设备 |
| 示例导入检查 | 不扫描、不连接、不配置全局日志 |

新增覆盖包括设备选择与环境变量、非法参数不访问硬件、类型化事件与请求 ID 关联、目标引脚样本过滤、首次 ADC 响应计数、未校准数据、无样本超时、固件拒绝、结果不确定和断线，以及采样中／清理中取消、清理失败保留原始错误、线程和任务退出。有限定时器另覆盖仍在运行、查询前自然结束和查询后清理前结束三种时序。

这些测试使用真实 SDK 和测试侧模拟传输，不访问真实硬件。模拟后端不作为示例的运行模式。

### BLE 实机环境与结果

- 时间：2026-10-22；Linux / BlueZ，项目内 Python 3.12.3 环境。
- 扫描发现 `LIMIVIA-B47A`，服务 UUID 符合 LIMIVIA；固件 `0.1.0`、协议 `1`，SDK 的 `luatos-esp32c3-usb` 板型校验通过。
- 握手能力：GPIO、PWM、ADC、timer；用户 LED 为 GPIO13，ADC 上限报告为 2500 mV，校准标志为 true。
- 初始状态 revision=0，全部实验引脚 idle，PWM／timer／ADC 流为空。
- 以下模块均以 `poetry run python -m examples.<模块>` 启动，追加 `--kind ble --target <本次扫描 ID>`，按顺序运行，不并发占用设备。

| 模块与参数 | 观察结果 |
|---|---|
| `discover` | 找到上述设备及连接 ID |
| `sync_state`、`async_state` | 自动握手、显式 hello、完整状态查询成功 |
| `async_events --duration 2` | 两个 hello 结果、一个 state 结果和事件计数；退出时无未完成请求 |
| `sync_gpio --duration 1` | GPIO13 配置 output、实读电平 1，释放确认 |
| `sync_pwm --duration 1` | 设备报告 1000 Hz、50% duty、14 位分辨率，停止确认 |
| `sync_pwm --breath-ms 2000 --duration 2` | 设备报告呼吸周期 2000 ms，停止确认 |
| `sync_timer --pattern blink --high-ms 200 --low-ms 200 --duration 1` | 持续闪烁启动、状态查询、停止确认 |
| `sync_timer --pattern pulse --high-ms 200 --duration 0.5` | 自然结束后读到 output/level=0；修复后通过 pin.release 释放确认 |
| `sync_timer --pattern blink --high-ms 100 --low-ms 100 --count 2 --duration 1` | 有限闪烁自然结束后 output/level=0，释放确认 |
| `sync_adc --pin 0` | 收到 raw=1112、834 mV、calibrated=true，释放确认 |
| `async_adc --pin 0 --samples 3 --interval-ms 200` | 恰好输出 3 个样本；设备时间间隔约 200 ms，停止确认 |
| `sync_pwm --duration 30`，真实 PTY 中发送 Ctrl+C | 先输出停止／释放确认，再以 130 退出 |
| `async_adc --samples 1000 --interval-ms 200`，真实 PTY 中发送 Ctrl+C | 收到 60 个样本后中断，先输出停止／释放确认，再以 130 退出 |
| `sync_cleanup --pin 13`、`sync_cleanup --all` | 均收到成功确认 |
| 最终重新运行 `sync_state` | revision=28；全部实验引脚 idle，`pwm=[]`、`timers=[]`、`streams=[]` |

### 实机发现、修复与未解决现象

1. **已修复：有限定时器结束后的清理。** 单脉冲自然结束后，固件将引脚改为 output/level=0；继续发 `timer.stop` 返回 `pin_busy`（要求先释放引脚）。示例改为对 pulse／有限 blink 使用 `pin.release`，持续 blink 使用 `timer.stop`，同时避免状态查询与自然结束之间的时序问题。新增 6 个回归用例，脉冲及有限闪烁均已实机复测成功。
2. **仍需观察：BLE 连接阶段间歇断开。** 批量调用示例期间记录到 4 次连接／握手失败，CLI 以 1 退出，未进入相应资源操作流程。重新查询和独立复测可以成功；原因尚未定位，未加入自动重连或命令重试。这些失败没有从结果中删除，不将后续成功等同于连接稳定性已经解决。
3. **未定位：一次非 PTY SIGINT 检查超时。** 外部子进程驱动在 PWM 启动后发送 SIGINT，等待退出 20 秒超时，随后结束测试进程；系统仍显示该设备 Connected=yes。通过 `bluetoothctl disconnect` 仅断开这台测试设备的遗留连接，再运行 `sync_cleanup --pin 13` 收到释放确认。该次驱动未保存完整退出阶段输出，不能确定原因；之后真实 PTY 的 PWM 和 ADC Ctrl+C 检查均通过。非 PTY 的这一结果仍记为异常，不能记作通过。

上述结果验证的是 BLE 命令、事件、状态与退出清理，没有使用仪器校验实际电压、PWM 波形、LED 亮度或硬件时序；未使用已知参考电压校验 GPIO0 读数，采样数值仅用于确认数据链路。USB、其他板型、其他系统平台和长期运行稳定性未在本次实测覆盖。
