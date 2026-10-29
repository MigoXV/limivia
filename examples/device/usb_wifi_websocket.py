"""先通过 USB 配网，再通过 WebSocket 控制同一块板卡的 D5。"""

import logging
from ipaddress import IPv4Address
from time import monotonic, sleep
from typing import Annotated

import typer

from limivia import Level, Limivia, LimiviaError, Pins, TransportKind

app = typer.Typer(pretty_exceptions_show_locals=False)


@app.command()
def main(
    usb_target: Annotated[
        str | None, typer.Option(envvar="LIMIVIA_USB_TARGET", help="USB 串口；缺省选择唯一板卡")
    ] = None,
    device_id: Annotated[
        str | None, typer.Option(envvar="LIMIVIA_DEVICE_ID", help="预期设备 MAC，可选")
    ] = None,
    persist: Annotated[
        bool, typer.Option(help="将 Wi-Fi 配置保存到板卡，重启后自动连接")
    ] = False,
) -> None:
    """USB 配网，等待 IP，关闭 USB 会话后用 WebSocket 点灯并读取确认电平。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ssid = typer.prompt("Wi-Fi 名称（2.4GHz）")
    password = typer.prompt("Wi-Fi 密码", hide_input=True, default="", show_default=False)
    try:
        with Limivia() as client:
            client.devices.list(kind=TransportKind.USB)
            with client.devices.connect(
                kind=TransportKind.USB, target=usb_target, expected_device_id=device_id
            ) as board:
                # 后续 WS 必须连接刚刚通过 USB 识别的板卡，而不是仅相信 IP。
                identity = board.identity
                if identity is None:
                    raise RuntimeError("USB 握手未取得设备身份")
                expected_device_id = identity.device_id
                board.wifi.configure(ssid=ssid, password=password, persist=persist)
                del password
                deadline = monotonic() + 20
                while monotonic() < deadline:
                    status = board.wifi.status().data
                    ip = status.get("ip")
                    if (
                        status.get("connected")
                        and isinstance(ip, str)
                        and not IPv4Address(ip).is_unspecified
                    ):
                        break
                    sleep(0.25)
                else:
                    raise RuntimeError("等待 Wi-Fi 地址超时")
                url = f"ws://{ip}/v3"
                # Wi-Fi 配置申请过控制令牌；主动释放，避免新会话等待旧租约。
                board.control.release()
            typer.echo(f"USB 会话已关闭，正在连接 {url}")
            with client.devices.connect(
                kind=TransportKind.WS, target=url, expected_device_id=expected_device_id
            ) as board:
                with board.gpio.output(Pins.LED, value=Level.LOW) as led:
                    confirmed = led.write(Level.HIGH)
                    typer.echo(f"点亮确认：电平 {confirmed.level}；读取电平 {led.read()}")
                    input("按回车熄灭并释放 D5…")
                    confirmed = led.write(Level.LOW)
                    typer.echo(f"熄灭确认：电平 {confirmed.level}；读取电平 {led.read()}")
                board.control.release()
            typer.echo("LED 资源及 WebSocket 会话已释放；Wi-Fi 连接保留。")
    except (LimiviaError, RuntimeError, ValueError, OSError) as exc:
        # 配网错误只显示类型，避免第三方异常文本或局部变量泄露凭据。
        typer.echo(
            f"示例未完成（{type(exc).__name__}）。请检查网络和资源占用；"
            "若写入结果未知，先查询设备，不要直接重发。",
            err=True,
        )
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
