"""Open Loop Engine — 未完成事件追踪引擎

追踪用户提到的未来/进行中事件：
    - 明天考试
    - 下周面试
    - 正在开发项目
    - 最近感冒
    - 下个月旅行

功能:
    - 自动创建事件
    - 自动追问（24h/48h 后）
    - 自动结束（用户明确回答）
    - 超时失效
    - 状态变更

存储:
    data/open_loops.json — 按用户分组（唯一存储，单轨）

历史说明:
    本模块早期存在一套并行的 SQLite 实现（OpenLoopStorage + detect_and_create /
    check_and_update / check_expired / get_follow_ups / generate_follow_up_message），
    从未被主链路调用，已于 2026-10-22 整块删除，统一为 JSON 单轨。
    `core/storage/constants.py` 的 LEGACY_TABLE_MAPPINGS 仍保留 open_loops.db 映射，
    用于老用户 data/ 目录下遗留数据库的一次性合并。
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger

from core.utils import atomic_write_json


# ========================================================================
# Enums
# ========================================================================

class OpenLoopStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    FAILED = "failed"
    ABANDONED = "abandoned"


class OpenLoopCategory(str, Enum):
    EXAM = "exam"           # 考试
    INTERVIEW = "interview" # 面试
    PROJECT = "project"     # 项目
    HEALTH = "health"       # 健康
    TRAVEL = "travel"       # 旅行
    MOVING = "moving"       # 搬家
    APPOINTMENT = "appointment"  # 预约
    OTHER = "other"         # 其他


# ---- 事件识别模式 ----

_EVENT_PATTERNS = [
    (r"明天(.+?)(?:[。.！]|$)", 1),
    (r"下周(.+?)(?:[。.！]|$)", 7),
    (r"后天(.+?)(?:[。.！]|$)", 2),
    (r"下个月(.+?)(?:[。.！]|$)", 30),
    (r"周末(.+?)(?:[。.！]|$)", 5),
    (r"今晚(.+?)(?:[。.！]|$)", 0),
    (r"正在(.+?)(?:[。.！]|$)", 0),
    (r"最近(.+?)(?:[。.！]|$)", 0),
    (r"过两天(.+?)(?:[。.！]|$)", 2),
    (r"感冒了", 0), (r"生病了", 0), (r"发烧了", 0),
    (r"考试了", 0), (r"面试了", 0), (r"搬家了", 0), (r"毕业了", 0), (r"入职了", 0),
]

_RESOLVE_KEYWORDS = [
    "考完了", "通过了", "挂科了", "失败了", "放弃了", "不去了",
    "结束了", "完成了", "搞定了", "好了", "痊愈了", "康复了",
    "取消了", "延期了", "推迟了",
]

# 标题里的虚词前缀/后缀：剥掉后才能和用户的后续说法对上。
# 例：标题「要面试了」 vs 消息「面试通过了」——不剥就永远匹配不上，
# 事件会一直 pending 到过期。
_TITLE_PREFIXES = ("要", "去", "想", "准备", "得", "会", "有", "在", "把", "被")
_TITLE_SUFFIXES = ("了", "啦", "吧", "呢", "啊", "呀", "的")


def _subject_key(title: str) -> str:
    """从事件标题里取出「主题词」，用于和后续消息做宽松匹配。"""
    text = (title or "").strip()
    if not text:
        return ""
    changed = True
    while changed:
        changed = False
        for prefix in _TITLE_PREFIXES:
            if text.startswith(prefix) and len(text) > len(prefix) + 1:
                text = text[len(prefix):]
                changed = True
                break
        for suffix in _TITLE_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix) + 1:
                text = text[:-len(suffix)]
                changed = True
                break
    return text.strip()


# ========================================================================
# OpenLoop 数据模型
# ========================================================================

@dataclass
class OpenLoop:
    """未完成事件"""
    id: str
    user_id: str = ""
    title: str = ""
    category: str = "other"
    status: str = "pending"
    importance: int = 3
    expected_date: str | None = None
    description: str = ""
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved_at: str | None = None
    last_asked: str | None = None
    ask_count: int = 0
    source_message: str = ""

    # ── 属性 ──

    @property
    def is_active(self) -> bool:
        return self.status == OpenLoopStatus.PENDING

    @property
    def is_closed(self) -> bool:
        return self.status in (OpenLoopStatus.RESOLVED, OpenLoopStatus.FAILED, OpenLoopStatus.ABANDONED)

    @property
    def is_expired(self) -> bool:
        if not self.expected_date or not self.is_active:
            return False
        try:
            expected = datetime.fromisoformat(self.expected_date)
            return datetime.now() > expected + timedelta(days=3)
        except (ValueError, TypeError):
            return False

    @property
    def days_until_expected(self) -> int | None:
        if not self.expected_date:
            return None
        try:
            expected = datetime.fromisoformat(self.expected_date)
            delta = (expected - datetime.now()).total_seconds() / 86400
            return int(delta)
        except (ValueError, TypeError):
            return None

    def should_follow_up(self, hours_since_expected: int = 24) -> bool:
        """判断是否需要追问"""
        if not self.is_active:
            return False
        if not self.expected_date:
            return False
        try:
            expected = datetime.fromisoformat(self.expected_date)
            hours_since = (datetime.now() - expected).total_seconds() / 3600
            return 0 <= hours_since <= hours_since_expected
        except (ValueError, TypeError):
            return False

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "importance": self.importance,
            "expected_date": self.expected_date,
            "description": self.description,
            "tags": self.tags,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
            "last_asked": self.last_asked,
            "ask_count": self.ask_count,
            "source_message": self.source_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenLoop":
        return cls(
            id=data["id"],
            user_id=data.get("user_id", ""),
            title=data.get("title", ""),
            category=data.get("category", "other"),
            status=data.get("status", "pending"),
            importance=data.get("importance", 3),
            expected_date=data.get("expected_date"),
            description=data.get("description", ""),
            tags=data.get("tags", []),
            notes=data.get("notes", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            resolved_at=data.get("resolved_at"),
            last_asked=data.get("last_asked"),
            ask_count=data.get("ask_count", 0),
            source_message=data.get("source_message", ""),
        )


# ========================================================================
# OpenLoopEngine — 未完成事件追踪引擎
# ========================================================================

class OpenLoopEngine:
    """未完成事件追踪引擎（JSON 存储）

    对外 API：
    - detect(user_id, message)        → 从消息中识别新事件
    - get_follow_up(user_id)          → 取一条待追问的话术
    - get_pending(user_id)            → 列出进行中的事件
    - get_context(user_id)            → 生成注入 prompt 的上下文块
    - update_status(...) / expire_old(...)
    """

    def __init__(self, data_dir: str | Path):
        self._data_dir = Path(data_dir)
        self._path = self._data_dir / "open_loops.json"
        self._loops: dict[str, list[OpenLoop]] = {}
        self._load()

    # ── 持久化 ──

    def _load(self):
        """加载 JSON 持久化数据"""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            for user_id, items in data.items():
                self._loops[user_id] = [OpenLoop.from_dict(i) for i in items]
        except Exception as e:
            logger.warning(f"Failed to load open loops: {e}")

    def _save(self):
        """持久化 JSON"""
        try:
            data = {
                uid: [l.to_dict() for l in loops]
                for uid, loops in self._loops.items()
            }
            atomic_write_json(self._path, data)
        except Exception as e:
            logger.error(f"Failed to save open loops: {e}")

    # ── 事件识别 ──

    def detect(self, user_id: str, message: str) -> list[OpenLoop]:
        """从用户消息中检测未完成事件"""
        created: list[OpenLoop] = []
        for pattern, days_offset in _EVENT_PATTERNS:
            match = re.search(pattern, message)
            if match:
                title = match.group(1).strip() if match.groups() else match.group(0).strip()
                if not title:
                    continue
                expected = None
                if days_offset > 0:
                    expected = (datetime.now() + timedelta(days=days_offset)).isoformat()
                loop = OpenLoop(
                    id=f"loop_{datetime.now().strftime('%Y%m%d%H%M%S')}_{len(created)}",
                    user_id=user_id,
                    title=title,
                    category=self._classify(title),
                    expected_date=expected,
                    source_message=message,
                )
                existing = self._find_similar(user_id, title)
                if not existing:
                    self._add(user_id, loop)
                    created.append(loop)
                    logger.info(f"OpenLoop created: {title}")
        self._check_resolved(user_id, message)
        return created

    def _classify(self, title: str) -> str:
        keywords = {
            "exam": ["考试", "测验", "笔试", "科目"],
            "interview": ["面试", "面经", "HR", "offer"],
            "travel": ["旅行", "旅游", "出差", "飞机", "酒店"],
            "health": ["感冒", "生病", "发烧", "医院", "体检", "手术"],
            "project": ["项目", "开发", "代码", "上线", "发布"],
            "move": ["搬家", "租房", "买房", "装修"],
            "study": ["学习", "考研", "雅思", "托福", "GRE"],
            "work": ["工作", "入职", "离职", "跳槽", "辞职"],
        }
        for cat, kws in keywords.items():
            if any(kw in title for kw in kws):
                return cat
        return "other"

    def _find_similar(self, user_id: str, title: str) -> OpenLoop | None:
        loops = self._loops.get(user_id, [])
        for loop in loops:
            if loop.status != "pending":
                continue
            if loop.title in title or title in loop.title:
                return loop
        return None

    def _add(self, user_id: str, loop: OpenLoop) -> None:
        if user_id not in self._loops:
            self._loops[user_id] = []
        self._loops[user_id].append(loop)
        self._save()

    def _check_resolved(self, user_id: str, message: str) -> None:
        loops = self._loops.get(user_id, [])
        if not any(kw in message for kw in _RESOLVE_KEYWORDS):
            return
        for loop in loops:
            if loop.status != "pending":
                continue
            subject = _subject_key(loop.title)
            # 主题词必须出现在消息里；否则「我面试通过了」不该关掉「搬家」这件事。
            matched = bool(subject) and subject in message
            if matched or loop.title in message:
                loop.status = "resolved"
                loop.updated_at = datetime.now().isoformat()
                loop.resolved_at = loop.updated_at
                logger.info(f"OpenLoop resolved: {loop.title}")
                self._save()
                break

    # ── 追问与查询 ──

    def get_follow_up(self, user_id: str) -> str | None:
        """获取需要追问的事件话术"""
        loops = self._loops.get(user_id, [])
        now = datetime.now()
        for loop in loops:
            if loop.status != "pending":
                continue
            if loop.last_asked:
                last = datetime.fromisoformat(loop.last_asked)
                days_since = (now - last).total_seconds() / 86400
                if loop.ask_count == 0 and days_since < 1:
                    continue
                if loop.ask_count == 1 and days_since < 2:
                    continue
                if loop.ask_count >= 2:
                    continue
            else:
                created = datetime.fromisoformat(loop.created_at)
                days_since = (now - created).total_seconds() / 86400
                if days_since < 1:
                    continue
            loop.last_asked = now.isoformat()
            loop.ask_count += 1
            loop.updated_at = now.isoformat()
            self._save()
            templates = [
                f"{loop.title}怎么样了？",
                f"上次说的{loop.title}进行得顺利吗？",
                f"{loop.title}的结果出来了吗？",
            ]
            return templates[min(loop.ask_count - 1, len(templates) - 1)]
        return None

    def get_pending(self, user_id: str) -> list[OpenLoop]:
        """获取用户的 pending 事件"""
        return [l for l in self._loops.get(user_id, []) if l.status == "pending"]

    def get_context(self, user_id: str) -> str:
        """生成 OpenLoop 上下文 prompt"""
        pending = self.get_pending(user_id)
        if not pending:
            return ""
        lines = ["【用户正在经历的事情】"]
        for loop in pending[:5]:
            status = "待完成" if loop.status == "pending" else loop.status
            lines.append(f"- {loop.title}（{status}）")
        return "\n".join(lines)

    def update_status(self, user_id: str, loop_id: str, status: str) -> bool:
        """手动更新事件状态"""
        loops = self._loops.get(user_id, [])
        for loop in loops:
            if loop.id == loop_id:
                loop.status = status
                loop.updated_at = datetime.now().isoformat()
                self._save()
                return True
        return False

    def expire_old(self, user_id: str, max_days: int = 30) -> int:
        """过期超过 max_days 的 pending 事件"""
        loops = self._loops.get(user_id, [])
        now = datetime.now()
        expired = 0
        for loop in loops:
            if loop.status != "pending":
                continue
            created = datetime.fromisoformat(loop.created_at)
            days = (now - created).total_seconds() / 86400
            if days > max_days:
                loop.status = "abandoned"
                loop.updated_at = now.isoformat()
                expired += 1
        if expired:
            self._save()
        return expired
