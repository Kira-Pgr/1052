"""
IM 集成路由 - Telegram、飞书配置、进化模式
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

from core.config import load_config, save_config

router = APIRouter()


class TelegramConfig(BaseModel):
    enabled: bool
    token: Optional[str] = None


class LarkConfig(BaseModel):
    enabled: bool
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    encrypt_key: Optional[str] = None           # 加密密钥（可选，用于消息加密）
    verification_token: Optional[str] = None    # 验证令牌（可选，用于回调验证）


class IMConfig(BaseModel):
    telegram: TelegramConfig
    lark: LarkConfig


@router.get("/im/status")
async def get_im_status(request: Request):
    """获取 IM 状态"""
    manager = request.app.state.im_manager
    return manager.get_status()


@router.get("/im/config")
async def get_im_config():
    """获取 IM 配置（敏感字段脱敏）"""
    cfg = load_config()
    im_cfg = cfg.get("im", {})

    tg = im_cfg.get("telegram", {})
    lark = im_cfg.get("lark", {})

    return {
        "telegram": {
            "enabled": tg.get("enabled", False),
            "token_set": bool(tg.get("token")),
            "token_hint": _mask_token(tg.get("token", "")) if tg.get("token") else "",
        },
        "lark": {
            "enabled": lark.get("enabled", False),
            "app_id_set": bool(lark.get("app_id")),
            "app_id": lark.get("app_id", "")[:8] + "..." if lark.get("app_id") else "",
            "app_secret_set": bool(lark.get("app_secret")),
            "encrypt_key_set": bool(lark.get("encrypt_key")),
            "verification_token_set": bool(lark.get("verification_token")),
        }
    }


@router.put("/im/config")
async def update_im_config(body: IMConfig, request: Request):
    """更新 IM 配置"""
    cfg = load_config()

    old_im = cfg.get("im", {})

    # 合并配置（保留旧值如果新值为空）
    new_cfg = {
        "telegram": {
            "enabled": body.telegram.enabled,
            "token": body.telegram.token or old_im.get("telegram", {}).get("token", ""),
        },
        "lark": {
            "enabled": body.lark.enabled,
            "app_id": body.lark.app_id or old_im.get("lark", {}).get("app_id", ""),
            "app_secret": body.lark.app_secret or old_im.get("lark", {}).get("app_secret", ""),
            "encrypt_key": body.lark.encrypt_key or old_im.get("lark", {}).get("encrypt_key", ""),
            "verification_token": body.lark.verification_token or old_im.get("lark", {}).get("verification_token", ""),
        }
    }

    # 如果显式传了空字符串，则清空
    if body.telegram.token == "":
        new_cfg["telegram"]["token"] = ""
    if body.lark.app_id == "":
        new_cfg["lark"]["app_id"] = ""
    if body.lark.app_secret == "":
        new_cfg["lark"]["app_secret"] = ""
    if body.lark.encrypt_key == "":
        new_cfg["lark"]["encrypt_key"] = ""
    if body.lark.verification_token == "":
        new_cfg["lark"]["verification_token"] = ""

    cfg["im"] = new_cfg
    save_config(cfg)

    # 重载 IM 管理器
    manager = request.app.state.im_manager
    await manager.reload()

    return {"ok": True}


@router.post("/im/reload")
async def reload_im(request: Request):
    """手动重载 IM"""
    manager = request.app.state.im_manager
    await manager.reload()
    return manager.get_status()


def _mask_token(token: str) -> str:
    """脱敏显示 Token"""
    if len(token) > 10:
        return token[:5] + "..." + token[-5:]
    return "***"


# ─── 进化模式 API ────────────────────────────────────────────────

@router.get("/im/evolution/status")
async def get_evolution_status():
    """获取进化模式状态"""
    from im_integration.evolution import evolution_manager
    status = evolution_manager.get_status()
    return {
        "active": status.active,
        "platform": status.platform,
        "user_id": status.user_id,
        "start_time": status.start_time,
        "log_file": status.log_file,
        "last_run": status.last_run,
        "result_count": status.result_count,
    }


class EvolutionStartRequest(BaseModel):
    platform: str = "web"
    user_id: str = "web_user"


@router.post("/im/evolution/start")
async def start_evolution(body: EvolutionStartRequest):
    """启动进化模式"""
    from im_integration.evolution import evolution_manager
    if evolution_manager.active:
        return {"ok": False, "message": "已经在进化模式中"}
    result = await evolution_manager.start(body.platform, body.user_id)
    return {"ok": True, "message": result}


@router.post("/im/evolution/stop")
async def stop_evolution():
    """停止进化模式"""
    from im_integration.evolution import evolution_manager
    if not evolution_manager.active:
        return {"ok": False, "message": "进化模式未启动"}
    result = await evolution_manager.stop()
    return {"ok": True, "message": result}


@router.get("/im/evolution/logs")
async def get_evolution_logs():
    """获取进化日志"""
    from im_integration.evolution import evolution_manager
    logs = evolution_manager.get_logs()
    return {"logs": logs}


# ─── 压缩上下文 API ────────────────────────────────────────────────

class CompressRequest(BaseModel):
    platform: str = "web"
    user_id: str = "web_user"


@router.post("/im/compress")
async def compress_context(body: CompressRequest, request: Request):
    """触发上下文压缩（后台执行）"""
    import asyncio

    # 获取 chat_handler
    chat_handler = getattr(request.app.state, "chat_handler", None)
    if not chat_handler:
        return {"ok": False, "message": "聊天处理器未配置"}

    # 启动后台压缩任务
    asyncio.create_task(
        _run_compress_task(body.platform, body.user_id, chat_handler)
    )

    # 返回压缩前的统计信息
    from core.config import load_conversation
    messages = load_conversation(platform=body.platform, user_id=body.user_id)
    original_count = len(messages)

    # 预估保留数量
    preserve_count = 2  # 假设保留最近一对对话

    return {
        "ok": True,
        "original_count": original_count,
        "preserve_count": preserve_count,
        "compress_ratio": int((1 - (preserve_count + 1) / max(original_count, 1)) * 100)
    }


async def _run_compress_task(platform: str, user_id: str, chat_handler):
    """执行压缩任务的辅助函数"""
    import json
    import re
    from core.config import DATA_DIR, load_conversation, save_conversation

    try:
        # 加载对话历史
        messages = load_conversation(platform=platform, user_id=user_id)

        if len(messages) < 10:
            return

        # 计算需要保留的消息
        recent_user_idx = -1
        recent_asst_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user" and recent_user_idx == -1:
                recent_user_idx = i
            elif messages[i].get("role") == "assistant" and recent_asst_idx == -1:
                recent_asst_idx = i
            if recent_user_idx != -1 and recent_asst_idx != -1:
                break

        preserve_count = max(recent_user_idx, recent_asst_idx) + 1 if recent_user_idx != -1 and recent_asst_idx != -1 else len(messages)
        old_messages = messages[:-preserve_count] if preserve_count < len(messages) else []

        # 构建压缩提示
        def build_compress_prompt(msgs):
            if not msgs:
                return ""
            formatted = []
            for msg in msgs:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if content:
                    role_name = {"user": "用户", "assistant": "助手", "system": "系统"}.get(role, role)
                    formatted.append(f"**{role_name}：**\n{content[:500]}")
            if not formatted:
                return ""
            separator = "=" * 50
            return f"""请将以下对话历史压缩成简洁的摘要，保留关键信息和要点：

