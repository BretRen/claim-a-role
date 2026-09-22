"""
Fluxer WebSocket Gateway 客户端：维持与 Fluxer Gateway 的长连接。
处理心跳保活、鉴权握手、事件分发以及自动断线重连。
"""

import asyncio
import json
import logging
from typing import Dict, Any, Callable, Optional, List, Coroutine
import aiohttp

import urllib.parse

logger = logging.getLogger("fluxer_gateway")


class GatewayClient:
    def __init__(self, token: str, gateway_url: str):
        self.token = token.strip()
        self.gateway_url = gateway_url.strip()
        self._handlers: Dict[str, List[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]]] = {}
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._seq: Optional[int] = None
        self._session_id: Optional[str] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self.bot_user: Optional[Dict[str, Any]] = None

    def _build_gateway_url(self) -> str:
        """
        构造正确的 Gateway WebSocket 连接 URL。
        Fluxer 强制要求连接参数包含 v=1，否则服务端会在发送 Hello 前直接断开 (4012 Invalid API version)。
        """
        parsed = urllib.parse.urlparse(self.gateway_url)
        query = urllib.parse.parse_qs(parsed.query)
        if "v" not in query:
            query["v"] = ["1"]
        if "encoding" not in query:
            query["encoding"] = ["json"]
        new_query = urllib.parse.urlencode(query, doseq=True)
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))

    def on(self, event_name: str, handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        """注册 Gateway 事件回调"""
        event_key = event_name.upper()
        if event_key not in self._handlers:
            self._handlers[event_key] = []
        self._handlers[event_key].append(handler)

    async def _dispatch(self, event_name: str, data: Dict[str, Any]) -> None:
        """异步分发事件给注册的回调函数"""
        handlers = self._handlers.get(event_name.upper(), [])
        for h in handlers:
            try:
                asyncio.create_task(h(data))
            except Exception as e:
                logger.error(f"Error executing event handler for {event_name}: {e}")

    async def _send(self, op: int, data: Any) -> None:
        """向 WebSocket 发送 Payload"""
        if self._ws and not self._ws.closed:
            payload = {"op": op, "d": data}
            await self._ws.send_str(json.dumps(payload))

    async def _send_heartbeat(self) -> None:
        """发送 Opcode 1 心跳"""
        logger.debug(f"Sending heartbeat (seq: {self._seq})")
        await self._send(1, self._seq)

    async def _heartbeat_loop(self, interval_ms: float) -> None:
        """周期性发送心跳任务"""
        interval_sec = interval_ms / 1000.0
        try:
            while self._running:
                await asyncio.sleep(interval_sec)
                await self._send_heartbeat()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Heartbeat loop error: {e}")

    async def _identify(self) -> None:
        """发送 Opcode 2 Identify 鉴权"""
        logger.info("Identifying with Gateway...")
        payload = {
            "token": self.token,
            "properties": {
                "os": "linux",
                "browser": "FluxerClaimRolesBot",
                "device": "FluxerClaimRolesBot"
            }
        }
        await self._send(2, payload)

    async def _resume(self) -> None:
        """尝试 Opcode 6 Resume 恢复会话"""
        logger.info("Attempting to resume session...")
        payload = {
            "token": self.token,
            "session_id": self._session_id,
            "seq": self._seq
        }
        await self._send(6, payload)

    async def connect_and_listen(self) -> None:
        """主连接循环，具备断线自动重连与指数退避机制"""
        self._running = True
        self._session = aiohttp.ClientSession()
        backoff = 1.0

        while self._running:
            try:
                ws_url = self._build_gateway_url()
                logger.info(f"Connecting to Gateway: {ws_url}")
                async with self._session.ws_connect(ws_url, heartbeat=30) as ws:
                    self._ws = ws
                    backoff = 1.0  # 连接成功重置退避时间

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_message(json.loads(msg.data))
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"WebSocket closed/error: type={msg.type}, code={ws.close_code}, extra={msg.extra}")
                            break

                    if ws.close_code:
                        logger.warning(f"Gateway closed connection with code {ws.close_code}")
                        if ws.close_code == 4004:
                            logger.critical("❌ 鉴权失败 (4004 Authentication Failed): 请检查 .env 中的 FLUXER_BOT_TOKEN 是否正确！")
                        elif ws.close_code == 4012:
                            logger.critical("❌ API 版本无效 (4012 Invalid API Version)")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Gateway connection error: {e}", exc_info=True)

            if self._heartbeat_task:
                self._heartbeat_task.cancel()

            if self._running:
                logger.info(f"Reconnecting in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 60.0)

        if self._session and not self._session.closed:
            await self._session.close()

    async def _handle_message(self, packet: Dict[str, Any]) -> None:
        """处理收到的 WebSocket 报文"""
        op = packet.get("op")
        data = packet.get("d")
        seq = packet.get("s")
        event_name = packet.get("t")

        if seq is not None:
            self._seq = seq

        # Opcode 10: HELLO
        if op == 10:
            heartbeat_interval = data.get("heartbeat_interval", 41250)
            logger.info(f"Gateway Hello received. Heartbeat interval: {heartbeat_interval}ms")
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(heartbeat_interval))

            # 发送首次心跳后 Identify 或 Resume
            await self._send_heartbeat()
            if self._session_id and self._seq:
                await self._resume()
            else:
                await self._identify()

        # Opcode 11: HEARTBEAT ACK
        elif op == 11:
            logger.debug("Heartbeat ACK received")

        # Opcode 1: HEARTBEAT REQUEST (Server requested instant heartbeat)
        elif op == 1:
            await self._send_heartbeat()

        # Opcode 7: RECONNECT
        elif op == 7:
            logger.warning("Gateway requested reconnect (Opcode 7)")
            if self._ws:
                await self._ws.close()

        # Opcode 9: INVALID SESSION
        elif op == 9:
            logger.warning(f"Gateway session invalid (Opcode 9), resumable: {data}")
            self._session_id = None
            self._seq = None
            await asyncio.sleep(1)
            await self._identify()

        # Opcode 0: DISPATCH
        elif op == 0:
            if event_name == "READY":
                self._session_id = data.get("session_id")
                self.bot_user = data.get("user")
                logger.info(f"Bot READY! Logged in as: {self.bot_user.get('username')}#{self.bot_user.get('discriminator')} (ID: {self.bot_user.get('id')})")
            elif event_name == "RESUMED":
                logger.info("Gateway session resumed successfully.")

            if event_name:
                await self._dispatch(event_name, data)

    async def close(self) -> None:
        """关闭 Gateway 连接"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
