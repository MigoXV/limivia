# LIMIVIA SDK工程约定

- 中文沟通与README；Python3.12，通过Poetry和项目内.venv运行。
- SDK位于src/limivia，server是相邻独立仓库，依赖方向server→SDK。当前版本0.3.0a2；用户已明确授权使用.bashrc中的PyPI令牌发布该版本，令牌不得输出或写入文件。不推送Git，不改server或固件；后续版本发布仍需明确授权。
- 当前使用协议v3，USB/BLE/WS/MQTT共用核心，拒绝v1/v2，移除旧引脚命令。契约快照docs/protocol-v3.md注明固件来源；运行/构建不依赖相邻检出。后续跨仓库变更需核对各自版本。
- 公开同步Limivia/异步AsyncLimivia；普通业务接口等待设备确认后返回类型化结果，raw保留提交返回请求ID及类型化事件流。设备accepted与job终态分开，后台查询不泄漏为公开请求结果；独立订阅不得抢读业务结果。
- types保存Pydantic模型和TypedDict；公开事件联合类型按type收窄，发布py.typed；constants.py统一协议值、固定选项与板级引脚命名，_schema.py统一操作参数；事件Literal保留收窄并以完整性测试防漂移，能力与引脚政策由固件裁定。
- 同步门面共用持续运行的异步核心，不能每调用创建新循环。普通、管理与停止分别有界；半帧、过期会话、boot变化和缓冲溢出必须明确处理。
- 业务资源按需申请控制权，退出上下文等待释放；取消等待不等于取消设备作业，清理错误不掩盖原异常。命令不自动重试/重放、不隐式抢控制或停止设备；凭据不写日志。网络库不得自动重连后重发控制命令。
- CLI为limivia.commands.app/Typer；库导入不配置全局日志，示例导入和--help不访问硬件。
- 按改动范围选择验证；测试数据、文档或示例整理只运行相关离线测试与静态检查，不默认重新构建或操作实机。SDK运行代码、依赖或打包变更的完整验证命令：poetry run pytest -q、poetry run ruff check src tests examples、poetry run mypy、poetry check --lock、poetry build。
- 后续所有任务均按逻辑分批本地提交，可独立审阅的改动分别提交，不合成单个大提交，不自动推送。
- 测试用凭据在运行时临时生成，不提交固定假密码或完整的内嵌凭据URL；保留凭据脱敏与URL拒绝测试。
- 模拟设备、真实客户端loopback网络与单板实测分别记录。实机需明确端口及MAC，沿用已有目标授权；不得用内部回环或模拟broker冒充外部互通/物理测量。
