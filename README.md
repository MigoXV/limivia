# LIMIVIA Python SDK

**0.3.0a3**，面向合宙 CORE ESP32-C3 简约版固件 **0.3.0-dev / JSON-RPC 2.0 / 协议 v3**。USB、BLE、WebSocket、MQTT 共用协议核心；同步 `Limivia` 和异步 `AsyncLimivia` 提供相同的业务语义。

普通方法等待设备确认后返回结果，失败抛类型化异常。SDK 负责请求关联、作业查询、控制权申请和资源释放；高级提交式接口保留在 `board.raw`。本次 Python API 有破坏性调整，见[迁移说明](docs/migration-v3.md)。开发版为 `0.3.0a3`；不要直接将本地 SDK 安装到尚未适配的 server 环境。

## 点亮 GPIO13

```python
from limivia import Level, Limivia, Pins, TransportKind

with Limivia.connect(kind=TransportKind.USB) as board:
    with board.gpio.output(Pins.LED, value=Level.HIGH) as led:
        input("灯已亮，按回车熄灭…")
        led.write(Level.LOW)
```

连接时仅有一个候选设备会自动选择；多个候选要求指定 `target`。进入资源上下文等待打开作业完成，`write()` 等待写入作业完成，退出等待资源释放。GPIO13 有板载 D5 LED 负载，引脚与镜像能力最终由固件裁定。

```python
from time import sleep
from limivia import Level, Limivia, Pins, TransportKind

with Limivia.connect(kind=TransportKind.USB) as board:
    with board.gpio.output(Pins.LED, value=Level.LOW) as led:
        for _ in range(5):
            led.write(Level.HIGH)
            sleep(0.5)
            led.write(Level.LOW)
            sleep(0.5)
```

## 异步调用

```python
import asyncio
from limivia import AsyncLimivia, Level, Pins, TransportKind

async def main():
    async with AsyncLimivia.connect(kind=TransportKind.USB) as board:
        async with board.gpio.output(Pins.LED, value=Level.LOW) as led:
            for _ in range(5):
                await led.write(Level.HIGH)
                await asyncio.sleep(0.5)
                await led.write(Level.LOW)
                await asyncio.sleep(0.5)

asyncio.run(main())
```

`await` 等待期间不阻塞事件循环；同步接口始终复用同一个后台异步循环。可以并发调用不同资源，同一资源的操作串行确认。取消等待不会释放在途操作持有的资源锁，关闭会等待该操作的确认结果。

## 安装与连接

开发使用 Python **3.12**、Poetry 和项目内 `.venv`：

```bash
poetry env use python3.12
poetry install
poetry run limivia scan --kind usb
poetry build
```

新建连接可传 `target`、`options`、`expected_device_id` 和客户端设置，例如 `timeout=6`、`connect_timeout=20`、`job_timeout=30`、`job_poll_interval=0.1`、`event_queue_size=256`。`timeout` 为单次 RPC 确认期限，`job_timeout` 为作业跟踪期限；资源清理有界，期限由这两项共同决定。

也可复用客户端实例进行扫描和顺序连接：

```python
from limivia import Limivia, TransportKind
with Limivia() as client:
    print(client.devices.list(kind=TransportKind.USB))
    with client.devices.connect(kind=TransportKind.USB, target="/dev/ttyACM0") as board:
        print(board.state.snapshot().to_json())
```

`Limivia.connect()` 默认 USB；保留的实例级 `client.devices.connect()` 默认 BLE。USB/BLE 省略目标时要求恰好一个扫描候选。稳定 USB by-id 别名必须解析到扫描得到的端口，最终由 hello 校验设备身份；可用 `expected_device_id` 核对 MAC。

网络不扫描，要求明确地址：

