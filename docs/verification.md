# JSON-RPC v3 / SDK 0.3.0a1 验证记录

日期：2026-10-23。本轮仅修改 SDK 源码、类型、测试、示例和文档。沿用 `feature/protocol-v2-sdk`，分批本地提交；没有发布、推送、发布 tag 或读取发布令牌，没有修改 server 或固件源码。镜像切换只使用现有固件 OTA 工具，没有重新分区、格式化或写 eFuse。

## 契约与构建来源

- SDK 实现/构建提交：`f2eba16ecc097336828502c1bccdc2c0320f3953`。验证文档在后续独立提交，不影响包内代码。
- 固件初次核查检出：`15e9e7f64fe9105d510e1669b6c76145d42f5ad6`；验收期间检出为 `f110c38ca370fe017fdf4c08e94632d2cbf52f84`，协议 C 实现、冻结镜像与 OTA 工具 SHA256 核对一致，没有切换或重置固件分支。
- 冻结镜像源码：`e0340006bd2c7bd6fb8345295299ce3085c45fe0`；上游验证工具提交：`64e312be720bcf7ae71e760ac9dde576dc349e1d`。
- 契约为 `protocol=3 / jsonrpc=2.0 / contract=limivia-v3-jsonrpc2`。完整上游快照、C 实现来源及文件 SHA256 见 [协议快照](protocol-v3.md) 和 `tests/vectors/contract-source.json`。
- 复制了12组独立请求案例和379条三镜像真实报文形状及来源元数据。运行、构建、常规测试不需要相邻固件检出。
- SDK Poetry 环境为 Python3.12.3；固件工具独立使用 `/home/migo/repositories/apps/limivia-esp32/.venv/bin/python` / Python3.10.20。

历史自定义 v3 的验证、原始构建摘要和旧行为保留于 [历史记录](verification-custom-v3.md)。相同的 0.3.0a1 版本号不能用于判断两种包络兼容。

## 软件与包验证

|检查|结果|
|---|---|
|`poetry run pytest -q`|691项通过|
|`poetry run ruff check src tests examples`|通过；另外检查了验收脚本|
|`poetry run mypy`|34个文件通过，含事件 discriminator、发现/快照及同步/异步 API 收窄|
|`poetry check --lock`|通过|
|`poetry build`|wheel / sdist 构建成功|
|示例导入和 `--help`|离线通过，不访问硬件、不由库配置全局日志|
|隔离 wheel 安装|通过；仓库外 Python3.12 环境，`python -I` 启动|
|包文件核对|wheel 内 18 个 SDK 文件与源码逐字节一致，含 `py.typed`|
|sdist|含独立 SDK、测试向量、测试、示例、契约快照与验收脚本|

覆盖 JSON-RPC 字符串/大整数/数值/null/缺失 ID、命名/位置参数、旧包络拒绝、严格 JSON/UTF-8、残帧/超长/缓冲溢出、错误整数码与附加信息、nonce 幂等与轮换、三种 ID/seq 的独立分配、乱序 batch、seq 窗口与耗尽轮换、心跳、后台 job 查询隐藏、停止原始 job、晚到旧 control 结果、boot/session 变化、丢通知后只读快照恢复、取消/结果过期/未知结果及同步持续事件循环。

四种传输共享该核心。真实 websockets15.0.1、paho-mqtt2.1.0 客户端的 loopback/TLS 测试通过，包括 MQTT3.1.1/5、订阅确认、non-retain/QoS0 控制发布、TLS 信任/拒绝和线程释放。MQTT 测试服务端是最小报文夹具，不能当作真实 broker 或板上无线互通。BLE 为传输适配模拟测试；主机 `bluetoothctl show` 返回 No default controller available。

## 同一 wheel 的三镜像 USB 验收

目标仅为 MAC `e4:b0:63:ca:b4:78`、串口 `/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_E4:B0:63:CA:B4:78-if00`。每次连接和 OTA 均核对身份；每个 bin 的 SHA256、应用描述中的 build_id 和对应 ELF SHA256 都与冻结 manifest 一致。

实际导入来自 `/tmp/limivia-jsonrpc-wheel-release-20261023/lib/python3.12/site-packages/limivia/__init__.py`，解释器为 `/tmp/limivia-jsonrpc-wheel-release-20261023/bin/python`。验收工作目录在 `/tmp`，排除了源码或编辑安装遮蔽。SDK/固件工具环境没有混用。GPIO10、GPIO12 均未用于 SDK 实验资源；GPIO12 仍是固件自己的状态 LED。

|profile|命名检查组数|结果|清理|精确 ELF build_id|
|---|---:|---|---|---|
|bus|14|通过|confirmed|`e4949bbcbcca673b3b1729e6cbb61dc3a1f67a54c373e55a8c21d1d43e7b1de4`|
|signal|11|通过|confirmed|`4087bd92c491c61650b5dab7f21caba582a88bf9d00156ba9a516913058195ed`|
|iot|16|通过|confirmed|`a6a933bb3d749ee03814c4085fb5e1e2882327c4b462a3da37a29e4191056d07`|

