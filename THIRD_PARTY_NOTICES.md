# 原始项目与二次开发说明

本项目基于 Picire 二次开发，保留原版算法、版权与许可证。

- 原始仓库：https://github.com/renatahodovan/picire
- 基准提交：`1e5b25c5aee2bee62f3e0192d591050219eaec22`
- 原作者：Renata Hodovan、Akos Kiss；部分原版文件还注明 Daniel Vince 等贡献者。
- 原版许可证：BSD-3-Clause；完整原文及其继承的版权声明保留在 `LICENSE.rst`。

PANDAO 修改内容：新增 `pandao_repro` 模块、中文使用说明、结构化输入重建、命令判定、稳定性核对、结果报告、演示入口及相关检查；调整发行名称和固定版本；让原版命令入口识别本发行包版本。

原版核心缩减算法未改写，不能将其归为 PANDAO 原创算法。PANDAO 新增部分也按 BSD-3-Clause 发布。原作者及贡献者不为本衍生项目背书。

运行依赖包括 chardet 与 inators，安装时通过其各自的发行包取得。它们的许可证以安装包内原文为准，未把依赖源码重新包装成本项目原创内容。
