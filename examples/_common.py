"""示例启动入口：只处理帮助、日志和退出码，不包装 SDK 业务调用。"""

import argparse
import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from limivia import LimiviaError


def run(main: Callable[[], None] | Callable[[], Coroutine[Any, Any, None]]) -> None:
    argparse.ArgumentParser(description=main.__doc__).parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        result = main()
        if result is not None:
            asyncio.run(result)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (LimiviaError, RuntimeError, ValueError, OSError) as exc:
        logger = logging.getLogger(__name__)
        logger.error("%s", exc)
        for note in getattr(exc, "__notes__", ()):
            logger.error("%s", note)
        raise SystemExit(1) from None
