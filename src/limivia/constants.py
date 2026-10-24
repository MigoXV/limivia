"""公开命名常量，值保持为原生 str/int，兼容严格 JSON-RPC 校验。

板型 luatos-esp32c3-usb；来源固件 f110c38ca370fe017fdf4c08e94632d2cbf52f84，
冻结协议见 docs/protocol-v3.md 与 docs/peripheral-matrix.md。
常量仅命名协议值和板级标识，不复制引脚准入或容量政策。
"""

from typing import Final


class EventType:
    """SDK 公开事件类型，包含设备通知与 SDK 聚合/错误事件。"""

    HELLO_COMPLETED: Final = "hello.completed"
    STATE_COMPLETED: Final = "state.completed"
    CAPABILITIES_COMPLETED: Final = "capabilities.completed"
    RESOURCE_GET_COMPLETED: Final = "resource.get.completed"
    DIAGNOSTICS_COMPLETED: Final = "diagnostics.completed"
    COMMAND_COMPLETED: Final = "command.completed"
    COMMAND_ACCEPTED: Final = "command.accepted"
    JOB_COMPLETED: Final = "job.completed"
    JOB_FAILED: Final = "job.failed"
    JOB_CANCELLED: Final = "job.cancelled"
    COMMAND_FAILED: Final = "command.failed"
    JOB_FINISHED: Final = "job.finished"
    STATE_CHANGED: Final = "state.changed"
    DATA_AVAILABLE: Final = "data.available"
    PROTOCOL_ERROR: Final = "protocol.error"
    UNKNOWN: Final = "unknown"
    CONNECTION_CLOSED: Final = "connection.closed"
    DISCOVERY_COMPLETED: Final = "discovery.completed"
    STATE_SNAPSHOT_COMPLETED: Final = "state.snapshot.completed"
    RPC_ERROR: Final = "rpc.error"
    NOTIFICATIONS_GAP: Final = "notifications.gap"


class OperationName:
    """JSON-RPC v3 的 76 个 wire 操作；参数定义仍由 _schema 管理。"""

    HELLO: Final = "hello"
    SESSION_PING: Final = "session.ping"
    EVENT_SUBSCRIBE: Final = "event.subscribe"
    EVENT_UNSUBSCRIBE: Final = "event.unsubscribe"
    CONTROL_ACQUIRE: Final = "control.acquire"
    CONTROL_RELEASE: Final = "control.release"
    OUTPUTS_STOP: Final = "outputs.stop"
    CAPABILITIES: Final = "capabilities"
    STATE: Final = "state"
    DIAGNOSTICS: Final = "diagnostics"
    MUX_QUERY: Final = "mux.query"
    MUX_PREFLIGHT: Final = "mux.preflight"
    RESOURCE_PREFLIGHT: Final = "resource.preflight"
    RESOURCE_OPEN: Final = "resource.open"
    RESOURCE_GET: Final = "resource.get"
    RESOURCE_CLOSE: Final = "resource.close"
    RESOURCE_RECOVER: Final = "resource.recover"
    RESOURCE_CALL: Final = "resource.call"
    JOB_GET: Final = "job.get"
    JOB_CANCEL: Final = "job.cancel"
    GPIO_GROUP_READ: Final = "gpio.group.read"
    GPIO_GROUP_WRITE: Final = "gpio.group.write"
    RMT_SYNC: Final = "rmt.sync"
    BUFFER_CREATE: Final = "buffer.create"
    BUFFER_WRITE: Final = "buffer.write"
    BUFFER_READ: Final = "buffer.read"
    BUFFER_DELETE: Final = "buffer.delete"
    STORAGE_STATUS: Final = "storage.status"
    STORAGE_LIST: Final = "storage.list"
    STORAGE_FORMAT: Final = "storage.format"
    STORAGE_BEGIN: Final = "storage.begin"
    STORAGE_CHUNK: Final = "storage.chunk"
    STORAGE_COMMIT: Final = "storage.commit"
    STORAGE_ABORT: Final = "storage.abort"
    STORAGE_READ: Final = "storage.read"
    STORAGE_DELETE: Final = "storage.delete"
    STORAGE_RECORD: Final = "storage.record"
    STORAGE_APPEND: Final = "storage.append"
    OTA_STATUS: Final = "ota.status"
    OTA_BEGIN: Final = "ota.begin"
    OTA_CHUNK: Final = "ota.chunk"
    OTA_COMMIT: Final = "ota.commit"
    OTA_ABORT: Final = "ota.abort"
    WIFI_STATUS: Final = "wifi.status"
    WIFI_CONFIGURE: Final = "wifi.configure"
    WIFI_SCAN: Final = "wifi.scan"
    WIFI_MAINTENANCE: Final = "wifi.maintenance"
    WIFI_DISCONNECT: Final = "wifi.disconnect"
    MQTT_STATUS: Final = "mqtt.status"
    MQTT_CONFIGURE: Final = "mqtt.configure"
    MQTT_PUBLISH: Final = "mqtt.publish"
    MQTT_SUBSCRIBE: Final = "mqtt.subscribe"
    MQTT_UNSUBSCRIBE: Final = "mqtt.unsubscribe"
    MQTT_RECEIVE: Final = "mqtt.receive"
    MQTT_STOP: Final = "mqtt.stop"
    ESPNOW_STATUS: Final = "espnow.status"
    ESPNOW_START: Final = "espnow.start"
    ESPNOW_STOP: Final = "espnow.stop"
    ESPNOW_PEER: Final = "espnow.peer"
    ESPNOW_REMOVE: Final = "espnow.remove"
    ESPNOW_SEND: Final = "espnow.send"
    ESPNOW_RECEIVE: Final = "espnow.receive"
    POWER_CONFIGURE: Final = "power.configure"
    POWER_SLEEP: Final = "power.sleep"
    SYSTEM_INFO: Final = "system.info"
    SYSTEM_TIME: Final = "system.time"
    SYSTEM_RESTART: Final = "system.restart"
    SYSTEM_NVS_FORMAT: Final = "system.nvs_format"
    FLOW_LOAD: Final = "flow.load"
    FLOW_LIST: Final = "flow.list"
    FLOW_GET: Final = "flow.get"
    FLOW_START: Final = "flow.start"
    FLOW_PAUSE: Final = "flow.pause"
    FLOW_RESUME: Final = "flow.resume"
    FLOW_STOP: Final = "flow.stop"
    FLOW_REMOVE: Final = "flow.remove"


