import asyncio
import os
import shutil
import tempfile
import unittest

from storage import Storage


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.test_dir, "config.json")
        self.storage = Storage(self.config_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_config(self):
        cfg = self.storage.get_guild_config("123")
        self.assertIsNone(cfg["home_channel_id"])
        self.assertIsNone(cfg["board_message_id"])
        self.assertEqual(cfg["roles"], [])

    def test_set_home_channel(self):
        asyncio.run(self.storage.set_home_channel("123", "456"))
        cfg = self.storage.get_guild_config("123")
        self.assertEqual(cfg["home_channel_id"], "456")

        # 重新加载验证持久化
        reloaded = Storage(self.config_path)
        self.assertEqual(reloaded.get_guild_config("123")["home_channel_id"], "456")

    def test_add_and_list_roles(self):
        asyncio.run(self.storage.add_role("123", "999", "VIP", "⭐", "VIP 会员"))
        roles = self.storage.list_roles("123")
        self.assertEqual(len(roles), 1)
        self.assertEqual(roles[0]["role_id"], "999")
        self.assertEqual(roles[0]["role_name"], "VIP")
        self.assertEqual(roles[0]["emoji"], "⭐")
        self.assertEqual(roles[0]["description"], "VIP 会员")

        # 查找
        by_emoji = self.storage.get_role_by_emoji("123", "⭐")
        self.assertIsNotNone(by_emoji)
        self.assertEqual(by_emoji["role_id"], "999")

        by_id = self.storage.get_role_by_id("123", "999")
        self.assertIsNotNone(by_id)
        self.assertEqual(by_id["emoji"], "⭐")

    def test_update_role(self):
        asyncio.run(self.storage.add_role("123", "999", "VIP", "⭐", "旧描述"))
        updated = asyncio.run(self.storage.update_role("123", "999", emoji="🌟", description="新描述"))
        self.assertTrue(updated)

        role = self.storage.get_role_by_id("123", "999")
        self.assertEqual(role["emoji"], "🌟")
        self.assertEqual(role["description"], "新描述")

    def test_remove_role(self):
        asyncio.run(self.storage.add_role("123", "999", "VIP", "⭐", "VIP 会员"))
        removed = asyncio.run(self.storage.remove_role("123", "⭐"))
        self.assertIsNotNone(removed)
        self.assertEqual(removed["role_id"], "999")
        self.assertEqual(self.storage.list_roles("123"), [])

    def test_clear_roles(self):
        asyncio.run(self.storage.add_role("123", "1", "R1", "1️⃣"))
        asyncio.run(self.storage.add_role("123", "2", "R2", "2️⃣"))
        self.assertEqual(len(self.storage.list_roles("123")), 2)

        count = asyncio.run(self.storage.clear_roles("123"))
        self.assertEqual(count, 2)
        self.assertEqual(len(self.storage.list_roles("123")), 0)


if __name__ == "__main__":
    unittest.main()
