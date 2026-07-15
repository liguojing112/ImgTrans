# AGENTS.md

## 项目概述

图片翻译软件（Image Translator）—— 将图片中的文字识别、翻译并渲染回图片中。

## 技术栈

待定（将在 ARCHITECTURE.md 中记录决策过程）

## 项目结构

```
image-translator/
├── AGENTS.md              # 本文件 — 公共 AI 协作规则
├── CLAUDE.md              # Claude Code 专属补充规则
├── README.md              # 项目说明
├── docs/                  # 文档
│   ├── source/            # 客户原始需求文档
│   ├── MVP_REQUIREMENTS.md
│   ├── ACCEPTANCE_CRITERIA.md
│   ├── ARCHITECTURE.md
│   └── DECISIONS.md
├── tasks/                 # 任务拆分
├── src/                   # 源代码
├── tests/                 # 测试
└── scripts/               # 工具脚本
```

## 编码规则

- 优先编辑现有文件，而非创建新文件
- 不要引入超出任务需求的抽象或重构
- 不要在代码中添加不必要的注释 — 只有 WHY 不明显时才加
- 不要主动创建文档类 `.md` 文件，除非任务明确要求
- 遇到不确定的决策时，先询问而非自行决断

## 测试命令

待补充

## 禁止事项

- 绝对禁止在没有明确指示的情况下主动打包项目（zip/tar/7z 等）
- 不要主动 commit 或 push，除非明确要求

## 完成标准

- 所有代码通过测试
- 功能符合 ACCEPTANCE_CRITERIA.md 中的验收标准
- 不引入已知的 bug 或回归问题
