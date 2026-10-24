# SDK 0.3.0a2 业务接口迁移

业务接口版本为 `0.3.0a2`。线协议保持 JSON-RPC v3，不改 server 或固件。需要同时核对 `protocol=3 / jsonrpc=2.0 / contract=limivia-v3-jsonrpc2`；历史自定义 v3 与 v1/v2 均不兼容。

## 使用命名常量

公开常量集中在 `limivia.constants`，常用的 `Pins/Level/TransportKind/EventType` 同时从根包导出。使用 `board.gpio.output(Pins.LED, value=Level.HIGH)`、`event.type == EventType.JOB_COMPLETED` 等写法，避免业务代码拼写协议值或混淆 GPIO 编号。

原有字符串、整数、JSON 值和事件 `Literal` discriminator 均保持兼容，不需要 `.value` 转换；`Operation`、`ResourceKind` 等类型别名继续用于类型注解，值常量分别为 `OperationName`、`PeripheralKind`。未知错误原因和 profile 仍保留原始值。

`Pins` 的板级别名依据现有固件契约：D5 LED 为 GPIO13，D4 状态灯为 GPIO12；BOOT、USB 和其他保留脚仍由固件限制。UART 示例的 GPIO20/21 不作为固定 TX/RX 别名。参数表仍由 `_schema.py` 管理，运行时协议值统一由 `constants.py` 命名。

## 从请求 ID 迁到业务结果

|旧用法|业务接口|
|---|---|
|扫描、选唯一设备、创建客户端和连接|`with Limivia.connect(kind="usb") as board:`|
|`connection.discover()` → 匹配事件|`board.discover()` → `DeviceDiscovery`|
|`connection.state.snapshot()` → 匹配事件|`board.state.snapshot()` → `StateSnapshot`|
|手动 acquire、open、提取 ID、call、finally close|`with board.gpio.output(13, value=1) as led:`，然后 `led.write(0)`|
|PWM open + resource.call(duty)|`with board.pwm.open(13, frequency=1000) as pwm:`，然后 `pwm.set_duty(25)`|
|ADC read + result 字段解析|`adc.read()` → `ADCSample`；`adc.events()` → 已解码采样列表|
|UART Base64 编解码|`uart.write(bytes)` → 字节数，`uart.read(length)` → `bytes`|
|通用外设资源 ID 与嵌套 call|`board.resources.open(kind, pins=..., config=...)` → 资源对象；`resource.call(action, **args)`|
|系统命令返回请求 ID|同名业务命名空间返回 `OperationResult`，数据为 `.data`|

异步版本通过 `await` 获得相同结果，资源用 `async with`；资源工厂本身不发送命令。显式打开可用同步 `.open()`、异步 `await .open()`，异步资源本身也可 `await`。

SDK 自动申请需要的控制权。其他端持有控制时抛 `ControlBusyError`，不会全局停止或隐式抢占。退出资源上下文等待关闭结果，退出板卡上下文清理其管理的资源；断连、fault 或超时会明确报告无法确认释放。若业务代码已有异常或取消，清理错误附加在原异常上。

## 保留提交式 raw 接口

需要原有协议处理方式时，将旧操作放到 `board.raw`：

```python
from limivia import TransportKind
with Limivia.connect(kind=TransportKind.USB) as board:
    raw = board.raw
    request_id = raw.state.retrieve(page=0)
    for event in raw:
        if event.type == "state.completed" and event.request_id == request_id:
            print(event.result.to_json())
            break
```

`raw.send/hello/discover/batch/resource/job/control` 等仍返回请求 ID；作业仍先有 `command.accepted`，再有终态事件。`raw` 不自动申请控制，也不负责关闭其创建的设备资源。原始普通/管理/停止通道、seq 窗口、帧上限、半帧处置和禁止写操作重放的规则保持。

业务方法不再直接提供 `send/recv/batch`、裸 `resource` 或裸 `job` 命名空间。显式作业使用 `board.jobs.submit/get` 与 `Job.status/cancel/wait`。`submit` 等待设备受理，`wait` 才等待执行结果；超时或取消等待不自动发送设备取消。

每个 raw 订阅各有一个消费者；可用 `with raw.subscribe() as events:` / `async with raw.subscribe()` 创建独立副本。订阅需要在提交前创建，除初始握手事件外不回放历史结果。慢订阅现在显式报自身溢出，其他订阅与业务等待继续；不再因为某个消费者不读取而终止整个业务连接。

## 通知与结果语义

通知改用 `board.notifications.subscribe(topics=[...])`；同步 `with/for`，异步 `async with/async for`。SDK 合并设备订阅，独立分发给各消费者，业务 Future 不读取用户队列。通知仍是可查询的最佳努力提示，不承载完整外设数据；丢失后用状态、作业及资源查询恢复。

完成的含义由固件契约决定：GPIO 写作业完成确认驱动已写入；UART 写入字节数与发送排空分开；PWM fade 仅确认渐变启动；flow.start/stop 不代表整个流程运行结束；级联关闭需要确认原资源树释放；停止需要确认清理及持久化。SDK 不将本地入队或设备 accepted 当成完成。

请求 ID、wire ID、seq 和 job_id 仍独立；后台心跳及 job.get 不产生公开请求结果。boot 变化使旧句柄失效，显式重新连接不能重放写事务。已知 job 可在核对原 boot 后通过新连接的 `jobs.get(job_id)` 查询，结果过期或历史淘汰都抛未知结果异常。

历史线协议迁移还包括：JSON-RPC args/context 分离、错误整数码与 `error.reason/data`、旧引脚命令移除。`gpio.group.read` 的真实 wire 参数为资源对象数组；`raw.gpio.group_read(resources=[id,...])` 继续负责该映射。完整来源见[冻结契约](protocol-v3.md)。

server 的后续适配需要单独核对自身版本；本轮不改动其代码或安装环境。本轮没有对新业务 API 做单板验收。
