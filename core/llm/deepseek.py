"""DeepSeek 模型接入"""

from .base import BaseLLM


class DeepSeekLLM(BaseLLM):
    """DeepSeek 大模型接入

    DeepSeek API 兼容 OpenAI 格式，使用 LiteLLM 的 deepseek/ 前缀。
    """

    def _build_model_id(self) -> str:
        # ⚠️ 用 openai/ 前缀而非 deepseek/：litellm 1.91.3 的 deepseek/ 专属
        # 路由会丢 image_url 内容块（多模态图片发不到模型，2026-10-18 实测
        # 模型回复"图我这边没收到"）。base_url / api_key 都是显式传入，
        # openai/ 前缀 = 纯 OpenAI 兼容透传，行为一致且保留图片内容块。
        return f"openai/{self.model_name}"