```python
from limivia import Limivia, TransportKind
from limivia.types import MQTTOptions, WebSocketOptions

ws = Limivia.connect(kind=TransportKind.WS, target="ws://192.168.1.20/v3")
mqtt = Limivia.connect(
    kind=TransportKind.MQTT, target="mqtts://broker.example:8883",
    options=MQTTOptions(device_id="e4:b0:63:ca:b4:78", ca_file="ca.pem"),
)
```

MQTT 支持 3.1.1/5.0、显式逻辑客户端名、独立用户名/密码和证书文件。WebSocket 支持 TLS 网关和证书选项。TLS 校验默认开启，URL 拒绝内嵌凭据；MQTT 默认生成新的逻辑客户端名。SDK 不自动重连或重发命令。

## 命名常量

常用名称可直接从根包导入：`Pins`、`Level`、`TransportKind`、`EventType`。其他分组统一位于 `limivia.constants`：

|用途|分组与示例|
|---|---|
|板级引脚与电平|`Pins.LED`、`Pins.GPIO0`、`Level.HIGH/LOW`|
|事件与通知|`EventType.JOB_COMPLETED`、`NotificationTopic.DATA`|
|协议操作与聚合查询|`OperationName.RESOURCE_OPEN`；`QueryName.STATE_SNAPSHOT` 仅用于 SDK 聚合，不是 wire 操作|
|外设与动作|`PeripheralKind.UART`、`ResourceAction.READ`|
|作业与资源状态|`JobState.COMPLETED`、`ResourceState.READY`；`ResourceState.FREE` 在资源查询中表现为资源不存在|
|传输与镜像|`TransportKind.USB`、`MQTTProtocol.V5`、`FirmwareProfile.BUS`|
|GPIO 配置|`GPIOMode.OUTPUT`、`Pull.UP`、`Edge.RISING`|
|UART/SPI/TWAI 配置|`UARTMode.RS485`、`Parity.NONE`、`SPIMode.MODE0`、`TWAIMode.NORMAL`|
|I²S 配置|`I2SMode.STANDARD`、`I2SRole.MASTER`、`I2SDirection.TX`|
|流程定义与状态|`FlowStep.DELAY`、`FlowCompare.EQ`、`FlowState.RUNNING`|
|电源配置|`SleepMode.LIGHT`、`ModemSleep.NONE`|
|错误诊断|`ErrorReason.CONTROL_BUSY`、`ErrorSource.DEVICE`|

事件判断也使用同一套名称，类型检查器可以据此收窄字段：

```python
from limivia import EventType
from limivia.types import DeviceEvent

def handle(event: DeviceEvent):
    if event.type == EventType.JOB_COMPLETED:
        print(event.job.result)
    elif event.type == EventType.JOB_FAILED:
        print(event.error.reason, event.job.driver_error)
```

这些分组提供 `Final` 命名常量，值仍是原生 `str/int`，不需要 `.value`，旧字符串和整数输入也兼容。`limivia.types` 中的 `Operation/ResourceKind/DeviceEvent` 等继续用于类型注解；命名常量不替代类型定义。参数名等 JSON 结构字段仍按契约表示，频率、时间和动态句柄等数值也保持其原有含义。

`Pins` 命名本板 GPIO0～GPIO21，并提供 `LED=GPIO13`（D5）、`STATUS_LED=GPIO12`（D4）、`BOOT_BUTTON=GPIO9`、`USB_DM=GPIO18`、`USB_DP=GPIO19`。系统、USB 和启动绑带保留脚有名称也不代表可以申请实验资源；实际能力与准入仍由设备决定。UART 的 GPIO20/21 是示例接线，不是固定 TX/RX 别名。LED 常量也不假定外接器件的有效电平。

已知错误与镜像名称可使用常量比较；未来固件返回的新错误原因、profile 等动态值仍保留原始字符串，不会因为缺少常量而丢弃诊断。

## 外设资源与返回值

