"""人设是否接受 emoji / 颜文字 / 卖萌语气。

单一实现，两个消费方：
- ``core/chat/pipeline.py``：后处理要不要往回复末尾挂一个表情
- ``core/proactive.py``：LLM 不可用时的兜底文案用哪一套语气

历史问题：这两处原本各自硬编码自己的口吻。人设里明确写着「不用颜文字」
「不刻意卖萌」，回复层却每条都挂一个颜文字，兜底文案则是「嗨~ 你今天怎么样呀？」
—— 人设与输出在最显眼的地方自相矛盾。

判定顺序（显式优先，永远是显式赢）：
1. ``persona.emoji_enabled`` 为 True/False → 直接采用
2. 否则读人设文本里用户亲手写下的约束
3. 都没有 → 允许
"""

from __future__ import annotations

# 人设文本里的明确否定。收得很窄：只认「不用/不要 + 表情类词」，
# 避免把「喜欢用表情」这种肯定句误判成否定。
_DISABLE_MARKERS = (
    "不用颜文字", "不要颜文字", "不使颜文字",
    "不用emoji", "不要emoji", "不使emoji",
    "不发表情", "不用表情", "不加表情",
    "不刻意卖萌", "不要卖萌", "不卖萌",
    "不用撒娇腔", "不撒娇",
)


def persona_allows_emoji(persona) -> bool:
    """该人设是否接受 emoji / 颜文字 / 卖萌语气。"""
    if persona is None:
        return True

    explicit = getattr(persona, "emoji_enabled", None)
    if explicit is not None:
        return bool(explicit)

    style = getattr(persona, "speaking_style", None) or {}
    if isinstance(style, dict):
        text = "".join(str(value) for value in style.values())
    else:
        text = str(style)
    text += str(getattr(persona, "emoji_habits", "") or "")
    normalized = text.lower().replace(" ", "")
    return not any(marker in normalized for marker in _DISABLE_MARKERS)
