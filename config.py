"""
配置管理模块：负责从环境变量中读取 Bot Token、管理员 ID 列表及 API 地址等。
"""

import os
from typing import Set
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 内置轻量 fallback 解析 .env
    def _fallback_load_dotenv():
        env_file = ".env"
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v
    _fallback_load_dotenv()



class Config:
    def __init__(self):
        self.bot_token: str = os.getenv("FLUXER_BOT_TOKEN", "").strip()
        self.api_base: str = os.getenv("FLUXER_API_BASE", "https://api.fluxer.app").strip().rstrip("/")
        self.config_path: str = os.getenv("CONFIG_PATH", "data/config.json").strip()
        
        # 解析 ADMIN_USER_IDS
        admin_ids_raw = os.getenv("ADMIN_USER_IDS", "")
        self.admin_user_ids: Set[str] = set()
        for uid in admin_ids_raw.split(","):
            cleaned = uid.strip()
            if cleaned:
                self.admin_user_ids.add(cleaned)

    def is_admin(self, user_id: str | int) -> bool:
        """检查指定用户 ID 是否在管理员白名单中"""
        if not user_id:
            return False
        return str(user_id).strip() in self.admin_user_ids

    def validate(self) -> None:
        """验证必要配置项"""
        if not self.bot_token:
            raise ValueError("环境变量 FLUXER_BOT_TOKEN 未配置，请在 .env 中设置正确的 Bot Token。")


# 单例全局配置对象
config = Config()
