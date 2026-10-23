"""识别当前镜像并读取全部能力；不申请控制或停止设备。"""

from ._common import Kind, KindOption, TargetOption, connect_sync, execute, wait


def main(kind: KindOption = Kind.usb, target: TargetOption = None):
    with connect_sync(kind, target) as connection:
        discovered = wait(connection, connection.discover())
        print(discovered.to_json())


if __name__ == "__main__":
    execute(main)()