class QueryName:
    """SDK 聚合查询名称，不是可通过 raw.send 提交的 wire 操作。"""

    DISCOVER: Final = "discover"
    STATE_SNAPSHOT: Final = "state.snapshot"


class PeripheralKind:
    """PeripheralKind 的固定选项。"""

    GPIO: Final = "gpio"
    PWM: Final = "pwm"
    ADC: Final = "adc"
    ADC_CONTINUOUS: Final = "adc.continuous"
    UART: Final = "uart"
    I2C_MASTER: Final = "i2c.master"
    I2C_DEVICE: Final = "i2c.device"
    I2C_SLAVE: Final = "i2c.slave"
    SPI_MASTER: Final = "spi.master"
    SPI_DEVICE: Final = "spi.device"
    SPI_SLAVE: Final = "spi.slave"
    TWAI: Final = "twai"
    RMT_TX: Final = "rmt.tx"
    RMT_RX: Final = "rmt.rx"
    I2S: Final = "i2s"
    SIGMA_DELTA: Final = "sigma_delta"
    TIMER: Final = "timer"
    TEMPERATURE: Final = "temperature"


class ResourceAction:
    """resource.call 动作名称；资源种类与动作是否匹配由设备裁定。"""

    READ: Final = "read"
    WRITE: Final = "write"
    DUTY: Final = "duty"
    FADE: Final = "fade"
    START: Final = "start"
    STOP: Final = "stop"
    BREAK: Final = "break"
    DRAIN: Final = "drain"
    CLEAR: Final = "clear"
    ERRORS: Final = "errors"
    PROBE: Final = "probe"
    SCAN: Final = "scan"
    RECOVER: Final = "recover"
    WRITE_READ: Final = "write_read"
    PRELOAD: Final = "preload"
    CLEAR_TX: Final = "clear_tx"
    TRANSFER: Final = "transfer"
    RESULT: Final = "result"
    QUEUE: Final = "queue"
    CANCEL: Final = "cancel"
    SEND: Final = "send"
    INFO: Final = "info"
    TRANSMIT: Final = "transmit"
    ABORT: Final = "abort"
    WAIT: Final = "wait"
    CAPTURE: Final = "capture"
    PLAY: Final = "play"
    RECORD: Final = "record"
    DENSITY: Final = "density"
    STATUS: Final = "status"
    EVENTS: Final = "events"


