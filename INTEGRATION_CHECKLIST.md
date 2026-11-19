# Muu 优化集成清单

## ✅ 已完成的代码工作

### 后端优化
- [x] `core/memory/embedder_lite.py` — 轻量化向量嵌入器（缓存 + 自适应批大小）
- [x] `core/memory/dynamic_gate.py` — 动态阈值系统（情绪/交互计数驱动）
- [x] `core/memory/causal_linker.py` — 因果链识别（记忆间关系提取）
- [x] `core/memory/lifecycle_manager.py` — 记忆生命周期管理（主动遗忘 + 归档）
- [x] `tests/test_optimizations.py` — 完整测试套件

### 前端美化
- [x] `webui/frontend/src/lib/theme.js` — 统一设计系统常量
- [x] `webui/frontend/src/styles/design-system.css` — 全局样式重构
- [x] `webui/frontend/src/components/ChatBubble.svelte` — 改进的气泡组件
- [x] `webui/frontend/src/components/layout/ModernChatLayout.svelte` — 现代化布局
- [x] `webui/frontend/src/components/InputBar.svelte` — 美化输入框
- [x] `webui/frontend/src/components/ConversationList.svelte` — 会话列表

### 文档
- [x] `OPTIMIZATION_GUIDE.md` — 详细优化指南
- [x] `INTEGRATION_CHECKLIST.md` — 集成清单（本文件）

---

## 📋 集成步骤

### 第1步：后端集成（预计 30-45 分钟）

#### 1.1 更新 `core/memory/manager.py`

替换硬编码的阈值和动态计算：

```python
from core.memory.dynamic_gate import DynamicGateSystem
from core.memory.causal_linker import CausalLinker
from core.memory.embedder_lite import LiteEmbedder

class MemoryManager:
    def __init__(self, data_dir, ...):
        # ... 现有代码 ...
        self._dynamic_gate = DynamicGateSystem()
        self._causal_linker = CausalLinker()
        self._embedder = LiteEmbedder(cache_size=1024)  # 替换原 embedder

    def get_memories(self, query, user_emotion=None, user_interaction_count=0):
        """获取相关记忆（应用动态阈值和因果链）"""
        
        # 1. 计算动态阈值
        threshold = self._dynamic_gate.compute_threshold(
            user_interaction_count=user_interaction_count,
            current_emotion=user_emotion,
            conversation_topic_consistency=0.5,  # TODO: 实际计算
        )
        
        # 2. 基础向量搜索
        candidates = self._vector_search(query, limit=200)
        
        # 3. 应用动态阈值过滤
        filtered = [c for c in candidates 
                   if c['similarity'] > threshold.absolute_min]
        
        # 4. 应用相对比率过滤
        if filtered:
            max_sim = max(c['similarity'] for c in filtered)
            filtered = [c for c in filtered 
                       if c['similarity'] >= max_sim * threshold.relative_ratio]
        
        # 5. 应用因果链加成
        scores = {c['id']: c['similarity'] for c in filtered}
        boosted_scores = self._causal_linker.rank_with_causal_boost(
            candidate_memories=filtered,
            query_memory_id=query,
            query_content=query,
            original_scores=scores,
        )
        
        # 6. 按增强分数排序返回
        return sorted(filtered, 
                     key=lambda c: boosted_scores.get(c['id'], 0),
                     reverse=True)[:50]
```

#### 1.2 更新 `core/chat/context_builder.py`

集成生命周期管理：

```python
from core.memory.lifecycle_manager import MemoryLifecycleManager

class ContextBuilder:
    def __init__(self, ...):
        self._lifecycle_mgr = MemoryLifecycleManager()

    def maintenance_pass(self, all_memories):
        """定期维护记忆（建议每天或每周一次）"""
        
        # 1. 计算遗忘评分
        forgotten = self._lifecycle_mgr.mark_for_forgetting(
            memory_ids=list(all_memories.keys()),
            memories=all_memories,
        )
        
        # 2. 归档旧记忆
        summaries = self._lifecycle_mgr.archive_old_memories(
            memories=all_memories,
            llm=self.llm,  # 可选，用于生成 LLM 摘要
        )
        
        # 3. 日志报告
        report = self._lifecycle_mgr.get_lifecycle_report(all_memories)
        logger.info(f"Memory lifecycle report: {report}")
        
        return forgotten, summaries
```

### 第2步：前端集成（预计 60 分钟）

