"""关系事件与亲密度模块。

历史上这里还有 `tracker.py`（RelationshipTracker）与 `evolution.py`
（RelationshipEvolution / BehaviorProfile）两套亲密度算法，但主链路从来没有
实例化过它们：真正在用的是 `events.py` 的 `RelationshipEventTracker`
（`core/chat/pipeline.py` 的 `PostProcessOrchestrator` 持有），以及
`webui/routes/common.py::_affection_stage` 按 `relationship_level` 分档。
两套并行算法已于第四十批删除 —— 同一件事有两套公式，迟早会算出一个数、
详情页显示另一个数（记忆的 `forget_score` 就踩过这个坑）。
"""

from .events import RelationshipEvent, RelationshipEventTracker

__all__ = [
    "RelationshipEvent",
    "RelationshipEventTracker",
]
