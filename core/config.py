import json
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
DATA_DIR = _ROOT / "data"

SYSTEM_PROMPT_FILE   = DATA_DIR / "system_prompt.md"
MCP_CONFIG_FILE      = DATA_DIR / "mcp_servers.json"
CONVERSATION_FILE    = DATA_DIR / "conversation.json"
CONFIG_FILE          = DATA_DIR / "config.json"
PREFERENCES_FILE     = DATA_DIR / "preferences.md"


# ─── Helpers ──────────────────────────────────────────────────────
def read_system_prompt() -> str:
    if SYSTEM_PROMPT_FILE.exists():
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    return "You are a helpful assistant."


def load_conversation(platform: str = None, user_id: str = None) -> list:
    """
    加载对话历史

    Args:
        platform: 可选，筛选指定平台（如 "web", "telegram"）
        user_id: 可选，筛选指定用户

    Returns:
        筛选后的对话历史列表
    """
    if CONVERSATION_FILE.exists():
        try:
            all_messages = json.loads(CONVERSATION_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    else:
        all_messages = []

    # 如果没有筛选条件，返回全部
    if platform is None and user_id is None:
        return all_messages

    # 按条件筛选
    filtered = []
    for msg in all_messages:
        meta = msg.get("_meta", {})
        if platform and meta.get("platform") != platform:
            continue
        if user_id and meta.get("user_id") != user_id:
            continue
        filtered.append(msg)

    return filtered


def save_conversation(messages: list, platform: str = "web", user_id: str = None):
    """
    保存对话历史，自动合并到统一文件

    Args:
        messages: 完整对话历史列表（或仅新增的 assistant 消息）
        platform: 来源平台（如 "web", "telegram"）
        user_id: 用户标识
    """
    DATA_DIR.mkdir(exist_ok=True)

    # 加载现有对话
    existing = []
    if CONVERSATION_FILE.exists():
        try:
            existing = json.loads(CONVERSATION_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    # 构建消息索引，用于去重
    seen = {}
    for i, msg in enumerate(existing):
        key = f"{msg.get('role', '')}:{msg.get('content', '')[:50]}"
        seen[key] = i

    # 合并新消息
    for msg in messages:
        if not msg.get("content"):
            continue
        # 添加元数据
        if "_meta" not in msg:
            msg["_meta"] = {}
        msg["_meta"]["platform"] = platform
        if user_id:
            msg["_meta"]["user_id"] = user_id

        # 检查是否已存在（避免重复）
        key = f"{msg.get('role', '')}:{msg.get('content', '')[:50]}"
        if key not in seen:
            existing.append(msg)
            seen[key] = len(existing) - 1

    # 保留最近 200 条消息
    existing = existing[-200:]

    CONVERSATION_FILE.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_preferences() -> str:
    if PREFERENCES_FILE.exists():
        return PREFERENCES_FILE.read_text(encoding="utf-8")
    return ""


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(data: dict):
    DATA_DIR.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
