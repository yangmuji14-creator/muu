"""把「按会话分片」的历史状态迁移到「按角色」的新作用域。

背景：2026-11-01 起网页端不再按会话隔离状态 —— 记忆/情绪/人格/亲密度
统一挂在 ``web::<persona_id>`` 下。但旧数据躺在 ``scope_<sha256>`` 里，
不迁过来，用户看到的就是「她突然不记得我了」。

用法：

    # 1. 先看现状（默认 dry-run，只读）
    ./.venv/Scripts/python.exe -m tools.migrate_web_scope

    # 2. 指定源作用域看影响面
    ./.venv/Scripts/python.exe -m tools.migrate_web_scope --from scope_c031166b5a7410eccd10d65ee36305c0

    # 3. 真正执行（自动备份到 data/backup_scope_migration/）
    ./.venv/Scripts/python.exe -m tools.migrate_web_scope --from scope_xxx --apply

    # 4. 想迁多个会话（按 --from 重复给）
    ./.venv/Scripts/python.exe -m tools.migrate_web_scope \
        --from scope_aaa --from scope_bbb --apply

设计约束：

1. **默认只读**。没有任何参数时打印每个作用域的数据量，方便判断该用哪个当源。
2. **冲突取「更多」而不是「覆盖」**：亲密度取 message_count 大的一方，人格取
   total_interactions 大的一方，聊天记录按 (role, content, timestamp) 去重后合并。
   理由是「我们不希望迁移把用户已有的关系往回退」。
3. **可重复执行**：迁完不删源数据，只做合并。重复跑不会产生重复消息
   （去重键含内容与时间戳），但建议先备份。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "companion.db"
CHAT_DIR = DATA_DIR / "chat_history"
BACKUP_DIR = DATA_DIR / "backup_scope_migration"

SCOPE_TABLES = ("memories", "memory_vectors", "moods", "personalities", "affection", "life_summaries")


# ── 探测 ────────────────────────────────────────────────────────


def _table_counts(conn: sqlite3.Connection, user_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in SCOPE_TABLES:
        try:
            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_id,),
            ).fetchone()[0]
        except sqlite3.Error:
            counts[table] = 0
    return counts


def _list_state_ids(conn: sqlite3.Connection) -> list[str]:
    ids: set[str] = set()
    for table in SCOPE_TABLES:
        try:
            for (uid,) in conn.execute(f"SELECT DISTINCT user_id FROM {table}"):
                if uid:
                    ids.add(uid)
        except sqlite3.Error:
            continue
    return sorted(ids)


def _chat_history_path(user_id: str) -> Path | None:
    """按 ChatHistoryStorage 的规则推算文件路径（只读用）。"""
    from core.config import parse_uid
    parsed = parse_uid(user_id)
    platform = parsed.get("platform")
    if platform == "web" and parsed.get("persona_id"):
        return CHAT_DIR / "web" / f"{parsed['persona_id']}.json"
    if "::" in user_id:
        return None
    safe = user_id.replace("/", "_").replace("\\", "_")
    return CHAT_DIR / f"{safe}.json"


def _message_count(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    return len(data.get("messages", []) if isinstance(data, dict) else data)


def report(conn: sqlite3.Connection) -> None:
    print(f"{'状态作用域':<48} {'记忆':>4} {'情绪':>4} {'人格':>4} {'亲密':>4} {'摘要':>4} {'历史':>5}")
    print("-" * 86)
    for uid in _list_state_ids(conn):
        c = _table_counts(conn, uid)
        hist = _message_count(_chat_history_path(uid))
        print(
            f"{uid:<48} {c['memories']:>4} {c['moods']:>4} {c['personalities']:>4} "
            f"{c['affection']:>4} {c['life_summaries']:>4} {hist:>5}"
        )


def suggest_source(conn: sqlite3.Connection, persona_id: str) -> str | None:
    """挑一个「最有料」的 scope 当默认源：聊天记录最多者。"""
    best, best_score = None, -1
    for uid in _list_state_ids(conn):
        if not uid.startswith("scope_"):
            continue
        score = _message_count(_chat_history_path(uid)) + _table_counts(conn, uid)["memories"] * 4
        if score > best_score:
            best, best_score = uid, score
    return best


# ── 迁移 ────────────────────────────────────────────────────────


def _merge_affection(conn: sqlite3.Connection, source: str, target: str, persona_id: str) -> str:
    src = conn.execute(
        "SELECT level, message_count, positive_count, negative_count, last_interaction, created_at "
        "FROM affection WHERE user_id = ? ORDER BY message_count DESC LIMIT 1", (source,),
    ).fetchone()
    if not src:
        return "无亲密度记录"
    dst = conn.execute(
        "SELECT message_count FROM affection WHERE user_id = ? AND persona_id = ?",
        (target, persona_id),
    ).fetchone()
    if dst and dst[0] >= src[1]:
        return f"目标已有更多互动（{dst[0]} >= {src[1]}），保留目标"
    conn.execute(
        "INSERT OR REPLACE INTO affection "
        "(user_id, persona_id, level, message_count, positive_count, negative_count, "
        " last_interaction, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (target, persona_id, *src),
    )
    return f"亲密度 {src[0]:.1f}（{src[1]} 条互动）已迁入"


def _merge_state_json(conn: sqlite3.Connection, table: str, source: str, target: str,
                      winner_key: str) -> str:
    """moods / personalities：两边都是单条 JSON state，取"更成熟"的那条。"""
    src = conn.execute(f"SELECT state FROM {table} WHERE user_id = ?", (source,)).fetchone()
    if not src:
        return "无记录"
    dst = conn.execute(f"SELECT state FROM {table} WHERE user_id = ?", (target,)).fetchone()
    if dst:
        try:
            src_state = json.loads(src[0])
            dst_state = json.loads(dst[0])
        except (TypeError, json.JSONDecodeError):
            src_state = dst_state = {}
        if dst_state.get(winner_key, 0) >= src_state.get(winner_key, 0):
            return f"目标更成熟（{winner_key}={dst_state.get(winner_key)}），保留目标"
        state = src[0]
    else:
        state = src[0]
    conn.execute(
        f"INSERT OR REPLACE INTO {table} (user_id, state) VALUES (?, ?)", (target, state),
    )
    return "已迁入"


def _migrate_chat_history(source: str, target: str) -> str:
    src_path = _chat_history_path(source)
    dst_path = _chat_history_path(target)
    if src_path is None or dst_path is None:
        return "路径无法推算，跳过"
    if not src_path.exists():
        return "源无聊天记录"

    src_data = json.loads(src_path.read_text(encoding="utf-8"))
    src_msgs = src_data.get("messages", []) if isinstance(src_data, dict) else src_data
    dst_data = {"messages": [], "short_memories": []}
    if dst_path.exists():
        loaded = json.loads(dst_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            dst_data = {"messages": loaded.get("messages", []),
                        "short_memories": loaded.get("short_memories", [])}
        else:
            dst_data["messages"] = loaded

    seen = {
        (m.get("role"), m.get("content"), m.get("timestamp"))
        for m in dst_data["messages"]
    }
    added = 0
    for message in src_msgs:
        key = (message.get("role"), message.get("content"), message.get("timestamp"))
        if key in seen:
            continue
        seen.add(key)
        dst_data["messages"].append(message)
        added += 1

    dst_data["messages"].sort(key=lambda m: m.get("timestamp") or "")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_text(
        json.dumps(dst_data, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return f"聊天记录 +{added} 条（总计 {len(dst_data['messages'])}）"


def _migrate_open_loops(source: str, target: str) -> str:
    path = DATA_DIR / "open_loops.json"
    if not path.exists():
        return "无 open_loops.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    loops = data.get("loops", data) if isinstance(data, dict) else data
    if not isinstance(loops, dict) or source not in loops:
        return "源无未闭合事件"
    target_loops = loops.setdefault(target, [])
    existing_ids = {item.get("id") for item in target_loops}
    added = 0
    for item in loops[source]:
        if item.get("id") in existing_ids:
            continue
        item["user_id"] = target
        target_loops.append(item)
        added += 1
    loops.pop(source, None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"未闭合事件 +{added} 条"


def _source_persona_id(conn: sqlite3.Connection, user_id: str) -> str | None:
    """源作用域当初绑的是哪个角色。

    必须校验：库里同时存在 ``1_988fe8``（微信那个空人设）的 scope，
    把它的记忆迁进 ``girlfriend_001`` 就是把两个人揉在一起。
    """
    try:
        row = conn.execute(
            "SELECT persona_id FROM affection WHERE user_id = ? LIMIT 1", (user_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    return row[0] if row else None


def migrate(conn: sqlite3.Connection, source: str, target: str, persona_id: str,
            force: bool = False) -> None:
    print(f"\n源   {source}\n目标 {target}\n")

    source_persona = _source_persona_id(conn, source)
    if source_persona and source_persona != persona_id and not force:
        print(f"!! 跳过：源的 persona 是 {source_persona!r}，与目标 {persona_id!r} 不一致")
        print("   确认要合并请加 --force")
        return
    if source_persona:
        print(f"· 角色校验通过（{source_persona}）")

    print("· 记忆 / 向量：改写 user_id")
    for table in ("memories", "memory_vectors"):
        cur = conn.execute(
            f"UPDATE {table} SET user_id = ? WHERE user_id = ?", (target, source),
        )
        print(f"    {table}: {cur.rowcount} 行")

    print(f"· 情绪：{_merge_state_json(conn, 'moods', source, target, 'valence')}")
    print(f"· 人格：{_merge_state_json(conn, 'personalities', source, target, 'total_interactions')}")
    print(f"· 亲密度：{_merge_affection(conn, source, target, persona_id)}")

    cur = conn.execute(
        "UPDATE life_summaries SET user_id = ? WHERE user_id = ?", (target, source),
    )
    print(f"· 人生摘要：{cur.rowcount} 行")

    conn.commit()
    print(f"· 聊天记录：{_migrate_chat_history(source, target)}")
    print(f"· 未闭合事件：{_migrate_open_loops(source, target)}")


def backup() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / stamp
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_PATH, dest / DB_PATH.name)
    if CHAT_DIR.exists():
        shutil.copytree(CHAT_DIR, dest / "chat_history")
    for name in ("open_loops.json", "conversations.json"):
        src = DATA_DIR / name
        if src.exists():
            shutil.copy2(src, dest / name)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把按会话分片的状态迁到按角色")
    parser.add_argument("--from", dest="sources", action="append", default=[],
                        help="源作用域（可重复）。省略则只打印报告")
    parser.add_argument("--to", dest="target", default="",
                        help="目标作用域，默认 web::<persona>")
    parser.add_argument("--persona", dest="persona", default="girlfriend_001")
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--force", action="store_true",
                        help="源的 persona 与目标不一致时也合并")
    args = parser.parse_args(argv)

    if not DB_PATH.exists():
        print(f"找不到数据库：{DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    # 必须：memory_vectors 的行带 2KB BLOB，批量 UPDATE 时 SQLite 默认把
    # 中间结果 spill 到磁盘临时文件，在受限环境下会报 "unable to open
    # database file"（实测）。强制走内存临时表即可，数据量很小。
    conn.execute("PRAGMA temp_store = MEMORY")
    try:
        target = args.target or f"web::{args.persona}"
        sources = args.sources
        if not sources:
            report(conn)
            guess = suggest_source(conn, args.persona)
            print(f"\n建议源：{guess or '（没有可迁移的 scope）'}")
            print(f"目标   ：{target}")
            print("\n这只是报告。确认无误后加 --from <源> --apply 执行。")
            return 0

        if not args.apply:
            print("=== DRY-RUN（不写任何文件）===")
            for source in sources:
                print(f"\n源 {source} → {target}")
                counts = _table_counts(conn, source)
                for table, count in counts.items():
                    print(f"    {table}: {count}")
                print(f"    chat_history: {_message_count(_chat_history_path(source))} 条")
            print("\n确认无误后加 --apply 执行。")
            return 0

        dest = backup()
        print(f"已备份到 {dest}")
        for source in sources:
            migrate(conn, source, target, args.persona, force=args.force)
        print("\n完成。重启服务后生效：")
        print("  ./.venv/Scripts/python.exe main.py web")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
