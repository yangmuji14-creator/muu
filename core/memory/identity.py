"""Identity Layer — 独立身份层

身份信息不属于普通记忆，不参与遗忘系统：
    - 教育背景
    - 专业
    - 兴趣爱好
    - 目标
    - 价值观
    - 性格特征
    - 重要人生事件

要求:
    - 独立存储（JSON 文件）
    - 不参与遗忘系统
    - Prompt 优先引用
    - 支持更新与冲突修正

存储:
    data/identities/{user_id}.json
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from core.utils import atomic_write_json

# 校名抓取：只在「大学 / 学院 / 学校」三种后缀上做锚点
_SCHOOL_SUFFIXES = ("大学", "学院", "学校")
# 往前扩词时遇到这些字符就断（标点、代词、助词、常见动词、指示词）。
# 注意不能把「上」放进来 —— 「上海交通大学」会从「上」处断成「海交通大学」。
_SCHOOL_STOP_CHARS = set(
    "。.！!？?，,、；;：: \t\r\n的了在我你他她它读去和与是到这那所么什哪几每"
)
# 候选名以这些字开头说明前面还粘着主语/指示词，不是校名
_SCHOOL_BAD_LEADING = set("我你他她它这那该每几哪么什的了")
# 专名部分最长多少字（含后缀），超出说明抓飞了
_SCHOOL_MAX_LEN = 12
# 候选名里如果还粘着这些动词/介词，从最后一个之后开始截
_SCHOOL_STOP_WORDS = (
    "毕业于", "毕业", "就读于", "就读", "考上了", "考上",
    "来自于", "来自", "去了", "来到", "我是", "我在",
)


def _strip_stop_words(name: str) -> str:
    """把候选校名里粘着的动词/介词剥掉（`毕业于上海交通大学` → `上海交通大学`）。"""
    cut = 0
    for word in _SCHOOL_STOP_WORDS:
        pos = name.rfind(word)
        if pos >= 0:
            cut = max(cut, pos + len(word))
    return name[cut:] if cut else name


def _extract_school(message: str) -> str:
    """从消息里抓校名，返回带后缀的完整名字（抓不到返回空串）。

    旧实现用 `group(1) + "大学"` 拼校名，并且要求后缀后面紧跟标点或句尾 ——
    于是「我在清华学院」被改成「清华大学」（后缀被改写），
    「我在清华大学读书」「我是北京大学的学生」直接一条都抓不到。
    这里改成：定位后缀 → 往前扩到标点/功能字为止 → 原样保留后缀。
    """
    for suffix in _SCHOOL_SUFFIXES:
        start_idx = 0
        while True:
            idx = message.find(suffix, start_idx)
            if idx < 0:
                break
            start_idx = idx + 1
            if idx == 0:
                continue
            start = idx
            while (
                start > 0
                and message[start - 1] not in _SCHOOL_STOP_CHARS
                and idx + len(suffix) - start < _SCHOOL_MAX_LEN
            ):
                start -= 1
            name = _strip_stop_words(message[start: idx + len(suffix)].strip())
            # 专名部分至少两个字（「这所大学」「我在学校」不算校名），
            # 也不能以主语/指示词开头（「我上大学」不算校名）
            if len(name) <= len(suffix) + 1:
                continue
            if name[0] in _SCHOOL_BAD_LEADING:
                continue
            return name
    return ""


@dataclass
class IdentityProfile:
    """用户身份档案"""

    user_id: str

    # 基本信息
    education: str = ""           # 教育背景
    major: str = ""               # 专业
    school: str = ""              # 学校
    grade: str = ""               # 年级/届
    career: str = ""              # 职业
    location: str = ""            # 所在地

    # 兴趣与性格
    interests: list[str] = field(default_factory=list)
    personality_traits: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    communication_style: str = ""  # 沟通风格

    # 目标与价值观
    goals: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    life_events: list[str] = field(default_factory=list)  # 重要人生事件
    important_life_events: list[str] = field(default_factory=list)  # 兼容旧名

    # 偏好
    preferences: dict[str, Any] = field(default_factory=dict)

    # 元数据
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "education": self.education,
            "major": self.major,
            "school": self.school,
            "grade": self.grade,
            "career": self.career,
            "location": self.location,
            "interests": self.interests,
            "personality_traits": self.personality_traits,
            "skills": self.skills,
            "communication_style": self.communication_style,
            "goals": self.goals,
            "values": self.values,
            "life_events": self.life_events,
            "important_life_events": self.important_life_events,
            "preferences": self.preferences,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IdentityProfile":
        return cls(
            user_id=data.get("user_id", ""),
            education=data.get("education", ""),
            major=data.get("major", ""),
            school=data.get("school", ""),
            grade=data.get("grade", ""),
            career=data.get("career", ""),
            location=data.get("location", ""),
            interests=data.get("interests", []),
            personality_traits=data.get("personality_traits", []),
            skills=data.get("skills", []),
            communication_style=data.get("communication_style", ""),
            goals=data.get("goals", []),
            values=data.get("values", []),
            life_events=data.get("life_events", []),
            important_life_events=data.get("important_life_events", []),
            preferences=data.get("preferences", {}),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            version=data.get("version", 1),
        )

    def merge(self, other: "IdentityProfile") -> "IdentityProfile":
        """合并另一个身份画像（新数据覆盖旧数据）"""
        merged = IdentityProfile(user_id=self.user_id)
        for field_name in (
            "education", "major", "career", "location", "school", "grade", "communication_style",
        ):
            val = getattr(other, field_name) or getattr(self, field_name)
            setattr(merged, field_name, val)

        # 列表字段：合并去重
        for list_field in (
            "interests", "goals", "values",
            "personality_traits", "life_events", "important_life_events",
            "skills",
        ):
            combined = list(set(getattr(self, list_field) + getattr(other, list_field)))
            setattr(merged, list_field, combined)

        # dict 字段：合并
        merged_prefs = {**getattr(self, "preferences", {}), **getattr(other, "preferences", {})}
        merged.preferences = merged_prefs

        merged.updated_at = datetime.now().isoformat()
        merged.created_at = self.created_at
        return merged

    def to_prompt(self) -> str:
        """生成身份档案 prompt 块"""
        parts = ["【用户身份档案】"]
        if self.education or self.school or self.major:
            parts.append(f"教育背景：{self.school} {self.education} {self.major}")
        if self.career:
            parts.append(f"职业：{self.career}")
        if self.location:
            parts.append(f"所在地：{self.location}")
        if self.interests:
            parts.append(f"兴趣爱好：{', '.join(self.interests)}")
        if self.personality_traits:
            parts.append(f"性格特征：{', '.join(self.personality_traits)}")
        if self.skills:
            parts.append(f"技能：{', '.join(self.skills)}")
        if self.goals:
            parts.append(f"目标：{', '.join(self.goals)}")
        if self.values:
            parts.append(f"价值观：{', '.join(self.values)}")
        if self.life_events:
            parts.append(f"重要经历：{', '.join(self.life_events)}")
        if self.important_life_events:
            parts.append(f"重要人生事件：{', '.join(self.important_life_events)}")
        return "\n".join(parts)

    def to_prompt_section(self) -> str:
        """生成 Prompt 段落 — 兼容旧版 API"""
        return self.to_prompt()


class IdentityLayer:
    """身份层管理器"""

    def __init__(self, data_dir: str | Path):
        self._data_dir = Path(data_dir)
        self._path = self._data_dir / "identities"
        self._path.mkdir(parents=True, exist_ok=True)

    def _file_path(self, user_id: str) -> Path:
        """获取用户身份文件路径"""
        return self._path / f"{user_id}.json"

    def load(self, user_id: str) -> IdentityProfile:
        """加载用户身份档案"""
        path = self._file_path(user_id)
        if not path.exists():
            return IdentityProfile(user_id=user_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return IdentityProfile.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load identity for {user_id}: {e}")
            return IdentityProfile(user_id=user_id)

    def save(self, profile: IdentityProfile) -> None:
        """保存用户身份档案"""
        profile.updated_at = datetime.now().isoformat()
        path = self._file_path(profile.user_id)
        atomic_write_json(path, profile.to_dict())

    def update(self, user_id: str, /, **kwargs) -> IdentityProfile:
        """更新身份档案字段

        `user_id` 是 positional-only（`/`）：这样 `update(uid, user_id=uid)` 里的
        `user_id=` 会落进 kwargs 而被跳过，而不是在函数入口就抛
        `TypeError: got multiple values for argument 'user_id'` ——
        把一条记录整个展开传进来（`update(uid, **row)`）是最自然的写法。
        """
        profile = self.load(user_id)
        kwargs.pop("user_id", None)
        for key, value in kwargs.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.version += 1
        self.save(profile)
        return profile

    def extract_from_message(self, user_id: str, message: str) -> IdentityProfile:
        """从消息中提取身份线索并更新档案

        简单的规则提取：
            - "我是学计算机的" → major="计算机"
            - "我喜欢Python" → interests += "Python"
            - "我在XX大学" → school="XX大学"
        """
        profile = self.load(user_id)
        changed = False

        # 专业
        major_patterns = [
            r"我是学(.+?)的",
            r"我学(.+?)的",
            r"专业是(.+?)(?:[。.！]|$)",
            r"读(.+?)专业",
        ]
        for pattern in major_patterns:
            match = re.search(pattern, message)
            if match:
                major = match.group(1).strip()
                if major and major != profile.major:
                    profile.major = major
                    changed = True
                break

        # 学校
        school = _extract_school(message)
        if school and school != profile.school:
            profile.school = school
            changed = True

        # 兴趣
        # 一句话里可能有多段「喜欢…」：「我喜欢跑步和游泳」「我喜欢猫，也喜欢狗」
        # 「我喜欢咖啡、喜欢跑步」「我不喜欢你这样但喜欢猫」。
        # 先按标点与转折词切段，每段独立判断 —— 一次贪婪匹配会把
        # 「喜欢你这样但喜欢猫」整串吞掉，后半段的真兴趣就丢了。
        for segment in re.split(r"[。.！!？?，,；;、]|但是|但|不过|可是", message):
            for match in re.finditer(r"(?:喜欢|爱好是|兴趣是|爱好|兴趣)(.+)", segment):
                # 否定式不是兴趣（「我不喜欢下雨」「喜欢和不喜欢」）
                if match.start() > 0 and segment[match.start() - 1] in "不没别":
                    continue
                for piece in match.group(1).split("和"):
                    interest = piece.strip().lstrip("是的")
                    if interest.startswith("不"):
                        continue
                    if interest and interest not in profile.interests:
                        profile.interests.append(interest)
                        changed = True

        # 教育背景
        edu_keywords = {"大一": "大一", "大二": "大二", "大三": "大三", "大四": "大四",
                       "研究生": "研究生", "硕士": "硕士", "博士": "博士"}
        for kw, grade in edu_keywords.items():
            if kw in message and grade != profile.grade:
                profile.grade = grade
                changed = True

        if changed:
            self.save(profile)
            logger.info(f"Identity updated for {user_id}: {profile.to_dict()}")

        return profile

    def get_context(self, user_id: str) -> str:
        """获取身份档案上下文 prompt"""
        profile = self.load(user_id)
        prompt = profile.to_prompt()
        return prompt if "教育背景" in prompt or "兴趣" in prompt else ""

