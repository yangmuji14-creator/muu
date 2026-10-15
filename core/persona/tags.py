"""性格标签 → 行为规则 的翻译表（CLI 向导与 WebUI 共用）

数据源是 `config/persona_tags.json`，结构为：

```json
{
  "话痨": {"speaking_style": {"说话量": "话多，经常连发多条消息", "话题跳跃": "话题跳跃快"}},
  "温柔": {"emotional_patterns": {...}, "relationship_behavior": {...}}
}
```

顶层 key 是行为层（speaking_style / emotional_patterns / relationship_behavior /
hard_rules），第二层是该层下的具体字段。

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


def tags_path() -> Path:
    """persona_tags.json 的位置（与 personas.json 同目录）"""
    from core.config import CONFIG_DIR

    return CONFIG_DIR / "persona_tags.json"


def load_persona_tags() -> dict[str, dict[str, Any]]:
    """读取全部性格标签及其行为规则。

    文件缺失或损坏时返回空 dict（调用方应降级为纯手填，不阻断建人）。
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


def tag_names() -> list[str]:
    """所有可选性格标签名（供前端下拉/标签选择器）"""
    return list(load_persona_tags().keys())


def apply_persona_tags(persona: dict[str, Any], tags: list[str]) -> dict[str, Any]:
    """把性格标签翻译成具体行为规则，原地合并进 persona。

    合并规则：
    - 已存在的字段**不覆盖**（用户在进阶配置里手填的优先）
    - `hard_rules` 是列表，去重追加；其余层是 dict，按键合并
    - 结束后保证 DEFAULT_LAYERS 都至少是空 dict、hard_rules 至少是空 list

    Returns:
        传入的 persona（原地修改，方便链式调用）
    """
    tag_map = load_persona_tags()
    if not isinstance(persona, dict):
        return persona

    for tag in tags or []:
        translation = tag_map.get(tag)
        if not isinstance(translation, dict):
            continue
        for layer, fields in translation.items():
            if not isinstance(fields, dict):
                continue
            if layer in LIST_LAYERS:
                existing = persona.get(layer)
                if not isinstance(existing, list):
                    existing = []
                # 保持顺序去重
                persona[layer] = list(dict.fromkeys([*existing, *fields]))
            elif layer in persona and isinstance(persona[layer], dict):
                for key, val in fields.items():
                    persona[layer].setdefault(key, val)
            else:
                persona[layer] = dict(fields)

    for layer in DEFAULT_LAYERS:
        if not isinstance(persona.get(layer), dict):
            persona[layer] = {}
    for layer in LIST_LAYERS:
        if not isinstance(persona.get(layer), list):
            persona[layer] = []

    return persona
