# JSON-RPC v3 源码示例

使用Python3.12和Poetry。先运行只读查询，再按任务选择资源示例。`--help`及导入均不访问设备；真正运行资源示例会改变板卡输出或文件。

```bash
poetry run python -m examples.discover --kind usb
poetry run python -m examples.async_profile --kind usb
poetry run python -m examples.sync_state --kind usb
poetry run python -m examples.async_state --kind usb
poetry run python -m examples.sync_gpio --kind usb --pin 13 --duration 1
poetry run python -m examples.sync_pwm --kind usb --frequency 1000 --duty 25
poetry run python -m examples.sync_timer --kind usb --high-ms 100 --low-ms 100 --count 2
poetry run python -m examples.sync_adc --kind usb --pin 0
poetry run python -m examples.async_adc --kind usb --pin 0 --samples 3 --interval-ms 100
poetry run python -m examples.async_events --kind usb --duration 2
poetry run python -m examples.sync_uart --kind usb
poetry run python -m examples.sync_storage --kind usb
poetry run python -m examples.sync_flow --kind usb
poetry run python -m examples.sync_cleanup --kind usb
```

USB/BLE扫描得到多台设备时必须`--target`明确选择；稳定by-id端口需解析到扫描到的原生USB端口。默认示例使用USB，库的旧默认连接方式仍为BLE。可用`LIMIVIA_TRANSPORT/LIMIVIA_TARGET`设置默认参数，`LIMIVIA_DEVICE_ID`校验预期MAC。

网络不扫描：

```bash
poetry run python -m examples.sync_state --kind ws --target ws://板卡IP/v3
LIMIVIA_DEVICE_ID=目标MAC poetry run python -m examples.sync_state --kind mqtt --target mqtts://broker.example:8883
```

MQTT另使用`LIMIVIA_MQTT_USERNAME/LIMIVIA_MQTT_PASSWORD`；TLS证书文件通过`LIMIVIA_CA_FILE/LIMIVIA_CERT_FILE/LIMIVIA_KEY_FILE`提供。SDK不会自动配置板上Wi-Fi或broker，也不自动发布/重连。不要在URL中嵌入凭据。

同步/异步示例分别展示同一资源生命周期：明确取得控制、等待open设备作业完成、操作、finally关闭并确认。采样通知本身没有样本，ADC示例查询events并解码8字节raw/mV记录；负mV表示未校准。连续ADC的原始type2格式与此不同，不能混用解码器。

UART示例用GPIO20/21内部回环，不要求外部器件；它不验证外部波形。存储示例用唯一文件名、SHA256分块写入/读回/删除；文件系统需已初始化，示例不自动格式化。流程示例上传默认手动、无外部输出的定义，启动并查询后停止/移除和删除文件。

PWM、GPIO和timer正常结束会关闭自有资源。流程完成本身不会清空输出；其他来源的实验也不会因SDK断开而停止。`sync_cleanup`显式停止全部实验并持久禁止自启，影响所有控制来源。首次中断会进入finally；断线、再次中断或驱动清理失败时，不能声称资源已释放，需重新核对设备再查询/停止。

状态示例携带revision读取全部页，遇到snapshot_expired最多重新取3次，只在整组成功后输出。不要同时启动多个recv或迭代器；后台心跳和作业查询无需单独消费者。

板级保护和能力以设备capabilities为准；GPIO0/1/3/4可改数字用途但先关闭ADC；GPIO13有板载LED负载。仅3.3V逻辑，不能把5V接入GPIO。没有仪器时不将状态、内部回环、浮空采样当作物理精度。

`discover` 识别当前镜像并聚合全部能力，不抢控制、不停止设备。`async_profile` 使用 available 选择 UART 内部回环或片内温度，等待设备作业终态，最后显式全局停止并确认清理/持久化；它会影响其他来源的实验。状态示例使用 state.snapshot()，包含 revision=0 时的跨页一致性检查。
