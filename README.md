# LIMIVIA Python SDK

**0.3.0a1** 面向合宙 CORE ESP32-C3 简约版固件 **0.3.0-dev / JSON-RPC 2.0 / 业务协议 v3**，支持 USB、BLE、WebSocket、MQTT。同步 `Limivia` 和异步 `AsyncLimivia` 共用核心：命令提交返回请求 ID，执行结果统一通过类型化事件流交付。

契约标识必须为 `limivia-v3-jsonrpc2`，相同的版本号不代表兼容。此前 0.3.0a1 的自定义 `v/id/op/ok/event` 包络已经失效；本次直接替换，不保留兼容层。

本版是破坏性升级：拒绝 v1/v2 固件，移除旧 `gpio.set/pwm.set/adc.start/pin.release` 等接口。三种固件镜像的全部 **76 个操作**均有命令门面，外设通过资源 ID 操作。server 尚未适配；不要将本地 SDK 安装到旧 server 环境。本轮只构建，**尚未发布 0.3.0a1**。

## 安装与构建

源码开发使用 Python **3.12**、Poetry、项目内 `.venv`：

```bash
poetry env use python3.12
poetry install
poetry run limivia scan --kind usb
poetry build
# 构建后可在独立环境安装本地wheel：
python3.12 -m pip install dist/limivia-0.3.0a1-py3-none-any.whl
```

默认依赖 Pydantic、AnyIO、pySerial、Bleak、websockets、paho-mqtt、Typer，安装后四种传输均可用。SDK 不包含工作台、FastAPI或固件，也不会自动烧录、格式化或发布软件包。

## 连接

USB/BLE 先扫描，再选取扫描结果；USB 的稳定 by-id 别名必须解析到已扫描端口。VID/PID只筛选候选，最终由 v3 hello 校验板型。连接可通过 `expected_device_id` 核对目标 MAC。

```python
from limivia import Limivia

with Limivia() as client:
    devices = client.devices.list(kind="usb")
    if len(devices) != 1:
        raise RuntimeError("请明确选择目标设备")
    with client.devices.connect(kind="usb", target=devices[0].id) as connection:
        request_id = connection.state.retrieve(page=0)
        for event in connection:
            if event.type == "state.completed" and event.request_id == request_id:
                print(event.result.to_json())
                break
```

异步门面对应 `async with AsyncLimivia()`、`await connection.state.retrieve(...)`、`async for event in connection`。同步门面在生命周期内持续运行同一个后台事件循环，不为每次调用创建循环。

网络连接不扫描，显式提供地址。板上 WebSocket 的地址为 `ws://板卡IP/v3`；`wss://` 可用于配置了 TLS 的网关。MQTT传输需要固件已配置连接同一broker，并明确目标MAC：

```python
from limivia.types import MQTTOptions, WebSocketOptions

# 以下均在已创建的client内使用连接上下文：
manager = client.devices.connect(kind="ws", target="ws://192.168.1.20/v3")
manager = client.devices.connect(
    kind="mqtt", target="mqtts://broker.example:8883",
    options=MQTTOptions(device_id="e4:b0:63:ca:b4:78", ca_file="ca.pem"),
)
```

`MQTTOptions`另支持`protocol="3.1.1"/"5.0"`、`logical_client`、`username/password`和客户端证书/私钥文件；`WebSocketOptions`支持CA和客户端证书。TLS验证默认开启，URL不允许内嵌账号密码。MQTT默认使用每次新生成的逻辑客户端名；明确复用名字时需等待固件旧会话过期。库不自动重连。

## 设备发现与镜像

连接握手后 `connection.identity` 提供 board、device_id、firmware、protocol、jsonrpc、contract、profile、完整 ELF build_id、boot_id 和设备容量。未知 profile 原样保留，不默认按 bus 处理。

```python
request_id = connection.discover()
for event in connection:
    if event.type == "discovery.completed" and event.request_id == request_id:
        print(event.result.identity.profile)
        available = [r.kind for r in event.result.resources if r.available]
        print(available)
        break
```

`discover()` 读取全部能力分页，聚合引脚、资源、动作、配置/动作参数范围和系统操作；`raw_pages` 保留原始描述。发现复用有效会话，不申请控制或停止输出。`refresh=True` 显式重读；身份、boot、build、profile 或 contract 变化后旧缓存失效。能力不代表资源预留，实际使用前做 preflight，并处理 busy、pin_conflict、feature_unavailable 与驱动失败。

