# 贡献指南

感谢你考虑为「慕」（muu）贡献力量！🎉

「慕」是一个**本地优先**的 AI 伴侣：数据不出设备，模型通过 LiteLLM 对接任意服务商。在提交贡献之前，请先花几分钟读完这份指南。

## 行为准则

参与本项目即表示你同意遵守 [行为守则](CODE_OF_CONDUCT.md)。

## 我可以贡献什么？

- 🐛 **Bug 修复** —— 先在 [Issues](https://github.com/yangmuji14-creator/muu/issues) 里搜索是否已有相同问题，没有再新建
- ✨ **新功能** —— 建议先开一个 issue 描述动机与方案，达成一致后再动手，避免白做
- 📖 **文档改进** —— README / CHANGELOG 的错漏与补充
- 🌍 **翻译** —— 界面与文档的本地化

## 开发环境搭建

```bash
# 1. 克隆
git clone https://github.com/yangmuji14-creator/muu.git
cd muu

# 2. 安装依赖（推荐虚拟环境；会自动选择）
python install.py

# 3. 首次配置（模型 + 人设向导）
python main.py setup

# 4. 启动
python main.py web     # 网页端 http://127.0.0.1:8000
```

前端改动需要重新构建（`webui/static/` 是构建产物，不是源码）：

```bash
cd webui/frontend
npm install
npm run build
```

## 项目约定（重要）

- **master 只保留产品源码**。交接/评审/排查类开发文档、打包脚本、截图对照等一律不入库
- **密钥与个人数据永不入库**：`.env`、`data/`、`config/tts_providers.json` 已被 .gitignore 拦截，请勿绕过
- 环境变量使用 `MU_` 前缀（旧 `CC_` 前缀处于兼容期）
- SQLite 写操作后必须在同一次调用内 `commit` 或 `rollback`（隐式事务不收尾会造成库级锁死）
- 改动前端后必须重新 build 才生效；改完 CSS 建议截图确认
- 涉及路径/密钥的代码请保持既有安全设计：密钥 DPAPI 加密、路径穿越防护、上传大小限制

## 贡献许可（重要）

提交 PR 即表示你同意以下两项声明：

1. 你的贡献以 **AGPL-3.0** 授权给本项目与所有使用者；
2. 你授予项目维护者一项**永久、免费、可转授权**的权利：在未来以其它许可（含商业许可）发布、再许可你的贡献。

这是项目「AGPL 社区版 + 可选商业授权」双许可模式的基础——没有这条，维护者将无法为企业用户提供闭源授权，也就无法持续投入维护。

## 提交变更

1. 从 `master` 拉出功能分支：`git checkout -b feat/your-feature`
2. 提交信息用中文，说清**动机**与**验证方式**（而不只是改了什么文件）
3. 提交前自查：
   - [ ] `python -c "import main"` 无报错（语法/导入完整）
   - [ ] 服务能启动、核心接口冒烟通过（`/api/health`、`/api/chat` 等）
   - [ ] `git diff --cached` 里没有密钥、聊天记录等敏感内容
4. 发起 Pull Request，描述清楚：改了什么、为什么、怎么验证的

## 报告问题

请使用 [Issue 模板](https://github.com/yangmuji14-creator/muu/issues/new/choose)：
- Bug 请附上**复现步骤**、预期/实际行为、启动日志（`logs/` 或控制台，注意脱敏）
- 功能建议请说明使用场景

## 安全问题

**请勿公开提交安全漏洞！** 见 [安全策略](SECURITY.md)，通过 GitHub 私密安全建议报告。
