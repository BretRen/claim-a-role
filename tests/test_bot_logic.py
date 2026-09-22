import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from config import config
from storage import Storage
from bot import ClaimRolesBot


class TestBotLogic(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "config.json")
        self.storage = Storage(self.config_path)

        # Mock API 客户端
        self.mock_api = AsyncMock()
        self.mock_api.send_message.return_value = {"id": "msg_100", "channel_id": "chan_200"}
        self.mock_api.edit_message.return_value = {"id": "msg_100", "channel_id": "chan_200"}
        self.mock_api.get_guild_roles.return_value = [
            {"id": "role_vip", "name": "VIP"},
            {"id": "role_mod", "name": "Moderator"}
        ]

        # Mock Gateway 客户端
        self.mock_gateway = AsyncMock()
        self.mock_gateway.bot_user = {"id": "bot_999", "username": "RoleBot"}
        self.mock_gateway.on = Mock()

        self.bot = ClaimRolesBot(self.mock_api, self.mock_gateway, self.storage)

        # 设置测试环境管理员 ID 为 1001
        config.admin_user_ids = {"1001"}

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_board_embed_empty(self):
        embed = self.bot.build_board_embed("guild_1")
        self.assertIn("No self-assignable roles", embed["description"])

    def test_board_embed_with_roles(self):
        asyncio.run(self.storage.add_role("guild_1", "role_vip", "VIP", "⭐", "VIP 会员"))
        embed = self.bot.build_board_embed("guild_1")
        self.assertIn("⭐ **@VIP** - VIP 会员", embed["description"])

    def test_unauthorized_user_silently_ignored(self):
        # 用户 2002 不是管理员，发送指令
        msg = {
            "content": "/set-role list",
            "author": {"id": "2002", "username": "normal_user", "bot": False},
            "guild_id": "guild_1",
            "channel_id": "chan_1"
        }
        asyncio.run(self.bot.handle_message_create(msg))
        # 验证没有任何 API 响应（静默忽略）
        self.mock_api.send_message.assert_not_called()

    def test_authorized_set_home_slash_and_exclamation(self):
        # 1. 测试斜杠指令 /set-home
        msg1 = {
            "content": "/set-home",
            "author": {"id": "1001", "username": "admin_user", "bot": False},
            "guild_id": "guild_1",
            "channel_id": "chan_main"
        }
        asyncio.run(self.bot.handle_message_create(msg1))
        cfg = self.storage.get_guild_config("guild_1")
        self.assertEqual(cfg["home_channel_id"], "chan_main")
        self.mock_api.send_message.assert_called()

        # 2. 测试感叹号指令 !set-home <#chan_new>
        self.mock_api.send_message.reset_mock()
        msg2 = {
            "content": "!set-home <#999888>",
            "author": {"id": "1001", "username": "admin_user", "bot": False},
            "guild_id": "guild_1",
            "channel_id": "chan_main"
        }
        asyncio.run(self.bot.handle_message_create(msg2))
        cfg = self.storage.get_guild_config("guild_1")
        self.assertEqual(cfg["home_channel_id"], "999888")

    def test_role_add_and_sync(self):
        # 先设置 home 频道
        asyncio.run(self.storage.set_home_channel("guild_1", "chan_home"))

        msg = {
            "content": "/set-role add ⭐ <@&role_vip> 贵宾赞助者",
            "author": {"id": "1001", "username": "admin", "bot": False},
            "guild_id": "guild_1",
            "channel_id": "chan_admin"
        }
        asyncio.run(self.bot.handle_message_create(msg))

        # 验证角色被添加
        role = self.storage.get_role_by_id("guild_1", "role_vip")
        self.assertIsNotNone(role)
        self.assertEqual(role["emoji"], "⭐")
        self.assertEqual(role["role_name"], "VIP")
        self.assertEqual(role["description"], "贵宾赞助者")

        # 验证自动向 home 频道添加了反应表情
        self.mock_api.add_reaction.assert_called_with("chan_home", "msg_100", "⭐")

    def test_role_remove_command(self):
        asyncio.run(self.storage.set_home_channel("guild_1", "chan_home"))
        asyncio.run(self.storage.add_role("guild_1", "role_vip", "VIP", "⭐"))

        msg = {
            "content": "/set-role remove ⭐",
            "author": {"id": "1001", "username": "admin", "bot": False},
            "guild_id": "guild_1",
            "channel_id": "chan_admin"
        }
        asyncio.run(self.bot.handle_message_create(msg))

        self.assertEqual(len(self.storage.list_roles("guild_1")), 0)

    def test_reaction_add_grants_role(self):
        # 准备看板与角色
        asyncio.run(self.storage.set_home_channel("guild_1", "chan_home"))
        asyncio.run(self.storage.set_board_message_id("guild_1", "msg_board_1"))
        asyncio.run(self.storage.add_role("guild_1", "role_vip", "VIP", "⭐"))

        # 群员添加反应
        reaction_event = {
            "user_id": "user_normal",
            "guild_id": "guild_1",
            "message_id": "msg_board_1",
            "emoji": {"name": "⭐"}
        }
        asyncio.run(self.bot.handle_reaction_add(reaction_event))

        # 验证调用了 add_member_role
        self.mock_api.add_member_role.assert_called_once_with("guild_1", "user_normal", "role_vip")

    def test_reaction_remove_revokes_role(self):
        asyncio.run(self.storage.set_home_channel("guild_1", "chan_home"))
        asyncio.run(self.storage.set_board_message_id("guild_1", "msg_board_1"))
        asyncio.run(self.storage.add_role("guild_1", "role_vip", "VIP", "⭐"))

        # 群员移除反应
        reaction_event = {
            "user_id": "user_normal",
            "guild_id": "guild_1",
            "message_id": "msg_board_1",
            "emoji": {"name": "⭐"}
        }
        asyncio.run(self.bot.handle_reaction_remove(reaction_event))

        # 验证调用了 remove_member_role
        self.mock_api.remove_member_role.assert_called_once_with("guild_1", "user_normal", "role_vip")

    def test_guild_role_delete_event(self):
        asyncio.run(self.storage.set_home_channel("guild_1", "chan_home"))
        asyncio.run(self.storage.add_role("guild_1", "role_deleted", "DeletedRole", "❌"))

        # 触发角色删除事件
        delete_event = {
            "guild_id": "guild_1",
            "role_id": "role_deleted"
        }
        asyncio.run(self.bot.handle_guild_role_delete(delete_event))

        # 确认已从自领配置库中移除
        self.assertIsNone(self.storage.get_role_by_id("guild_1", "role_deleted"))

    def test_gateway_url_builder(self):
        from fluxer_gateway import GatewayClient
        gw = GatewayClient("dummy_token", "wss://newchat.pdnode.com/gateway")
        url = gw._build_gateway_url()
        self.assertIn("v=1", url)
        self.assertIn("encoding=json", url)
        self.assertTrue(url.startswith("wss://newchat.pdnode.com/gateway?"))



if __name__ == "__main__":
    unittest.main()
