# LIMIVIA 示例

普通示例直接展示 SDK 用法：连接设备、操作外设、退出时等待资源释放。同步示例不带前缀，异步示例使用 `async_` 前缀。默认连接唯一 USB 板卡；引脚、电平和固定选项使用 SDK 命名常量，频率、时长等参数直接写在代码里，便于阅读、复制和修改。

## 从点灯开始

[点灯](peripherals/gpio.py)的主体只有几行：

```python
from limivia import Level, Limivia, Pins, TransportKind

with Limivia.connect(kind=TransportKind.USB) as board:
    with board.gpio.output(Pins.LED, value=Level.HIGH) as led:
        input("灯已亮，按回车熄灭…")
        led.write(Level.LOW)
```

使用 Python3.12、Poetry 和项目内 `.venv`，从仓库根目录运行：

```bash
poetry run python -m examples.peripherals.gpio
poetry run python -m examples.peripherals.gpio_blink
poetry run python -m examples.peripherals.async_gpio_blink
```

闪烁示例执行五次，每次高、低电平各保持约 0.5 秒；每次写入都等待设备确认。异步示例以 `await` 和 `async with` 表达相同生命周期，不阻塞事件循环。

所有示例导入和 `--help` 都不访问硬件。连接与 USB 配网示例保留 CLI 参数；普通脚本的 `_common.run(main)` 只处理帮助、日志与退出码；连接、采样和资源操作都直接写在 `main()` 中。

`Pins.LED` 是本板 D5 / GPIO13，`Level.HIGH/LOW` 是逻辑电平；`TransportKind.USB` 是 USB 传输。这些常量的值仍是原生字符串或整数，不需要 `.value`。其余固定选项从 `limivia.constants` 导入，例如通知主题 `NotificationTopic.DATA`、外设种类 `PeripheralKind.TIMER` 和动作 `ResourceAction.READ`。

引脚名称不等于使用许可：`Pins.STATUS_LED`、`Pins.BOOT_BUTTON`、`Pins.USB_DM/USB_DP` 仍受固件保护。UART 示例使用 `Pins.GPIO20/21` 表达示例接线；频率、采样间隔和计数继续按 API 单位直接填写。

## 普通示例

|用途|模块|默认行为|
|---|---|---|
|能力发现|`examples.device.discover`|只读完整能力|
|同步状态|`examples.device.state`|只读一致快照|
|异步状态|`examples.device.async_state`|异步读取一致快照|
|通知订阅|`examples.device.async_events`|订阅两秒，退出时取消订阅|
|点灯|`examples.peripherals.gpio`|GPIO13 点亮，按回车熄灭|
|同步闪烁|`examples.peripherals.gpio_blink`|GPIO13 闪烁五次|
|异步闪烁|`examples.peripherals.async_gpio_blink`|同上，异步等待|
|PWM|`examples.peripherals.pwm`|GPIO13，1kHz、25% 占空比|
|ADC|`examples.peripherals.adc`|读取 GPIO0 的 raw/mV|
|周期 ADC|`examples.peripherals.async_adc`|每 100ms 采样，读取三条已解码记录|
|UART|`examples.peripherals.uart`|GPIO20/21 内部回环，读写字节|
|板上定时器|`examples.peripherals.timer`|GPIO13 定时翻转，等待资源释放|

统一用 `poetry run python -m 模块名` 运行，不再接受旧的 `--kind/--target/--pin/--duration` 等参数。需要修改时，直接编辑相应 SDK 调用。例如，多台 USB 设备时明确指定目标：

```python
from limivia import TransportKind

with Limivia.connect(kind=TransportKind.USB, target="/dev/ttyACM0") as board:
    ...
```

BLE 使用 `kind=TransportKind.BLE`；网络连接还需明确 URL 及对应配置，见下节。

## 多传输与凭据配置

[连接配置示例](device/connect.py)是专门保留 CLI 的入口，只读设备状态：

```bash
poetry run python -m examples.device.connect --help
poetry run python -m examples.device.connect --kind usb --target /dev/ttyACM0
poetry run python -m examples.device.connect --kind ble
poetry run python -m examples.device.connect --kind ws --target ws://板卡IP/v3
LIMIVIA_DEVICE_ID=目标MAC poetry run python -m examples.device.connect --kind mqtt --target mqtts://broker.example:8883
```

此入口支持 `LIMIVIA_TRANSPORT/LIMIVIA_TARGET` 默认参数和 `LIMIVIA_DEVICE_ID` 身份校验；MQTT 的账号/密码使用 `LIMIVIA_MQTT_USERNAME/LIMIVIA_MQTT_PASSWORD`。TLS 证书文件使用 `LIMIVIA_CA_FILE/LIMIVIA_CERT_FILE/LIMIVIA_KEY_FILE`，不把凭据嵌入 URL。

这些环境变量只由专门的连接示例读取。普通示例直接使用源码中的连接参数；可将连接配置示例中的相应 SDK 配置复制过去。

## USB 配网后通过 WebSocket 点灯

[完整示例](device/usb_wifi_websocket.py)适用于 SDK / 固件 0.3.0a7（r2），从 USB 开始完成 Wi-Fi 配置、等待 IP、释放 USB 会话，再通过 WebSocket 核对同一设备身份、点亮 D5 / GPIO13、读取确认电平，按回车熄灭并释放资源。