一个包提供 bus、signal、iot 的全部公开接口。运行时使用设备的 available 字段，不能仅凭 profile 字符串推断能力。GPIO0/1/3/4 同时支持发现描述中的数字和 ADC 用途，互斥由固件裁定。支持接口不表示自动识别接入的器件型号。

## 命令与作业

`connection.control.acquire()`的结果确认后，才提交需要控制权的操作。SDK不隐式抢占控制。任何有效会话可调用`connection.outputs.stop()`；停止会撤销控制并持久抑制流程自启，修改前需重新申请控制。

```python
# 已连接且已取得控制权后：
request_id = connection.resource.open(
    kind="uart", pins={"tx": 20, "rx": 21},
    config={"baud": 115200, "loopback": True},
)
for event in connection:
    if getattr(event, "request_id", None) != request_id:
        continue
    if event.type == "command.accepted":
        print("设备已受理", event.job.job_id)
    elif event.type == "job.completed":
        resource_id = event.job.resource
        break
    elif event.type in ("job.failed", "command.failed", "job.cancelled"):
        raise RuntimeError(event.to_json())
# 使用resource.call读写，最后resource.close确认释放。
```

方法返回的整数只说明SDK本地入队成功。异步设备作业经历`command.accepted`，随后SDK自动查询`job.get`并交付一次终态；内部查询与心跳不会混入公开事件流。`job.finished`通知只是提示，不能代替作业查询。普通RPC成功结果通过`command.completed`或专用类型交付；`hello/state/capabilities/resource.get/diagnostics`分别有类型化result。

|门面|用途|
|---|---|
|`resource.open/preflight/get/call/close/recover`|GPIO、PWM、ADC、UART、I²C/SPI主从、TWAI、RMT、I²S、SDM、timer、温度；完整kind/config/action见能力页|
|`capabilities.retrieve`、`state.retrieve`、`mux.query/preflight`|能力、矩阵、资源分页；状态后续页携带首个revision|
|`job.get/cancel`|显式查询或请求协作取消；cancel受理不等于已取消|
|`buffer.create/write/read/delete`|显式分块二进制缓存|
|`events.subscribe/unsubscribe`|job/resource/flow/data有界提示通知|
|`storage.*`、`ota.*`|原子文件、JSONL、写入非活动OTA槽；不隐式格式化|
|`flow.*`|加载、启动、暂停、停止、移除声明式流程|
|`wifi.*`、`mqtt.*`、`espnow.*`、`power.*`、`system.*`|板上网络、低功耗与系统服务；与SDK自身的连接传输区分|
|`gpio.group_read/group_write`、`rmt.sync`|组操作与同步发射|

所有结果保留`op/request_id/boot_id/session`；作业结果另有`job_id/resource/action/driver_error/result_expired/external_effect_possible`。外设结果以原始JSON对象保留，已知数据可用`BinaryResult.model_validate(result).to_bytes()`或`FlowInfo.model_validate(result)`等模型解释。输入支持`ClientEvent`及`{"type": ..., "params": ...}`字典，未知操作/字段会在发送前拒绝。

`resource.close(cascade=True)`返回的`state="closing"`、`flow.start`返回的流程状态等仍是协议原样状态，须继续查询；RPC成功并不宣称整个资源树或流程已经结束。

## JSON-RPC、批量与错误

请求为 `{jsonrpc:"2.0",id,method,params:{context,args}}`。context 包含 session、独立分配的 seq 和必要的 control；hello 使用 client_nonce。协议编解码也支持位置参数 `[context,args]`，字符串、数值、显式 null ID 与缺失 ID 通知。公开提交始终携带自动生成的 wire ID；无法关联的 `id:null` 错误交付 `rpc.error`，不绑定某个请求。

SDK 请求 ID、wire ID、seq 和 job_id 各有不同用途。所有 seq 在持续运行的核心实际发送时分配，内部心跳/查询不占公开请求 ID。相同 nonce 的显式 hello 保持有效会话；不同 nonce 撤销旧控制绑定。seq 耗尽时排空已发送请求后以新 nonce 轮换，不重放写命令或重新申请控制。

```python
ids = connection.batch([
    {"type": "state", "params": {"page": 0}},
    {"type": "diagnostics", "params": {}},
])
# 单消费者保存每项事件，使用 request_id 在 ids 中关联；结果可能乱序。
```

`gpio.group_read(resources=[id,...])` 门面会编码为资源对象数组；直接 send 的 `gpio.group.read` 使用 `{"resources":[{"resource":id}]}`，这是当前 C 实现和实机确认的形状。

