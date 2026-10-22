# LIMIVIA SDK 示例

这些脚本通过 USB／BLE 直接连接开发板，展示完整的扫描、连接、命令提交和事件确认过程。请从仓库根目录使用 `poetry run python -m examples.<模块>` 运行；examples 不随 SDK wheel 安装。

## 准备与选择设备

需要 Python 3.12、`poetry install`，以及已烧录 LIMIVIA 协议 v1 固件的合宙 CORE ESP32-C3 简约版。Linux BLE 需要 BlueZ 与 D-Bus 权限，USB 需要串口权限；运行前关闭占用设备的工作台或其他程序。

```bash
poetry run python -m examples.discover --kind ble
poetry run python -m examples.discover --kind usb
poetry run python -m examples.sync_state --kind usb --target /dev/ttyACM0
poetry run python -m examples.async_state --kind ble --target '扫描得到的设备 ID'
```

`--target` 必须匹配本次扫描结果。只有一台设备时可以省略；存在多台时会列出候选并退出，不默认操作第一台。所有连接示例支持 `LIMIVIA_TRANSPORT` 与 `LIMIVIA_TARGET` 环境变量，显式参数优先。命令行不会自动读取 `.env`；VS Code 调试配置会加载它。

## 阅读顺序

| 模块 | 学习内容 | 正常结束后的设备状态 |
|---|---|---|
| [discover](discover.py) | 扫描与设备 ID | 不建立连接 |
| [sync_state](sync_state.py) / [async_state](async_state.py) | 同步／异步对照；自动握手、显式 hello、状态查询 | 不改变引脚 |
| [sync_gpio](sync_gpio.py) | 输入／输出、上下拉、读取电平 | 目标引脚 idle |
| [sync_pwm](sync_pwm.py) | 固定 PWM、呼吸与停止 | 目标引脚 idle |
| [sync_adc](sync_adc.py) | 单次 ADC、校准状态、电压 | 目标引脚 idle |
| [sync_timer](sync_timer.py) | 板上闪烁／脉冲、状态查询与停止 | 目标引脚 idle |
| [async_adc](async_adc.py) | 有限次持续采样、无数据超时、取消清理 | 目标引脚 idle |
| [async_events](async_events.py) | 单消费者分发、命令模型／TypedDict、通知与状态刷新 | 不改变设备原有任务 |
| [sync_cleanup](sync_cleanup.py) | 单引脚释放、停止全部实验资源 | 指定范围内的实验引脚 idle |

每个脚本都支持 `--help`。`run(client, ...)` 保留具体 SDK 调用和事件循环，便于阅读及使用模拟后端测试；`main()` 负责 CLI 和客户端上下文。共享模块只处理命令行、日志与设备选择。

## GPIO、PWM 与定时器

以下命令使用默认 BLE 连接；都可追加 `--kind usb` 和 `--target`。

```bash
# GPIO13 对应本板 D5；默认输出高电平、读取后保持 5 秒，再释放。
poetry run python -m examples.sync_gpio --pin 13 --duration 5
# 输入示例：GPIO3 接按键到 GND，启用内部上拉；不要使用未说明的板卡映射。
poetry run python -m examples.sync_gpio --pin 3 --mode input --pull up
# 1 kHz、50% 占空比，默认观察 5 秒。
poetry run python -m examples.sync_pwm --frequency 1000 --duty 50
# 2 秒呼吸周期，duty 是亮度峰值对应的占空比。
poetry run python -m examples.sync_pwm --breath-ms 2000 --duration 6
# 设备端闪烁；count=0 表示持续，到观察时长后显式停止。
poetry run python -m examples.sync_timer --pattern blink --high-ms 500 --low-ms 500
# 单脉冲；pulse 忽略 low-ms/count 的作用，但参数仍需合法。
poetry run python -m examples.sync_timer --pattern pulse --high-ms 500 --duration 2
```

输出会包含启动确认、实际读取值或设备状态，最后出现“已确认停止／释放”。`timer.start.completed` 只代表任务已启动；有限闪烁或脉冲自然结束后会停在低电平 output，此时 `timer.stop()` 会被固件拒绝。示例对有限任务使用 `pin.release()`，同时兼容仍在运行和刚刚自然结束的情况；持续闪烁使用 `timer.stop()`。两种清理都等待确认并释放到 idle。`--duration` 是观察时长，到期可能截断尚未完成的有限任务。

GPIO 使用 3.3V 逻辑。GPIO13／D5 是本板用户 LED，GPIO12／D4 是系统 LED；外接 LED 需按板卡规格限流并共地，不能把 GPIO 当作负载电源。支持的引脚与能力以握手返回值为准。

## 单次 ADC

```bash
poetry run python -m examples.sync_adc --pin 0
```

ADC 支持 GPIO0／1／3／4。输入信号应与板卡共地，范围以板卡限制和 `hello.capabilities.adc_max_mv` 为准，不要将 5V 直接接入。输出包含原始值、校准状态、电压和设备运行时间；电压为 null 时显示“未校准／无电压值”，不会伪造 0 mV。单次读取也占用 ADC 引脚，示例收到结果后显式释放。

