"""慕（muu）测试套件。

运行:
    ./.venv/Scripts/python.exe -m pytest            # 全部
    ./.venv/Scripts/python.exe -m pytest -q         # 安静
    ./.venv/Scripts/python.exe -m pytest tests/test_config_uid.py -v

约定:
- 全部为纯函数 / 纯数据结构测试，不联网、不读写真实 data/ 与 config/。
- 需要临时目录时用 pytest 的 tmp_path，不碰仓库内文件。
- 覆盖的核心点见各文件顶部 docstring。
"""