batch 返回与输入对应的 SDK 请求 ID 列表，每项沿用原有结果和 job 事件。数量以设备 batch_max 为准，当前最多8项；整批共享1024字节请求上限。hello 必须单独发送，控制申请及依赖结果的操作应分开提交。batch 不保证执行顺序、事务或回滚，普通写调用不会自动合并。

错误的 `error.code` 为 JSON-RPC 整数，业务名称使用 `error.reason`，附加字段保留在 `error.data`。SDK 本地错误的 code 为 None，source 为 sdk。`response_capacity` 可能已有外部副作用，保留 external_effect_possible 与已知 job_id，不能重发原写事务。作业驱动错误保留在 job.driver_error/error_code；它不是第二条 RPC 错误响应。

停止具有独立通道，受理后旧控制绑定不可恢复。晚到的旧 acquire/batch 响应仍可交付原请求事件，但不会重新绑定 token。只有原始 stop job completed 且 cleanup_faults/persist_error 为0、自启抑制确认后，SDK 才交付停止成功。

## 二进制、分页和故障恢复

`data`可传`bytes`，SDK转换为规范Base64。请求仍受**1024字节**上限约束；大数据先显式写入buffer，再通过buffer_id提交，或使用storage/OTA的chunk接口，建议每块384字节。SDK不把一个UART/SPI/I²C事务自动拆成多笔写入。

使用 `connection.state.snapshot()` 取得类型化一致快照，结果为 `state.snapshot.completed`；按设备页数读取并检查 revision/epoch，最多采集三次。也可保留逐页 retrieve 接口。通知丢失交付 `notifications.gap`，原始通知保留序号和 dropped；通过状态、资源和 job 查询恢复。

SDK默认RPC期限6秒，作业跟踪期限30秒，查询间隔100ms，普通待受理/跟踪作业上限取 min(8, job_history-1)；停止有独立通道。可通过客户端构造参数`timeout/job_timeout/job_poll_interval/event_queue_size`调整。设备还受自身资源、作业历史、DMA和内存限制，最终由固件准入。

设备普通查询和写帧共用普通准入位置，SDK 在该位置串行发送；心跳、作业查询与停止另有有界通道。同优先级后续有效响应仅释放已确认准入/丢弃的序号记账，不替丢失回复合成成功。其他有效 RPC 持续确认同一会话时，单条心跳回复丢失不会被误报为租约失效。

写命令**不自动重试或重放**。未知执行结果交付`command.failed`和`may_have_executed=true`，已知job_id会保留，调用者可显式查询。job终态与结果过期分别报告，不把查询丢失当成驱动失败。boot变化、无效会话、半帧写入及接收溢出会关闭当前连接，需重新握手；重启/深睡可能在受理后断开，SDK不合成完成事件。

每个连接只允许一个事件消费者。通知丢失可查询恢复；SDK事件队列溢出会明确终止连接。关闭SDK连接只释放主机资源，**不会自动停止板上实验**；完整示例用finally关闭自有资源，需要全局停止时显式调用outputs.stop。

## 示例、验证与迁移

[示例指南](examples/README.md)、[v3契约快照](docs/protocol-v3.md)、[迁移说明](docs/migration-v3.md)、[验证记录](docs/verification.md)。例如：

```bash
poetry run python -m examples.device.discover --kind usb
poetry run python -m examples.workflows.async_profile --kind usb
poetry run python -m examples.device.sync_state --kind usb
poetry run python -m examples.peripherals.sync_uart --kind usb --target /dev/ttyACM0
poetry run python -m examples.workflows.sync_storage --kind usb
poetry run python -m examples.workflows.sync_flow --kind usb
poetry run python -m examples.peripherals.async_adc --kind usb --samples 3
```

这些是源码示例，资源示例会实际操纵目标板；不作为wheel内置模块。WS/MQTT同样使用`--kind/--target`，凭据通过环境变量提供，不通过命令行打印。

```bash
poetry run pytest -q
poetry run ruff check src tests examples
poetry run mypy
poetry check --lock
poetry build
```

单板USB、测试侧网络夹具和真实无线互通分别记录。BLE和实际板上WS/MQTT/TLS尚缺无线夹具，不能将本机模拟设备或历史v1/v2验收当作v3无线实测。

## 开源协议

GNU Affero General Public License v3.0（AGPL-3.0-only），见[LICENSE](LICENSE)。