```bash
poetry run python -m examples.device.usb_wifi_websocket --help
poetry run python -m examples.device.usb_wifi_websocket
# 多块板卡时指定串口和预期设备 MAC：
poetry run python -m examples.device.usb_wifi_websocket --usb-target /dev/ttyACM0 --device-id 目标MAC
# 需要重启后自动连接时，显式将配置保存到板卡：
poetry run python -m examples.device.usb_wifi_websocket --persist
```

- 可通过 `LIMIVIA_USB_TARGET`、`LIMIVIA_DEVICE_ID` 设置串口与预期 MAC。
- 终端交互输入 2.4GHz Wi-Fi 名称与密码，密码隐藏输入，不放在代码或命令参数里。开放网络的密码可直接回车；示例不读取主机已保存密码。
- 默认 `persist=False`，只应用本次配网，不覆盖板卡已保存的网络配置；重启后会使用原来保存的配置。`--persist` 将本次凭据写入板卡，后续上电可自动连接；DHCP 地址可能变化，应核实当前 IP。
- USB 只用于首次配网或更换网络。已配好网时，可直接使用上节 `examples.device.connect --kind ws --target ws://板卡IP/v3`，无需每次先连 USB。示例关闭 USB 协议会话，USB 线可以保留供电；拔线后需另行供电。
- 主机必须能访问板卡所在网络；仅处于相同 Wi-Fi 名称不保证路由可达，访客网络或 AP 隔离可能阻止访问。
- 运行前先在工作台停止并释放 D5 实验，再断开设备，避免 USB 串口或控制令牌被占用。示例不抢占其他会话、不关闭其他资源，也不自动重试写操作。
- 配网提交后最多轮询 20 秒等待取得地址；等待时间不包括单次 SDK 调用耗时。失败即退出，不连接未确认地址，不自动重发配置。错误输出不展示凭据或局部变量；可用 SDK 类型化异常进一步定位。
- 正常结束只关闭本示例的 LED 资源和 WebSocket 会话，Wi-Fi 连接保留，方便接着从工作台连接。若网络意外中断，输出是否继续需查询设备，不能依据脚本退出推定已释放。

## 高级示例

|模块|展示内容|
|---|---|
|`examples.device.raw_events`|独立订阅 raw 事件，关联两个只读请求|
|`examples.workflows.async_profile`|按实际能力选择 UART 内部回环或片内温度|
|`examples.workflows.storage`|SHA256、分块上传、读回校验，以及删除/中止|
|`examples.workflows.flow`|上传流程定义、启动、查询、停止并移除|
|`examples.workflows.cleanup`|显式全局停止，并持久禁止流程自启|

高级示例同样不带 CLI 参数。存储与流程仍保留上传 ID、分块、提交和清理步骤，避免隐去真实生命周期；清理失败不能覆盖原始错误。文件系统需预先初始化，示例不自动格式化。`cleanup` 会影响其他控制来源，只有需要全局停止时才运行它。

普通示例只释放自己创建的资源，不隐式全局停止或抢占控制。超时不等于未执行，取消等待不等于设备作业已取消，清理失败也不能声称资源已释放。通知与业务等待独立分发，通知本身不包含完整采样数据。

## 验证边界

示例精简阶段运行相关离线测试；随后常量接入阶段执行 SDK 完整回归与本地构建。此前整理阶段没有连接单板或访问外部服务。模拟设备验证了普通资源示例的实际入口；高级上传编排另有清理失败注入测试。全部模块均检查离线导入和 `--help`。

GPIO13 带板载 LED 负载；UART 内部回环不能证明外部器件互通，ADC 未校准时 `millivolts=None`。板级保护、镜像能力和电气约束仍以实际固件与硬件为准。

### USB → Wi-Fi → WebSocket 示例验证（2026-10-26）

新增示例及现有示例相关离线测试 55 项通过，Ruff 与 mypy（50 个文件）通过，包含导入/帮助不访问设备、搜索后连接指定 USB、同设备身份校验参数传递、资源释放、配网超时不进入 WS、结果未知不重发与凭据不输出等检查。`--persist` 的参数传递通过模拟设备验证，实机使用 `persist=False`，没有为测试改写已保存网络配置。

随后在 B47A（e4:b0:63:ca:b4:78，bus；SDK/固件均 0.3.0a7、r2）运行了这份示例，测试工具只替代交互输入，USB/WS 连接和业务调用均使用真实 SDK：USB 配网取得地址后关闭 USB 会话，WS 点亮与独立读取均为 1，熄灭与独立读取均为 0，结束查询本次资源为零。未烧录或重启，未做物理波形测量。实机前置检查发现指定 USB 目标需先搜索，已补入示例并加入回归检查；首次失败及后续成功记录都保留。

测试前工作台已有 D5/GPIO13 低电平和 GPIO10 高电平实验，测试后已恢复同样的确认电平及工作台 WS 连接（ready、stale=false、snapshot_sync=current）。原始日志、测试工具与恢复记录保存在独立 limivia-server 工作区的忽略目录 `artifacts/usb-wifi-example/`，不是 SDK 运行依赖。本次为单轮功能验证，不代表长期稳定性；BLE/MQTT 未重测。
