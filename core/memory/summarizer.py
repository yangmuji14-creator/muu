"""记忆总结器 + 智能检索

机制：
1. 短期记忆：保存最近的原始对话（用户+AI）
2. 当短期记忆达到阈值，用 LLM 总结为长期记忆
3. 检索：多路召回（关键词 + 标签 + 分类） + LLM 重排序
"""

import json
import re
from datetime import datetime

from loguru import logger

from core.utils import parse_json_response
from ..llm.base import BaseLLM


def _parse_memory_json(text: str) -> dict | None:
    """容错解析模型输出：接受单个对象、对象数组、代码块包裹。"""
    body = (text or "").strip()
    if not body:
        return None
    m = re.search(r"```(?:json)?\s*(.*?)```", body, re.DOTALL)
    if m:
        body = m.group(1).strip()
    data = None
    try:
        data = json.loads(body)
    except Exception:
        for left, right in (("{", "}"), ("[", "]")):
            i, j = body.find(left), body.rfind(right)
            if i != -1 and j > i:
                try:
                    data = json.loads(body[i: j + 1])
                    break
                except Exception:
                    continue
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), None)
    return data if isinstance(data, dict) else None


def _clean_memory_content(raw) -> str:
    """把模型返回的记忆内容清洗成可直接入库的纯文本。

    模型有时会把整个 JSON 数组/对象塞进 content（一次给多条记忆），
    直接入库会变成一大块 JSON 文本、还会被当作记忆注入 prompt。
    这里尝试还原出真正的内容；还原不干净就返回空串（调用方丢弃）。
    """
    text = str(raw if raw is not None else "").strip()
    if not text:
        return ""
    if text[:1] in "[{":
        # 尝试解析出结构里的第一条内容
        parsed = None
        try:
            parsed = json.loads(text)
        except Exception:
            return ""
        item = parsed
        if isinstance(item, list):
            # 纯数字/短数组（[1,2,3]）不是记忆内容，宁可不记；
            # 只有 dict 项或足够长的字符串项才值得还原
            item = next((x for x in item if isinstance(x, dict)), None)
            if item is None:
                item = next(
                    (x for x in parsed if isinstance(x, str) and len(x.strip()) >= 4),
                    None,
                )
        if isinstance(item, dict):
            item = item.get("content")
        text = str(item or "").strip()
    # 仍然是 JSON 片段 / 空 / 过长 -> 丢弃，宁可不记也不存垃圾
    if not text or text[:1] in "[{" or len(text) > 200:
        return ""
    return text


def _parse_memory_items(text: str) -> list[str]:
    """从模型输出里取出**多条**记忆内容（支持 JSON 数组 / 单个对象）。

    为什么单独写：`core.utils.parse_json_response` 只接受 dict，而 summarize() 的 prompt
    明确要求输出 JSON **数组** —— 用它解析必然失败，旧代码的 fallback 会把整段 JSON
    当成一条记忆存下来（污染记忆库并被注入 prompt）。
    """
    body = (text or "").strip()
    if not body:
        return []
    m = re.search(r"```(?:json)?\s*(.*?)```", body, re.DOTALL)
    if m:
        body = m.group(1).strip()
    data = None
    try:
        data = json.loads(body)
    except Exception:
        for left, right in (("[", "]"), ("{", "}")):
            i, j = body.find(left), body.rfind(right)
            if i != -1 and j > i:
                try:
                    data = json.loads(body[i: j + 1])
                    break
                except Exception:
                    continue
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    items: list[str] = []
    for entry in data:
        raw_content = entry.get("content") if isinstance(entry, dict) else entry
        cleaned = _clean_memory_content(raw_content)
        if cleaned:
            items.append(cleaned)
    return items