---
{separator.join(formatted)}
---

压缩要求：
1. 提取对话的主要话题和目标
2. 记录重要的结论和决定
3. 保留关键的用户偏好和信息
4. 使用简洁的语言，不超过 500 字

请直接输出压缩后的摘要，不需要解释。"""

        compress_prompt = build_compress_prompt(old_messages)
        summary_text = ""

        if compress_prompt:
            try:
                summarize_messages = [
                    {"role": "system", "content": "你是一个对话历史压缩助手。你的任务是将冗长的对话历史压缩成简洁的摘要，保留关键信息和要点。"},
                    {"role": "user", "content": compress_prompt}
                ]

                async for chunk in chat_handler(summarize_messages):
                    if chunk.get("type") == "delta":
                        summary_text += chunk.get("content", "")

                if summary_text:
                    # 清理思考标签
                    summary_text = re.sub(r'<result>[\s\S]*?</result>', '', summary_text)
                    summary_text = re.sub(r'<thinking>[\s\S]*?</thinking>', '', summary_text)
                    # 清理 <think>...</think> 标签（使用简单字符串替换）
                    summary_text = summary_text.replace('<think>', '').replace('</think>', '')
                    summary_text = summary_text.strip()
            except Exception as e:
                print(f"[Compress] 摘要生成失败: {e}")
                return

        # 构建新消息
        new_messages = []
        if summary_text:
            new_messages.append({
                "role": "assistant",
                "content": f"【上下文压缩摘要】\n\n{summary_text[:2000]}",
                "_meta": {"platform": platform, "user_id": user_id, "compressed": True}
            })

        if preserve_count > 0:
            new_messages.extend(messages[-preserve_count:])

        # 保存压缩后的对话
        conv_file = DATA_DIR / "conversation.json"
        try:
            all_messages = []
            if conv_file.exists():
                all_messages = json.loads(conv_file.read_text(encoding="utf-8"))

            all_messages = [m for m in all_messages
                          if m.get("_meta", {}).get("user_id") != user_id
                          or m.get("_meta", {}).get("platform") != platform]

            all_messages.extend(new_messages)
            all_messages = all_messages[-200:]

            conv_file.write_text(json.dumps(all_messages, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[Compress] 压缩完成: {platform}/{user_id}")
        except Exception as e:
            print(f"[Compress] 保存压缩对话失败: {e}")

    except Exception as e:
        print(f"[Compress] 压缩上下文异常: {e}")
