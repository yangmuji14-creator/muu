"""VisionManager：双路径判定与链路描述（core/multimodal 首个测试）。

覆盖 2026-11-01 B0 修复的契约：vision_model 指向不存在模型时必须
诚实禁用（``bool(model_name)``），而不是带着坏值假装可用。
"""

from __future__ import annotations

from core.multimodal.vision import VisionManager


class FakeMainModel:
    """带 multimodal_declared 属性的鸭子类型主模型。"""

    def __init__(self, model_name: str = "deepseek-chat", declared: str = "auto"):
        self.model_name = model_name
        self.multimodal_declared = declared


class TestVisionEnabled:
    def test_empty_model_name_means_disabled(self) -> None:
        """B0 修复的契约：置空即诚实禁用，坏值比缺值更糟。"""
        mgr = VisionManager(vision_config={"provider": "openai", "model_name": ""})
        assert mgr._vision_enabled is False

    def test_missing_config_means_disabled(self) -> None:
        assert VisionManager(vision_config=None)._vision_enabled is False

    def test_named_model_enables(self) -> None:
        mgr = VisionManager(vision_config={"model_name": "some-vision"})
        assert mgr._vision_enabled is True


class TestImageMode:
    def test_invalid_mode_falls_back_to_auto(self) -> None:
        mgr = VisionManager(image_mode="whatever")
        assert mgr.image_mode == "auto"

    def test_valid_modes_kept(self) -> None:
        for mode in ("auto", "direct", "vision"):
            assert VisionManager(image_mode=mode).image_mode == mode


class TestImageChain:
    """链路描述是设置页给用户看的「诚信文本」，四条路径都要说人话。"""

    def test_direct_mode(self) -> None:
        mgr = VisionManager(
            main_model=FakeMainModel(),
            vision_config={"model_name": "v"},
            image_mode="direct",
        )
        assert "直接发给语言模型" in mgr.image_chain

    def test_vision_mode_without_model_admits_it(self) -> None:
        mgr = VisionManager(image_mode="vision")
        assert "还没有设置识别模型" in mgr.image_chain

    def test_no_capability_admits_it(self) -> None:
        """既没勾多模态也没备用识别——必须明说「识别不了」。"""
        mgr = VisionManager(
            main_model=FakeMainModel(declared="no"),
            vision_config={"model_name": ""},
        )
        assert "识别不了图片" in mgr.image_chain

    def test_multimodal_direct_by_declaration(self) -> None:
        mgr = VisionManager(
            main_model=FakeMainModel(declared="yes"),
            vision_config={"model_name": ""},
        )
        assert "多模态" in mgr.image_chain


class TestMultimodalDeclaration:
    def test_set_declared_updates_main_model(self) -> None:
        model = FakeMainModel(declared="auto")
        mgr = VisionManager(main_model=model)
        mgr.set_multimodal_declared("no")
        assert mgr._multimodal_declared == "no"
        assert model.multimodal_declared == "no"

    def test_no_main_model_is_not_multimodal(self) -> None:
        assert VisionManager(main_model=None).main_is_multimodal is False

    def test_declared_no_overrides_model_name(self) -> None:
        """用户说不能看图，模型叫什么名字都不能看——显式声明压过启发式。"""
        mgr = VisionManager(
            main_model=FakeMainModel(model_name="gpt-4o", declared="no"),
        )
        assert mgr.main_is_multimodal is False
