# LIMIVIA SDK 工程约定

- 使用中文沟通和维护 README；Python 3.12，通过 Poetry 和项目内 .venv 运行。
- SDK 位于 src/limivia，server 是相邻的 limivia-server 独立仓库；依赖方向为 server → SDK。
- 直连 USB/BLE，保持协议 v1；线协议真源为 ../limivia-server/docs/protocol.md。修改线协议需协同 server 与固件；SDK 内部事件名称不直接写入固件。
- 公开同步 Limivia 和异步 AsyncLimivia；命令仅提交并返回 ID，执行结果统一走类型化事件流。
- types 保存 Pydantic 模型与 TypedDict；公开联合类型应支持按 type 收窄，发布 py.typed。
- 同步门面复用异步核心和持续运行的事件循环；禁止每次方法调用创建新循环。
- 命令不得自动重试；保留部分写入、断线、超时、缓冲溢出和取消时的资源释放语义。
- CLI 位于 limivia.commands.app，使用 Typer；库导入时不配置全局日志。
- 默认验证：poetry run pytest -q、poetry run ruff check src tests examples、poetry run mypy、poetry check --lock、poetry build。
- 测试使用模拟设备，实机结果必须单独记录；按功能分批本地提交，不自动推送。