#### 2.1 更新全局样式

在 `webui/frontend/src/App.svelte` 顶部导入新设计系统：

```svelte
<script>
  import 'svelte/transition';
  import './styles/design-system.css';
  import './lib/theme.js';
  
  // ... 现有代码 ...
</script>
```

#### 2.2 使用新布局组件

替换旧的对话布局：

```svelte
<!-- 原来的 -->
{#if activePage === 'chat'}
  <ChatPage />
{/if}

<!-- 替换为 -->
{#if activePage === 'chat'}
  <ModernChatLayout {conversations} {currentConversation} on:sendMessage />
{/if}
```

#### 2.3 迁移现有组件

逐步替换现有组件使用新的设计系统 CSS 变量：

```svelte
<!-- 原来的 -->
<button style="background: #9d7eff; color: white;">
  发送
</button>

<!-- 替换为 -->
<button class="btn-primary">
  发送
</button>
```

#### 2.4 响应式测试

在不同屏幕尺寸测试：
- 桌面 (1440px+)
- 平板 (768px - 1024px)
- 手机 (320px - 640px)

### 第3步：测试和性能验证（预计 30 分钟）

```bash
# 1. 运行单元测试
pytest tests/test_optimizations.py -v

# 2. 运行集成测试（如果有）
pytest tests/test_integration.py -v

# 3. 性能基准测试
pytest tests/test_optimizations.py --benchmark-only

# 4. 前端构建测试
cd webui/frontend
npm run build
npm run preview
```

### 第4步：启用优化功能（配置）

#### 4.1 环境变量

在 `.env` 中添加：

```env
# 向量嵌入器配置
MU_EMBEDDING_CACHE_SIZE=1024
MU_EMBEDDING_QUANTIZE=false  # 可选：启用 int8 量化

# 记忆系统配置
MU_MEMORY_DYNAMIC_GATE=true
MU_MEMORY_CAUSAL_LINKING=true
MU_MEMORY_LIFECYCLE_MANAGEMENT=true

# 生命周期管理
MU_ARCHIVE_AGE_DAYS=90
MU_FORGET_SCORE_THRESHOLD=0.8
```

#### 4.2 配置文件 (`config/muu.yaml` 或类似)

```yaml
memory:
  embedder:
    type: lite
    cache_size: 1024
    batch_size: null  # 自动计算
  
  dynamic_gate:
    enabled: true
    min_absolute: 0.35
    relative_ratio: 0.9
  
  causal_linking:
    enabled: true
    time_window_hours: 48
  
  lifecycle:
    enabled: true
    archive_age_days: 90
    forget_threshold: 0.8
```

---

## 🧪 验证清单

在每个集成阶段后验证：

- [ ] Python 代码无语法错误
- [ ] 所有新模块可以正常导入
- [ ] 单元测试全部通过（pytest）
- [ ] 对话功能正常运作（无回归）
- [ ] 前端样式正确应用
- [ ] 缓存命中率 > 20%（生产环境）
- [ ] 内存占用对比基准（应下降 30-50%）
- [ ] 对话延迟 < 50ms（用户感知）
- [ ] 移动端响应式工作正常

---

## 📊 性能目标

| 指标 | 目标 | 验证方法 |
|------|------|--------|
| 嵌入器内存占用 | < 100MB | `psutil.Process().memory_info()` |
| 缓存命中率 | > 30% | 内置统计 |
| 平均查询延迟 | < 50ms | 基准测试 |
| 前端首屏加载 | < 2s | Lighthouse |
| 对话气泡渲染 | 60fps | DevTools Performance |

---

## 🚀 部署步骤

1. **测试环境验证**（所有清单项通过）
2. **灰度发布**（10% 用户）
3. **监控性能指标**（1-2 周）
4. **全量发布**（若无异常）

---

## 📚 相关文件

- `OPTIMIZATION_GUIDE.md` — 详细优化方案说明
- `tests/test_optimizations.py` — 单元测试代码
- 各模块源文件（见"已完成代码工作"）

---

## 🔗 下一步工作（可选）

- [ ] 启用 int8 量化（需要 bitsandbytes）
- [ ] LLM 摘要生成（集成 LLM 接口）
- [ ] 图表化性能仪表板（可视化内存/缓存/延迟）
- [ ] A/B 测试（对比优化前后的用户体验）
- [ ] 用户情绪识别（从对话文本自动提取）