|接口|返回值与确认语义|
|---|---|
|`board.gpio.output(Pins.LED, value=Level.LOW)` / `.input(0)`|GPIO 资源上下文；`read()` 返回电平，`write(value)` 成功返回 `None`|
|`board.pwm.open(Pins.LED, frequency=1000, duty=25)`|PWM 资源；`set_duty()`、`fade(duty, duration_ms=...)` 成功返回 `None`|
|`board.adc.open(Pins.GPIO0, attenuation=0, interval_ms=0)`|ADC 资源；`read()` 返回 `ADCSample(raw, millivolts)`；`events()` 返回已解码的采样列表|
|`board.uart.open(tx=Pins.GPIO20, rx=Pins.GPIO21, baud=115200)`|UART 资源；`write(bytes)` 返回确认写入字节数，`read(length)` 返回 `bytes`，另有 `drain/clear/errors/events/send_break`|
|`board.resources.open(kind, pins=..., config=..., parent=...)`|其他 v3 外设的统一资源对象；`call(action, **args)`、`status()` 返回 `OperationResult`|

工厂创建上下文时尚未访问设备。上下文以外，同步资源用 `resource.open()` 显式打开，异步资源用 `await resource.open()` 或 `await board.adc.open(Pins.GPIO0)`；随后显式 `close()`。资源对象隐藏协议 ID 与 `resource.call` 嵌套，`info` 仅供高级诊断。

UART 示例：

```python
from limivia import Limivia, Pins, TransportKind
with Limivia.connect(kind=TransportKind.USB) as board:
    with board.uart.open(tx=Pins.GPIO20, rx=Pins.GPIO21, loopback=True) as uart:
        uart.write(b"hello")
        uart.drain()
        print(uart.read(5))
```

UART `write()` 确认驱动接收写入，`drain()` 确认发送排空。PWM `fade()` 确认驱动启动渐变；当前固件没有渐变物理结束确认，SDK 不将作业完成解释为渐变已经结束。通知只提示可查询，外设 `events/read` 才消费驱动数据。

通用资源支持 `parent=父资源对象`、`controller=...`，覆盖 I²C、SPI、RMT、TWAI、I²S、连续 ADC、Sigma-Delta、timer 和温度等协议能力。`close(cascade=True)` 查询原资源树直到删除或 fault。释放失败保留占用，`recover()` 是显式重试清理，不会重新打开。句柄不能跨连接、boot 或资源实例复用。

普通操作按需申请控制权；其他端占用时抛 `ControlBusyError`。SDK 不隐式停止、抢占、释放他人的控制权，也不自动重放失败的写操作。退出板卡上下文按逆创建顺序释放本门面管理的资源；通过 `raw` 创建的资源由调用者负责。全局停止仍须显式 `board.outputs.stop()`，且会影响其他来源的实验。

## 查询、系统操作与通知

`board.identity` 提供握手身份；`board.discover()` 聚合全部能力页；`board.state.snapshot()` 读取一致快照；`state.retrieve()`、`capabilities.retrieve()`、`diagnostics.retrieve()` 返回各自模型。发现不申请控制、不停止输出；未知 profile 原样保留，运行时以 available 和固件准入为准。

存储、OTA、网络、流程、电源和系统操作保留现有命名空间，普通调用直接返回 `OperationResult`，完整数据位于 `.data`。产生设备作业的调用等待终态；直接 RPC 等待设备回复。`flow.start/stop` 的回复确认相应状态转换请求，不代表整个流程执行结束。睡眠或重启导致链路断开时不能合成成功。

```python
from limivia.constants import NotificationTopic
from limivia import AsyncLimivia, TransportKind
async with AsyncLimivia.connect(kind=TransportKind.USB) as board:
    async with board.notifications.subscribe(topics=[NotificationTopic.DATA, NotificationTopic.RESOURCE]) as updates:
        async for event in updates:
            print(event.to_json())
```

