"""性格标签 → 行为描述 的翻译表（CLI 向导与 WebUI 共用）

数据源是 `config/persona_tags.json`。**支持两代 schema**：

## v2（当前，推荐）

```json
{
  "version": 2,
  "max_tags": 3,
  "mutex_groups": [["话痨", "高冷"]],
  "tags": {
    "温柔": {
      "speaking": "语气温和耐心……",
      "emotion": "善于安抚对方情绪……",
      "relationship": "会主动照顾对方的情绪……",
      "hard_rules": []
    }
  }
}
```

每个标签产出**三句人话 + 零到多条硬规则**，落点固定为四个契约 key：

| 标签字段 | 写入 persona 的位置 | 消费方 |
|---|---|---|
| `speaking` | `speaking_style["基础风格"]` | `prompt_builder.py:198`、`proactive.py:218` |
| `emotion` | `emotional_patterns["情感表达"]` | `prompt_builder.py:215` |
| `relationship` | `relationship_behavior["相处模式"]` | `prompt_builder.py:257` |
| `hard_rules` | `hard_rules`（列表去重追加） | `prompt_builder.py:117` |

v1 的问题是「翻译表产出 16 个 key，消费方只认其中 1~3 个」，命中率 1/16，
80% 的内容是死数据。v2 用**固定的三个落点**保证每个标签都真正进 prompt。

## v1（历史，仍可读）

```json
{"话痨": {"speaking_style": {"说话量": "话多，经常连发多条消息"}}}
```

顶层 key 是标签名，第二层是行为层（speaking_style / emotional_patterns /
relationship_behavior / hard_rules），第三层是具体字段。v1 走原来的
`setdefault` 合并语义（已存在的字段不覆盖），保持向后兼容。

CLI 的 setup_wizard 与 WebUI 的建人接口都走这里，**不要再各自实现一份**
—— 两处逻辑漂移会让同一个人设在两个入口得到不同行为规则。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

# 行为层：合并时这些层即使没有标签也要保证存在（下游 PromptBuilder 会读）
DEFAULT_LAYERS = ("speaking_style", "emotional_patterns", "relationship_behavior")

# 这些顶层 key 是列表而非 dict，合并方式不同
LIST_LAYERS = ("hard_rules",)

# v2 标签字段 → persona 落点。顺序决定 prompt 里的呈现顺序。
V2_LAYER_KEYS = (
    ("speaking", "speaking_style", "基础风格"),
    ("emotion", "emotional_patterns", "情感表达"),
    ("relationship", "relationship_behavior", "相处模式"),
)

# v2 的默认多选上限。前端与后端都读这个值，避免两处写死不同的数字。
DEFAULT_MAX_TAGS = 3

# 冲突合并时用的分隔符。用全角分号而不是逗号，让「两个来源」在视觉上
# 能分开，同时仍然是合法的一句中文。
CONFLICT_JOINER = "；"


def tags_path() -> Path:
    """persona_tags.json 的位置（与 personas.json 同目录）"""
    from core.config import CONFIG_DIR

    return CONFIG_DIR / "persona_tags.json"


def load_persona_tags() -> dict[str, Any]:
    """读取 persona_tags.json 的**原始**结构。

    文件缺失或损坏时返回空 dict（调用方应降级为纯手填，不阻断建人）。
    返回的是原始 JSON，v1/v2 的差异由 `tag_names()` / `tag_specs()` 吸收。
    """
    path = tags_path()
    if not path.exists():
        logger.debug(f"persona_tags.json not found: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load persona tags: {e}")
        return {}


def _v2_block(data: dict[str, Any]) -> dict[str, Any] | None:
    """取出 v2 的 tags 块；不是 v2 结构时返回 None。

    判定条件：顶层有 `tags`，且它是 dict。v1 的顶层 key 全是标签名，
    不会出现 `tags` 这个 key（除非用户真造了个叫 tags 的标签——那种情况下
    它的值也不会是 dict of dict，会退化成 v1 处理，不会静默丢标签）。
    """
    tags = data.get("tags")
    if isinstance(tags, dict) and all(isinstance(v, dict) for v in tags.values()):
        return tags
    return None


def is_v2(data: dict[str, Any] | None = None) -> bool:
    """当前翻译表是否为 v2 结构"""
    if data is None:
        data = load_persona_tags()
    return _v2_block(data) is not None


def tag_names() -> list[str]:
    """所有可选性格标签名（供前端下拉/标签选择器），保持文件里的顺序"""
    data = load_persona_tags()
    v2 = _v2_block(data)
    if v2 is not None:
        return list(v2.keys())
    return list(data.keys())


def max_tags() -> int:
    """多选上限。v2 读文件里的 `max_tags`，v1 与缺省一律 3。"""
    data = load_persona_tags()
    if _v2_block(data) is None:
        return DEFAULT_MAX_TAGS
    try:
        n = int(data.get("max_tags") or DEFAULT_MAX_TAGS)
    except (TypeError, ValueError):
        return DEFAULT_MAX_TAGS
    return n if n > 0 else DEFAULT_MAX_TAGS


def mutex_groups() -> list[list[str]]:
    """互斥标签对。只用于**提示与自动取消**，后端不因冲突拒绝请求。"""
    data = load_persona_tags()
    raw = data.get("mutex_groups")
    if not isinstance(raw, list):
        return []
    out: list[list[str]] = []
    for group in raw:
        if isinstance(group, list):
            names = [str(t).strip() for t in group if str(t).strip()]
            if len(names) >= 2:
                out.append(names)
    return out


def tag_specs() -> list[dict[str, Any]]:
    """前端用的完整标签规格：名字 + 三句描述 + 硬规则。

    v1 的标签没有这三句，返回空字符串——前端据此判断「这个标签只写字段，
    不产出草稿」，退化成一个纯标记而非可预览草稿。
    """
    data = load_persona_tags()
    v2 = _v2_block(data)
    if v2 is None:
        return [
            {"name": name, "speaking": "", "emotion": "", "relationship": "", "hard_rules": []}
            for name in data.keys()
        ]
    specs = []
    for name, spec in v2.items():
        specs.append(
            {
                "name": name,
                "speaking": str(spec.get("speaking") or "").strip(),
                "emotion": str(spec.get("emotion") or "").strip(),
                "relationship": str(spec.get("relationship") or "").strip(),
                "hard_rules": [str(r).strip() for r in (spec.get("hard_rules") or []) if str(r).strip()],
            }
        )
    return specs


def _merge_text(values: list[str]) -> str:
    """把多个标签的同一层描述合成一句。

    去重（完全相同的不重复）后按 `；` 并列。这取代了 v1 的 `setdefault`
    静默丢弃——两个标签都想说「说话量」时，用户应该看到两句话，而不是
    其中一句凭空消失。
    """
    seen: list[str] = []
    for v in values:
        text = (v or "").strip().rstrip("。")
        if text and text not in seen:
            seen.append(text)
    return CONFLICT_JOINER.join(seen)


def detect_conflicts(tags: list[str]) -> list[list[str]]:
    """检出本次选择里命中的互斥对（返回命中了的组，每组至少两个名字）。"""
    chosen = {str(t).strip() for t in (tags or [])}
    hits = []
    for group in mutex_groups():
        present = [name for name in group if name in chosen]
        if len(present) >= 2:
            hits.append(present)
    return hits


def preview_persona_tags(tags: list[str]) -> dict[str, Any]:
    """把标签翻译成「三组可编辑草稿」，**不写 persona**。

    这是「点标签 → 预填草稿」交互的后端一半：前端拿到这三段文本填进
    可编辑 textarea，用户改完再随建人请求提交。这样标签只负责降低填写
    门槛，最终落库的内容是用户看见并确认过的东西。

    Returns:
        {
          "speaking": str, "emotion": str, "relationship": str,
          "hard_rules": [...],
          "conflicts": [[..]],     # 命中的互斥组
          "unknown": [...],        # 不认识的标签名
          "truncated": [...],      # 超出上限被截掉的标签名
        }
    """
    specs = {s["name"]: s for s in tag_specs()}
    chosen: list[str] = []
    unknown: list[str] = []
    for raw in tags or []:
        name = str(raw).strip()
        if not name:
            continue
        if name not in specs:
            unknown.append(name)
            continue
        if name not in chosen:
            chosen.append(name)

    limit = max_tags()
    truncated = chosen[limit:]
    chosen = chosen[:limit]

    speaking = _merge_text([specs[t]["speaking"] for t in chosen])
    emotion = _merge_text([specs[t]["emotion"] for t in chosen])
    relationship = _merge_text([specs[t]["relationship"] for t in chosen])
    hard: list[str] = []
    for t in chosen:
        for rule in specs[t]["hard_rules"]:
            if rule not in hard:
                hard.append(rule)

    return {
        "speaking": speaking,
        "emotion": emotion,
        "relationship": relationship,
        "hard_rules": hard,
        "conflicts": detect_conflicts(chosen),
        "unknown": unknown,
        "truncated": truncated,
    }


def _apply_v2(persona: dict[str, Any], tags: list[str]) -> None:
    """v2 合并：三句草稿落到固定契约 key，已有手填内容优先。

    与 v1 的差别：同一层内不再 `setdefault` 丢弃，而是先算好合并后的整句
    再整体写入——因为每个标签在同一层只产出一句，合并发生在句级，不会
    出现「两个标签抢同一个 key、后到的消失」。
    """
    preview = preview_persona_tags(tags)

    for draft_key, layer, field in V2_LAYER_KEYS:
        text = preview[draft_key]
        if not text:
            continue
        bucket = persona.get(layer)
        if not isinstance(bucket, dict):
            bucket = {}
        # 用户手填过的优先：只要这一层已有任意内容，标签就不再覆盖。
        # 但如果是标签自己上一次写进去的（值完全相同），保持幂等。
        if bucket.get(field):
            continue
        if any(isinstance(v, str) and v.strip() for v in bucket.values()):
            # 该层已有其它字段（v1 时代的手填或旧数据）——仍然写入新 key，
            # 因为 `基础风格` / `情感表达` / `相处模式` 在旧数据里不会出现，
            # 写进去只是新增信息，不构成覆盖。
            pass
        bucket[field] = text
        persona[layer] = bucket

    rules = preview["hard_rules"]
    if rules:
        existing = persona.get("hard_rules")
        if not isinstance(existing, list):
            existing = []
        persona["hard_rules"] = list(dict.fromkeys([*existing, *rules]))


def _apply_v1(persona: dict[str, Any], tags: list[str]) -> None:
    """v1 合并：原 `setdefault` 语义，保持历史行为不变。"""
    tag_map = load_persona_tags()

    for tag in tags or []:
        translation = tag_map.get(tag)
        if not isinstance(translation, dict):
            continue
        for layer, fields in translation.items():
            # 注意：这里**不能**先统一 `if not isinstance(fields, dict): continue`。
            # LIST_LAYERS 的值本来就是列表，先判 dict 会把 hard_rules 整层滤掉
            # —— v1 数据里「冷暴力」「有主见」「大度」的 hard_rules 全是列表，
            # 那样三个标签的硬规则会静默失效。
            if layer in LIST_LAYERS:
                if not isinstance(fields, list):
                    continue
                existing = persona.get(layer)
                if not isinstance(existing, list):
                    existing = []
                # 保持顺序去重
                persona[layer] = list(dict.fromkeys([*existing, *fields]))
            elif not isinstance(fields, dict):
                continue
            elif layer in persona and isinstance(persona[layer], dict):
                for key, val in fields.items():
                    persona[layer].setdefault(key, val)
            else:
                persona[layer] = dict(fields)


def apply_persona_tags(persona: dict[str, Any], tags: list[str]) -> dict[str, Any]:
    """把性格标签翻译成具体行为规则，原地合并进 persona。

    合并规则（v2）：
    - 三个描述层各自合并成一句，落到 `基础风格` / `情感表达` / `相处模式`
    - 已存在的字段**不覆盖**（用户在进阶配置里手填的优先）
    - `hard_rules` 去重追加
    - 结束后保证 DEFAULT_LAYERS 都至少是空 dict、hard_rules 至少是空 list

    合并规则（v1）：与原实现完全一致（按键 `setdefault`，列表去重追加）。

    Returns:
        传入的 persona（原地修改，方便链式调用）
    """
    if not isinstance(persona, dict):
        return persona

    if is_v2():
        _apply_v2(persona, tags or [])
    else:
        _apply_v1(persona, tags or [])

    for layer in DEFAULT_LAYERS:
        if not isinstance(persona.get(layer), dict):
            persona[layer] = {}
    for layer in LIST_LAYERS:
        if not isinstance(persona.get(layer), list):
            persona[layer] = []

    return persona


# 草稿字段名 → persona 落点。与 V2_LAYER_KEYS 的前两列一致，但草稿是
# **用户改过的文本**，优先级高于标签翻译，所以单独一条写入路径。
DRAFT_LAYER_KEYS = V2_LAYER_KEYS


def apply_drafts(persona: dict[str, Any], drafts: dict[str, Any]) -> dict[str, Any]:
    """把「用户改过的三段草稿」写进 persona，覆盖标签翻译的结果。

    交互链路：
      1. 用户点标签 → POST /api/persona/tags/preview → 拿到三段草稿
      2. 前端把草稿填进 textarea，用户可以改
      3. 建人时把改后的文本放进 body.drafts
      4. 这里在 `apply_persona_tags` **之后**执行，所以用户改过的内容一定赢

    为什么不在前端拼 persona 字段：speaking_style / emotional_patterns /
    relationship_behavior 的 key 名是后端契约，让前端硬编码等于把契约抄成
    两份，改一处就漂移。落点只在后端定义一次。

    空串视为「用户清空了这一项」，不写入 —— 但也不删掉标签已经写进去的
    内容。清空草稿的语义是「这次不用标签给的建议」，用户想要真的清空字段
    可以在角色详情的进阶配置里删。
    """
    if not isinstance(persona, dict) or not isinstance(drafts, dict):
        return persona

    for draft_key, layer, field in DRAFT_LAYER_KEYS:
        raw = drafts.get(draft_key)
        if not isinstance(raw, str):
            continue
        text = raw.strip()
        if not text:
            continue
        bucket = persona.get(layer)
        if not isinstance(bucket, dict):
            bucket = {}
        bucket[field] = text
        persona[layer] = bucket

    return persona
