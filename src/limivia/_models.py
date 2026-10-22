from typing import Any

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """协议数据模型；保留新固件附加的字段。"""

    model_config = ConfigDict(extra="allow", strict=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        return self.model_dump_json()
