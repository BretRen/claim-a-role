"""
Fluxer 角色领取机器人启动入口：
初始化全局配置、REST 客户端、本地存储与 Gateway 连接，并进入长轮询事件循环。
"""

import asyncio
import logging
import signal
import sys

from config import config
from storage import Storage
from fluxer_api import FluxerClient
from fluxer_gateway import GatewayClient
from bot import ClaimRolesBot

# 日志输出配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("main")


async def async_main() -> None:
    logger.info("=========================================")
    logger.info("🚀 Starting Fluxer ClaimRolesBot ...")
    logger.info("=========================================")

    # 1. Validate configuration
    try:
        config.validate()
    except ValueError as e:
        logger.critical(f"❌ Configuration check failed: {e}")
        sys.exit(1)

    logger.info(f"API Base URL: {config.api_base}")
    logger.info(f"Configured Admin IDs ({len(config.admin_user_ids)}): {', '.join(config.admin_user_ids) if config.admin_user_ids else 'None'}")
    logger.info(f"Configuration file path: {config.config_path}")

    # 2. Initialize persistent storage
    storage = Storage(config.config_path)

    # 3. Initialize REST API client
    api_client = FluxerClient(config.bot_token, config.api_base)

    # 4. Automatically discover endpoints and Gateway URL
    endpoints = await api_client.discover_endpoints()
    logger.info(f"Instance discovery completed: Public API: {endpoints.get('api_public')}")

    gateway_url = await api_client.get_gateway_url()
    logger.info(f"Discovered Gateway URL: {gateway_url}")

    # 5. Initialize Gateway client
    gateway_client = GatewayClient(config.bot_token, gateway_url)

    # 6. Initialize Bot logic
    ClaimRolesBot(api_client, gateway_client, storage)

    # Graceful shutdown handling
    loop = asyncio.get_running_loop()

    async def shutdown():
        logger.info("Stopping bot and closing connections...")
        await gateway_client.close()
        await api_client.close()
        logger.info("Successfully stopped.")

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    try:
        await gateway_client.connect_and_listen()
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Received interrupt signal...")
    finally:
        await shutdown()


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
