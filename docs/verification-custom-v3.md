# 历史自定义 v3 验证记录

以下记录对应 SDK 提交 396dfe9 及失效的 v/id/op 包络；不代表当前 JSON-RPC 兼容性。原构建产物和 SHA256 已保留，历史向量可从该提交查看。当前验收见 [verification.md](verification.md)。

# SDK 0.3.0a1 / 协议v3验证

日期：2026-10-23。本轮仅修改SDK，版本为0.3.0a1，已本地build，**未发布、未推送、未创建发布tag**，未读取发布令牌，未改server或固件。历史0.2.0a1及v1/v2记录保留于[verification-v2.md](verification-v2.md)。

## 实现与基线

- 分支沿用feature/protocol-v2-sdk；初始工作区干净，基线bf124a8，原151项pytest/Ruff/mypy通过。
- 16f656e：v3操作/类型/资源、自动作业跟踪、USB/BLE/WS/MQTT及测试。
- 04933dd：设备拒绝旧控制权后清除本地token。
- 545cbee：同步/异步示例迁移及类型/CLI检查。
- 8a28d96：连接参数与网络选项校验、心跳生命周期。
- 960d310：作业期限独立于慢查询RPC，保留查询所有权，最终SDK代码。
- 协议快照来源固件2198795，生产固件代码7c53341699007551de317dfa4e3601532bb9b73e；SDK构建/运行不读取相邻仓库。

## 自动化结果

|检查|结果|
|---|---|
|poetry run pytest -q|**387项通过**|
|poetry run ruff check src tests examples|通过|
|poetry run mypy|32个源文件通过，含公开API事件收窄及示例|
|poetry check --lock|通过|
|poetry build|wheel和sdist均生成|
|13个源码示例的导入/--help|通过，不访问硬件或配置库全局日志|
|独立Python3.12环境安装wheel|通过；隔离导入、CLI、版本、py.typed确认|
|wheel内全部limivia包文件对照源码|逐字节一致|

覆盖全部76个操作的编码及资源门面；从固件三profile最终USB验收整理140种真实响应形状，验证类型解码与RPC/通知桥接。其他用例覆盖严格JSON/Base64/帧边界、参数错误不泄露凭据、请求ID映射、受理与终态分离、结果过期、取消、8作业容量和停止入口、旧token不重绑定、慢查询下的作业期限、显式job.get不递归跟踪、心跳/旧通知/新boot、部分写入、单消费者、缓冲溢出、连接取消和同步线程释放。

首轮操作矩阵的两项失败是测试输入遗漏了MQTT/ESP-NOW必需payload，已修正测试。最后边界检查发现慢job.get会推迟作业期限，已修正并增加回归：到期只报告result_unknown，未取消在途查询future，后续显式查询可正常完成且原写命令只发送一次。首次日志保留，不能将后来的通过当作首次即通过。

## 本机网络测试

真实websockets15.0.1、paho-mqtt2.1.0客户端连接loopback套接字：WebSocket TEXT传输、MQTT3.1.1/5订阅确认后握手、保留回复过滤、控制发布QoS0/non-retain、有界队列与线程释放通过。使用临时CA/证书验证WSS/MQTTS信任成功与不信任拒绝。

MQTT服务端是测试侧最小报文夹具，设备响应由测试模型提供，**不是实际broker验收或板上无线链路验收**。没有对外部公开broker发送测试命令。

## 最终wheel的USB实测

明确目标：/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_E4:B0:63:CA:B4:78-if00，MAC e4:b0:63:ca:b4:78。保持pySerial默认DTR/RTS，不重新烧录或切换profile。

实际固件为bus / 0.3.0-dev / 协议3，ELF build_id：
8279ce3e84a2b6bb944185fead6483f3552bdcdd697ee6693e19d40c8ac81e45。

首轮源码、首轮wheel、最终wheel分别保留独立记录。最终用/tmp下独立Python3.12虚拟环境、`python -I`启动，确认导入路径在该环境site-packages，排除本地源码/编辑安装遮蔽。通过七组检查：

1. hello身份与全部28个能力页。
2. GPIO13资源打开/内部读回/类型化resource.get/关闭。
3. ADC0采样后关闭，同一引脚改数字输入再关闭。
4. UART内部回环，bytes输入与含NUL/0xff结果一致。
5. 1024字节显式缓存分块读回/删除。
6. SHA256文件分块上传、读回校验和删除。
7. 默认手动流程启动后断开6秒，重连boot不变、变量由1变2；停止、移除及删除定义文件。

最终outputs.stop作业确认完成，分页确认无资源，owner_endpoint=-1、自启抑制为true；测试创建的缓存/文件/流程已删除。SDK关闭本身不被当作板上停止确认。

这证明指定板的USB SDK路径、内部读回/回环和文件/流程生命周期，不证明外部器件互通、GPIO电压、ADC精度或UART波形。SDK测试过程中没有变更固件源码、分区或eFuse。

## 构建产物

Python要求：>=3.12,<3.13；源码和元数据版本均0.3.0a1。默认依赖仅为SDK客户端库，无FastAPI、server或本机file://依赖。

|产物|字节|SHA256|
|---|---:|---|
|dist/limivia-0.3.0a1-py3-none-any.whl|48027|4812827ce97b9c9bbf43503d99f3d5418029791fc51315f0ed3f081aea956d53|
|dist/limivia-0.3.0a1.tar.gz|45669|b2eda0ece62c1ec61a7c098775e72ca4a412c2f092aa6ad602960f56c2247c3b|

本地Git忽略目录artifacts保存：

- sdk-v3-build-final.json：最终代码提交、依赖、产物摘要与检查结果。
- sdk-v3-wheel-install.json：独立解释器、site-packages导入及CLI核验。
- sdk-v3-usb-first.json、sdk-v3-usb-wheel.json、sdk-v3-usb-wheel-final.json：分别记录源码/两次wheel实测事件和清理。
- build-first/与sdk-v3-build-manifest.json：重建前的首轮产物和摘要，不冒充最终包。
- verification-logs/：各轮测试、构建、安装与实机日志。

源码示例和验证文档由Git提供；wheel/sdist包含独立SDK实现及构建所需文件，不依赖相邻项目。旧0.2.0a1的dist文件未删除。

## 未验证边界

当前主机无可用BlueZ适配器及Wi-Fi接口。v3真实BLE、板上WebSocket、板端MQTT/TLS与真实broker、ESP-NOW第二节点均未实测。signal/iot的命令和结果模型由协议矩阵、固件真实帧及模拟测试覆盖，本轮未重烧录这两种镜像。其他操作系统、长期运行稳定性、外部总线器件、音频和仪器精度也未验证。

server保持原版本，不适用于此破坏性SDK升级；本轮没有安装新包到server环境。SDK0.3.0a1只有本地产物，没有发布PyPI。
