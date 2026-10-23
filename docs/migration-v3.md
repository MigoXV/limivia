# 迁移到 JSON-RPC v3 / SDK 0.3.0a1

此次保持开发版版本号，但线协议发生破坏性变化。历史 0.3.0a1 的自定义包络不能连接当前固件，也不能以 protocol=3 判定兼容；必须匹配 `jsonrpc=2.0` 和 `contract=limivia-v3-jsonrpc2`。没有旧包络兼容或降级。server 保持原版本，本轮不改动其环境。

## 当前版本的调用变化

- 请求改为 jsonrpc/id/method/params；业务参数位于 params.args，会话和 seq 位于 params.context。位置参数为 [context,args]。
- SDK 请求 ID、wire ID、seq 独立，job_id 用于设备异步作业。内部查询不占公开请求 ID，不产生公开查询结果。
- `error.code` 从业务字符串改为整数或 None；原字符串判断改用 `error.reason`，完整附加信息在 `error.data`。本地错误 source=sdk、code=None。
- `connection.identity` 提供类型化身份；`connection.discover()` 返回请求 ID，通过 discovery.completed 提供完整能力和原始分页。发现复用已有会话，不撤权。
- `connection.batch([...])` 返回每项请求 ID 列表；应用的单个事件消费者必须保存乱序结果，不能依次等待一个 ID 时丢弃其他 ID 的事件。
- `connection.state.snapshot()` 代替应用自己拼接分页；snapshot_expired 或跨页 revision/epoch 变化时最多采集三次。
- stop 的 accepted 不是完成；只有原始 job 的清理与持久化确认后才有成功事件。晚到的旧控制结果不恢复当前 token。
- 新 boot 失效旧 job/资源/能力。相同 boot 的显式断线恢复可按已知 job 查询，例如 light sleep；不重发睡眠或其他写事务。

`gpio.group_read(resources=[id,...])` 门面保留整数 ID 输入，但 wire args 使用资源对象数组。直接 send 应传 `{"resources":[{"resource":id}]}`；上游协议文档的整数数组描述与当前 C 实现不符，已用真实设备拒绝和成功路径核实。

## 资源与作业

|旧接口|v3操作|
|---|---|
|gpio.set/read(pin)|resource.open(kind=GPIO,pins/config)→resource.call(resource,action,args)→close|
|pwm.set/stop(pin)|open(kind=pwm)→call(duty/fade)→close|
|adc.read/start/stop(pin)|open(kind=adc,interval_ms)→call(read/events)→close|
|timer.start/stop(pin)|open(kind=timer,config)→查询→close|
|pin.release/recover(pin)|resource.close/recover(resource)，父资源有子资源时显式cascade|
|单页state/capabilities|显式page，状态后续页携带revision|
|旧adc.sample通知|订阅data.available提示，再call(events/read)读取有界队列|
|outputs.stop成功快照|command.accepted→job.completed；确认持久抑制与清理结果|

参数kind使用协议小写字符串。资源ID、job_id、buffer_id、flow_id仅在对应boot内有效；新boot应重新发现状态，不沿用旧句柄。不从引脚号猜资源ID。

提交仍返回SDK请求ID；另有 wire ID、独立防重复 seq 与设备 job_id。`command.accepted`只表示设备受理，SDK自动查询后才有job.completed/failed/cancelled。同步读取类响应仍有专用事件，其他直接RPC成功为command.completed并使用op区分。

`job.get/cancel`是显式查询/取消请求，返回command.completed/result，不会因为结果自身含job_id再建立新跟踪器。flow.start/stop和cascade关闭返回的状态按协议解释，不能把RPC成功当作流程/整树已结束。

## 连接与恢复

保留同步/异步门面及单消费者事件流。USB/BLE继续扫描并明确选择，新增WS/MQTT显式URL及类型化选项。MQTTOptions必须提供目标device_id，库为每次连接生成新逻辑客户端名。网络依赖默认安装，无需extras。

任何写操作超时、断线或结果过期都不自动重试。SDK失败携带source、may_have_executed及已知job_id；设备失败保留driver_error与external_effect_possible。关闭连接不停止设备实验。需要紧急全局停止时走独立outputs.stop入口，随后重新获取控制权。

旧event_to_wire已更新为v3真实RPC/通知映射；SDK查询得到的job终态返回None，不伪造第二条设备RPC响应。服务端以后适配时需显式桥接SDK事件，不能继续假设每个请求只有一条旧式completed事件。

完整契约见[来源注明的快照](protocol-v3.md)，可运行流程见[示例指南](../examples/README.md)。
