# LIMIVIA Python SDK

LIMIVIA 是直接通过 USB / BLE 控制开发板的 Python SDK。它提供同步 `Limivia` 和异步 `AsyncLimivia`，以资源方法提交命令，以类型化事件接收全部执行结果和设备通知。

首版适配合宙 CORE ESP32-C3 简约版与 LIMIVIA 协议 v1。网页工作台位于相邻的 [limivia-server](../limivia-server/README.md)，server 依赖本 SDK。SDK 可在 Python 脚本中独立使用。

## 安装

需要 Python 3.12 和 Poetry，源码使用 `src/limivia` 布局：

```bash
poetry env use python3.12
poetry install
poetry run python --version
poetry run limivia scan --kind ble
```

项目通过 `poetry.toml` 使用独立的 `.venv`。USB 扫描使用 `--kind usb`，CLI 默认值也可通过 `LIMIVIA_TRANSPORT` 设置。SDK 客户端的连接类型由方法参数显式决定。

可从 PyPI 安装：`pip install limivia`，或在其他 Poetry 项目中运行 `poetry add limivia`。需要本地联调时可运行 `poetry add --editable /path/to/limivia`。发布文件通过 `poetry build` 构建。

蓝牙依赖 Bleak，Linux 需要 BlueZ 和可访问的系统 D-Bus。USB 依赖 pySerial，需要串口权限。设备必须已安装 LIMIVIA 专用固件；安装 SDK 不会烧录设备。

## 同步与异步调用

同步 `Limivia` 与异步 `AsyncLimivia` 使用相同的资源名称、参数和事件类型。完整、可运行的入门对照见 [同步状态查询](examples/sync_state.py) 与 [异步状态查询](examples/async_state.py)：

```bash
poetry run python -m examples.sync_state --kind ble
poetry run python -m examples.async_state --kind usb
```

两个示例都会先扫描并选择设备；存在多台时，需要通过 `--target` 指定本次扫描得到的 ID。连接自动发送并校验 `hello`，结果仍由事件流交付。

命令方法返回的整数仅表示已通过校验并进入发送队列。是否执行成功，以匹配请求 ID 的结果事件为准。同步版本使用 `for event in connection` 或 `connection.recv()`；异步版本通过 `await` 提交命令，通过 `async for` 或 `await connection.recv()` 接收事件。

每个连接仅允许一个事件消费者，不能同时从两个任务调用 `recv()` 或迭代连接。多个订阅者的分发方式见 [异步事件示例](examples/async_events.py)。命令处理与事件消费独立运行，不要求先迭代才能发送命令；同步客户端的后台事件循环在整个生命周期内持续运行。

## 资源与返回事件

| 方法 | 成功事件 | result 类型 |
|---|---|---|
| `connection.hello()` | `hello.completed` | Hello |
| `connection.state.retrieve()` | `state.completed` | Snapshot |
| `connection.gpio.set(...)` | `gpio.set.completed` | Snapshot |
| `connection.gpio.read(pin=...)` | `gpio.read.completed` | GPIOReading |
| `connection.pwm.set(...)` / `stop(pin=...)` | `pwm.set.completed` / `pwm.stop.completed` | Snapshot |
| `connection.adc.read(pin=...)` / `start(...)` | `adc.read.completed` / `adc.start.completed` | ADCSample |
| `connection.adc.stop(pin=...)` | `adc.stop.completed` | Snapshot |
| `connection.timer.start(...)` / `stop(pin=...)` | `timer.start.completed` / `timer.stop.completed` | Snapshot |
| `connection.pin.release(pin=...)` | `pin.release.completed` | Snapshot |
| `connection.outputs.stop()` | `outputs.stop.completed` | Snapshot |

全部命令结果包含 `request_id` 和 `op`。固件拒绝、命令超时和连接中断导致的失败通过 `command.failed` 交付，包含 `error.code`、`message`、`source` 和 `may_have_executed`。

其他事件：

- `state.changed`：设备状态版本变化，包含 `revision`；发送 `state.retrieve()` 获取完整状态。
- `adc.sample`：后续采样，包含 `data: ADCSample`。
- `protocol.error`：无法解析的协议帧；超长行丢弃到 LF 后恢复。
- `unknown`：新固件中尚未建模的通知，完整内容保存在 `raw`。
- `connection.closed`：事件流终态；可能包含连接错误信息。