class NotificationTopic:
    """NotificationTopic 的固定选项。"""

    JOB: Final = "job"
    RESOURCE: Final = "resource"
    FLOW: Final = "flow"
    DATA: Final = "data"


class TransportKind:
    """TransportKind 的固定选项。"""

    USB: Final = "usb"
    BLE: Final = "ble"
    WS: Final = "ws"
    MQTT: Final = "mqtt"


class FirmwareProfile:
    """已知镜像名称；发现结果仍允许未知 profile。"""

    BUS: Final = "bus"
    SIGNAL: Final = "signal"
    IOT: Final = "iot"


class JobState:
    """JobState 的固定选项。"""

    ACCEPTED: Final = "accepted"
    COMPLETED: Final = "completed"
    FAILED: Final = "failed"
    CANCELLED: Final = "cancelled"


class ResourceState:
    """资源生命周期；free 状态在资源查询中表现为资源不存在。"""

    FREE: Final = "free"

    OPENING: Final = "opening"
    READY: Final = "ready"
    CLOSING: Final = "closing"
    FAULT: Final = "fault"


class FlowState:
    """固件 v3 的流程状态名称。"""

    LOADED: Final = "loaded"
    OPENING: Final = "opening"
    RUNNING: Final = "running"
    PAUSED: Final = "paused"
    STOPPING: Final = "stopping"
    STOPPED: Final = "stopped"
    COMPLETED: Final = "completed"
    FAILED: Final = "failed"
    SLEEPING: Final = "sleeping"


class FlowStep:
    """固件 v3 的流程步骤名称。"""

    CALL: Final = "call"
    SERVICE: Final = "service"
    AWAIT: Final = "await"
    DELAY: Final = "delay"
    SET: Final = "set"
    ADD: Final = "add"
    IF: Final = "if"
    LOOP: Final = "loop"
    SLEEP: Final = "sleep"
    END: Final = "end"


class FlowCompare:
    """固件 v3 的流程比较名称。"""

    EQ: Final = "eq"
    NE: Final = "ne"
    LT: Final = "lt"
    LE: Final = "le"
    GT: Final = "gt"
    GE: Final = "ge"