同步版本使用 `with` 和 `for`。每次订阅拥有独立有界队列，不与业务等待或其他订阅抢读。一个订阅只允许一个读取者；慢订阅抛 `SubscriptionOverflowError`，业务等待继续。设备通知仍是最佳努力，`notifications.gap` 提示缺口，可用状态/作业查询恢复。

## 显式作业、超时与错误

```python
from limivia.constants import OperationName
from limivia import Limivia, ResultUnknownError, TransportKind

with Limivia.connect(kind=TransportKind.USB) as board:
    job = board.jobs.submit({"type": OperationName.SYSTEM_TIME, "params": {}})
    try:
        result = job.wait(timeout=2)
    except ResultUnknownError:
        print(job.status().to_json())  # 显式查询，不重发原命令
```

异步版本对 `submit/status/cancel/wait` 使用 `await`。`submit()` 等设备受理后返回 `Job`；`wait()` 等原作业终态；`cancel()` 仅确认协作取消请求，仍需等待终态。多个等待者可等待同一作业。

超时不代表设备没有执行，取消等待不代表设备作业已取消，设备取消也不撤销已经发生的外部副作用。已知作业可通过 `board.jobs.get(job_id)` 显式恢复查询；需要核对原 boot，历史过期和结果过期都不能算成功。

`OperationError` 保留 `request_id/op/job_id/job/driver_error/error/event/may_have_executed/external_effect_possible`。常见异常包括 `DeviceRejectedError`、`ControlBusyError`、`ResourceConflictError`、`JobFailedError`、`JobCancelledError`、`ResultUnknownError` 和 `ResourceCleanupError`。清理错误额外保留 `resource_info`；底层原因在异常链中。已有用户异常或取消时，清理失败附加至原异常的 notes 与 `cleanup_errors`，不会替换原异常。

低层 `board.raw.send()/batch()/resource.*` 保留请求 ID 语义；`board.raw` 或独立 `board.raw.subscribe()` 提供类型化事件流。订阅仅接收创建后的事件，握手身份事件可作为初始事件提供，不回放此前的业务结果。

## 契约与验证

只接受 `protocol=3 / jsonrpc=2.0 / contract=limivia-v3-jsonrpc2`。拒绝 v1/v2 和历史自定义 v3 包络，不恢复旧引脚命令。版本号相同不能证明线协议兼容；运行与构建不依赖相邻固件检出。

[示例指南](examples/README.md)中的普通脚本直接展示 SDK 调用，默认连接唯一 USB 板卡，不带 CLI 参数：

```bash
poetry run python -m examples.peripherals.gpio
poetry run python -m examples.peripherals.gpio_blink
poetry run python -m examples.peripherals.async_gpio_blink
```

多传输、指定目标和凭据配置集中在 `examples.device.connect`：

```bash
poetry run python -m examples.device.connect --kind usb --target /dev/ttyACM0
poetry run python -m examples.device.connect --kind ws --target ws://板卡IP/v3
```

引脚等业务参数直接修改示例中的 SDK 调用，旧的示例 `--kind/--pin/--duration` 等选项已移除。另见[固件契约快照](docs/protocol-v3.md)、[迁移说明](docs/migration-v3.md)、[验证记录](docs/verification.md)。SDK 完整验证命令：

```bash
poetry run pytest -q
poetry run ruff check src tests examples
poetry run mypy
poetry check --lock
poetry build
```

本轮业务层重构使用模拟设备和真实客户端 loopback 测试，**没有进行实物验证**。历史单板记录不能替代新业务 API 的硬件验收，内部 UART 回环也不能作为外部器件互通或物理精度证据。

GNU Affero General Public License v3.0（AGPL-3.0-only），见 [LICENSE](LICENSE)。

### 0.3.0a3 通知修复

通知序号缺口与资源采样丢弃分开处理：连续 event_sequence 不因 data.available.dropped 累计计数而误报；真正缺失通知时，notifications.gap.dropped 返回缺失条数。保留原始采样丢弃信息，JSON-RPC v3 与 a2 业务接口兼容。
