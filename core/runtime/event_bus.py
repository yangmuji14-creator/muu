"""进程内轻量事件总线 —— SSE 实时推送的后端支撑。

设计约束：
- 纯内存、零依赖，按 scope_id（记忆隔离键）订阅
- 发布永不阻塞、永不抛错（订阅者慢就丢事件，客户端有轮询兜底）
- core 层可安全使用（不依赖 webui）

典型用途：微信/后台任务写入新消息后发布 history_changed，
Web 前端的 EventSource 收到后立即刷新聊天列表，替代固定间隔轮询。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)


def subscribe(key: str) -> asyncio.Queue:
    """订阅某 scope 的事件流，返回队列（消费方持有，退出时 unsubscribe）。"""
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers[key].add(q)
    return q


def unsubscribe(key: str, q: asyncio.Queue) -> None:
    _subscribers[key].discard(q)
    if not _subscribers.get(key):
        _subscribers.pop(key, None)


def publish(key: str, payload: dict[str, Any]) -> None:
    """向某 scope 的所有订阅者广播；满队列直接丢弃（不阻塞发布方）。"""
    if not key:
        return
    for q in list(_subscribers.get(key, ())):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            continue


def publish_history_changed(scope_id: str, **extra: Any) -> None:
    """历史消息有变化（新消息落库）——前端据此刷新聊天列表。"""
    if scope_id:
        publish(scope_id, {"type": "history_changed", **extra})
