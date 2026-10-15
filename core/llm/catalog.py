"""User-facing model provider catalog.

The catalog is data-driven so adding a provider does not require changing the
WebUI onboarding flow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    description: str
    base_url: str
    default_model: str
    env_key: str
    provider: str = "openai"

    def public_dict(self) -> dict[str, str]:
        return asdict(self)


PROVIDER_CATALOG: tuple[ProviderSpec, ...] = (
    # 国内厂商
    ProviderSpec("deepseek", "DeepSeek", "国产便宜好用，推荐新手", "https://api.deepseek.com/v1", "deepseek-chat", "DEEPSEEK_API_KEY", provider="deepseek"),
    ProviderSpec("qwen", "通义千问", "阿里云，国内访问快，VL 版本支持视觉", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-turbo", "TONGYI_API_KEY"),
    ProviderSpec("zhipu", "智谱 GLM", "GLM-4V-Flash 支持视觉，有免费额度", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash", "ZHIPU_API_KEY"),
    ProviderSpec("kimi", "Kimi", "月之暗面，长上下文对话", "https://api.moonshot.cn/v1", "kimi-latest", "KIMI_API_KEY"),
    ProviderSpec("moonshot", "Moonshot VL", "Kimi 同厂，VL 版本支持视觉", "https://api.moonshot.cn/v1", "moonshot-v1-8k", "MOONSHOT_API_KEY"),
    ProviderSpec("mimo", "小米 MiMo", "V2.5 系列，多模态 + 深度思考", "https://api.xiaomimimo.com/v1", "mimo-v2.5-pro", "MIMO_API_KEY"),
    ProviderSpec("doubao", "豆包 (字节)", "字节跳动，Vision 版本支持图片", "https://ark.cn-beijing.volces.com/api/v3", "doubao-1.5-pro-32k", "DOUBAO_API_KEY"),
    ProviderSpec("baichuan", "百川", "Baichuan 系列，国产大模型", "https://api.baichuan-ai.com/v1", "baichuan4", "BAICHUAN_API_KEY"),
    ProviderSpec("minimax", "MiniMax", "海螺 AI，abab 系列", "https://api.minimax.chat/v1", "abab6.5s-chat", "MINIMAX_API_KEY"),
    ProviderSpec("stepfun", "阶跃星辰", "Step 系列，Step-1V 支持视觉", "https://api.stepfun.com/v1", "step-1-8k", "STEPFUN_API_KEY"),
    # 海外厂商
    ProviderSpec("openai", "OpenAI", "GPT-4o 系列，多模态，需海外网络", "https://api.openai.com/v1", "gpt-4o-mini", "OPENAI_API_KEY"),
    # Gemini 走 Google 的 OpenAI 兼容端点, 复用 OpenAICompatibleLLM
    ProviderSpec("gemini", "Gemini", "Google 模型，多模态，有免费额度", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash", "GEMINI_API_KEY"),
)


def get_provider_spec(key: str) -> ProviderSpec | None:
    return next((item for item in PROVIDER_CATALOG if item.key == key), None)


def public_provider_catalog() -> list[dict[str, str]]:
    return [item.public_dict() for item in PROVIDER_CATALOG]

