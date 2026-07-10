"""Lark International (Larksuite) OAuth / Open API client."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

LARKSUITE_APP_TOKEN_URL = "https://open.larksuite.com/open-apis/auth/v3/app_access_token/internal"
LARKSUITE_ACCESS_TOKEN_URL = "https://open.larksuite.com/open-apis/authen/v1/access_token"
LARKSUITE_OIDC_TOKEN_URL = "https://open.larksuite.com/open-apis/authen/v1/oidc/access_token"
LARKSUITE_USER_INFO_URL = "https://open.larksuite.com/open-apis/authen/v1/user_info"


@dataclass
class LarksuiteConfig:
    client_id: str
    client_secret: str
    redirect_uri: str = ""
    auto_create_user: bool = False
    default_oid: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LarksuiteConfig":
        auto = data.get("auto_create_user")
        if isinstance(auto, str):
            auto = auto.lower() in ("1", "true", "yes")
        default_oid = data.get("default_oid") or 0
        if isinstance(default_oid, str) and default_oid.isdigit():
            default_oid = int(default_oid)
        return cls(
            client_id=str(data.get("client_id") or ""),
            client_secret=str(data.get("client_secret") or ""),
            redirect_uri=str(data.get("redirect_uri") or ""),
            auto_create_user=bool(auto),
            default_oid=int(default_oid),
        )


@dataclass
class LarksuiteUserInfo:
    open_id: str
    union_id: Optional[str] = None
    name: str = ""
    email: str = ""
    en_name: str = ""


class LarksuiteClient:
    def __init__(self, config: LarksuiteConfig):
        self.config = config

    def _check_api_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("code") != 0:
            raise RuntimeError(
                payload.get("msg") or payload.get("message") or f"larksuite api error: {payload}"
            )
        return payload.get("data") or {}

    def _user_from_token_data(self, token_data: dict[str, Any]) -> LarksuiteUserInfo:
        return LarksuiteUserInfo(
            open_id=str(token_data.get("open_id") or ""),
            union_id=token_data.get("union_id"),
            name=str(token_data.get("name") or ""),
            email=str(token_data.get("email") or token_data.get("enterprise_email") or ""),
            en_name=str(token_data.get("en_name") or ""),
        )

    def _extract_access_token(self, payload: dict[str, Any]) -> str:
        token = payload.get("app_access_token") or payload.get("tenant_access_token")
        if token:
            return str(token)
        data = payload.get("data") or {}
        token = data.get("app_access_token") or data.get("tenant_access_token")
        if token:
            return str(token)
        raise RuntimeError("missing app_access_token in larksuite response")

    async def get_app_access_token(self) -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                LARKSUITE_APP_TOKEN_URL,
                json={
                    "app_id": self.config.client_id,
                    "app_secret": self.config.client_secret,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                raise RuntimeError(payload.get("msg") or f"larksuite api error: {payload}")
            return self._extract_access_token(payload)

    async def validate_credentials(self) -> bool:
        await self.get_app_access_token()
        return True

    async def exchange_code_in_app(self, code: str) -> dict[str, Any]:
        """Exchange requestAuthCode / requestAccess code from Lark client H5."""
        app_token = await self.get_app_access_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                LARKSUITE_ACCESS_TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                },
                headers={
                    "Authorization": f"Bearer {app_token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            return self._check_api_response(resp.json())

    async def exchange_code_oidc(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange OAuth redirect code (e.g. QR login) with redirect_uri."""
        app_token = await self.get_app_access_token()
        body: dict[str, Any] = {
            "grant_type": "authorization_code",
            "code": code,
        }
        if redirect_uri:
            body["redirect_uri"] = redirect_uri
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                LARKSUITE_OIDC_TOKEN_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {app_token}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            return self._check_api_response(resp.json())

    async def get_user_info(self, user_access_token: str) -> LarksuiteUserInfo:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                LARKSUITE_USER_INFO_URL,
                headers={"Authorization": f"Bearer {user_access_token}"},
            )
            resp.raise_for_status()
            data = self._check_api_response(resp.json())
            return LarksuiteUserInfo(
                open_id=str(data.get("open_id") or ""),
                union_id=data.get("union_id"),
                name=str(data.get("name") or ""),
                email=str(data.get("email") or data.get("enterprise_email") or ""),
                en_name=str(data.get("en_name") or ""),
            )

    async def login_with_code(
        self,
        code: str,
        redirect_uri: str = "",
        *,
        in_app: bool = False,
    ) -> tuple[LarksuiteUserInfo, dict[str, Any]]:
        if in_app:
            token_data = await self.exchange_code_in_app(code)
            user = self._user_from_token_data(token_data)
            if user.open_id:
                return user, token_data
            access_token = token_data.get("access_token")
            if not access_token:
                raise RuntimeError("missing access_token from larksuite in-app login")
            user = await self.get_user_info(access_token)
        else:
            token_data = await self.exchange_code_oidc(code, redirect_uri)
            access_token = token_data.get("access_token")
            if not access_token:
                raise RuntimeError("missing access_token from larksuite oidc")
            user = await self.get_user_info(access_token)
        if not user.open_id:
            raise RuntimeError("missing open_id from larksuite user_info")
        return user, token_data
