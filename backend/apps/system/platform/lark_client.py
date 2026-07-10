"""Domestic Feishu (Lark CN) Open API client for credential validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

FEISHU_APP_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"


@dataclass
class LarkConfig:
    client_id: str
    client_secret: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LarkConfig":
        return cls(
            client_id=str(data.get("client_id") or ""),
            client_secret=str(data.get("client_secret") or ""),
        )


class LarkClient:
    def __init__(self, config: LarkConfig):
        self.config = config

    async def validate_credentials(self) -> bool:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                FEISHU_APP_TOKEN_URL,
                json={
                    "app_id": self.config.client_id,
                    "app_secret": self.config.client_secret,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                raise RuntimeError(payload.get("msg") or f"feishu api error: {payload}")
            token = payload.get("app_access_token") or payload.get("tenant_access_token")
            if not token:
                token = (payload.get("data") or {}).get("app_access_token")
            if not token:
                raise RuntimeError("missing app_access_token in feishu response")
            return True