三镜像均通过身份及全部能力发现、available/不可用功能区分、GPIO内部读回、GPIO0/1/3/4 ADC与数字复用/冲突、六 PWM 通道共享定时器、timer/温度、二进制 buffer、原子文件、真实通知、混合直接结果/job 的 batch、batch 内停止屏障、RMT、手动流程和 SDK OTA status/begin/chunk/abort。

bus/iot 另外通过 UART内部回环与原始 read job 的协作取消、I²C主机/子资源及真实 NACK、SPI主机驱动事务、TWAI控制器生命周期；bus 通过 I²C/SPI从机预装与 pending 事务关闭。signal 通过连续 ADC type2 通道标签检查、I²S standard/TDM/PDM TX 和 Sigma-Delta 生命周期。没有把内部读回、浮空采样或驱动成功当作外部器件互通或物理精度。

IoT 通过 Wi-Fi扫描/显式维护AP开关、MQTT3.1.1/5非持久配置与停止、ESP-NOW启动/peer/停止。这里的 MQTT URI 是设备自身 loopback 的无 broker 地址，仅检验驱动生命周期，不证明 broker 连接；没有向其他节点发送 ESP-NOW 测试数据。

IoT light sleep 先保存 accepted job_id，显式关闭/恢复链路，在同一 boot 查询原 job 到 completed；没有重发 sleep。计划 deep sleep 验证新 boot 及流程检查点恢复，落盘记录严格为 before/x=7、after/x=8，然后清除流程和文件。

完整命名检查和原始收发报文见 `artifacts/sdk-jsonrpc-hardware-final/<profile>-sdk.json`。镜像激活由现有固件工具完成，单独保留 switch/restore OTA 证据；不以固件 verify 命令代替 SDK 验收。全程没有重做首次启动失败故障注入。

## 失败保留与修正

- `sdk-jsonrpc-hardware-01/`：三镜像均揭示 gpio.group.read 文档/实现差异。实际 C 实现需要资源对象数组，整数数组返回 -32602。门面保留整数 ID 输入并正确编码为对象；直接 send 使用对象数组，补独立预期报文与拒绝回归。
- `sdk-jsonrpc-hardware-02/`：暴露新发送器错误移除了可能需要控制的 resource.call/read token。修正为保留当前有效绑定，交由固件按资源类型裁定。
- `sdk-jsonrpc-bus-preflight/`：一条心跳回复未确认后，过于保守的 seq 记账阻塞后续查询。修正为以同优先级 FIFO 后续响应确认旧帧准入/丢弃，只释放 seq 记账；原 RPC 仍保留独立超时与未知结果。普通查询与写帧共享固件准入位置，改为串行；没有重发原写操作。
- 上述每轮均保留原始失败，最终恢复 bus 和清理均 confirmed。修正后的 bus 完整预检位于 `sdk-jsonrpc-bus-preflight-02/`；最终三镜像证据均由同一最终 wheel 产生，不将旧候选结果当作最终产物验收。

## 最终设备与清理

最终 profile：**bus**。build_id：`e4949bbcbcca673b3b1729e6cbb61dc3a1f67a54c373e55a8c21d1d43e7b1de4`；boot_id：`b5dffcbbb14a40df`。

最后一次原始 stop job：`8`，状态 completed，cleanup_faults=0、persist_error=0、autostart_inhibited=true。完整状态分页确认 resources=[]、owner_endpoint=-1、stopping=false。测试流程/文件已删除；4个 buffer 槽全部可分配，探测后全部删除。收尾显式重启后再验证，persisted_autostart_inhibited=true、inhibit_pending=false，NVS/FS/checkpoint/inhibit 错误均0，最终再次确认 stop。

证据为 `artifacts/sdk-jsonrpc-hardware-final/final-bus-sdk.json`、`summary.json`；全局 finally 的恢复故障注入单元测试也覆盖了原始失败保留、恢复尝试与恢复未确认时报 unknown。

## 本地产物与边界

|产物|字节|SHA256|
|---|---:|---|
|`dist/limivia-0.3.0a1-py3-none-any.whl`|59264|`94a6978483144d5897896077a14dae6f62e25e3626728617f3ebf67caf2f9279`|
|`dist/limivia-0.3.0a1.tar.gz`|137781|`9b69f2725792767ed9321286a304c8989e889e9b87429f1a97ce8fd66bd46ba5`|

构建清单：`artifacts/sdk-jsonrpc-build-final.json`；安装清单：`artifacts/sdk-jsonrpc-wheel-installed.json`。旧产物保存在 `artifacts/pre-jsonrpc-sdk/`，中间候选也分别保留摘要。构建/安装/软件测试日志没有覆盖首次失败。

真实 BLE、板上 WebSocket、SDK MQTT 到实际 broker/TLS、ESP-NOW第二节点、外部 I²C/SPI/RS485/CAN器件、外部音频/RMT输入、GPIO/ADC/PWM时序精度、功耗和冷上电均未验证。I²S本轮实测为TX，不能据此声称音频采集或原始PDM接收已经外部互通。OTA激活由固件工具验证，SDK commit 的完整镜像激活路径未单独执行。不同操作系统、长稳和外设所有参数组合也未验收。

这是本地开发候选交付，没有安装到 server、没有发布 PyPI。
