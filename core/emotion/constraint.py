"""把情绪状态翻译成解码约束。

为什么需要这一层：

情绪此前只有两个出口——prompt 里一句形容词，和后处理往句尾挂一个表情。
前者模型可以完全无视（"你有点累，回复简短" 照样能写出三百字），后者只是装饰。
``max_tokens`` 不一样：它拿到的不是「你很难过」，而是「你只有这么长」。
模型没法演这一层。

设计原则：

1. **只在聊天主链路上收窄上限，不抬高**。取
   ``min(配置的 max_tokens, 按精力算出的预算)`` —— 用户给模型配了 8000
   token，情绪低也只是在这 8000 以内再收紧，绝不突破用户设置。
2. **纯函数、无 IO、无随机**。给定同一个 MoodState 永远得到同一个预算，
   便于测试，也避免「同一状态两次回复长度不同」这种排不掉的问题。
3. **不做问句抑制**。OpenAI 兼容 API 拿不到 logit，后处理改写问句会改坏
   语义（"你要不要早点睡？" 改成陈述句就变成命令）。这一层留空。
"""

from __future__ import annotations

from dataclasses import dataclass

from .mood import MoodState


# 精力到预算的映射端点。energy=1.0 → 满预算，energy=0.0 → 四成预算。
# 四成而不是一成：再低就会把"我在忙，等下说"这种正常短回复也截断。
_MIN_ENERGY_FACTOR = 0.4

# 聊天回复的默认预算上限（token）。模型侧配置的 max_tokens 通常是 2048+
# ——那是给长文和推理留的余量，聊天场景下等于没有约束。
DEFAULT_REPLY_TOKEN_BUDGET = 600

# 无论如何不低于这个值：一句完整的中文话大约 20-40 token，
# 120 足够说两三句，再低就只能吐半句。
MIN_REPLY_TOKEN_BUDGET = 120


@dataclass(frozen=True)
class OutputConstraint:
    """一次回复的解码约束。"""

    max_tokens: int


def build_output_constraint(
    mood: MoodState | None,
    *,
    budget: int = DEFAULT_REPLY_TOKEN_BUDGET,
    configured_max_tokens: int | None = None,
) -> OutputConstraint:
    """按当前精力收窄回复预算。

    Args:
        mood: 当前情绪状态；None 时返回中性约束。
        budget: 本场景的回复预算（聊天默认 600 token）。
        configured_max_tokens: 模型配置里的 max_tokens。给了就取两者较小值，
            保证「再紧也不突破用户给模型设置的上限」。

    Returns:
        OutputConstraint
    """
    limit = max(MIN_REPLY_TOKEN_BUDGET, int(budget))
    if configured_max_tokens and configured_max_tokens > 0:
        limit = min(limit, int(configured_max_tokens))
    if mood is None:
        return OutputConstraint(max_tokens=limit)

    try:
        energy = float(mood.energy)
    except (TypeError, ValueError):
        energy = 0.5
    energy = max(0.0, min(1.0, energy))

    factor = _MIN_ENERGY_FACTOR + (1.0 - _MIN_ENERGY_FACTOR) * energy
    max_tokens = int(round(limit * factor))
    return OutputConstraint(
        max_tokens=max(MIN_REPLY_TOKEN_BUDGET, min(limit, max_tokens)),
    )