class MemorySummarizer:
    """记忆总结器

    机制（借鉴 My-Dream-Moments）：
    1. 短期记忆：保存最近的原始对话（用户+AI）
    2. 当短期记忆达到阈值（如 15 组对话），用 LLM 总结为长期记忆
    3. 长期记忆用于注入 prompt，短期记忆用于上下文连续性
    """

    def __init__(self, llm: BaseLLM, summarize_threshold: int = 15):
        self._llm = llm
        self._threshold = summarize_threshold

    async def summarize(self, conversations: list[dict[str, str]]) -> str | None:
        """将对话记录总结为长期记忆

        Args:
            conversations: 对话记录列表，格式 [{"user": "...", "assistant": "..."}]

        Returns:
            总结文本，失败返回 None
        """
        if len(conversations) < 3:
            return None

        # 构建对话文本
        lines = []
        for conv in conversations:
            lines.append(f"用户: {conv.get('user', '')}")
            lines.append(f"助手: {conv.get('assistant', '')}")
        conversation_text = "\n".join(lines)

        today_date = datetime.now().strftime("%Y年%m月%d日")
        prompt = f"""以第一人称写日记的方式，从以下对话中提取**关于他**的事。

【只写】
- 他告诉过你的、关于他自己的事实（名字、生日、工作/学业、住处、家人、宠物…）
- 他经历或计划的事（考试、旅行、约定、日程…）
- 他明确表达过的喜好 / 厌恶 / 习惯

【绝对不要写】
- 你自己的身份、设定或任务（例如"我在进行恋爱角色扮演""我需要扮演伴侣角色"）
- 系统 / 程序 / 模型 / 提示词 / 好感度亲密度数值等一切机制相关的东西
- 这段对话本身的形式（例如"他刚才在测试功能""他在和我聊天"）
- 你的推测 —— 只写他明确说过的

【写法】
- 用「今天」开头，像写日记一样自然；每条 1-2 句话，不要太长
- 主语是他，用「他」称呼；不要出现"用户""助手"这类词
- 如果提到了具体时间，根据当前日期 {today_date} 推算绝对日期
- 没有值得记的就输出空数组 []

只输出 JSON 数组（每项一个对象）：
[
  {{"content": "今天他说想吃火锅了，之前还说过想去重庆吃正宗的。", "importance": 3}},
  {{"content": "他告诉我生日是5月20日。", "importance": 4}}
]"""

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": conversation_text}],
                system_prompt=prompt,
                max_tokens=800,
                temperature=0.5,
            )

            raw = response.content.strip()
            if not raw or len(raw) < 10:
                return None

            # 模型被要求输出 JSON 数组：逐条取出并清洗。
            # 注意不能用 parse_json_response（只认 dict），否则数组会整段落库。
            items = _parse_memory_items(raw)
            if items:
                logger.info(f"Memory summarized: {len(items)} diary entries")
                return "\n\n".join(items)

            # 兜底：只在**非 JSON 文本**上退回原文，避免把 JSON 当记忆存
            cleaned = _clean_memory_content(raw)
            if cleaned:
                logger.debug(f"JSON parse fallback, raw: {cleaned[:50]}...")
                return cleaned
            logger.debug("memory summarize skipped: 输出无法解析为可用文本")
            return None

        except Exception as e:
            logger.error(f"Memory summarization failed: {e}")
            return None

    async def extract_memory(self, user_msg: str, assistant_reply: str) -> dict | None:
        """从单条对话中提取记忆（LLM 辅助）

        Args:
            user_msg: 用户消息
            assistant_reply: AI 回复

        Returns:
            {"content": "提取的信息", "importance": 1-5, "category": "..."} 或 None
        """
        prompt = f"""你在以第一人称记录**关于他**的事，供以后聊天时记得他。

【只写这三类】
1. 他告诉过你的、关于他自己的事实：名字、生日、年龄、工作/学业、住处、家人、宠物、身体情况
2. 他经历或计划的事：考试、旅行、约定、日程、正在做的事
3. 他明确表达过的喜好 / 厌恶 / 习惯：爱吃的、讨厌的、作息、脾气

【绝对不要写】
- 你自己的身份、设定或任务（例如"我在进行恋爱角色扮演""我需要扮演一个伴侣角色"）
- 系统 / 程序 / 模型 / 提示词 / 好感度亲密度数值等一切机制相关的东西
- 这段对话本身的形式（例如"他刚才在测试功能""他在和我聊天"）
- 你的推测（例如"他可能在做技术开发"）—— 只写他明确说过的

【写法】
- 主语永远是他，用「他」称呼；不要出现"用户""助手"这类词
- 一句话，具体、以后能直接用；不要客套，不要点评你们的对话

对话：
他: {user_msg}
你: {assistant_reply}

如果这段对话里**没有关于他的事实**，返回：null

示例（仅示意写法，不要照抄内容）：
- 好：「他养了一只猫叫团子，很黏人。」
- 好：「他明天有课，最近常熬夜到十二点以后。」
- 不好：「我正在和他进行角色扮演…」← 那是你的任务，不是关于他的事
- 不好：「好感度被系统调节到了60」← 系统机制，不是事实
- 不好：「他今天去公园散步了」← 太琐碎（除非他说这是习惯、或对它有特别感受）

只返回**一个** JSON 对象（不要返回数组）：
{{"content": "关于他的一句话", "importance": 1-5, "category": "personal|emotion|event|preference|relationship|opinion|other"}}

重要度说明：
5 = 核心信息（生日、名字、关系里程碑）
4 = 重要事件（考试、旅行、纪念日）
3 = 个人偏好（喜欢/讨厌什么）
2 = 一般信息（日常安排、习惯）
1 = 不值得记住
"""

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": f"用户: {user_msg}\n助手: {assistant_reply}"}],
                system_prompt=prompt,
                max_tokens=200,
                temperature=0.1,
            )

            content = response.content.strip()

            # 解析响应
            if content.lower() == "null" or not content:
                return None

            result = _parse_memory_json(content)
            if not result:
                return None
            cleaned = _clean_memory_content(result.get("content"))
            if not cleaned:
                # 清洗后为空（模型给的是一坨 JSON 或超长文本）-> 宁可不记
                logger.debug("memory extraction skipped: content 清洗后为空")
                return None
            # importance 必须钳制为 1-5 的 int：模型可能返回 "4"（字符串）或 100，
            # 不钳制会在 pipeline 里 `"4" >= 2` 抛 TypeError，被误判为调用失败
            # 而走规则兜底把用户原话写进记忆库（与防噪目标背道而驰）。
            try:
                importance = int(result.get("importance", 3))
            except (TypeError, ValueError):
                importance = 3
            importance = max(1, min(5, importance))
            return {
                "content": cleaned,
                "importance": importance,
                "category": str(result.get("category") or "other"),
            }

        except Exception as e:
            # 这里要**向上抛**，让调用方能区分两种"没有结果"：
            #   返回 None = 模型判定这段对话不值得记（正确结果，不该兜底）
            #   抛异常     = 调用失败（这时才值得用规则写入兜底）
            logger.error(f"Memory extraction failed: {e}")
            raise

    async def retrieve_relevant(
        self, query: str, memories: list, limit: int = 5
    ) -> list[str]:
        """智能检索相关记忆：多路召回 + LLM 重排序

        Args:
            query: 用户当前消息
            memories: 记忆对象列表（Memory 实例或 content 字符串）
            limit: 返回条数上限

        Returns:
            相关记忆内容列表
        """
        if not memories:
            return []

        # 处理输入：兼容 Memory 对象和字符串
        if hasattr(memories[0], 'content'):
            # Memory 对象
            memory_items = [
                {
                    "content": m.content,
                    "category": getattr(m, 'category', 'other'),
                    "level": getattr(m, 'level', 1),
                    "access_count": getattr(m, 'access_count', 0),
                }
                for m in memories
            ]
        else:
            # 纯字符串列表（兼容旧接口）
            memory_items = [
                {"content": m, "category": "other", "level": 1, "access_count": 0}
                for m in memories
            ]

        # === 第一阶段：多路召回 ===
        recalled = self._multi_path_recall(query, memory_items, recall_limit=15)

        if not recalled:
            return []

        if len(recalled) <= limit:
            return [item["content"] for item in recalled]

        # === 第二阶段：LLM 重排序 ===
        if self._llm:
            try:
                ranked = await self._llm_rerank(query, recalled, limit)
                if ranked is not None:
                    # None = 调用失败（走下方规则回退）；[] = 模型明确判定无相关
                    # 记忆（此前 [] 被当成失败，把模型判为不相关的记忆又塞回 prompt）
                    return ranked
            except Exception as e:
                logger.debug(f"LLM rerank failed, falling back to rule-based: {e}")

        # 回退：按 level 降序取前 N
        recalled.sort(key=lambda x: x.get("level", 1), reverse=True)
        return [item["content"] for item in recalled[:limit]]

    def _multi_path_recall(
        self, query: str, memory_items: list[dict], recall_limit: int = 15
    ) -> list[dict]:
        """多路召回：关键词 + 分类 + 热度

        Args:
            query: 查询文本
            memory_items: 记忆条目列表
            recall_limit: 召回数量上限

        Returns:
            召回的记忆条目（可能有重复，需去重）
        """
        seen_ids: set[str] = set()
        recalled: list[dict] = []

        def _add(item: dict, match_type: str):
            content = item["content"]
            if content not in seen_ids:
                seen_ids.add(content)
                item_copy = dict(item)
                item_copy["match_type"] = match_type
                recalled.append(item_copy)

        # 1. 关键词召回：query 中的词出现在记忆中
        query_chars = set(query.replace(" ", "").replace("？", "").replace("。", ""))
        for item in memory_items:
            content = item["content"]
            content_chars = set(content)
            overlap = len(query_chars & content_chars)
            if overlap >= 2:  # 至少 2 个字符匹配
                _add(item, "keyword")

        # 2. 分类召回：根据 query 意图匹配分类
        category_hints = {
            "personal": ["叫什么", "名字", "生日", "多大", "住哪", "在哪"],
            "emotion": ["开心", "难过", "喜欢", "讨厌", "心情", "感觉"],
            "event": ["什么时候", "去了", "做了", "发生", "经历"],
            "preference": ["喜欢什么", "爱吃什么", "习惯", "爱好"],
            "relationship": ["家人", "朋友", "爸妈", "男朋友", "女朋友"],
        }
        for category, hints in category_hints.items():
            if any(hint in query for hint in hints):
                for item in memory_items:
                    if item.get("category") == category:
                        _add(item, "category")

        # 3. 热度召回：高访问次数 + 高重要度的记忆始终可召回
        for item in memory_items:
            if item.get("level", 1) >= 4 or item.get("access_count", 0) >= 3:
                _add(item, "hot")

        # 限制召回数量
        return recalled[:recall_limit]

    async def _llm_rerank(
        self, query: str, candidates: list[dict], limit: int
    ) -> list[str] | None:
        """LLM 重排序：从候选中选出最相关的

        Args:
            query: 查询文本
            candidates: 候选记忆条目
            limit: 返回数量

        Returns:
            重排序后的记忆内容列表
        """
        # 构建候选列表文本
        candidate_lines = []
        for i, item in enumerate(candidates):
            candidate_lines.append(f"{i + 1}. {item['content']}")
        candidate_text = "\n".join(candidate_lines)

        prompt = f"""从以下记忆中选出与用户问题最相关的条目。

用户问题：{query}

记忆列表：
{candidate_text}

要求：
1. 只返回最相关的 {limit} 条记忆的编号（如：1,3,5）
2. 按相关性从高到低排序
3. 如果都不相关，返回：无
4. 只返回编号，不要其他内容"""

        try:
            response = await self._llm.chat(
                messages=[{"role": "user", "content": "请排序"}],
                system_prompt=prompt,
                max_tokens=100,
                temperature=0.1,
            )

            content = response.content.strip()

            if "无" in content and len(content) < 5:
                return []

            # 解析编号
            numbers = re.findall(r'\d+', content)
            if not numbers:
                return None

            results = []
            for num_str in numbers:
                idx = int(num_str) - 1
                if 0 <= idx < len(candidates):
                    results.append(candidates[idx]["content"])
                    if len(results) >= limit:
                        break

            return results if results else None

        except Exception as e:
            logger.debug(f"LLM rerank error: {e}")
            return None