## 持续采样与事件分发

```bash
# 首次响应也算一个样本；只输出目标 GPIO 的 10 个样本，然后等待停止确认。
poetry run python -m examples.async_adc --kind usb --pin 0 --samples 10 --interval-ms 200
# 低频采样时，可调整连续无样本的超时；建议大于采样间隔并留有通信余量。
poetry run python -m examples.async_adc --pin 1 --samples 3 --interval-ms 10000 --idle-timeout 15
# 只读观察 10 秒；不会启动采样或改变引脚。
poetry run python -m examples.async_events --duration 10
```

持续采样的典型日志如下，数值仅作说明：

```text
INFO 样本 1/10：GPIO0 raw=1234，电压=900 mV，calibrated=True，设备时间=100 ms
...
INFO 样本 10/10：GPIO0 raw=1230，电压=897 mV，calibrated=True，设备时间=1900 ms
INFO ADC 已确认停止，GPIO0 已释放
```

`--idle-timeout` 默认 15 秒，从启动响应后计算；只有目标引脚的有效样本能重置计时。其他引脚、状态变更、无效帧不会延长等待。收足后仍会消费停止确认前的事件，但不继续打印样本。停止失败将以非零状态退出，不把“已提交停止”当作“已经停止”。

`async_events` 在一个循环中读取事件，分别交给展示和计数两个处理函数；处理函数不再调用 `recv()`。它使用 `HelloCommand` 模型和 `StateCommandParam` TypedDict 提交只读命令，通过 ID 关联结果，收到 `state.changed` 后获取完整状态；连续通知会合并，最多一个状态查询等待结果。`protocol.error` 和未知通知会被展示，而不会使观察程序直接崩溃。

没有设备状态变化或原有 ADC 流时，观察器只会输出握手、状态及计数，这是正常行为。观察到的原有任务归原程序管理，观察器退出时不会停止它们。`--duration` 是连接建立后的观察时长，到期会列出尚未返回的只读请求并关闭连接，不承诺这些查询已成功。

应用中的事件处理应保持简短。若需多个耗时订阅者，应自行设计有界队列和背压，仍只让一个任务读取连接；本示例刻意保留直接、同步分发以突出这一约束。同步 PWM／GPIO／timer 的保持阶段使用短时 `sleep`，由 SDK 后台线程接收事件；长时间阻塞或同时存在高频通知时，应改用持续消费事件的异步结构，避免事件缓冲溢出。

## 退出与恢复

资源示例先检查握手状态中的目标引脚必须为 idle；已占用时提示退出，避免覆盖其他程序留下的任务。检查并非跨 USB／BLE 客户端的原子锁，运行时应避免其他程序同时操作同一引脚。

正常结束和首次 Ctrl+C 会在连接关闭前尝试停止本次任务并等待对应请求 ID 的确认。参数校验或设备明确拒绝启动时不会清理目标引脚；启动超时且可能已执行时会尝试清理，但不会重试启动。清理失败会报告“停止状态未确认”，并保留原始错误。

异步 ADC 先退出主消费循环，再由清理任务接管事件流；不会让两个任务同时 `recv()`。清理在连接上下文内部完成，并屏蔽首次取消，最多等待 `2 × client.timeout + 1` 秒（默认 13 秒，容纳尚未完成的启动命令及停止命令）。SDK 随后的传输关闭另有最多 5 秒等待。同步示例的命令等待由 SDK 超时管理；连接失败会由上下文释放客户端资源。

```bash
# 在检查状态后，明确选择需要释放的引脚。
poetry run python -m examples.sync_cleanup --pin 13
# 停止全部实验输出、定时器与 ADC 流；会影响其他程序留下的任务。
poetry run python -m examples.sync_cleanup --all
```

`--pin` 与 `--all` 必须且只能选一个。持续供电时，单纯断开连接不会停止设备任务；断线、强制结束进程或再次 Ctrl+C 都可能使清理无法确认。恢复连接后先查询状态，再显式清理。普通完成退出码为 0，预期运行错误为 1，参数错误为 2，中断为 130。

## 验证边界

自动化测试使用真实 SDK 加模拟传输，验证命令和事件关联、资源释放、超时及中断处理，不访问真实 USB／BLE。另已在 `LIMIVIA-B47A` 上验证 BLE 示例及真实终端 Ctrl+C，并确认最终资源清空；连接阶段的间歇断开和一次非终端 SIGINT 检查超时仍保留为实测限制。USB、电气精度和物理时序未实测。模拟与实机结果分开记录。

```bash
poetry run pytest -q tests/test_examples_sync.py tests/test_examples_async.py tests/test_examples_cli.py
poetry run ruff check src tests examples
poetry run mypy
poetry check --lock
poetry build
```

模拟后端只存在于 tests，示例没有 `--mock` 入口，也不依赖测试代码。默认 mypy 已覆盖全部示例。完整验证结果见 [验证记录](../docs/verification.md)。
