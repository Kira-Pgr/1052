"""
飞书(Lark) Bot 集成 - 长连接模式，使用交互式卡片
"""

import asyncio
import json
import re
import os
from typing import Callable, Optional

try:
    import lark_oapi as lark
    from lark_oapi import Client
    from lark_oapi.ws import Client as WSClient
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest, CreateMessageRequestBody,
        UpdateMessageRequest, UpdateMessageRequestBody,
        CreateImageRequest, CreateImageRequestBody,
        CreateFileRequest, CreateFileRequestBody
    )
    LARK_AVAILABLE = True
except ImportError as e:
    print(f"[Lark] lark-oapi 导入失败: {e}")
    LARK_AVAILABLE = False

from core.config import DATA_DIR, load_conversation, save_conversation


class LarkBot:
    """飞书机器人，长连接模式，使用交互式卡片"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        encrypt_key: Optional[str] = None,
        verification_token: Optional[str] = None,
        chat_handler: Optional[Callable] = None
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.encrypt_key = encrypt_key
        self.verification_token = verification_token
        self.chat_handler = chat_handler
        self.client: Optional[Client] = None
        self.ws_client = None
        self._enabled = False
        self._task: Optional[asyncio.Task] = None

    @property
    def enabled(self) -> bool:
        return self._enabled and LARK_AVAILABLE

    async def start(self):
        """启动飞书机器人"""
        if not LARK_AVAILABLE:
            print("[Lark] lark-oapi 未安装，跳过")
            return
        if not self.app_id or not self.app_secret:
            print("[Lark] AppID 或 AppSecret 未配置")
            return

        try:
            self.client = lark.Client.builder() \
                .app_id(self.app_id) \
                .app_secret(self.app_secret) \
                .log_level(lark.LogLevel.INFO) \
                .build()

            self._task = asyncio.create_task(self._run_ws())
            self._enabled = True
            print(f"[Lark] 机器人已启动 (AppID: {self.app_id[:8]}...)")

        except Exception as e:
            print(f"[Lark] 启动失败: {e}")

    async def stop(self):
        """停止机器人"""
        if self._task and self._enabled:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._enabled = False
            print("[Lark] 机器人已停止")

    async def _run_ws(self):
        """运行 WebSocket 长连接"""
        try:
            def on_message(data):
                try:
                    asyncio.create_task(self._handle_ws_event(data))
                except Exception as e:
                    print(f"[Lark] 消息处理错误: {e}")

            builder = EventDispatcherHandler.builder(
                self.encrypt_key or "",
                self.verification_token or ""
            )
            event_handler = builder.register_p2_im_message_receive_v1(on_message).build()

            self.ws_client = WSClient(
                app_id=self.app_id,
                app_secret=self.app_secret,
                log_level=lark.LogLevel.INFO,
                event_handler=event_handler,
            )

            await asyncio.to_thread(self.ws_client.start)

        except Exception as e:
            print(f"[Lark] WebSocket 运行失败: {e}")
            await asyncio.sleep(5)
            if self._enabled:
                self._task = asyncio.create_task(self._run_ws())

    async def _handle_ws_event(self, event):
        """处理 WebSocket 事件"""
        try:
            event_type = ""
            if hasattr(event, "header") and event.header:
                event_type = getattr(event.header, "event_type", "")
            elif isinstance(event, dict):
                event_type = event.get("header", {}).get("event_type", "")

            if event_type == "im.message.receive_v1":
                await self._handle_message(event)

        except Exception as e:
            print(f"[Lark] 事件处理错误: {e}")

    async def _handle_message(self, event_data):
        """处理用户消息"""
        if not self.chat_handler:
            return

        if isinstance(event_data, dict):
            event = event_data.get("event", {})
            message = event.get("message", {})
            sender = event.get("sender", {}).get("sender_id", {}).get("open_id", "")
            chat_id = message.get("chat_id", "")
            content = json.loads(message.get("content", "{}"))
            text = content.get("text", "").strip()
        else:
            event = getattr(event_data, "event", None)
            if not event:
                return
            sender = getattr(getattr(event, "sender", None), "sender_id", None)
            sender = getattr(sender, "open_id", "") or ""
            message = getattr(event, "message", None)
            if not message:
                return
            chat_id = getattr(message, "chat_id", "") or ""
            raw_content = getattr(message, "content", "{}") or "{}"
            content = json.loads(raw_content)
            text = content.get("text", "").strip()

        if not text:
            return

        # 处理命令
        if text == "/new":
            self._clear_conversation(sender)
            await self._send_text(chat_id, "✅ 已新建对话")
            return

        if text in ["/help", "帮助"]:
            card = self._build_help_card()
            await self._send_card(chat_id, card)
            return

        if text in ["/压缩上下文", "/compress"]:
            # 启动后台压缩任务
            asyncio.create_task(self._compress_context_task(sender, chat_id))
            return

        if text == "/evolve":
            # 启动进化模式
            from im_integration.evolution import evolution_manager
            if evolution_manager.active:
                await self._send_text(chat_id, "已经在进化模式中，发送任意消息退出")
                return
            result = await evolution_manager.start("lark", sender)
            await self._send_text(chat_id, result)
            return

        # 加载对话历史
        messages = self._load_conversation(sender)
        messages.append({"role": "user", "content": text})

        # 流式处理 - 使用文本消息进行流式更新
        full_response = ""
        thinking_content = []
        current_tool = None
        streaming_msg_id = None  # 文本消息 ID，用于更新
        last_update_time = 0
        update_interval = 1.5  # 1.5秒更新一次
        tool_call_msg_id = None  # 工具调用消息 ID

        try:
            # 1. 先创建初始文本消息
            print(f"[Lark] 创建流式消息, chat_id={chat_id}")
            streaming_msg_id = await self._send_text(chat_id, "正在思考...")
            print(f"[Lark] 流式消息创建结果: {streaming_msg_id}")

            # 2. 流式处理响应
            async for chunk in self.chat_handler(messages):
                chunk_type = chunk.get("type")
                print(f"[Lark] chunk: type={chunk_type}")

                if chunk_type == "delta":
                    delta = chunk.get("content", "")
                    full_response += delta
                    self._extract_thinking(delta, thinking_content)

                    # 节流更新文本消息（每 1.5秒最多一次）
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_update_time >= update_interval and streaming_msg_id:
                        display_text = self._remove_thinking_tags(full_response)
                        display_text = display_text[-2000:] if len(display_text) > 2000 else display_text
                        if display_text:
                            print(f"[Lark] 更新消息, 内容长度={len(display_text)}")
                            await self._update_text_message(streaming_msg_id, display_text + "\n\n思考中...")
                        last_update_time = current_time

                elif chunk_type == "tool_call":
                    tool_name = chunk.get("name", "")
                    current_tool = tool_name
                    thinking_content.append(f"调用工具: {tool_name}")

                    # 工具调用时更新消息
                    if streaming_msg_id:
                        display_text = self._remove_thinking_tags(full_response)
                        update_text = (display_text[-1500:] if len(display_text) > 1500 else display_text) if display_text else ""
                        update_text += f"\n\n使用工具: {tool_name}..."
                        await self._update_text_message(streaming_msg_id, update_text)

                elif chunk_type == "tool_result":
                    result_content = str(chunk.get("result", ""))
                    print(f"[Lark] 工具结果: {result_content[:200]}")

                    # 检测 send_to_lark 工具返回的 [LARK_FILE:xxx] 标记
                    lark_file_match = re.search(r'\[LARK_FILE:([^\]]+)\]', result_content)
                    if lark_file_match:
                        file_path = lark_file_match.group(1)
                        await self._send_file(chat_id, file_path)

                    thinking_content.append("工具执行完成")
                    current_tool = None

                    # 工具结果后更新消息
                    if streaming_msg_id:
                        display_text = self._remove_thinking_tags(full_response)
                        update_text = (display_text[-1500:] if len(display_text) > 1500 else display_text) if display_text else ""
                        update_text += "\n\n工具执行完成，继续思考..."
                        await self._update_text_message(streaming_msg_id, update_text)

                elif chunk_type == "file":
                    file_path = chunk.get("url", "")
                    await self._send_file(chat_id, file_path)

                elif chunk_type == "error":
                    error_text = f"错误: {chunk.get('content', '')}"
                    if streaming_msg_id:
                        await self._update_text_message(streaming_msg_id, error_text)
                    else:
                        await self._send_text(chat_id, error_text)
                    return

            # 3. 最终结果 - 发送结果卡片
            print(f"[Lark] 流式处理完成")
            final_display = self._remove_thinking_tags(full_response)

            # 发送结果卡片
            result_card = self._build_result_card(
                final_display,
                thinking_content,
                None,
                "green"
            )
            await self._send_card(chat_id, result_card)

            # 删除中间的流式消息
            if streaming_msg_id:
                try:
                    from lark_oapi.api.im.v1 import DeleteMessageRequest
                    delete_request = DeleteMessageRequest.builder() \
                        .message_id(streaming_msg_id) \
                        .build()
                    self.client.im.v1.message.delete(delete_request)
                    print(f"[Lark] 删除中间消息成功")
                except Exception as e:
                    print(f"[Lark] 删除中间消息失败: {e}")

        except Exception as e:
            print(f"[Lark] 流式处理异常: {e}")
            import traceback
            traceback.print_exc()
            await self._send_text(chat_id, f"处理异常: {str(e)[:200]}")

        # 保存对话
        print(f"[Lark] 保存对话: sender={sender}, messages数量={len(messages)}")
        messages.append({"role": "assistant", "content": full_response})
        self._save_conversation(sender, messages[-20:])

        # 验证保存
        saved = load_conversation(platform="lark", user_id=sender)
        print(f"[Lark] 验证保存: 加载到 {len(saved)} 条消息")

    def _extract_thinking(self, text: str, thinking_content: list):
        """提取思考标签内容"""
        # 提取 <result>...</result>
        for match in re.finditer(r'<result>([\s\S]*?)</result>', text):
            content = match.group(1).strip()
            if content:
                thinking_content.append(content)
        # 提取 <thinking>...</thinking>
        for match in re.finditer(r'<thinking>([\s\S]*?)</thinking>', text):
            content = match.group(1).strip()
            if content:
                thinking_content.append(content)
        # 提取 <think>...</think> ( Anthropic 格式)
        for match in re.finditer(r'<think>([\s\S]*?)</think>', text):
            content = match.group(1).strip()
            if content:
                thinking_content.append(content)

    def _build_streaming_card(self, content: str, thinking: list, tool_name: str = None, header_color: str = "blue") -> dict:
        """构建流式输出卡片（简化版，兼容飞书）"""
        main_content = self._remove_thinking_tags(content)

        elements = []

        # 状态栏
        if tool_name:
            status_text = f"使用工具: {tool_name}"
        elif content:
            status_text = "生成回答中..."
        else:
            status_text = "正在思考..."
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": status_text
            }
        })

        # 主内容 - 限制在 2000 字符以内
        if main_content.strip():
            display_content = main_content[:2000]
            if len(main_content) > 2000:
                display_content += "\n\n(内容过长已截断)"
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": display_content
                }
            })
        else:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "等待响应..."
                }
            })

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "AI 思考中"},
                "template": header_color
            },
            "elements": elements
        }

    def _build_result_card(self, content: str, thinking: list, tool_name: str = None, header_color: str = "green") -> dict:
        """构建结果卡片（简化版，兼容飞书）"""
        main_content = self._remove_thinking_tags(content)

        elements = []

        # 成功状态
        if tool_name:
            status_text = f"回答完成 (使用工具: {tool_name})"
        else:
            status_text = "回答完成"
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": status_text
            }
        })

        elements.append({"tag": "hr"})

        # 主内容 - 限制在 2500 字符以内
        if main_content.strip():
            display_content = main_content[:2500]
            if len(main_content) > 2500:
                display_content += "\n\n(内容过长已截断)"
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": display_content
                }
            })

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "回答完成"},
                "template": header_color
            },
            "elements": elements
        }

    def _build_help_card(self) -> dict:
        """构建帮助卡片（简化版）"""
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "1052 AI 助理"},
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**欢迎使用 1052 AI 助理！**\n\n直接发送消息开始对话，支持：\n\n- 文字对话\n- 图片分析\n- 文件处理\n- 工具调用"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**命令：**\n\n- /new - 新建对话\n- /compress - 压缩对话历史\n- /evolve - 开启进化模式\n- /help - 显示帮助"
                    }
                }
            ]
        }

    def _remove_thinking_tags(self, text: str) -> str:
        """移除思考标签"""
        text = re.sub(r'<result>[\s\S]*?</result>', '', text)
        text = re.sub(r'<thinking>[\s\S]*?</thinking>', '', text)
        text = re.sub(r'<think>[\s\S]*?</think>', '', text)
        return text.strip()

    async def _create_streaming_card(self, chat_id: str) -> str:
        """创建流式卡片，返回消息 ID"""
        card = self._build_streaming_card("💭 正在思考...", [], "blue")
        return await self._send_card(chat_id, card)

    async def _send_card(self, chat_id: str, card: dict) -> str:
        """发送卡片消息"""
        try:
            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("interactive") \
                .content(json.dumps(card, ensure_ascii=False)) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            response = self.client.im.v1.message.create(request)

            if response.success():
                return response.data.message_id
            else:
                print(f"[Lark] 发送卡片失败: {response.msg}")
                return ""

        except Exception as e:
            print(f"[Lark] 发送卡片异常: {e}")
            return ""

    async def _update_card(self, message_id: str, card: dict):
        """更新卡片（通过删除+重建实现）"""
        if not message_id:
            return False

        try:
            # 1. 删除旧卡片
            from lark_oapi.api.im.v1 import DeleteMessageRequest
            delete_request = DeleteMessageRequest.builder() \
                .message_id(message_id) \
                .build()
            delete_response = self.client.im.v1.message.delete(delete_request)

            if not delete_response.success():
                print(f"[Lark] 删除旧卡片失败: {delete_response.msg}")
                return False

            return True

        except Exception as e:
            print(f"[Lark] 更新卡片异常: {e}")
            return False

    async def _update_text_message(self, message_id: str, text: str):
        """更新文本消息"""
        if not message_id:
            return

        try:
            if len(text) > 3000:
                text = text[:3000] + "\n...(内容已截断)"

            body = UpdateMessageRequestBody.builder() \
                .msg_type("text") \
                .content(json.dumps({"text": text}, ensure_ascii=False)) \
                .build()

            request = UpdateMessageRequest.builder() \
                .message_id(message_id) \
                .request_body(body) \
                .build()

            response = self.client.im.v1.message.update(request)

            if not response.success():
                print(f"[Lark] 更新文本失败: {response.msg}")

        except Exception as e:
            print(f"[Lark] 更新文本异常: {e}")

    async def _send_text(self, chat_id: str, text: str) -> str:
        """发送纯文本消息（备用）"""
        try:
            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("text") \
                .content(json.dumps({"text": text}, ensure_ascii=False)) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            response = self.client.im.v1.message.create(request)

            if response.success():
                return response.data.message_id
            else:
                print(f"[Lark] 发送文本失败: {response.msg}")
                return ""

        except Exception as e:
            print(f"[Lark] 发送文本异常: {e}")
            return ""

    async def _send_file(self, chat_id: str, file_path: str):
        """发送文件"""
        if not file_path:
            return

        if file_path.startswith("/files/"):
            filename = file_path[8:]
            local_path = str(DATA_DIR / "1111" / filename)
        elif not os.path.isabs(file_path):
            local_path = str(DATA_DIR / "1111" / file_path)
        else:
            local_path = file_path

        local_path = os.path.normpath(local_path)

        if not os.path.exists(local_path):
            print(f"[Lark] 文件不存在: {local_path}")
            return

        try:
            filename_lower = local_path.lower()

            if filename_lower.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                await self._send_image(chat_id, local_path)
            else:
                await self._send_document(chat_id, local_path)

        except Exception as e:
            print(f"[Lark] 发送文件失败: {e}")

    async def _send_image(self, chat_id: str, image_path: str):
        """发送图片"""
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()

            upload_request = CreateImageRequest.builder() \
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(image_data)
                    .build()
                ) \
                .build()

            upload_response = self.client.im.v1.image.create(upload_request)

            if not upload_response.success():
                print(f"[Lark] 上传图片失败: {upload_response.msg}")
                return

            image_key = upload_response.data.image_key

            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("image") \
                .content(json.dumps({"image_key": image_key}, ensure_ascii=False)) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            response = self.client.im.v1.message.create(request)

            if response.success():
                print(f"[Lark] 图片发送成功")
            else:
                print(f"[Lark] 发送图片失败: {response.msg}")

        except Exception as e:
            print(f"[Lark] 发送图片异常: {e}")

    async def _send_document(self, chat_id: str, file_path: str):
        """发送文件"""
        try:
            with open(file_path, 'rb') as f:
                file_data = f.read()

            filename = os.path.basename(file_path)

            if filename.lower().endswith(('.mp3', '.wav', '.m4a', '.ogg')):
                file_type = "audio"
            elif filename.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')):
                file_type = "video"
            else:
                file_type = "file"

            upload_request = CreateFileRequest.builder() \
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_name(filename)
                    .file_size(str(len(file_data)))
                    .file_type(file_type)
                    .content(file_data)
                    .build()
                ) \
                .build()

            upload_response = self.client.im.v1.file.create(upload_request)

            if not upload_response.success():
                print(f"[Lark] 上传文件失败: {upload_response.msg}")
                return

            file_key = upload_response.data.file_key

            body = CreateMessageRequestBody.builder() \
                .receive_id(chat_id) \
                .msg_type("file") \
                .content(json.dumps({"file_key": file_key}, ensure_ascii=False)) \
                .build()

            request = CreateMessageRequest.builder() \
                .receive_id_type("chat_id") \
                .request_body(body) \
                .build()

            response = self.client.im.v1.message.create(request)

            if response.success():
                print(f"[Lark] 文件发送成功")
            else:
                print(f"[Lark] 发送文件失败: {response.msg}")

        except Exception as e:
            print(f"[Lark] 发送文件异常: {e}")

    def _load_conversation(self, user_id: str) -> list:
        """加载用户对话历史（统一会话）"""
        return load_conversation(platform="lark", user_id=user_id)

    def _save_conversation(self, user_id: str, messages: list):
        """保存用户对话历史到统一会话"""
        save_conversation(messages, platform="lark", user_id=user_id)

    def _clear_conversation(self, user_id: str):
        """清空对话历史"""
        conv_file = DATA_DIR / "conversation.json"
        if conv_file.exists():
            try:
                all_messages = json.loads(conv_file.read_text(encoding="utf-8"))
                all_messages = [m for m in all_messages
                              if m.get("_meta", {}).get("user_id") != user_id
                              or m.get("_meta", {}).get("platform") != "lark"]
                conv_file.write_text(json.dumps(all_messages, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    async def _compress_context_task(self, user_id: str, chat_id: str):
        """后台压缩上下文任务"""
        try:
            # 1. 发送压缩开始提示
            await self._send_text(chat_id,
                "🔄 **正在压缩上下文...**\n\n"
                "📋 即将进行以下操作：\n"
                "• 分析并理解对话历史\n"
                "• 提取关键信息和要点\n"
                "• 生成压缩摘要\n\n"
                "⏱️ 预计需要 **1-2 分钟**，请稍候...\n\n"
                "💡 压缩期间您可以继续使用，任务会在后台完成。"
            )

            # 2. 加载对话历史
            messages = self._load_conversation(user_id)

            if len(messages) < 10:
                await self._send_text(chat_id,
                    "📝 **上下文较短，无需压缩**\n\n"
                    "当前对话历史较少（少于 10 条），无需压缩。\n"
                    "继续对话直到历史积累较多后再试。"
                )
                return

            # 3. 保留最近的消息（user 最后一条 + assistant 最后一条 + 系统提示位置前的消息）
            # 找到最后一个 user 消息和 assistant 消息
            recent_user_idx = -1
            recent_asst_idx = -1
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user" and recent_user_idx == -1:
                    recent_user_idx = i
                elif messages[i].get("role") == "assistant" and recent_asst_idx == -1:
                    recent_asst_idx = i
                if recent_user_idx != -1 and recent_asst_idx != -1:
                    break

            # 需要保留的消息：最近的 user + assistant 消息对
            preserve_count = max(recent_user_idx, recent_asst_idx) + 1 if recent_user_idx != -1 and recent_asst_idx != -1 else len(messages)

            # 4. 调用 AI 进行摘要压缩
            old_messages = messages[:-preserve_count] if preserve_count < len(messages) else []
            compress_prompt = self._build_compress_prompt(old_messages)
            print(f"[Lark] 压缩上下文: 总消息={len(messages)}, 旧消息={len(old_messages)}, prompt长度={len(compress_prompt)}")

            summary_done = False
            summary_text = ""

            if not compress_prompt:
                # 没有旧消息需要压缩
                await self._send_text(chat_id,
                    "📝 **上下文较短，无需压缩**\n\n"
                    "当前对话历史较少，无需压缩。"
                )
                return

            if not self.chat_handler:
                await self._send_text(chat_id,
                    "❌ **chat_handler 未配置**\n\n"
                    "压缩功能需要配置 chat_handler。"
                )
                return

            if compress_prompt and self.chat_handler:
                try:
                    # 构建摘要请求
                    summarize_messages = [
                        {"role": "system", "content": "你是一个对话历史压缩助手。你的任务是将冗长的对话历史压缩成简洁的摘要，保留关键信息和要点。"},
                        {"role": "user", "content": compress_prompt}
                    ]

                    # 调用流式 handler 获取摘要
                    async for chunk in self.chat_handler(summarize_messages):
                        if chunk.get("type") == "delta":
                            summary_text += chunk.get("content", "")

                    if summary_text:
                        summary_text = self._remove_thinking_tags(summary_text).strip()
                        summary_done = True
                except Exception as e:
                    print(f"[Lark] 摘要生成失败: {e}")

            # 5. 更新对话历史
            if summary_done and summary_text:
                # 保留最新的一对对话（user + assistant），将更早的历史替换为摘要
                new_messages = []

                # 添加摘要作为 assistant 的压缩消息
                new_messages.append({
                    "role": "assistant",
                    "content": f"【上下文压缩摘要】\n\n{summary_text[:2000]}",
                    "_meta": {"platform": "lark", "user_id": user_id, "compressed": True}
                })

                # 添加保留的最近对话
                if preserve_count > 0:
                    new_messages.extend(messages[-preserve_count:])

                # 保存压缩后的对话
                self._save_compressed_conversation(user_id, new_messages)

                await self._send_text(chat_id,
                    "✅ **上下文压缩完成！**\n\n"
                    f"📊 **压缩结果：**\n"
                    f"• 原始消息数：{len(messages)} 条\n"
                    f"• 压缩后：1 条摘要 + {preserve_count} 条最近对话\n"
                    f"• 压缩比：约 {int((1 - len(new_messages)/len(messages))*100)}%\n\n"
                    "🔄 您可以继续对话，上下文已精简。"
                )
            else:
                # 没有成功摘要，但已经等待了一段时间，给用户反馈
                await self._send_text(chat_id,
                    "⏰ **压缩任务已超时**\n\n"
                    "由于摘要生成超时，上下文未被压缩。\n"
                    "您可以稍后重试，或使用 `/new` 新建对话。"
                )

        except Exception as e:
            print(f"[Lark] 压缩上下文异常: {e}")
            await self._send_text(chat_id, f"❌ **压缩失败**：{str(e)[:100]}")

    def _build_compress_prompt(self, messages: list) -> str:
        """构建压缩提示"""
        if not messages:
            return ""

        # 将消息格式化为文本
        formatted = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if content:
                role_name = {"user": "用户", "assistant": "助手", "system": "系统"}.get(role, role)
                formatted.append(f"**{role_name}：**\n{content[:500]}")

        if not formatted:
            return ""

        separator = "=" * 50
        prompt = f"""请将以下对话历史压缩成简洁的摘要，保留关键信息和要点：

---
{separator.join(formatted)}
---

压缩要求：
1. 提取对话的主要话题和目标
2. 记录重要的结论和决定
3. 保留关键的用户偏好和信息
4. 使用简洁的语言，不超过 500 字

请直接输出压缩后的摘要，不需要解释。"""

        return prompt

    def _save_compressed_conversation(self, user_id: str, messages: list):
        """保存压缩后的对话历史"""
        conv_file = DATA_DIR / "conversation.json"
        try:
            all_messages = []
            if conv_file.exists():
                all_messages = json.loads(conv_file.read_text(encoding="utf-8"))

            # 移除该用户的旧消息
            all_messages = [m for m in all_messages
                          if m.get("_meta", {}).get("user_id") != user_id
                          or m.get("_meta", {}).get("platform") != "lark"]

            # 添加压缩后的消息
            all_messages.extend(messages)

            # 保留最近 200 条
            all_messages = all_messages[-200:]

            conv_file.write_text(json.dumps(all_messages, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[Lark] 保存压缩对话失败: {e}")

