"""
Bot 核心业务逻辑模块：
- 指令解析与路由（支持 / 和 ! 双前缀）
- 环境变量管理员白名单校验（非管理员静默忽略）
- Home Channel 设置与看板维护
- 角色增删改查（CRUD）与看板自动同步
- 反应表情添加/移除处理（Reaction Role 赋权与剥权）
- 角色删除级联清理
"""

import logging
import re
import shlex
from typing import Dict, Any, Optional, List

from config import config
from storage import Storage
from fluxer_api import FluxerClient, FluxerAPIError
from fluxer_gateway import GatewayClient

logger = logging.getLogger("claimrolesbot")


class ClaimRolesBot:
    def __init__(self, api_client: FluxerClient, gateway_client: GatewayClient, storage: Storage):
        self.api = api_client
        self.gateway = gateway_client
        self.storage = storage

        # 注册 Gateway 事件处理器
        self.gateway.on("MESSAGE_CREATE", self.handle_message_create)
        self.gateway.on("MESSAGE_REACTION_ADD", self.handle_reaction_add)
        self.gateway.on("MESSAGE_REACTION_REMOVE", self.handle_reaction_remove)
        self.gateway.on("GUILD_ROLE_DELETE", self.handle_guild_role_delete)

    # ==========================
    # Role Board Generation & Sync
    # ==========================
    def build_board_embed(self, guild_id: str | int) -> Dict[str, Any]:
        """Generate the role board Embed structure based on configured roles."""
        roles = self.storage.list_roles(guild_id)

        if not roles:
            description = (
                "📌 **No self-assignable roles available yet.**\n\n"
                "Admins can use `/set-role add <emoji> <@role> [description]` to configure roles."
            )
        else:
            lines = ["React with the emojis below to claim or unclaim a role:\n"]
            for r in roles:
                desc_str = f" - {r['description']}" if r.get("description") else ""
                lines.append(f"{r['emoji']} **@{r['role_name']}**{desc_str}")
            description = "\n".join(lines)

        return {
            "title": "✨ Self-Assignable Roles (Claim Roles)",
            "description": description,
            "color": 0x5865F2,  # Blurple color
            "footer": {
                "text": "💡 Free multi-select. Click emojis to toggle roles instantly."
            }
        }

    async def sync_role_board(self, guild_id: str | int) -> Optional[str]:
        """
        Synchronize the role board in the home channel.
        Edits existing message if present, or sends a new one and adds all emoji reactions.
        """
        cfg = self.storage.get_guild_config(guild_id)
        home_channel_id = cfg.get("home_channel_id")
        if not home_channel_id:
            logger.info(f"Guild {guild_id} has no home channel set yet.")
            return None

        embed = self.build_board_embed(guild_id)
        board_msg_id = cfg.get("board_message_id")
        board_msg = None

        if board_msg_id:
            try:
                board_msg = await self.api.edit_message(home_channel_id, board_msg_id, embeds=[embed])
            except FluxerAPIError as e:
                logger.info(f"Existing board message {board_msg_id} could not be edited ({e}), sending new one...")
                board_msg = None

        if not board_msg:
            try:
                board_msg = await self.api.send_message(home_channel_id, embeds=[embed])
                board_msg_id = str(board_msg["id"])
                await self.storage.set_board_message_id(guild_id, board_msg_id)
            except Exception as e:
                logger.error(f"Failed to post role board in channel {home_channel_id}: {e}")
                return None

        # Add reactions for all configured roles
        roles = self.storage.list_roles(guild_id)
        for r in roles:
            try:
                await self.api.add_reaction(home_channel_id, board_msg_id, r["emoji"])
            except Exception as e:
                logger.warning(f"Failed to add reaction {r['emoji']} to board message {board_msg_id}: {e}")

        return board_msg_id

    # ==========================
    # Gateway Message Handling (Commands)
    # ==========================
    async def handle_message_create(self, msg: Dict[str, Any]) -> None:
        """Handle incoming messages, supporting / and ! command prefixes."""
        content = (msg.get("content") or "").strip()
        if not content:
            return

        # Ignore messages from bots or itself
        author = msg.get("author") or {}
        if author.get("bot") is True:
            return

        bot_user = self.gateway.bot_user or {}
        if str(author.get("id")) == str(bot_user.get("id")):
            return

        # Check for / or ! prefix
        prefix = None
        if content.startswith("/"):
            prefix = "/"
        elif content.startswith("!"):
            prefix = "!"

        if not prefix:
            return

        command_body = content[len(prefix):].strip()
        if not command_body:
            return

        # Split command and arguments
        try:
            parts = shlex.split(command_body)
        except Exception:
            parts = command_body.split()

        if not parts:
            return

        cmd_name = parts[0].lower()
        args = parts[1:]

        if cmd_name not in ("set-role", "set-home", "setrole", "sethome"):
            return

        # Admin whitelist check
        author_id = str(author.get("id"))
        if not config.is_admin(author_id):
            logger.info(f"Unauthorized command attempt by user {author_id} ({author.get('username')}). Silently ignored.")
            return

        guild_id = msg.get("guild_id")
        channel_id = msg.get("channel_id")
        if not guild_id:
            return

        # Route command
        try:
            if cmd_name in ("set-home", "sethome"):
                await self.cmd_set_home(guild_id, channel_id, args)
            elif cmd_name in ("set-role", "setrole"):
                await self.cmd_set_role(guild_id, channel_id, args)
        except FluxerAPIError as e:
            if e.status == 403:
                logger.error(f"❌ Missing Permissions (403): Please ensure the bot has 'View Channel', 'Send Messages', 'Embed Links', and 'Add Reactions' permissions in the channel, as well as 'Manage Roles' in the server. Details: {e}")
            else:
                logger.error(f"Fluxer API error during {cmd_name}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error handling {cmd_name}: {e}", exc_info=True)

    # ==========================
    # Command Implementations
    # ==========================
    async def cmd_set_home(self, guild_id: str, channel_id: str, args: List[str]) -> None:
        """
        Set Home Channel:
        /set-home [channel_id/mention]
        """
        target_channel_id = channel_id
        if args:
            raw = args[0].strip()
            match = re.match(r"<#(\d+)>", raw)
            if match:
                target_channel_id = match.group(1)
            elif raw.isdigit():
                target_channel_id = raw

        await self.storage.set_home_channel(guild_id, target_channel_id)
        logger.info(f"Guild {guild_id} home channel set to {target_channel_id}")

        # Sync board
        board_msg_id = await self.sync_role_board(guild_id)

        # Send confirmation
        try:
            if board_msg_id:
                await self.api.send_message(
                    channel_id,
                    content=f"✅ Successfully set <#{target_channel_id}> as the role claim channel! The role board has been published."
                )
            else:
                await self.api.send_message(
                    channel_id,
                    content=f"⚠️ Home channel recorded as <#{target_channel_id}>, but failed to post the role board. Please check that the bot has 'View Channel', 'Send Messages', and 'Embed Links' permissions in that channel."
                )
        except FluxerAPIError as e:
            logger.error(f"Could not send confirmation to channel {channel_id}: {e}")

    async def cmd_set_role(self, guild_id: str, channel_id: str, args: List[str]) -> None:
        """
        Manage self-assignable roles:
        - /set-role add <emoji> <@role/role_id> [description]
        - /set-role list
        - /set-role update <role_id/emoji> <new_emoji> [new_description]
        - /set-role remove <role_id/emoji>
        - /set-role clear
        - /set-role refresh
        - /set-role help
        """
        if not args:
            await self.send_help(channel_id)
            return

        sub_cmd = args[0].lower()

        if sub_cmd == "add":
            await self._handle_role_add(guild_id, channel_id, args[1:])
        elif sub_cmd in ("list", "ls"):
            await self._handle_role_list(guild_id, channel_id)
        elif sub_cmd in ("remove", "delete", "rm", "del"):
            await self._handle_role_remove(guild_id, channel_id, args[1:])
        elif sub_cmd == "update":
            await self._handle_role_update(guild_id, channel_id, args[1:])
        elif sub_cmd == "clear":
            await self._handle_role_clear(guild_id, channel_id)
        elif sub_cmd in ("refresh", "post", "sync"):
            await self._handle_role_refresh(guild_id, channel_id)
        else:
            await self.send_help(channel_id)

    async def _handle_role_add(self, guild_id: str, channel_id: str, args: List[str]) -> None:
        """/set-role add <emoji> <@role/role_id> [description]"""
        if len(args) < 2:
            await self.api.send_message(
                channel_id,
                content="❌ Insufficient arguments. Usage: `/set-role add <emoji> <@role or role_id> [description]`"
            )
            return

        emoji = args[0].strip()
        role_raw = args[1].strip()
        description = " ".join(args[2:]).strip() if len(args) > 2 else ""

        # Extract role ID
        role_id = None
        match = re.match(r"<@&([a-zA-Z0-9_]+)>", role_raw)
        if match:
            role_id = match.group(1)
        elif role_raw.isdigit():
            role_id = role_raw

        # Resolve role name from guild roles
        role_name = None
        try:
            guild_roles = await self.api.get_guild_roles(guild_id)
            for gr in guild_roles:
                gr_id = str(gr.get("id"))
                gr_name = gr.get("name")
                if role_id and gr_id == str(role_id):
                    role_name = gr_name
                    break
                elif gr_id == role_raw or gr_name == role_raw:
                    role_id = gr_id
                    role_name = gr_name
                    break
        except Exception as e:
            logger.warning(f"Failed to fetch guild roles: {e}")

        if not role_id:
            role_id = role_raw

        if not role_name:
            role_name = f"Role_{role_id}"

        await self.storage.add_role(guild_id, role_id, role_name, emoji, description)
        logger.info(f"Role {role_name} ({role_id}) added with emoji {emoji} in guild {guild_id}")

        # Auto-sync board
        await self.sync_role_board(guild_id)

        desc_hint = f" (Description: {description})" if description else ""
        await self.api.send_message(
            channel_id,
            content=f"✅ Successfully added role!\n{emoji} **@{role_name}** (`ID: {role_id}`){desc_hint}\nThe home channel role board has been updated with the reaction."
        )

    async def _handle_role_list(self, guild_id: str, channel_id: str) -> None:
        """/set-role list"""
        roles = self.storage.list_roles(guild_id)
        if not roles:
            await self.api.send_message(
                channel_id,
                content="📋 No self-assignable roles configured yet. Use `/set-role add` to add roles."
            )
            return

        lines = [f"📋 **Configured Self-Assignable Roles ({len(roles)} total):**\n"]
        for idx, r in enumerate(roles, 1):
            desc = f" - *{r['description']}*" if r.get("description") else ""
            lines.append(f"{idx}. {r['emoji']} **@{r['role_name']}** (ID: `{r['role_id']}`){desc}")

        await self.api.send_message(channel_id, content="\n".join(lines))

    async def _handle_role_remove(self, guild_id: str, channel_id: str, args: List[str]) -> None:
        """/set-role remove <role_id/emoji>"""
        if not args:
            await self.api.send_message(
                channel_id,
                content="❌ Please specify the role ID, @role, or emoji to remove. Usage: `/set-role remove <role_id/emoji>`"
            )
            return

        target = args[0].strip()
        match = re.match(r"<@&(\d+)>", target)
        if match:
            target = match.group(1)

        removed = await self.storage.remove_role(guild_id, target)
        if removed:
            await self.sync_role_board(guild_id)
            await self.api.send_message(
                channel_id,
                content=f"✅ Successfully removed role: {removed['emoji']} **@{removed['role_name']}** (`ID: {removed['role_id']}`). Role board updated."
            )
        else:
            await self.api.send_message(
                channel_id,
                content=f"❌ No matching self-assignable role found for `{target}`."
            )

    async def _handle_role_update(self, guild_id: str, channel_id: str, args: List[str]) -> None:
        """/set-role update <role_id> <new_emoji> [new_description]"""
        if len(args) < 2:
            await self.api.send_message(
                channel_id,
                content="❌ Insufficient arguments. Usage: `/set-role update <@role or role_id> <new_emoji> [new_description]`"
            )
            return

        target_raw = args[0].strip()
        match = re.match(r"<@&(\d+)>", target_raw)
        role_id = match.group(1) if match else target_raw
        new_emoji = args[1].strip()
        new_desc = " ".join(args[2:]).strip() if len(args) > 2 else None

        updated = await self.storage.update_role(guild_id, role_id, emoji=new_emoji, description=new_desc)
        if updated:
            await self.sync_role_board(guild_id)
            await self.api.send_message(
                channel_id,
                content=f"✅ Role ID `{role_id}` updated successfully. The role board and reactions have been synchronized."
            )
        else:
            await self.api.send_message(
                channel_id,
                content=f"❌ Role ID `{role_id}` was not found in the configuration."
            )

    async def _handle_role_clear(self, guild_id: str, channel_id: str) -> None:
        """/set-role clear"""
        count = await self.storage.clear_roles(guild_id)
        await self.sync_role_board(guild_id)
        await self.api.send_message(
            channel_id,
            content=f"🧹 Cleared all {count} self-assignable roles. The role board has been reset."
        )

    async def _handle_role_refresh(self, guild_id: str, channel_id: str) -> None:
        """/set-role refresh"""
        cfg = self.storage.get_guild_config(guild_id)
        if not cfg.get("home_channel_id"):
            await self.api.send_message(
                channel_id,
                content="❌ No home channel set yet. Please run `/set-home` in the target channel first."
            )
            return

        msg_id = await self.sync_role_board(guild_id)
        if msg_id:
            await self.api.send_message(
                channel_id,
                content=f"🔄 Role board refreshed successfully in <#{cfg['home_channel_id']}>!"
            )
        else:
            await self.api.send_message(
                channel_id,
                content="❌ Failed to refresh the role board. Please check that the bot has permissions to send messages and add reactions in that channel."
            )

    async def send_help(self, channel_id: str) -> None:
        """Send admin help manual."""
        help_text = (
            "🛠️ **ClaimRolesBot Admin Manual**\n\n"
            "**Channel Setup:**\n"
            "• `/set-home` - Set current channel as the role claim channel (and post the board)\n"
            "• `/set-home <channel_id>` - Set a specific channel as the role claim channel\n\n"
            "**Role Management (CRUD):**\n"
            "• `/set-role add <emoji> <@role/role_id> [description]` - Add a self-assignable role\n"
            "• `/set-role list` - View all configured self-assignable roles\n"
            "• `/set-role update <role_id> <new_emoji> [new_description]` - Update role emoji or description\n"
            "• `/set-role remove <role_id/emoji>` - Remove a role and update the board\n"
            "• `/set-role clear` - Clear all self-assignable roles\n"
            "• `/set-role refresh` - Force re-send or refresh the role board message\n\n"
            "*(Note: All commands also support the exclamation mark prefix, e.g. `!set-role`)*"
        )
        await self.api.send_message(channel_id, content=help_text)

    # ==========================
    # Gateway 反应事件处理 (群员领退角色)
    # ==========================
    async def handle_reaction_add(self, data: Dict[str, Any]) -> None:
        """群员点击 Emoji 反应：赋予对应角色"""
        user_id = str(data.get("user_id"))
        bot_user = self.gateway.bot_user or {}
        if user_id == str(bot_user.get("id")):
            return  # 忽略机器人自身的反应

        guild_id = str(data.get("guild_id") or "")
        message_id = str(data.get("message_id") or "")
        if not guild_id or not message_id:
            return

        cfg = self.storage.get_guild_config(guild_id)
        if str(cfg.get("board_message_id")) != message_id:
            return  # 不是当前公会的角色看板消息，不予处理

        emoji_obj = data.get("emoji") or {}
        emoji_name = (emoji_obj.get("name") or "").strip()
        if not emoji_name:
            return

        role_info = self.storage.get_role_by_emoji(guild_id, emoji_name)
        if not role_info:
            return

        role_id = role_info["role_id"]
        try:
            await self.api.add_member_role(guild_id, user_id, role_id)
            logger.info(f"[Role Added] User {user_id} claimed role {role_info['role_name']} ({role_id}) in guild {guild_id}")
        except Exception as e:
            logger.error(f"Failed to grant role {role_id} to user {user_id}: {e}")

    async def handle_reaction_remove(self, data: Dict[str, Any]) -> None:
        """群员取消 Emoji 反应：移除对应角色"""
        user_id = str(data.get("user_id"))
        bot_user = self.gateway.bot_user or {}
        if user_id == str(bot_user.get("id")):
            return  # 忽略机器人自身的反应

        guild_id = str(data.get("guild_id") or "")
        message_id = str(data.get("message_id") or "")
        if not guild_id or not message_id:
            return

        cfg = self.storage.get_guild_config(guild_id)
        if str(cfg.get("board_message_id")) != message_id:
            return

        emoji_obj = data.get("emoji") or {}
        emoji_name = (emoji_obj.get("name") or "").strip()
        if not emoji_name:
            return

        role_info = self.storage.get_role_by_emoji(guild_id, emoji_name)
        if not role_info:
            return

        role_id = role_info["role_id"]
        try:
            await self.api.remove_member_role(guild_id, user_id, role_id)
            logger.info(f"[Role Removed] User {user_id} un-claimed role {role_info['role_name']} ({role_id}) in guild {guild_id}")
        except Exception as e:
            logger.error(f"Failed to revoke role {role_id} from user {user_id}: {e}")

    # ==========================
    # Gateway 角色删除事件处理 (级联同步)
    # ==========================
    async def handle_guild_role_delete(self, data: Dict[str, Any]) -> None:
        """当公会中有角色被删除时，自动清理配置库中的该角色并更新看板"""
        guild_id = str(data.get("guild_id") or "")
        role_id = str(data.get("role_id") or "")
        if not guild_id or not role_id:
            return

        removed = await self.storage.remove_role(guild_id, role_id)
        if removed:
            logger.info(f"Role {role_id} was deleted from guild {guild_id}, removed from claimables.")
            await self.sync_role_board(guild_id)