class ErrorReason:
    """已知错误原因；未知设备原因仍以原始字符串保留。"""

    ADC_UNAVAILABLE: Final = "adc_unavailable"
    ADC_UNIT_CONFLICT: Final = "adc_unit_conflict"
    BATCH_REJECTED: Final = "batch_rejected"
    BOOT_CHANGED: Final = "boot_changed"
    BUFFER_NOT_FOUND: Final = "buffer_not_found"
    BUSY: Final = "busy"
    BUSY_LOOP: Final = "busy_loop"
    CANCELLED: Final = "cancelled"
    CAPACITY: Final = "capacity"
    CHECKPOINT_DEFINITION_CHANGED: Final = "checkpoint_definition_changed"
    CHILDREN_EXIST: Final = "children_exist"
    CLOSE_FAILED: Final = "close_failed"
    CONNECTION_LOST: Final = "connection_lost"
    CONTROL_BUSY: Final = "control_busy"
    CONTROL_REQUIRED: Final = "control_required"
    CONTROL_REVOKED: Final = "control_revoked"
    CONTROLLER_CONFLICT: Final = "controller_conflict"
    DEVICE_CAPACITY: Final = "device_capacity"
    DRIVER_ERROR: Final = "driver_error"
    DUPLICATE_DEVICE: Final = "duplicate_device"
    DUPLICATE_FLOW_RESOURCE: Final = "duplicate_flow_resource"
    DUPLICATE_PIN: Final = "duplicate_pin"
    DUPLICATE_REQUEST: Final = "duplicate_request"
    DUPLICATE_RESOURCE: Final = "duplicate_resource"
    EVENT_BUFFER_OVERFLOW: Final = "event_buffer_overflow"
    EXPERIMENTS_ACTIVE: Final = "experiments_active"
    FEATURE_UNAVAILABLE: Final = "feature_unavailable"
    FIXED_ADC_ROUTE: Final = "fixed_adc_route"
    FLOW_BUSY: Final = "flow_busy"
    FLOW_CAPACITY: Final = "flow_capacity"
    FLOW_NOT_FOUND: Final = "flow_not_found"
    FLOW_NOT_PAUSED: Final = "flow_not_paused"
    FLOW_NOT_RUNNING: Final = "flow_not_running"
    FRAME_TOO_LARGE: Final = "frame_too_large"
    HEARTBEAT_FAILED: Final = "heartbeat_failed"
    INCOMPATIBLE_DEVICE: Final = "incompatible_device"
    INCOMPATIBLE_PROFILE: Final = "incompatible_profile"
    INVALID_ARGUMENT: Final = "invalid_argument"
    INVALID_CALL: Final = "invalid_call"
    INVALID_CHECKPOINT: Final = "invalid_checkpoint"
    INVALID_COMPARE: Final = "invalid_compare"
    INVALID_CONTROLLER: Final = "invalid_controller"
    INVALID_DELAY: Final = "invalid_delay"
    INVALID_FLOW: Final = "invalid_flow"
    INVALID_FLOW_NAME: Final = "invalid_flow_name"
    INVALID_FLOW_RESOURCE: Final = "invalid_flow_resource"
    INVALID_IDENTITY: Final = "invalid_identity"
    INVALID_JOB_RESPONSE: Final = "invalid_job_response"
    INVALID_LOOP: Final = "invalid_loop"
    INVALID_MODE: Final = "invalid_mode"
    INVALID_PARENT: Final = "invalid_parent"
    INVALID_PIN: Final = "invalid_pin"
    INVALID_REPEAT: Final = "invalid_repeat"
    INVALID_REQUEST: Final = "invalid_request"
    INVALID_RESOURCE: Final = "invalid_resource"
    INVALID_RESPONSE: Final = "invalid_response"
    INVALID_SERVICE: Final = "invalid_service"
    INVALID_SESSION: Final = "invalid_session"
    INVALID_SLEEP: Final = "invalid_sleep"
    INVALID_STEP: Final = "invalid_step"
    INVALID_TARGET: Final = "invalid_target"
    INVALID_VARIABLE: Final = "invalid_variable"
    INVALID_WAIT: Final = "invalid_wait"
    JOB_EXPIRED: Final = "job_expired"
    JOB_NOT_CANCELLABLE: Final = "job_not_cancellable"
    MAINTENANCE_BUSY: Final = "maintenance_busy"
    MISSING_PIN: Final = "missing_pin"
    NACK: Final = "nack"
    PARSE_ERROR: Final = "parse_error"
    PIN_CONFLICT: Final = "pin_conflict"
    PWM_TIMER_CONFLICT: Final = "pwm_timer_conflict"
    RESERVED_PIN: Final = "reserved_pin"
    RESOURCE_BUSY: Final = "resource_busy"
    RESOURCE_NOT_FOUND: Final = "resource_not_found"
    RESOURCE_NOT_READY: Final = "resource_not_ready"
    RESOURCES_REMAINING: Final = "resources_remaining"
    RESPONSE_CAPACITY: Final = "response_capacity"
    RESULT_EXPIRED: Final = "result_expired"
    RESULT_UNKNOWN: Final = "result_unknown"
    SEQUENCE_WINDOW_BLOCKED: Final = "sequence_window_blocked"
    SESSION_CHANGED: Final = "session_changed"
    SLEEP_COMMITTED: Final = "sleep_committed"
    SNAPSHOT_EXPIRED: Final = "snapshot_expired"
    STOP_IN_PROGRESS: Final = "stop_in_progress"
    STOP_UNCONFIRMED: Final = "stop_unconfirmed"
    TIMEOUT: Final = "timeout"
    TRANSPORT_ERROR: Final = "transport_error"
    UNKNOWN_OPERATION: Final = "unknown_operation"
    UNKNOWN_RESOURCE_KIND: Final = "unknown_resource_kind"
    UNKNOWN_STEP: Final = "unknown_step"
    UNSUPPORTED_CONFIGURATION: Final = "unsupported_configuration"
    UNSUPPORTED_OPERATION: Final = "unsupported_operation"
    WRITE_TIMEOUT: Final = "write_timeout"
    WRONG_DEVICE: Final = "wrong_device"
    HANDSHAKE_MUST_BE_SINGLE: Final = "handshake_must_be_single"
    RETAINED_COMMAND: Final = "retained_command"


