"""
JSON 持久化存储模块：管理每个公会（Guild）的 Home 频道、看板消息 ID 及可领取角色列表。
格式整洁、支持人工直接查看与修改，并具备文件保存原子性。
"""

import json
import os
import tempfile
import asyncio
from typing import Dict, Any, Optional, List


class Storage:
    def __init__(self, file_path: str = "data/config.json"):
        self.file_path = file_path
        self._data: Dict[str, Any] = {"guilds": {}}
        self._lock = asyncio.Lock()
        self.load()

    def load(self) -> None:
        """从文件加载配置，若文件不存在则初始化空结构"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        self._data = json.loads(content)
                        if "guilds" not in self._data:
                            self._data["guilds"] = {}
                        return
            except Exception as e:
                print(f"[Storage] 读取配置文件失败: {e}，将初始化默认配置。")
        self._data = {"guilds": {}}

    async def save(self) -> None:
        """异步安全保存配置到 JSON 文件"""
        async with self._lock:
            self._sync_save()

    def _sync_save(self) -> None:
        """同步原子写入 JSON 文件"""
        dir_name = os.path.dirname(self.file_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

        temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix="config_tmp_", suffix=".json")
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            # 原子重命名替换
            os.replace(temp_path, self.file_path)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def get_guild_config(self, guild_id: str | int) -> Dict[str, Any]:
        """获取指定公会的配置，不存在则初始化"""
        gid = str(guild_id)
        if gid not in self._data["guilds"]:
            self._data["guilds"][gid] = {
                "home_channel_id": None,
                "board_message_id": None,
                "roles": []
            }
        return self._data["guilds"][gid]

    async def set_home_channel(self, guild_id: str | int, channel_id: str | int) -> None:
        """设置公会的 home channel"""
        cfg = self.get_guild_config(guild_id)
        cfg["home_channel_id"] = str(channel_id)
        await self.save()

    async def set_board_message_id(self, guild_id: str | int, message_id: Optional[str | int]) -> None:
        """更新公会看板消息 ID"""
        cfg = self.get_guild_config(guild_id)
        cfg["board_message_id"] = str(message_id) if message_id else None
        await self.save()

    def list_roles(self, guild_id: str | int) -> List[Dict[str, Any]]:
        """获取公会已注册的可自选角色列表"""
        cfg = self.get_guild_config(guild_id)
        return list(cfg.get("roles", []))

    def get_role_by_id(self, guild_id: str | int, role_id: str | int) -> Optional[Dict[str, Any]]:
        """通过角色 ID 查找配置"""
        rid = str(role_id)
        for r in self.list_roles(guild_id):
            if str(r.get("role_id")) == rid:
                return r
        return None

    def get_role_by_emoji(self, guild_id: str | int, emoji: str) -> Optional[Dict[str, Any]]:
        """通过 Emoji 查找对应的可领取角色"""
        emoji_clean = emoji.strip()
        for r in self.list_roles(guild_id):
            if r.get("emoji") == emoji_clean:
                return r
        return None

    async def add_role(
        self,
        guild_id: str | int,
        role_id: str | int,
        role_name: str,
        emoji: str,
        description: str = ""
    ) -> bool:
        """
        添加或覆盖一个自领角色。
        如果角色 ID 或 Emoji 已经存在，更新其信息；否则追加。
        """
        cfg = self.get_guild_config(guild_id)
        rid = str(role_id)
        emoji = emoji.strip()

        # 检查是否已存在此 role_id 或 emoji
        for r in cfg["roles"]:
            if str(r["role_id"]) == rid:
                r["emoji"] = emoji
                r["role_name"] = role_name
                r["description"] = description
                await self.save()
                return True
            if r["emoji"] == emoji:
                # 表情被其他角色占用，更新为新角色
                r["role_id"] = rid
                r["role_name"] = role_name
                r["description"] = description
                await self.save()
                return True

        cfg["roles"].append({
            "role_id": rid,
            "role_name": role_name,
            "emoji": emoji,
            "description": description
        })
        await self.save()
        return True

    async def update_role(
        self,
        guild_id: str | int,
        role_id: str | int,
        emoji: Optional[str] = None,
        description: Optional[str] = None,
        role_name: Optional[str] = None
    ) -> bool:
        """更新现有角色的属性"""
        cfg = self.get_guild_config(guild_id)
        rid = str(role_id)
        found = False
        for r in cfg["roles"]:
            if str(r["role_id"]) == rid:
                if emoji is not None:
                    r["emoji"] = emoji.strip()
                if description is not None:
                    r["description"] = description.strip()
                if role_name is not None:
                    r["role_name"] = role_name.strip()
                found = True
                break
        if found:
            await self.save()
        return found

    async def remove_role(self, guild_id: str | int, identifier: str) -> Optional[Dict[str, Any]]:
        """
        根据角色 ID 或 Emoji 移除自领角色，返回被移除的角色字典（未找到返回 None）
        """
        cfg = self.get_guild_config(guild_id)
        ident = identifier.strip()
        removed_role = None
        new_roles = []
        for r in cfg["roles"]:
            if str(r.get("role_id")) == ident or r.get("emoji") == ident:
                removed_role = r
            else:
                new_roles.append(r)

        if removed_role:
            cfg["roles"] = new_roles
            await self.save()
        return removed_role

    async def clear_roles(self, guild_id: str | int) -> int:
        """清空指定公会的所有自领角色"""
        cfg = self.get_guild_config(guild_id)
        count = len(cfg.get("roles", []))
        cfg["roles"] = []
        await self.save()
        return count
