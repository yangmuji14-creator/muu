"""Vision Manager — 双路径图片识别

路径A（多模态模型）：将图片直接发送给主模型
路径B（文本模型）：将图片发送给视觉模型获取文字描述，再结合用户文本发送给主模型

配置（settings.json advanced 段）:
    "vision_model": {
        "provider": "openai",        // 视觉模型提供商
        "model_name": "gpt-4o",      // 模型名
        "api_key": "sk-xxx",          // API key（不填用环境变量）
        "base_url": ""                // 自定义 endpoint（可选）
    }

用法:
    vm = VisionManager(main_model, vision_config)
    result = await vm.process("/path/to/image.jpg", "这张图里有什么？")
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

from loguru import logger


# 模型是否支持图片，由用户在设置页勾选（models.<key>.multimodal = "yes"/"no"），
# 不再按模型名字猜 —— 旧的 MULTIMODAL_PATTERNS/NOT_MULTIMODAL 启发式已删除：
# 厂商上新比代码快（deepseek-flash 上线视觉时这张表就漏了），猜错要么白发
# 图片请求、要么把图硬塞给纯文本模型造成幻觉。


def _compress_image(image_path: str | Path, long_edge: int = 1280, quality: int = 85) -> tuple[bytes, str]:
    """把图片压缩为适合发给视觉模型的 JPEG 字节（显著加快上传与识别）。

    长边压到 long_edge、转 JPEG（透明通道先铺白底）。PIL 不可用或图片
    本身很小时原样返回。失败时降级为原始文件字节。
    """
    path = Path(image_path)
    raw = path.read_bytes()
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(path) as im:
            im.load()
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            w, h = im.size
            scale = long_edge / max(w, h)
            if scale < 1:
                im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            data = buf.getvalue()
        # 只有确实变小才用压缩结果
        return (data, "image/jpeg") if len(data) < len(raw) else (raw, _guess_mime(path))
    except Exception as e:
        logger.debug(f"Image compress skipped: {e}")
        return raw, _guess_mime(path)


def _guess_mime(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(str(path))
    return mime_type if mime_type and mime_type.startswith("image/") else "image/png"


def encode_image(image_path: str | Path, *, compress: bool = True) -> tuple[str, str]:
    """将图片编码为 base64 data URL（默认先压缩，加速传输与识别）

    Returns:
        (data_url, mime_type)
    """
    path = Path(image_path)
    if compress:
        data, mime_type = _compress_image(path)
    else:
        data = path.read_bytes()
        mime_type = _guess_mime(path)

    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}", mime_type


class VisionManager:
    """双路径图片识别管理器"""

    def __init__(
        self,
        main_model: Any = None,           # litellm 模型实例
        vision_config: dict | None = None,  # settings.json vision_model 配置
        multimodal_declared: str = "auto",  # 用户声明的主模型多模态能力
        image_mode: str = "auto",           # auto / direct / vision
    ):
        self._main_model = main_model
        self._vision_config = vision_config or {}
        self._vision_enabled = bool(self._vision_config.get("model_name"))
        self._image_mode = image_mode if image_mode in ("auto", "direct", "vision") else "auto"
        self._multimodal_declared = str(multimodal_declared or "auto").strip().lower()

        if self._vision_enabled:
            logger.info(
                f"Vision fallback enabled: "
                f"{self._vision_config.get('provider')}/{self._vision_config.get('model_name')}"
            )

    @property
    def main_is_multimodal(self) -> bool:
        """主模型是否支持图片 —— **用户显式声明优先于启发式检测**

        以 VisionManager 自己的声明为准（用户在设置页改的实时生效），
        而不是读模型实例启动时注册的旧属性——否则改了配置链路描述不会变。
        """
        if not self._main_model:
            return False
        from core.config import resolve_multimodal

        model_name = getattr(self._main_model, "model_name", "")
        return resolve_multimodal(model_name, self._multimodal_declared or "auto")

    def set_multimodal_declared(self, declared: str) -> None:
        """更新用户的多模态声明（auto / yes / no），立即影响链路判定。"""
        self._multimodal_declared = str(declared or "auto").strip().lower() or "auto"
        # 同步回模型实例, 让 /api/model 等只读实例属性的调用方也拿到一致结果
        if self._main_model is not None:
            try:
                self._main_model.multimodal_declared = self._multimodal_declared
            except Exception:
                pass

    @property
    def image_mode(self) -> str:
        """当前图片处理方式"""
        return self._image_mode

    @property
    def image_chain(self) -> str:
        """当前图片流程的一句话说明（设置页展示，把「何时走哪条路」讲清楚）"""
        direct = self.main_is_multimodal
        fallback = self._vision_enabled
        vname = self._vision_config.get("model_name") or "未设置"
        mname = str(getattr(self._main_model, "model_name", "") or "语言模型")

        if self._image_mode == "direct":
            return f"图片直接发给语言模型（{mname}）看，一次调用出结果（已强制直连，备用识别不启用）"
        if self._image_mode == "vision":
            return (f"图片先由 {vname} 转成文字描述，描述再交给语言模型（已强制备用识别）"
                    if fallback else "已强制备用识别，但还没有设置识别模型")
        if direct:
            return (f"图片直接发给语言模型（{mname} 已勾选「多模态」），一次调用最快；"
                    f"备用识别不启用")
        if fallback:
            return (f"语言模型（{mname}）没勾「多模态」→ 图片先由 {vname} 转成文字描述，"
                    f"描述再交给语言模型（两次调用，备用识别）")
        return "当前识别不了图片：给语言模型勾上「多模态」，或把某个模型设为「识别」（备用）"

    def update_config(
        self,
        vision_config: dict | None,
        image_mode: str | None = None,
        multimodal_declared: str | None = None,
    ) -> None:
        """Apply a validated fallback model configuration without restarting."""
        self._vision_config = dict(vision_config or {})
        self._vision_enabled = bool(self._vision_config.get("model_name"))
        if image_mode is not None:
            self._image_mode = image_mode if image_mode in ("auto", "direct", "vision") else "auto"
        if multimodal_declared is not None:
            self.set_multimodal_declared(multimodal_declared)
        logger.info(
            "Vision fallback {} (mode={}, chain={})",
            "updated" if self._vision_enabled else "disabled",
            self._image_mode,
            self.image_chain,
        )

    def update_main_model(self, main_model: Any) -> None:
        """Refresh the active main model after a live registry reload."""
        self._main_model = main_model

    # ── 路由 ──

    async def process(
        self,
        image_path: str | Path,
        user_text: str = "请描述这张图片的内容",
    ) -> str:
        """处理图片识别请求

        Args:
            image_path: 图片路径
            user_text: 用户对图片的附加问题

        Returns:
            图片描述文本
        """
        if not Path(image_path).exists():
            return f"[图片不存在: {image_path}]"

        # 用户可通过 advanced.image_mode 强制某一条链路
        direct_ok = self.main_is_multimodal and self._main_model is not None
        fallback_ok = self._vision_enabled
        if self._image_mode == "direct":
            fallback_ok = False      # 强制直连主模型, 跳过中间层
        elif self._image_mode == "vision":
            direct_ok = False        # 强制走视觉模型, 不让主模型看图

        # 路径A：主模型支持多模态 → 直接发送（最快，跳过中间层）
        if direct_ok:
            logger.info(f"Vision: using main model (multimodal) for {image_path}")
            result = await self._direct_vision(image_path, user_text)
        elif fallback_ok:
            logger.info(f"Vision: using fallback model for {image_path}")
            result = await self._fallback_vision(image_path, user_text)
        else:
            # 都不行
            logger.warning(f"Vision: no model available for {image_path}")
            return ("[图片识别未配置] 当前模型不支持图片识别，且未配置视觉降级模型。\n"
                    "请在「设置 → 模型设置」中选择主模型是否多模态，或配置视觉降级模型。")

        # ⚠️ 空描述必须视为失败：推理类视觉模型在 max_tokens 太小时会把预算
        # 全耗在 reasoning 上返回空 content（HANDOFF 已踩坑记录）。若把空串
        # 当描述继续传给主模型，主模型会顺着聊天语境**幻觉编造**图片内容
        # （2026-10-17 实测：两人的图被说成"纯棕色"）。
        if not str(result or "").strip():
            logger.error(f"Vision returned EMPTY description for {image_path}")
            return "[图片识别失败] 视觉模型没有返回内容，请重试或更换视觉模型。"
        return result

    # ── 路径A：直传 ──

    async def _openai_vision_call(
        self, model_name: str, base_url: str, api_key: str, messages: list,
    ) -> str:
        """OpenAI 兼容格式发图片（直连/备用两条路线共用）。

        ⚠️ 不要走 litellm 的 `deepseek/` 等厂商专属前缀路由：1.91.3 实测
        会把 image_url 内容块丢掉（模型回复"没收到图片附件"）；
        `openai/` 前缀 + base_url 或原生 openai client 都正常。
        """
        import os

        actual_base = base_url or "https://api.openai.com/v1"
        actual_key = api_key or os.environ.get("OPENAI_API_KEY", "")

        try:
            from openai import AsyncOpenAI
        except ImportError:
            AsyncOpenAI = None

        if AsyncOpenAI is not None:
            client = AsyncOpenAI(api_key=actual_key, base_url=actual_base)
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=2000,
            )
            return response.choices[0].message.content

        # 旧版本 openai 库降级：litellm openai/ 前缀（同样保留图片内容块）
        import litellm
        response = await litellm.acompletion(
            model=f"openai/{model_name}",
            messages=messages,
            api_key=actual_key,
            api_base=actual_base,
            max_tokens=2000,
        )
        return response.choices[0].message.content

    async def _direct_vision(self, image_path: str | Path, user_text: str) -> str:
        """将图片直接发送给多模态主模型（勾了「能看图」的语言模型）"""
        data_url, mime_type = encode_image(image_path)

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": user_text or "请描述这张图片"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }]

        try:
            # 主模型 wrapper 自带 model_name / api_key / base_url 时，
            # 一律走 OpenAI 兼容直连（见 _openai_vision_call 的 litellm 警告）
            model_name = str(getattr(self._main_model, "model_name", "") or "")
            api_key = str(getattr(self._main_model, "api_key", "") or "")
            base_url = str(getattr(self._main_model, "base_url", "") or "")
            if model_name and api_key:
                return await self._openai_vision_call(model_name, base_url, api_key, messages)

            # 兜底：无密钥属性的 wrapper 走统一 chat 接口
            if hasattr(self._main_model, "chat"):
                response = await self._main_model.chat(messages=messages)
                return response.content if hasattr(response, "content") else str(response)

            import litellm
            response = await litellm.acompletion(
                model=model_name or "gpt-4o",
                messages=messages,
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Direct vision failed: {e}")
            if self._vision_enabled:
                return await self._fallback_vision(image_path, user_text)
            return "[图片识别失败] 主模型暂时无法读取这张图片，请稍后重试。"

    # ── 路径B：降级 ──

    async def _fallback_vision(self, image_path: str | Path, user_text: str) -> str:
        """备用路线：用独立视觉模型把图片转成文字描述"""
        data_url, mime_type = encode_image(image_path)

        vision_cfg = self._vision_config
        model_name = vision_cfg.get("model_name", "gpt-4o")
        base_url = vision_cfg.get("base_url", "")
        api_key = vision_cfg.get("api_key", "")

        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": user_text or "请客观描述这张图片的内容：画面里有什么、是什么场景、有什么细节"},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }]

        try:
            description = await self._openai_vision_call(model_name, base_url, api_key, messages)
            logger.debug(f"Fallback vision result ({len(description)} chars)")

            # 密钥经显式传参（api_key=），不依赖环境变量，也无需恢复任何
            # 全局状态。旧版本这里有一段 load_dotenv(override=True) + 手工
            # 回读 .env 的补丁（MiMo 密钥污染 bug 的遗迹），会把 .env 占位符
            # 重新灌回环境变量（resolve 优先级修复前的 401 复发源），已删除。

            return f"[图片描述] {description}"

        except Exception as e:
            logger.error(f"Fallback vision failed: {e}")
            return f"[图片识别失败: {e}]"

    # ── 辅助：为 Pipeline 构造带图片描述的增强消息 ──

    @staticmethod
    def single_line_description(vision_result: str) -> str:
        """把视觉模型输出规整为单行纯描述（供 image_desc 字段/上下文注入）。

        换行折叠为空格；剥掉 _fallback_vision 加的 [图片描述] 内部前缀。
        """
        desc = " ".join(str(vision_result or "").split())
        if desc.startswith("[图片描述]"):
            desc = desc[len("[图片描述]"):].strip()  # 内部标记，不进对话上下文
        return desc

    def build_enhanced_message(
        self,
        vision_result: str,
        user_text: str,
    ) -> str:
        """将视觉模型的输出和用户文本组合为增强消息（CLI /img 路径用）。

        ⚠️ 必须输出单行：pipeline.format_multi_message 会按换行把消息拆成
        [消息1]/[消息2]... 并全部落库。这里若多行，描述的每一行、甚至
        "请用角色自然回应"之类的指令行都会被当成独立消息吃掉大量上下文
        （2026-10-17 用户实测：一张图被拆成 16 条"消息"）。

        Web/微信路径已改走 pipeline 的 image_desc 注入机制（存储/显示分离），
        不再经过本方法。

        Returns:
            单行组合消息
        """
        desc = self.single_line_description(vision_result)
        parts = []
        if user_text:
            parts.append(f'对方同时说：「{user_text}」')
        parts.append(f'对方发了一张图片：{desc}')
        return "。".join(p for p in parts if p)
