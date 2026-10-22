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

其他 Poetry 项目可运行 `poetry add --editable /path/to/limivia`。发布文件通过 `poetry build` 构建；本仓库尚未发布到 PyPI。

蓝牙依赖 Bleak，Linux 需要 BlueZ 和可访问的系统 D-Bus。USB 依赖 pySerial，需要串口权限。设备必须已安装 LIMIVIA 专用固件；安装 SDK 不会烧录设备。

## 同步调用

```python
from limivia import Limivia

with Limivia() as client:
    devices = client.devices.list(kind="ble")
    if not devices:
        raise RuntimeError("未发现设备")

    with client.devices.connect(kind="ble", target=devices[0].id) as connection:
        request_id = connection.gpio.set(pin=13, mode="output", level=1)

        for event in connection:
            if event.type == "gpio.set.completed" and event.request_id == request_id:
                print(event.result.pins)
                break
            if event.type == "command.failed" and event.request_id == request_id:
                raise RuntimeError(event.error.message)
            if event.type == "connection.closed":
                raise RuntimeError("设备已断开")
```

命令方法返回的整数仅表示已通过校验并进入发送队列。设备是否执行成功，以匹配请求 ID 的结果事件为准。连接自动发送并校验 `hello`，事件流首先包含这次握手结果。

## 异步事件流

```python
import asyncio

from limivia import AsyncLimivia


async def main():
    async with AsyncLimivia() as client:
        devices = await client.devices.list(kind="ble")
        if not devices:
            raise RuntimeError("未发现设备")

        async with client.devices.connect(kind="ble", target=devices[0].id) as connection:
            start_id = await connection.adc.start(pin=0, interval_ms=200)
            async for event in connection:
                if event.type == "adc.start.completed" and event.request_id == start_id:
                    print("首次采样", event.result.millivolts)
                elif event.type == "adc.sample":
                    print(event.data.millivolts)
                elif event.type == "command.failed":
                    print(event.request_id, event.error.code, event.error.message)
                elif event.type == "connection.closed":
                    break


asyncio.run(main())
```

两种客户端的资源名称、参数和事件类型相同；异步版本通过 `await` 提交命令，通过 `async for` 或 `await connection.recv()` 接收事件。同步版本的后台事件循环持续运行，调用者处理数据时也能接收 BLE 通知。

每个连接仅允许一个事件消费者，不能同时从两个任务调用 `recv()` 或迭代连接。应用需要多个订阅者时，应在自己的一个消费循环内分发。命令处理与事件消费独立运行，不要求先迭代才能发送命令。

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

可执行示例（会实际操纵已连接的开发板）：

```bash
poetry run python -m examples.sync_gpio --kind ble
poetry run python -m examples.async_adc --kind usb --samples 10
```

ADC 示例收满指定数量后提交停止命令并等待确认。提前中断程序可能留下板上采集任务，可重连后显式停止。

开发验证：

```bash
poetry run pytest -q
poetry run ruff check src tests examples
poetry run mypy
poetry check --lock
poetry build
```

测试采用模拟传输，覆盖全部资源、同步／异步一致性、事件类型、分片与错误、队列和生命周期。模拟验证不能替代真实 USB/BLE 实机验收。本次拆分未执行实机控制。

## 开源协议

采用 GNU Affero General Public License v3.0（AGPL-3.0-only），见 [LICENSE](LICENSE)。
