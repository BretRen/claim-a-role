"""
Fluxer REST API 客户端：封装 Fluxer 平台的 HTTP 接口交互。
包括实例发现、消息收发、反应表情添加、成员身份组变更及角色信息拉取等。
"""

import asyncio
import logging
import urllib.parse
from typing import Dict, Any, Optional, List
import aiohttp

logger = logging.getLogger("fluxer_api")


class FluxerAPIError(Exception):
    def __init__(self, status: int, message: str, data: Any = None):
        super().__init__(f"Fluxer API Error ({status}): {message}")
        self.status = status
        self.message = message
        self.data = data


class FluxerClient:
    def __init__(self, bot_token: str, base_url: str = "https://api.fluxer.app"):
        self.bot_token = bot_token.strip()
        self.base_url = base_url.strip().rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "FluxerClaimRolesBot/1.0",
        }

    async def request(
        self,
        method: str,
        path: str,
        json_data: Any = None,
        max_retries: int = 3
    ) -> Any:
        """通用的 HTTP 请求封装，带 429 限流退避与重试机制"""
        session = await self.get_session()
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        headers = self._get_headers()

        for attempt in range(max_retries):
            try:
                async with session.request(method, url, headers=headers, json=json_data) as resp:
                    if resp.status == 429:
                        # 处理限流
                        data = await resp.json() if resp.content_type == "application/json" else {}
                        retry_after = data.get("retry_after", 1.0)
                        logger.warning(f"Rate limited on {method} {url}, waiting {retry_after}s...")
                        await asyncio.sleep(float(retry_after))
                        continue

                    if resp.status in (200, 201):
                        return await resp.json()
                    elif resp.status == 204:
                        return None
                    else:
                        error_data = None
                        try:
                            error_data = await resp.json()
                        except Exception:
                            error_data = await resp.text()
                        raise FluxerAPIError(resp.status, f"Request failed: {error_data}", error_data)

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.error(f"Network error on {method} {url}: {e}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))

        raise FluxerAPIError(429, f"Exceeded max retries for {method} {url}")

    async def discover_endpoints(self) -> Dict[str, str]:
        """
        通过 /.well-known/fluxer 自动探测公共 API 根地址及 WebSocket Gateway 地址
        """
        session = await self.get_session()
        well_known_url = f"{self.base_url}/.well-known/fluxer"
        try:
            async with session.get(well_known_url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    endpoints = data.get("endpoints", {})
                    if "api_public" in endpoints:
                        self.base_url = endpoints["api_public"].rstrip("/")
                    return {
                        "api_public": endpoints.get("api_public", self.base_url),
                        "gateway": endpoints.get("gateway")
                    }
        except Exception as e:
            logger.debug(f"Instance discovery via /.well-known/fluxer skipped/failed: {e}")
        return {"api_public": self.base_url, "gateway": None}

    async def get_gateway_url(self) -> str:
        """获取 Gateway WebSocket 连接地址"""
        # 首先尝试从 /v1/gateway/bot 获取
        try:
            data = await self.request("GET", "/v1/gateway/bot")
            if isinstance(data, dict) and "url" in data:
                return data["url"]
        except Exception as e:
            logger.debug(f"GET /v1/gateway/bot failed: {e}, falling back to discovery")

        # 其次尝试从 discovery 获取
        disc = await self.discover_endpoints()
        if disc.get("gateway"):
            return disc["gateway"]

        # 默认 fallback
        return "wss://gateway.fluxer.app"

    async def get_current_user(self) -> Dict[str, Any]:
        """获取当前 Bot 自身信息"""
        try:
            return await self.request("GET", "/v1/users/@me")
        except Exception:
            return await self.request("GET", "/v1/oauth2/applications/@me")

    async def get_guild_roles(self, guild_id: str | int) -> List[Dict[str, Any]]:
        """获取公会内所有角色信息列表"""
        return await self.request("GET", f"/v1/guilds/{guild_id}/roles")

    async def add_member_role(self, guild_id: str | int, user_id: str | int, role_id: str | int) -> None:
        """为公会成员赋予角色"""
        await self.request("PUT", f"/v1/guilds/{guild_id}/members/{user_id}/roles/{role_id}")

    async def remove_member_role(self, guild_id: str | int, user_id: str | int, role_id: str | int) -> None:
        """为公会成员移除角色"""
        await self.request("DELETE", f"/v1/guilds/{guild_id}/members/{user_id}/roles/{role_id}")

    async def send_message(
        self,
        channel_id: str | int,
        content: Optional[str] = None,
        embeds: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """向指定频道发送消息"""
        payload: Dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        if embeds is not None:
            payload["embeds"] = embeds
        return await self.request("POST", f"/v1/channels/{channel_id}/messages", json_data=payload)

    async def edit_message(
        self,
        channel_id: str | int,
        message_id: str | int,
        content: Optional[str] = None,
        embeds: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """修改已发送的消息"""
        payload: Dict[str, Any] = {}
        if content is not None:
            payload["content"] = content
        if embeds is not None:
            payload["embeds"] = embeds
        return await self.request("PATCH", f"/v1/channels/{channel_id}/messages/{message_id}", json_data=payload)

    async def delete_message(self, channel_id: str | int, message_id: str | int) -> None:
        """删除消息"""
        await self.request("DELETE", f"/v1/channels/{channel_id}/messages/{message_id}")

    async def add_reaction(self, channel_id: str | int, message_id: str | int, emoji: str) -> None:
        """为指定消息添加表情反应（Bot 自身反应）"""
        encoded_emoji = urllib.parse.quote(emoji.strip())
        await self.request("PUT", f"/v1/channels/{channel_id}/messages/{message_id}/reactions/{encoded_emoji}/@me")
