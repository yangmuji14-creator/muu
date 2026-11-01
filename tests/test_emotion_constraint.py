"""输出约束：把情绪翻译成解码预算。

这一层的价值在于「模型没法演」：它拿到的不是「你很难过」，
而是「你只有这么多 token」。所以断言的是**单调性**和**边界**，
而不是某个具体数字。
"""

from __future__ import annotations

import pytest

from core.emotion.constraint import (
    DEFAULT_REPLY_TOKEN_BUDGET,
    MIN_REPLY_TOKEN_BUDGET,
    OutputConstraint,
    build_output_constraint,
)
from core.emotion.mood import MoodState, MoodType


def _mood(energy: float) -> MoodState:
    return MoodState(mood=MoodType.NEUTRAL, energy=energy)


class TestNeutral:
    def test_none_mood_uses_full_budget(self) -> None:
        result = build_output_constraint(None)
        assert result == OutputConstraint(max_tokens=DEFAULT_REPLY_TOKEN_BUDGET)

    def test_full_energy_keeps_full_budget(self) -> None:
        assert build_output_constraint(_mood(1.0)).max_tokens == DEFAULT_REPLY_TOKEN_BUDGET

    def test_zero_energy_shrinks_to_floor_factor(self) -> None:
        result = build_output_constraint(_mood(0.0))
        assert result.max_tokens < DEFAULT_REPLY_TOKEN_BUDGET
        assert result.max_tokens >= MIN_REPLY_TOKEN_BUDGET


class TestMonotonic:
    def test_lower_energy_never_increases_budget(self) -> None:
        """单调性是这一层的核心契约：更累只能更短，不能反过来。"""
        budgets = [
            build_output_constraint(_mood(e)).max_tokens
            for e in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
        ]
        assert budgets == sorted(budgets)

    def test_energy_actually_changes_budget(self) -> None:
        """不能退化成常数 —— 否则和「在 prompt 里写一句请简短」没区别。"""
        assert build_output_constraint(_mood(0.0)).max_tokens < \
            build_output_constraint(_mood(1.0)).max_tokens


class TestConfiguredCeiling:
    def test_never_exceeds_configured_max_tokens(self) -> None:
        result = build_output_constraint(
            _mood(1.0), budget=2000, configured_max_tokens=300,
        )
        assert result.max_tokens <= 300

    def test_ignores_invalid_configured_value(self) -> None:
        for bad in (0, -5, None):
            result = build_output_constraint(_mood(1.0), configured_max_tokens=bad)
            assert result.max_tokens > 0


class TestFloor:
    @pytest.mark.parametrize("budget", [10, MIN_REPLY_TOKEN_BUDGET, 600])
    def test_never_below_floor(self, budget) -> None:
        """低于下限只能吐半句话，比「不回」更糟。"""
        result = build_output_constraint(_mood(0.0), budget=budget)
        assert result.max_tokens >= MIN_REPLY_TOKEN_BUDGET

    def test_bad_energy_falls_back_to_middle(self) -> None:
        mood = MoodState(mood=MoodType.NEUTRAL)
        mood.energy = None  # type: ignore[assignment]
        assert build_output_constraint(mood).max_tokens > 0