class ErrorSource:
    """ErrorSource 的固定选项。"""

    DEVICE: Final = "device"
    SDK: Final = "sdk"


class GPIOMode:
    """GPIOMode 的固定选项。"""

    INPUT: Final = "input"
    OUTPUT: Final = "output"
    OPEN_DRAIN: Final = "open_drain"


class Pull:
    """Pull 的固定选项。"""

    NONE: Final = "none"
    UP: Final = "up"
    DOWN: Final = "down"


class Edge:
    """Edge 的固定选项。"""

    NONE: Final = "none"
    RISING: Final = "rising"
    FALLING: Final = "falling"
    ANY: Final = "any"


class UARTMode:
    """UARTMode 的固定选项。"""

    UART: Final = "uart"
    RS485: Final = "rs485"


class Parity:
    """Parity 的固定选项。"""

    NONE: Final = "none"
    EVEN: Final = "even"
    ODD: Final = "odd"


class SPIMode:
    """SPIMode 的固定选项。"""

    MODE0: Final = 0
    MODE1: Final = 1
    MODE2: Final = 2
    MODE3: Final = 3


class I2SMode:
    """I2SMode 的固定选项。"""

    STANDARD: Final = "standard"
    TDM: Final = "tdm"
    PDM: Final = "pdm"


class I2SRole:
    """I2SRole 的固定选项。"""

    MASTER: Final = "master"
    SLAVE: Final = "slave"


class I2SDirection:
    """I2SDirection 的固定选项。"""

    TX: Final = "tx"
    RX: Final = "rx"
    DUPLEX: Final = "duplex"


class TWAIMode:
    """TWAIMode 的固定选项。"""

    NORMAL: Final = "normal"
    LISTEN_ONLY: Final = "listen_only"
    SELF_TEST: Final = "self_test"


class SleepMode:
    """SleepMode 的固定选项。"""

    LIGHT: Final = "light"
    DEEP: Final = "deep"


class ModemSleep:
    """ModemSleep 的固定选项。"""

    NONE: Final = "none"
    MIN: Final = "min"
    MAX: Final = "max"


class MQTTProtocol:
    """MQTTProtocol 的固定选项。"""

    V3_1_1: Final = "3.1.1"
    V5: Final = "5.0"


class Level:
    """逻辑电平，不假定外接器件或 LED 的有效电平。"""

    LOW: Final = 0
    HIGH: Final = 1


class Pins:
    """luatos-esp32c3-usb 芯片 GPIO 编号；命名不代表固件允许使用。"""

    GPIO0: Final = 0
    GPIO1: Final = 1
    GPIO2: Final = 2
    GPIO3: Final = 3
    GPIO4: Final = 4
    GPIO5: Final = 5
    GPIO6: Final = 6
    GPIO7: Final = 7
    GPIO8: Final = 8
    GPIO9: Final = 9
    GPIO10: Final = 10
    GPIO11: Final = 11
    GPIO12: Final = 12
    GPIO13: Final = 13
    GPIO14: Final = 14
    GPIO15: Final = 15
    GPIO16: Final = 16
    GPIO17: Final = 17
    GPIO18: Final = 18
    GPIO19: Final = 19
    GPIO20: Final = 20
    GPIO21: Final = 21
    LED: Final = GPIO13  # D5 板载实验 LED，带负载
    STATUS_LED: Final = GPIO12  # D4 固件会话指示灯，系统保留
    BOOT_BUTTON: Final = GPIO9  # BOOT 按键，启动绑带保留
    USB_DM: Final = GPIO18  # 原生 USB D−，系统保留
    USB_DP: Final = GPIO19  # 原生 USB D+，系统保留


__all__ = [
    "Edge",
    "ErrorReason",
    "ErrorSource",
    "EventType",
    "FirmwareProfile",
    "FlowCompare",
    "FlowState",
    "FlowStep",
    "GPIOMode",
    "I2SDirection",
    "I2SMode",
    "I2SRole",
    "JobState",
    "Level",
    "MQTTProtocol",
    "ModemSleep",
    "NotificationTopic",
    "OperationName",
    "Parity",
    "PeripheralKind",
    "Pins",
    "Pull",
    "QueryName",
    "ResourceAction",
    "ResourceState",
    "SPIMode",
    "SleepMode",
    "TWAIMode",
    "TransportKind",
    "UARTMode",
]