设备启动日志通过模块 logger 的 DEBUG 级别记录。请求参数和强类型模型位于 `limivia.types`；模型支持 `to_dict()`、`to_json()` 和 Pydantic 标准方法。公开 `ClientEvent`、`ClientEventParam`、`DeviceEvent` 联合类型及各具体事件类，例如 `GPIOSetCompletedEvent`。编辑器可以根据 `event.type` 自动收窄 `result` 类型。

也可以发送完整命令模型或 TypedDict：

```python
from limivia.types import GPIOReadCommand

request_id = connection.send(GPIOReadCommand(params={"pin": 13}))
another_id = connection.send({"type": "state", "params": {}})
```

SDK 的事件名称由宿主端映射，设备上仍使用原有的 `v/id/op/params` 和 `event` 字段。[设备协议真源](../limivia-server/docs/protocol.md) 位于 server 仓库，编解码实现由 SDK 的 `limivia.protocol` 提供。

## 生命周期、错误与恢复

客户端参数：`timeout=6`（单命令秒数）、`connect_timeout=20`（打开设备和握手总秒数）、`event_queue_size=256`。每次扫描最长 12 秒，写入和关闭各最多等待 5 秒。命令超时预算包含写入时间。

- 每个客户端同一时刻管理一个连接或一次扫描；只能连接该客户端最近扫描到的候选。结束连接上下文后可重新扫描和连接。
- 请求 ID 在一个连接内递增；一个命令在途，最多八个命令等待发送。资源方法不会等待设备执行结果。
- `InvalidCommandError`、Pydantic `ValidationError` 和 `QueueFullError` 表示命令尚未提交；连接建立或握手失败会直接从上下文入口抛出异常。
- 已提交命令恰有一个终态；固件错误和超时通过事件报告。超时不等于未执行，SDK 不自动重试或重连。响应超时后可查询状态；半帧写入超时会关闭连接，避免下一条命令污染旧帧。
- 事件缓冲区满时终止连接并提供 `event_buffer_overflow`，保留已缓冲事件、刚完成的命令结果和所有待处理命令的失败信息。
- 退出连接上下文、客户端关闭或异常断线会取消收发任务并释放设备；同步客户端同时关闭后台线程。`AsyncLimivia` 必须始终在同一 asyncio 事件循环使用。
- 持续供电时，关闭连接不会停止板上 PWM、定时或 ADC 任务。显式发送停止命令并等待对应成功事件，才能确认任务已停止。

引脚、资源和电气边界最终由固件校验。GPIO 使用 3.3V 逻辑，ADC 输入遵循板卡限制；示例的 GPIO13 是该板型的 D5，不适用于其他板卡映射。

## 示例与验证

完整学习顺序、参数、接线及退出行为见 [示例指南](examples/README.md)。从只读查询开始，再运行资源示例（会实际操纵开发板）：

```bash
poetry run python -m examples.discover --kind usb
poetry run python -m examples.sync_state --kind usb
poetry run python -m examples.sync_gpio --kind ble
poetry run python -m examples.async_adc --kind usb --samples 10
```

资源示例正常结束或首次 Ctrl+C 时等待停止／释放确认；持续采样精确收集指定数量并检测无数据超时。设备断线或强制结束程序时可能留下板上任务，可重连后通过 `examples.sync_cleanup --pin <GPIO>` 显式释放。

开发验证：

```bash
poetry run pytest -q
poetry run ruff check src tests examples
poetry run mypy
poetry check --lock
poetry build
```

自动化测试采用模拟传输，覆盖全部资源、同步／异步一致性、事件类型、分片与错误、队列和生命周期。示例另已在 BLE 实机验证，并修复有限定时器自然结束后的释放问题；连接阶段的间歇断开及一次非终端 SIGINT 检查超时也已记录。USB 尚未实测。完整命令、结果与验证边界见 [验证记录](docs/verification.md)。

## 开源协议

采用 GNU Affero General Public License v3.0（AGPL-3.0-only），见 [LICENSE](LICENSE)。
