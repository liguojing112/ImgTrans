<div align="center">

<img src="https://api.iconify.design/mdi/image-search-outline.svg?color=%234F8CFF&height=64" alt="ImgTrans">

<h1>优译图 AI · ImgTrans</h1>

<h3>图片翻译桌面客户端 + 授权服务端</h3>

<p><b>电商图片一键翻译 —— 识别原文 · 智能擦除 · 译文回排 · 多端授权</b></p>

<p>
<img src="https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11">
<img src="https://img.shields.io/badge/PySide6-6.11.1-41CD52?style=flat-square&logo=qt&logoColor=white" alt="PySide6">
<img src="https://img.shields.io/badge/FastAPI-0.104+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
<img src="https://img.shields.io/badge/SQLAlchemy-2.x-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy">
<img src="https://img.shields.io/badge/PostgreSQL-psycopg3-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL">
<img src="https://img.shields.io/badge/Alembic-1.13+-6BA81E?style=flat-square" alt="Alembic">
</p>

<p>
<img src="https://img.shields.io/badge/ONNX%20Runtime-1.23.2-005CED?style=flat-square&logo=onnx&logoColor=white" alt="ONNX Runtime">
<img src="https://img.shields.io/badge/RapidOCR-3.9.1-FF6F00?style=flat-square" alt="RapidOCR">
<img src="https://img.shields.io/badge/LaMa-inpainting-8A2BE2?style=flat-square" alt="LaMa">
<img src="https://img.shields.io/badge/OpenCV-4.11-5C3EE8?style=flat-square&logo=opencv&logoColor=white" alt="OpenCV">
<img src="https://img.shields.io/badge/NumPy-1.26.4-013243?style=flat-square&logo=numpy&logoColor=white" alt="NumPy">
<img src="https://img.shields.io/badge/Pillow-12.3.0-11557C?style=flat-square" alt="Pillow">
</p>

<p>
<img src="https://img.shields.io/badge/%E6%B5%8B%E8%AF%95-816%20passed-brightgreen?style=flat-square&logo=pytest&logoColor=white" alt="测试 816 passed">
<img src="https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square" alt="平台">
<img src="https://img.shields.io/badge/%E6%8E%A8%E7%90%86-CPU%20only-orange?style=flat-square" alt="CPU only">
<img src="https://img.shields.io/badge/%E6%94%AF%E4%BB%98-%E5%BE%AE%E4%BF%A1%E6%94%AF%E4%BB%98-07C160?style=flat-square&logo=wechat&logoColor=white" alt="微信支付">
<img src="https://img.shields.io/badge/License-%E9%97%AD%E6%BA%90%E5%95%86%E7%94%A8-red?style=flat-square" alt="License 闭源商用">
</p>

</div>

---

## ![](https://api.iconify.design/mdi/clipboard-text.svg?color=%23546E7A&height=24) 工单信息

> 本仓库由启创科技工单系统自动创建，仅限本工单开发协作使用。

| 项目 | 内容 |
| :--- | :--- |
| **承接单位** | 启创科技 |
| **开发工程师** | 李国敬 |
| **工程师 ID** | `175` |
| **工号** | `QCGCS059965` |
| **GitCode 账号** | [@xiaohaibo112](https://gitcode.com/xiaohaibo112) |
| **工单号** | `5127681961385028631` |
| **项目名称** | app.doc |
| **创建时间** | 2026-08-10 18:00:00 |
| **交付期限** | 未设定 |
| **开发内容** | app.doc |

**交付要求**

1. 代码请推送到 `main` 分支，提交信息使用中文并说明改动要点。
2. 请及时推送代码，系统每 8 小时巡检一次，长期无提交将邮件提醒并上报管理员。
3. 完成开发后请在工单系统提交交付，等待管理员验收。
4. 工单验收完成后，本仓库的协作权限将被自动回收。

<sub>启创科技 · [www.zce.ee](https://www.zce.ee) · 本文件由系统自动生成于 2026-08-19 16:35:41</sub>

---

## ![](https://api.iconify.design/mdi/target.svg?color=%23F4511E&height=24) 项目简介

跨平台桌面应用，把电商图片里的文字识别出来、翻译、擦掉原文、再把译文排版回原位。配套一个服务端负责激活码授权、翻译代理、微信支付和后台管理。

| 模块 | 技术栈 | 说明 |
| --- | --- | --- |
| ![](https://api.iconify.design/mdi/monitor.svg?color=%2342A5F5&height=18) **客户端** | Python 3.11 + PySide6（Qt6） | 本地推理，原图不出本机 |
| ![](https://api.iconify.design/mdi/cloud.svg?color=%2326C6DA&height=18) **服务端** | FastAPI + SQLAlchemy + Alembic + PostgreSQL | 激活授权、翻译代理、支付、后台 |
| ![](https://api.iconify.design/mdi/text-recognition.svg?color=%23EC407A&height=18) **识别** | RapidOCR（PP-OCRv5/v6 ONNX） | 9 个模型，支持中英韩泰阿拉伯等 |
| ![](https://api.iconify.design/mdi/auto-fix.svg?color=%23AB47BC&height=18) **修复** | LaMa（ONNX，Apache-2.0） | 傅里叶卷积，全图感受野 |
| ![](https://api.iconify.design/mdi/flash.svg?color=%23FFA726&height=18) **推理** | onnxruntime **CPU**（无 CUDA 依赖） | 用户机器不要求独显 |
| ![](https://api.iconify.design/mdi/currency-cny.svg?color=%2366BB6A&height=18) **商业模式** | 激活码 + 时长包 + 微信支付 | **闭源商用**，见[许可红线](#12-许可合规红线) |

---

## ![](https://api.iconify.design/mdi/book-open-page-variant.svg?color=%235E35B1&height=24) 这份文档的定位

这是一份**交接文档**，目标是让接手的人不依赖任何口头说明就能：配好环境 → 跑通测试 → 看懂架构 → 知道哪里是雷区 → 继续开发。

已经把上一轮开发的完整技术背景（含**失败的尝试**和**被证伪的判断**）写进[第 9 章](#9-擦除质量完整技术背景)和[第 10 章](#10-关键决策记录)。这两章比代码更重要——擦除质量这块，光看代码会想不通为什么写成这样，然后很可能重走一遍已经被数据证伪的路。**动手改擦除逻辑之前请务必读完第 9 章。**

本仓库**只含源代码**，不含虚拟环境、模型文件、构建产物和测试语料图片（打包进去要几百 MB）。按[第 3 章](#3-部署教程)自己拉一遍，全程约 15 分钟，取决于网速。

---

## ![](https://api.iconify.design/mdi/format-list-bulleted.svg?color=%235C6BC0&height=24) 目录

| 章节 | 内容 | 什么时候看 |
| --- | --- | --- |
| [1. 五分钟上手](#1-五分钟上手) | 一串命令跑起来 | 现在 |
| [2. 环境要求](#2-环境要求) | Python 版本、系统、磁盘 | 配环境前 |
| [3. 部署教程](#3-部署教程) | 依赖、模型下载、启动客户端与服务端 | 配环境时 |
| [4. 开发教程](#4-开发教程) | 测试、质量基准、分层规则、how-to、调试、协作规范 | 开始写代码时 |
| [5. 架构](#5-架构) | 分层图、主流程、代码地图、领域模型、API 清单 | 读代码时 |
| [6. 模型清单与下载地址](#6-模型清单与下载地址) | 9 个模型的来源与校验 | 配环境时 / 换模型时 |
| [7. 环境变量参考](#7-环境变量参考) | 客户端 5 个 + 服务端 20 多个 | 部署时 |
| [8. 本次开发的文件](#8-本次开发的文件) | 上一轮改了什么、为什么 | 接手时 |
| [9. 擦除质量：完整技术背景](#9-擦除质量完整技术背景) | **改擦除逻辑前必读** | 改蒙版/修复前 |
| [10. 关键决策记录](#10-关键决策记录) | 那些「为什么不那样做」 | 做技术选型前 |
| [11. 已知问题与路线图](#11-已知问题与路线图) | 遗留缺陷、优先级 | 排期时 |
| [12. 许可合规红线](#12-许可合规红线) | GPL 禁令、数据集限制 | **引入任何依赖前** |
| [附. 快速核对清单](#附-快速核对清单) | 6 条命令自检 | 配完环境 |

---

<a id="1-五分钟上手"></a>
## ![](https://api.iconify.design/mdi/rocket-launch.svg?color=%23FF7043&height=24) 1. 五分钟上手

已经装好 Python 3.11 的话，从这里开始。四步，命令可直接抄。

```bash
# ① 虚拟环境 + 依赖
/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[test,server]"

# ② 下 5 个多语言 OCR 模型（另外 3 个随 pip 包自带）
BASE="https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/onnx/PP-OCRv5/rec"
DEST=$(.venv/bin/python -c "import rapidocr,pathlib;print(pathlib.Path(rapidocr.__file__).parent)")
for f in korean_PP-OCRv5_rec_mobile.onnx cyrillic_PP-OCRv5_rec_mobile.onnx \
         arabic_PP-OCRv5_rec_mobile.onnx devanagari_PP-OCRv5_rec_mobile.onnx \
         th_PP-OCRv5_rec_mobile.onnx; do
  curl -L "$BASE/$f" -o "$DEST/$f"
done

# ③ 下 LaMa 修复模型（198.4 MB，注意是 fp32 版）
curl -L "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx" \
     -o "$HOME/Downloads/inpainting_lama_2025jan.onnx"
.venv/bin/python scripts/install_local_e2e_models.py \
     --lama-model "$HOME/Downloads/inpainting_lama_2025jan.onnx"

# ④ 验证
.venv/bin/python -m pytest -q                 # 期望 816 passed, 6 skipped
.venv/bin/python -m src.main                  # 启动客户端
```

跑不通就按[第 3 章](#3-部署教程)逐步排查，每一步都有说明和常见错误。配完建议过一遍[附录的核对清单](#附-快速核对清单)。

---

<a id="2-环境要求"></a>
## ![](https://api.iconify.design/mdi/toolbox.svg?color=%238D6E63&height=24) 2. 环境要求

| 项目 | 要求 | 说明 |
| --- | --- | --- |
| Python | **>= 3.11, < 3.12** | `pyproject.toml` 里的硬约束。3.12+ 装不上，PySide6 6.11.1 与 numpy 1.26.4 都锁死了版本 |
| 操作系统 | macOS / Windows / Linux | 本仓库在 macOS(arm64) 验证过全量测试。6 个测试是 Windows 专属，在非 Windows 上 skip |
| 磁盘 | 约 1.5 GB | 依赖约 700 MB + 模型约 271 MB + 虚拟环境开销 |
| 内存 | 建议 8 GB 以上 | LaMa 单次推理峰值约 1.5 GB |
| 网络 | 首次配置需要 | 下依赖与模型；运行时客户端要连授权服务端 |
| GPU | **不需要** | 全部 CPU 推理，这是刻意的产品约束，见[第 10 章](#10-关键决策记录) |

### 装 Python 3.11

```bash
# macOS
brew install python@3.11
/opt/homebrew/bin/python3.11 --version      # 应输出 Python 3.11.x
```

Windows 从 [python.org](https://www.python.org/downloads/release/python-3119/) 下 3.11.x 安装包，勾选 Add to PATH。Linux 用包管理器装 `python3.11` 与 `python3.11-venv`。

---

<a id="3-部署教程"></a>
## ![](https://api.iconify.design/mdi/package-variant-closed.svg?color=%2326A69A&height=24) 3. 部署教程

### 3.1 虚拟环境与依赖

在仓库根目录（有 `pyproject.toml` 这一层）执行：

```bash
# macOS / Linux
/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[test,server]"
```

```powershell
# Windows PowerShell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[test,server]"
```

`-e`（editable）**是必须的**：测试和脚本都按 `src.*` / `server.*` 顶级包导入，不装成 editable 会 `ModuleNotFoundError`。

可选依赖组：

| 组 | 何时需要 | 关键内容 |
| --- | --- | --- |
| `test` | 跑测试 | pytest 8.3.5、pytest-qt 4.5.0、uharfbuzz、fonttools、python-bidi |
| `server` | 开发/部署服务端 | FastAPI、SQLAlchemy 2.x、Alembic、psycopg 3、boto3、wechatpayv3 |
| `release` | 打桌面安装包 | PyInstaller 6.19.0 |

只做客户端开发可以只装 `".[test]"`。

核心运行时依赖（版本全部锁定，别随意升）：

```
PySide6==6.11.1      Pillow==12.3.0        numpy==1.26.4
onnxruntime==1.23.2  opencv-python==4.11.0.86
rapidocr==3.9.1      playwright==1.53.0    qrcode / pypng
```

`playwright` 只被 `src/application/link_parse.py` 用到（解析商品链接）。若不需要该功能，浏览器内核不装也能跑其余流程。

### 3.2 下载模型

一共 9 个 ONNX 模型，约 271 MB。**3 个随 pip 包自带，5 个从 ModelScope 下，1 个从 HuggingFace 下。**

#### 第 1 步：确认随包自带的 3 个

`rapidocr==3.9.1` 装好后，包目录里已经有：

```bash
.venv/bin/python -c "import rapidocr,pathlib;print(pathlib.Path(rapidocr.__file__).parent)"
```

该目录下应能找到：

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `PP-OCRv6_det_small.onnx` | 9.4 MB | 文本检测 |
| `PP-OCRv6_rec_small.onnx` | 20.2 MB | 中英文识别 |
| `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | 0.5 MB | 方向分类 |

#### 第 2 步：下载 5 个多语言识别模型

来自 ModelScope 的 `RapidAI/RapidOCR`，tag `v3.9.1`（与 pip 包版本对齐）。**地址不是网上搜的，是从 `rapidocr` 包内 `default_models.yaml` 读出来的**，所以一定和当前代码匹配：

```bash
BASE="https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/onnx/PP-OCRv5/rec"
DEST=$(.venv/bin/python -c "import rapidocr,pathlib;print(pathlib.Path(rapidocr.__file__).parent)")

for f in korean_PP-OCRv5_rec_mobile.onnx \
         cyrillic_PP-OCRv5_rec_mobile.onnx \
         arabic_PP-OCRv5_rec_mobile.onnx \
         devanagari_PP-OCRv5_rec_mobile.onnx \
         th_PP-OCRv5_rec_mobile.onnx; do
  curl -L "$BASE/$f" -o "$DEST/$f"
done
```

下到 `rapidocr` 包目录，是为了让下一步的安装脚本一次找齐 8 个 OCR 文件（脚本用 `rglob` 在 `--rapidocr-root` 下递归搜文件名）。也可以下到任意目录，把 8 个文件放一起，再用 `--rapidocr-root` 指过去。

> `curl` 一定要带 `-L`。ModelScope 会跳转，不带 `-L` 会存下一个 HTML 页面，后面安装时报「模型文件无效」。

<a id="第-3-步下载-lama-修复模型"></a>
#### 第 3 步：下载 LaMa 修复模型

```bash
curl -L "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx" \
     -o "$HOME/Downloads/inpainting_lama_2025jan.onnx"
```

**必须是 `lama_fp32.onnx`，不是同仓库的 `lama.onnx`。** 代码里钉死了 SHA-256（`src/infrastructure/lama_onnx_adapter.py` 的 `LAMA_MODEL_SHA256`），加载时校验，不匹配直接报错：

| 文件 | 大小（字节） | SHA-256 | 能用 |
| --- | --- | --- | --- |
| `lama_fp32.onnx` | 208 044 816 | `1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6` | ![](https://api.iconify.design/mdi/check-circle.svg?color=%232E7D32&height=16) |
| `lama.onnx` | 207 479 252 | `351e481e287f345b7fbfd026068cfb9ec0c7f24b440e6501458ebe54a833d1a1` | ![](https://api.iconify.design/mdi/close-circle.svg?color=%23C62828&height=16) 校验不过 |

建议下载时就重命名为 `inpainting_lama_2025jan.onnx`，与常量 `LAMA_MODEL_FILENAME` 一致，`scripts/prepare_bundled_models.py` 才能自动找到。

自己核一下哈希：

```bash
shasum -a 256 "$HOME/Downloads/inpainting_lama_2025jan.onnx"    # macOS/Linux
certutil -hashfile inpainting_lama_2025jan.onnx SHA256           # Windows
```

#### 第 4 步：安装进模型仓库

```bash
.venv/bin/python scripts/install_local_e2e_models.py \
  --lama-model "$HOME/Downloads/inpainting_lama_2025jan.onnx"
```

成功输出：

```
local_e2e_model_install_ok models=9 target=<平台>-<架构>
```

脚本会逐个算 SHA-256、写入带版本号的目录、安装后再校验一遍。

常见错误：

| 报错 | 原因 | 处理 |
| --- | --- | --- |
| `本地联调模型不完整：...` | 列出的模型文件没找到 | 回第 2 步，确认 5 个多语言模型下全了 |
| `本地联调模型文件无效` | 文件不是 `.onnx` 或大小为 0 | `curl` 漏了 `-L`，下到的是 HTML |
| `LaMa 本地联调模型 SHA-256 不匹配` | 下的是 `lama.onnx` | 换 `lama_fp32.onnx` |

模型装到平台数据目录：

| 平台 | 路径 |
| --- | --- |
| macOS | `~/Library/Application Support/ImgTrans/models` |
| Windows | `%LOCALAPPDATA%\ImgTrans\models` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/ImgTrans/models` |

可用 `--target-dir` 改。装完是 9 个目录、约 271 MB。

### 3.3 启动客户端

```bash
.venv/bin/python -m src.main
```

冒烟检查（建窗口后立即退出，用来验证环境，**exit code 0 即通过**）：

```bash
.venv/bin/python -m src.main --smoke-test
```

命令行参数：

| 参数 | 作用 |
| --- | --- |
| `--smoke-test` | 建主窗口后自动退出，且跳过单实例检查 |
| `--editor` | 启动新版编辑器 UI |

日志在数据目录的 `logs/imgtrans.log`（macOS：`~/Library/Application Support/ImgTrans/logs/imgtrans.log`）。启动成功的标志是最后一行：

```
application_ready version=0.1.0
```

**客户端要激活才能翻译。** 默认连 `https://imgtrans.rchtop.top`（`src/main.py` 的 `DEFAULT_BACKEND_URL`），首次启动在激活对话框输入激活码。指向自建服务端用 `IMGTRANS_API_BASE_URL`。

### 3.4 部署服务端

```bash
# 1. 数据库迁移（生产用 PostgreSQL；不设则默认 sqlite 内存库，只够跑测试）
export IMGTRANS_DATABASE_URL="postgresql+psycopg://user:pass@host:5432/imgtrans"
.venv/bin/alembic upgrade head

# 2. 必需的密钥
export IMGTRANS_ACTIVATION_SECRET="<激活令牌签名密钥>"
export IMGTRANS_CLIENT_API_TOKEN="<客户端调用令牌>"
export IMGTRANS_ADMIN_TOKEN="<管理接口令牌>"
export IMGTRANS_SETTINGS_ENCRYPTION_KEY="<服务配置加密密钥>"

# 3. 启动
export IMGTRANS_SERVER_HOST=0.0.0.0
export IMGTRANS_SERVER_PORT=8000
.venv/bin/python -m server.main
```

生产环境记得设 `IMGTRANS_ENVIRONMENT=production`（会关掉 `/docs`）。

健康检查：

```bash
curl http://127.0.0.1:8000/health/live      # {"status":"ok"}
curl http://127.0.0.1:8000/health/ready     # 探数据库，不通返回 503
```

后台管理在 `/admin`，需要 `IMGTRANS_ADMIN_USERNAME` + `IMGTRANS_ADMIN_PASSWORD_HASH` + `IMGTRANS_ADMIN_SESSION_SECRET`。翻译代理、微信支付、GLM 的密钥见[第 7 章](#7-环境变量参考)，不配则对应功能不可用，但服务能起来。

---

<a id="4-开发教程"></a>
## ![](https://api.iconify.design/mdi/hammer-wrench.svg?color=%2342A5F5&height=24) 4. 开发教程

### 4.1 跑测试

```bash
.venv/bin/python -m pytest -q
```

**基线：816 passed / 6 skipped，约 20–35 秒。** 任何改动都应保持这个数字。

6 个 skip 是 Windows 专属检查，在 macOS/Linux 上必然跳过，不是失败：

| 文件 | 数量 | 原因 |
| --- | --- | --- |
| `tests/prototypes/platform_bootstrap/test_bootstrap.py` | 1 | PE 文件校验只在 Windows 有意义 |
| `tests/release/test_desktop_release.py` | 1 | PE 宿主检查 |
| `tests/visual/test_font_resolution.py` | 4 | Windows 字体注册回归 |

常用命令：

```bash
.venv/bin/python -m pytest tests/unit -q                     # 只跑单元测试（最快）
.venv/bin/python -m pytest tests/ui -q                       # 只跑 Qt UI 测试
.venv/bin/python -m pytest tests/server -q                   # 只跑服务端
.venv/bin/python -m pytest -q -p no:cacheprovider            # 不写 .pytest_cache
.venv/bin/python -m pytest tests/unit/test_basic_layout.py -k condensing -vv
.venv/bin/python -m pytest -q -x --lf                        # 只重跑上次失败的，遇错即停
```

测试目录分布：

| 目录 | 文件数 | 内容 |
| --- | --- | --- |
| `tests/unit` | 27 | 领域逻辑、排版、蒙版、保护规则 |
| `tests/ui` | 28 | Qt 窗口/面板/编辑器交互（pytest-qt） |
| `tests/integration` | 21 | 端到端流程（OCR → 翻译 → 擦除 → 渲染） |
| `tests/server` | 18 | 服务端 API、激活、支付、后台 |
| `tests/prototypes` | 15 | 原型验证 |
| `tests/release` | 2 | 打包产物校验 |
| `tests/visual` | 2 | 字体解析 |
| `tests/scripts` | 1 | 脚本 |

UI 测试不需要额外配置，Qt 走离屏模式，不会弹窗。

> **一条历史经验**：这套测试以前会**永久挂死**——业务代码在翻译路径里直接调阻塞式 `QMessageBox.warning`，无人值守时卡在 `QDialog::exec()`，当时只能靠一个临时 pytest 插件替换模态框静态方法绕过。上一轮把根因修掉了（给测试注入有效的 `ActivationSession`），**现在不需要任何脚手架**。如果你发现测试又开始挂，先查是不是新加了未注入激活状态的模态框路径。

<a id="42-擦除质量基准改蒙版逻辑前必读"></a>
### 4.2 擦除质量基准（改蒙版逻辑前必读）

`scripts/measure_erase_quality.py` 是擦除质量的量化验收工具。**改 `pillow_mask_rasterizer.py` 或 `fallback_inpaint_adapter.py` 必须过这道验收**——单元测试只保证不崩，基准才保证不退化。

```bash
# 先准备语料：把电商图片放到仓库根目录的 测试数据/ 下（任意层级，支持 jpg/png/webp/bmp）
ERASE_BENCH_SAMPLE=60 .venv/bin/python scripts/measure_erase_quality.py run base   # 改之前
# ... 改代码 ...
ERASE_BENCH_SAMPLE=60 .venv/bin/python scripts/measure_erase_quality.py run fix    # 改之后
.venv/bin/python scripts/measure_erase_quality.py compare base fix                 # 配对对比
```

单轮约 5 分钟（60 张 / 约 1100 区域）。翻译走 `MockTranslationAdapter` 保证多轮结果确定可配对；抽样按固定步长取，保证多轮取到同一批图。JSON 默认写 `/tmp`，可用 `ERASE_BENCH_OUTPUT` 改。

两个指标：**蒙版覆盖率** 和 **擦除后 Sobel 残留能量**。

<a id="验收门槛"></a>
#### 验收门槛

1. 残留恶化的区域数 **不得超过** 改善的区域数
2. 覆盖率 ≥ 99% 的区域数 **不得增加**
3. 覆盖率高的区域**必须开图人工核实**

#### 为什么门槛是这三条

**两个指标必须联合判读**，因为残留指标会被「过度擦除」刷分：把整个文字框连背景一起填平后，边缘能量趋近于零，指标看起来极好，实际破坏了背景。

真实案例：某版实现显示 46 处改善、净收益 +483，看着远优于最终版。但其中多例覆盖率跳到 99.9%（「1.0k+人已采」51.3% → 99.9%，残留 143.2 → 5.3），正是整框误擦；同批的「拼」（89.5% → 100.0%，残留 73.2 → **212.4**）暴露了真相。最终版改善数从 46 降到 4，是指标不再被刷分的结果，不是能力退步。

所以：**覆盖率异常接近 100% 应视为误擦嫌疑，不是成绩。**

另外，**目标图片修好不构成修复成立**。上一轮有三个方案都在目标图片上「修好了」，但两个在语料上净负被撤回，第三个 35 个区域恶化、只有 2 个改善。详细数据见[第 9 章](#9-擦除质量完整技术背景)。

<a id="43-分层约定"></a>
### 4.3 分层约定

代码严格分四层，依赖只能由外向内：

```
ui  ──▶  application  ──▶  domain
              │
              ▼
        infrastructure   （实现 application/ports.py 定义的 Protocol）
```

| 层 | 职责 | 硬规则 |
| --- | --- | --- |
| `domain/` | 纯数据结构与业务规则 | **不导入任何第三方库**（无 Qt、无 numpy、无 cv2）。全是 `@dataclass(frozen=True, slots=True)` 与 `Enum` |
| `application/` | 用例编排 | 只依赖 `domain` 和 `ports.py` 里的抽象接口，不 import `infrastructure` |
| `infrastructure/` | 具体实现 | ONNX 推理、Pillow/OpenCV 图像处理、HTTP 客户端、文件存储 |
| `ui/` | PySide6 窗口与面板 | 不放业务逻辑，只做交互与展示 |
| `platform/` | 跨平台差异 | 路径、字体、凭据、Qt 运行时、进程内存 |

`application/ports.py` 里定义的 Protocol（这是架构的关节）：

| Protocol | 实现 |
| --- | --- |
| `ImageCodec` | `pillow_image_codec.PillowImageCodec` |
| `ImageCropper` | `pillow_image_cropper.PillowImageCropper` |
| `OcrAdapter` | `rapidocr_adapter.RapidOcrAdapter` |
| `TranslationAdapter` | `server_translation_adapter` / `llm_adapter` / `mock_translator` |
| `MaskRasterizer` | `pillow_mask_rasterizer.PillowMaskRasterizer` |
| `InpaintingAdapter` | `fallback_inpaint_adapter` → `lama_onnx_adapter` / `opencv_inpaint_adapter` |
| `TextLayoutAdapter` / `TextRenderer` | `text_renderer` |
| `BatchResultStore` | `batch_result_store` |
| `BrandTermsPreferences` / `TerminologyPreferences` | `user_preferences` |

**新增外部能力的正确姿势**：先在 `ports.py` 定义 Protocol → 在 `infrastructure/` 写实现 → 在 `application/bootstrap.py` 注入。这样测试里能直接替换成 fake，不需要 mock 库。

### 4.4 常见开发任务

#### 加一种翻译后端（比如接入新的 LLM）

1. 在 `src/infrastructure/` 新建 `xxx_translation_adapter.py`，实现 `TranslationAdapter` Protocol（`adapter_id` + `translate`）
2. 在 `src/application/bootstrap.py` 里按配置选择注入
3. 测试：`tests/unit/` 加一个用例，直接构造 adapter 调 `translate`，不要起真实网络

#### 改擦除蒙版逻辑

1. **先读[第 9 章](#9-擦除质量完整技术背景)**
2. 跑基线：`ERASE_BENCH_SAMPLE=60 ... run base`
3. 改 `src/infrastructure/pillow_mask_rasterizer.py`
4. 跑 `run fix` + `compare base fix`，按[4.2 的三条门槛](#验收门槛)判定
5. 跑全量测试确认 816
6. 覆盖率高的区域开图核实

<a id="改排版渲染"></a>
#### 改排版/渲染

改 `src/infrastructure/text_renderer.py`。写测试时**用相对断言**：

```python
# 不要这样（换平台就红）
assert 16.0 < font_size <= 17.0

# 要这样
assert box.height * 0.65 < font_size <= box.height * 0.85
```

因为 macOS（苹方/黑体）与 Windows（雅黑/宋体）的 ascent/descent 比例不同，同一段文字拟合出的字号不一样。上一轮有 3 个测试就是踩了这个坑。

#### 加一个服务端 API

1. `server/api/` 下新建或扩展模块，定义 `APIRouter(prefix=...)`
2. 请求/响应模型放 `server/api/contracts.py`
3. 业务逻辑放 `server/application/`，数据访问放 `server/infrastructure/`
4. 在 `server/app.py` 的 `create_app()` 里 `include_router`
5. 测试放 `tests/server/`，用 FastAPI `TestClient`

#### 改数据库表

```bash
.venv/bin/alembic revision -m "描述"        # 生成迁移脚本（在 server/migrations/versions/）
# 手写 upgrade/downgrade
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1               # 回滚一步
```

#### 加一个 OCR 语言

1. 从 ModelScope 下对应的 `*_PP-OCRv5_rec_mobile.onnx`（地址见[第 6 章](#6-模型清单与下载地址)）
2. 在 `src/infrastructure/rapidocr_models.py` 的 `RECOGNITION_MODEL_IDS` 加映射
3. 在 `scripts/install_local_e2e_models.py` 的 `_RAPIDOCR_FILES` 加文件名
4. 在 `src/infrastructure/ocr_profiles.py` 配语言 → profile 的对应关系
5. 重跑安装脚本

### 4.5 调试技巧

#### 绕过 UI 直接驱动流水线

排查擦除/翻译质量时，不要点 UI，直接跑管线，能拿到中间产物：

```python
from pathlib import Path
from PySide6.QtWidgets import QApplication
QApplication.instance() or QApplication(["dbg"])

import numpy as np
from src.application.inpainting import BuildEraseMask, RepairTranslatedRegions
from src.application.ocr import RecognizeText
from src.application.translation import TranslateRegions
from src.domain.image import ImageLimits
from src.domain.protection import ProtectionEngine
from src.domain.terminology import TerminologyCatalog
from src.domain.translation import TranslationMode, TranslationSelection
from src.infrastructure.fallback_inpaint_adapter import FallbackInpaintAdapter
from src.infrastructure.inpainting_process import ProcessLamaAdapter
from src.infrastructure.mock_translator import MockTranslationAdapter
from src.infrastructure.model_delivery import FileModelRepository
from src.infrastructure.opencv_inpaint_adapter import OpenCvInpaintAdapter
from src.infrastructure.pillow_image_codec import PillowImageCodec
from src.infrastructure.pillow_mask_rasterizer import PillowMaskRasterizer
from src.infrastructure.rapidocr_adapter import RapidOcrAdapter
from src.infrastructure.rapidocr_models import InstalledRapidOcrModels
from src.platform.paths import PlatformPaths

repo = FileModelRepository(PlatformPaths.discover().data_dir / "models")
codec = PillowImageCodec()
doc = codec.load(Path("图片.jpg"), ImageLimits())
ocr = RecognizeText(
    RapidOcrAdapter(model_resolver=InstalledRapidOcrModels(repo).resolve)
).execute(doc, "zh-Hans")
tr = TranslateRegions(
    MockTranslationAdapter(), ProtectionEngine(),
    terminology_catalog=TerminologyCatalog(),
).execute(ocr, TranslationSelection(TranslationMode.ALL, "en"))
outcome = RepairTranslatedRegions(
    BuildEraseMask(PillowMaskRasterizer()),
    FallbackInpaintAdapter(
        ProcessLamaAdapter(Path(repo.active("lama-inpainting").path)),
        OpenCvInpaintAdapter(),
    ),
).execute(doc, ocr, tr)

print("后端:", outcome.result.backend_id)      # 看走了哪条修复路径
# outcome.erase_mask         擦除蒙版
# outcome.result.document    仅擦除后的中间图
```

用 `MockTranslationAdapter` 可以避开网络和激活，结果确定、可重复。`scripts/measure_erase_quality.py` 就是这么写的，可以直接抄。

#### 给蒙版决策打点

`_high_contrast_text_mask` 内部是一串颜色判据，想看某个区域走了哪条分支，最快的办法是猴补丁替换内部函数并记录：

```python
from src.infrastructure import pillow_mask_rasterizer as pmr

original = pmr._corrected_background
def probe(pixels, polygon, background):
    result = original(pixels, polygon, background)
    if not np.allclose(result, background):
        print(f"背景纠偏 {tuple(background.round(0))} -> {tuple(result.round(0))}")
    return result
pmr._corrected_background = probe
```

#### 看客户端日志

```bash
tail -f "$HOME/Library/Application Support/ImgTrans/logs/imgtrans.log"     # macOS
```

关键日志行：`application_ready`（启动完成）、`image_limits_ready`（限额配置就绪）、`backend_id=...`（修复走了哪条路径）。

#### 单实例锁卡住

客户端用共享内存做单实例检查，被 `kill -9` 后锁会残留，再启动会弹「客户端已在运行」：

```bash
ipcs -mo                   # 找 NATTCH 为 0 的段
ipcrm -m <ID>              # 删掉
```

`--smoke-test` 跳过单实例检查，不受影响。

#### 服务端本地调试

```bash
export IMGTRANS_DATABASE_URL="sqlite+pysqlite:///./dev.db"
.venv/bin/alembic upgrade head
.venv/bin/python -m server.main
# 打开 http://127.0.0.1:8000/docs 看 OpenAPI 文档
```

### 4.6 协作规范

**提交信息**用 Conventional Commits，现有 180 条提交的实际分布：

| 前缀 | 条数 | 用途 |
| --- | --- | --- |
| `feat:` | 71 | 新功能 |
| `fix:` | 68 | 修 bug |
| `style:` | 6 | 界面/样式 |
| `debug:` | 5 | 临时排查日志（合并前应清理） |
| `build:` | 4 | 打包脚本 |
| `test:` | 3 | 只动测试 |
| `docs:` | 3 | 文档 |
| `refactor:` | 2 | 重构 |
| `perf:` | 1 | 性能 |

带作用域更好，例如 `feat(client): ...`、`fix(build): ...`、`feat(translation): ...`。

**分支**：`main` 为主线，功能分支形如 `feature/desktop-client-v1`。交接时的 HEAD 是 `4a813be`（`feature/desktop-client-v1`）。

**改代码的基本纪律**：

- 动生产代码前先跑一遍测试，确认基线是 816
- 改擦除相关代码必须过[质量基准](#42-擦除质量基准改蒙版逻辑前必读)
- 不为了让测试变绿而重新实现作者主动删除的功能。上一轮遇到两个测试引用了已被删除的 `_region_box` / `_circular_path_for_retranslation`，用 `git log -S '符号名'` 查证是在提交 `72e976b` 被有意删除后，把僵尸测试删掉并在原位留注释，而不是把功能加回来
- 引入任何新依赖前先查许可，见[第 12 章](#12-许可合规红线)

### 4.7 打包桌面应用

```bash
.venv/bin/python -m pip install -e ".[release]"
.venv/bin/python scripts/prepare_bundled_models.py --lama-model <模型路径>   # 把模型拷进打包目录
.venv/bin/python scripts/build_desktop.py
.venv/bin/python scripts/verify_desktop_artifact.py                        # 校验产物
```

macOS 另有 `scripts/build_macos.sh`，Windows 安装包用 `packaging/` 下的 `.iss`（Inno Setup，LZMA2 压缩、中文向导）。

安装包体积参考：OCR 模型约 74 MB，加上 LaMa 的 198.4 MB 后约 272 MB。若要压体积，可考虑换更小的 MI-GAN，但需产品决策（见[第 11 章](#11-已知问题与路线图)）。

---

<a id="5-架构"></a>
## ![](https://api.iconify.design/mdi/sitemap.svg?color=%237E57C2&height=24) 5. 架构

### 5.0 分层技术栈一览

<table>
<thead>
<tr><th width="90">层</th><th width="150">目录</th><th>职责</th><th>技术</th></tr>
</thead>
<tbody>
<tr>
<td align="center"><img src="https://api.iconify.design/mdi/palette.svg?color=%2342A5F5" width="26" height="26"><br><sub><b>表现</b></sub></td>
<td><code>src/ui/</code></td>
<td>窗口、画布、面板、对话框。<b>不放业务逻辑</b></td>
<td><img src="https://img.shields.io/badge/PySide6-6.11.1-41CD52?style=flat-square&logo=qt&logoColor=white"></td>
</tr>
<tr>
<td align="center"><img src="https://api.iconify.design/mdi/cog-transfer.svg?color=%23FFA726" width="26" height="26"><br><sub><b>应用</b></sub></td>
<td><code>src/application/</code></td>
<td>用例编排。只依赖 domain 与 <code>ports.py</code> 的抽象</td>
<td><img src="https://img.shields.io/badge/%E7%BA%AF%20Python-Protocol%20%E6%8E%A5%E5%8F%A3-3776AB?style=flat-square"></td>
</tr>
<tr>
<td align="center"><img src="https://api.iconify.design/mdi/diamond-stone.svg?color=%237E57C2" width="26" height="26"><br><sub><b>领域</b></sub></td>
<td><code>src/domain/</code></td>
<td>业务规则与数据结构。<b>禁止导入任何第三方库</b></td>
<td><img src="https://img.shields.io/badge/dataclass-frozen%20%2B%20slots-3776AB?style=flat-square"></td>
</tr>
<tr>
<td align="center"><img src="https://api.iconify.design/mdi/server-network.svg?color=%2326A69A" width="26" height="26"><br><sub><b>基础设施</b></sub></td>
<td><code>src/infrastructure/</code></td>
<td>推理、图像处理、HTTP、存储。实现 Protocol</td>
<td><img src="https://img.shields.io/badge/ONNX-1.23.2-005CED?style=flat-square&logo=onnx&logoColor=white"> <img src="https://img.shields.io/badge/OpenCV-4.11-5C3EE8?style=flat-square&logo=opencv&logoColor=white"> <img src="https://img.shields.io/badge/Pillow-12.3-11557C?style=flat-square"></td>
</tr>
<tr>
<td align="center"><img src="https://api.iconify.design/mdi/laptop.svg?color=%23789098" width="26" height="26"><br><sub><b>平台</b></sub></td>
<td><code>src/platform/</code></td>
<td>路径、字体、凭据、Qt 运行时、单实例锁</td>
<td><img src="https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square"></td>
</tr>
<tr>
<td align="center"><img src="https://api.iconify.design/mdi/api.svg?color=%23009688" width="26" height="26"><br><sub><b>服务端</b></sub></td>
<td><code>server/</code></td>
<td>激活授权、翻译代理、支付、后台（60 个端点）</td>
<td><img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white"> <img src="https://img.shields.io/badge/SQLAlchemy-2.x-D71F00?style=flat-square"> <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white"></td>
</tr>
<tr>
<td align="center"><img src="https://api.iconify.design/mdi/test-tube.svg?color=%2343A047" width="26" height="26"><br><sub><b>测试</b></sub></td>
<td><code>tests/</code></td>
<td>单元 / 集成 / UI / 服务端 / 原型 / 发布 / 视觉</td>
<td><img src="https://img.shields.io/badge/pytest-816%20passed-brightgreen?style=flat-square&logo=pytest&logoColor=white"></td>
</tr>
</tbody>
</table>

依赖方向是单向的：

```
表现  ──▶  应用  ──▶  领域
             │
             ▼
        基础设施   （实现应用层定义的 Protocol，不被应用层直接 import）
```

核心能力落在哪几个文件（改动风险最高的三个已标注）：

<table>
<tr>
<td align="center" width="33%">
<img src="https://api.iconify.design/mdi/text-recognition.svg?color=%23EC407A" width="30" height="30"><br>
<b>文字识别</b><br>
<sub><code>rapidocr_adapter.py</code></sub><br>
<img src="https://img.shields.io/badge/RapidOCR-3.9.1-FF6F00?style=flat-square">
</td>
<td align="center" width="33%">
<img src="https://api.iconify.design/mdi/image-filter-center-focus.svg?color=%23EF5350" width="30" height="30"><br>
<b>擦除蒙版</b> <img src="https://api.iconify.design/mdi/star.svg?color=%23F9A825" width="14" height="14"><br>
<sub><code>pillow_mask_rasterizer.py</code></sub><br>
<img src="https://img.shields.io/badge/%E8%B4%A8%E9%87%8F%E5%85%B3%E9%94%AE-%E8%A7%81%E7%AC%AC%209%20%E7%AB%A0-red?style=flat-square">
</td>
<td align="center" width="33%">
<img src="https://api.iconify.design/mdi/auto-fix.svg?color=%23AB47BC" width="30" height="30"><br>
<b>背景修复</b> <img src="https://api.iconify.design/mdi/star.svg?color=%23F9A825" width="14" height="14"><br>
<sub><code>fallback_inpaint_adapter.py</code></sub><br>
<img src="https://img.shields.io/badge/LaMa%20%2F%20OpenCV-3%20%E6%9D%A1%E8%B7%AF%E5%BE%84-8A2BE2?style=flat-square">
</td>
</tr>
<tr>
<td align="center">
<img src="https://api.iconify.design/mdi/format-text.svg?color=%2329B6F6" width="30" height="30"><br>
<b>译文排版</b> <img src="https://api.iconify.design/mdi/star.svg?color=%23F9A825" width="14" height="14"><br>
<sub><code>text_renderer.py</code></sub><br>
<img src="https://img.shields.io/badge/%E5%AD%97%E5%8F%B7%E6%8B%9F%E5%90%88%20%2B%20%E5%AD%97%E8%B7%9D%E5%8E%8B%E7%BC%A9-29B6F6?style=flat-square">
</td>
<td align="center">
<img src="https://api.iconify.design/mdi/shield-key.svg?color=%23546E7A" width="30" height="30"><br>
<b>激活授权</b><br>
<sub><code>activation_client.py</code></sub><br>
<img src="https://img.shields.io/badge/%E6%BF%80%E6%B4%BB%E7%A0%81%20%2B%20%E8%AE%BE%E5%A4%87%E7%BB%91%E5%AE%9A-546E7A?style=flat-square">
</td>
<td align="center">
<img src="https://api.iconify.design/mdi/credit-card.svg?color=%2307C160" width="30" height="30"><br>
<b>支付</b><br>
<sub><code>payment_client.py</code></sub><br>
<img src="https://img.shields.io/badge/%E5%BE%AE%E4%BF%A1%E6%94%AF%E4%BB%98-07C160?style=flat-square&logo=wechat&logoColor=white">
</td>
</tr>
</table>

### 5.1 目录结构全景

```
┌──────────────────────────── 桌面客户端（src/）────────────────────────────────────┐
│                                                                                  │
│  ui/  PySide6                                                                    │
│  ├─ main_window.py        主窗口 / 导航                                          │
│  ├─ editor/               编辑器：画布、图层、蒙版涂抹、二次翻译、导入导出       │
│  ├─ product/             商品信息 → AI 分析 → 文案生成（三步向导）              │
│  ├─ toolbox/              工具箱：裁剪、拼接、水印                               │
│  └─ *_panel.py            OCR / 翻译 / 修复 / 批量 / 手动区域 / 弧形文字 面板     │
│                    │                                                             │
│                    ▼                                                             │
│  application/  用例编排（不含框架代码）                                          │
│  ├─ translate_image.py    * 主流程：OCR → 翻译 → 擦除 → 排版                     │
│  ├─ ocr.py / translation.py / inpainting.py / composition.py                      │
│  ├─ batch.py / batch_export.py       批量处理与导出                              │
│  ├─ activation.py / image_limits.py  激活与限额                                  │
│  ├─ product_analysis.py / copywriting.py / product_export.py                      │
│  ├─ manual_region.py / toolbox_operations.py / coordinate_transform.py            │
│  ├─ bootstrap.py          * 依赖注入装配点                                       │
│  └─ ports.py              * 所有外部依赖的抽象接口（Protocol）                    │
│                    │                                                             │
│         ┌──────────┴───────────┐                                                 │
│         ▼                      ▼                                                 │
│  domain/  纯业务规则      infrastructure/  具体实现                              │
│  ├─ ocr / translation     ├─ rapidocr_adapter.py        OCR 推理                 │
│  ├─ layout / composition  ├─ pillow_mask_rasterizer.py  * 擦除蒙版生成           │
│  ├─ inpainting            ├─ fallback_inpaint_adapter.py * 修复后端选择           │
│  ├─ protection            ├─ lama_onnx_adapter.py       LaMa 推理                │
│  │    数字/品牌词保护     ├─ inpainting_process.py      子进程隔离推理           │
│  ├─ terminology 术语库    ├─ opencv_inpaint_adapter.py  OpenCV 兜底              │
│  ├─ activation 激活       ├─ text_renderer.py           * 译文排版渲染           │
│  ├─ image / job / batch   ├─ model_delivery.py          模型仓库与校验           │
│  ├─ manual_region         ├─ server_translation_adapter.py  服务端翻译           │
│  ├─ product / copywriting ├─ llm_adapter.py             LLM（OpenAI/Claude/GLM） │
│  └─ session / models      ├─ activation_client.py       激活 / 配额 / 支付       │
│                           └─ project_store.py           工程文件读写             │
│                                                                                  │
│  platform/  paths · fonts · font_candidates · credentials · qt_runtime            │
│             · process_memory · storage                                           │
└──────────────────────────────────────────────────────────────────────────────────┘
                                     │ HTTPS
                                     ▼
┌──────────────────────── 授权服务端（server/）────────────────────────────────────┐
│  api/          activation · translation · payment · usage · image_limits          │
│                · product_llm · auth · rate_limit · correlation · contracts        │
│  application/  激活、审计、配额、支付、管理员、服务配置                          │
│  domain/       激活码与套餐、支付单、限额规则、审计、管理员                      │
│  infrastructure/ PostgreSQL(SQLAlchemy) · 微软翻译 · GLM · 微信支付 · 限流       │
│                · 密钥加密 · 各类 repository                                      │
│  admin/        后台管理（Jinja2 模板 + 静态资源 + 会话安全）                     │
│  migrations/   Alembic 版本                                                      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 图片翻译主流程

```
原图
 │
 ▼
① OCR 识别          RapidOcrAdapter → 文本框（四点多边形）+ 文字 + 置信度
 │                  检测用 PP-OCRv6_det_small，识别按语言选 PP-OCRv5/v6 rec
 │                  可选高召回模式（HighRecallOcrOptions）
 ▼
② 保护规则          ProtectionEngine：数字、单位、品牌词、型号不翻译
 │                  !! 被保护区域的蒙版覆盖率为 0 是预期行为，不是缺陷
 ▼
③ 翻译              服务端代理（微软翻译 / GLM）或本地 LLM；术语库覆盖优先
 │
 ▼
④ 生成擦除蒙版      PillowMaskRasterizer  * 质量关键，见第 9 章
 │                  按框内颜色统计推断「文字色 vs 底色」，只擦文字：
 │                  ├─ 背景色估计（边缘环中位色 → _corrected_background 纠偏）
 │                  ├─ 主前景（距前景近 且 距背景远）
 │                  ├─ 描边/双色字的补充前景（_companion_foreground_mask）
 │                  └─ 第三色混排的额外色簇 + 双阈值区域生长
 ▼
⑤ 修复              FallbackInpaintAdapter 三条路径，按内容自动选：
 │                  ├─ transparent-text-clear  透明层文字，直接清除
 │                  ├─ opencv-text-fill        纯色/文字形背景快路径（约 300 ms）
 │                  └─ lama-onnxruntime        复杂背景，LaMa 推理（约 5 s）
 │                  事后瑕疵检测，不合格自动回退到下一条
 ▼
⑥ 排版渲染          TextRenderer：字号拟合、字距压缩、水平吸附、
 │                  重复面板字号统一、弧形/切向文字
 ▼
译文图
```

LaMa 推理跑在**独立子进程**（`inpainting_process.py`）里，避免 onnxruntime 的内存占用和潜在崩溃影响 Qt 主进程。

### 5.3 代码地图

#### `src/domain/` — 19 个文件，纯业务规则

| 文件 | 内容 |
| --- | --- |
| `ocr.py` | `Point`、`OcrObservation`、`TextRegionStatus`、`OcrMode`、`RingBand`、`HighRecallOcrOptions` |
| `translation.py` | `TranslationMode`、`TranslationSelection`、`TranslationUnit`、`TranslationResult`、`TranslationAdapterItem`、`TranslationStatus` |
| `layout.py` | `TextBox`、`PathPoint`、`ArcTextPath`、`TextAlignment`、`VerticalAlignment`、`ArtisticPreset`、`FontStyleHint` |
| `inpainting.py` | `EraseMask`、`InpaintingRequest`、`InpaintingResult`、`RepairOutcome` |
| `image.py` | `ImageAsset`、`ImageDocument`、`ImageLimits`、`ExportOptions`、`ImageFileFormat` |
| `protection.py` | `ProtectionEngine`、`ProtectionKind`、`ProtectedSpan`、`ProtectedText` — 决定哪些内容不翻译 |
| `activation.py` | `ActivationSession`（注意 `active` 是**属性**，定义为 `expires_at > now`） |
| `composition.py` | 图层合成模型 |
| `terminology.py` | 术语库与词条 |
| `manual_region.py` | 手动框选区域 |
| `batch.py` / `job.py` / `session.py` | 批量任务、作业、会话 |
| `product.py` / `product_info.py` / `copywriting.py` | 商品信息与文案 |
| `models.py` | `InstalledModel`、`ModelManifestEntry`、`ModelDeliveryError` |
| `language.py` | 语言代码与显示名 |

#### `src/application/` — 20 个文件，用例编排

| 文件 | 关键类 |
| --- | --- |
| `translate_image.py` | `TranslateImage` — 主流程编排 |
| `ocr.py` | `RecognizeText` |
| `translation.py` | `TranslateRegions` |
| `inpainting.py` | `BuildEraseMask`、`RepairTranslatedRegions` |
| `composition.py` | 图层合成用例 |
| `ports.py` | 全部 Protocol 定义（见 [4.3](#43-分层约定)） |
| `bootstrap.py` | 依赖装配 |
| `batch.py` / `batch_export.py` | 批量翻译与导出 |
| `activation.py` | 激活流程 |
| `image_limits.py` / `image_io.py` | 图片限额与读写 |
| `manual_region.py` | 手动区域处理 |
| `toolbox_operations.py` | 工具箱操作 |
| `coordinate_transform.py` | 坐标变换（画布 ↔ 原图） |
| `product_analysis.py` / `product_export.py` / `copywriting.py` | 商品分析与文案 |
| `link_parse.py` | 商品链接解析（用 playwright） |

#### `src/infrastructure/` — 28 个文件，具体实现

| 文件 | 说明 |
| --- | --- |
| **`pillow_mask_rasterizer.py`** | ![](https://api.iconify.design/mdi/star.svg?color=%23F9A825&height=16) 擦除蒙版生成，本次改动最大（+398）。全部颜色启发式规则在这里。**改前读第 9 章** |
| **`fallback_inpaint_adapter.py`** | ![](https://api.iconify.design/mdi/star.svg?color=%23F9A825&height=16) 修复后端选择与事后瑕疵回退。`_fill_text_mask` 里有个已知的 0.6 刀锋阈值 |
| **`text_renderer.py`** | ![](https://api.iconify.design/mdi/star.svg?color=%23F9A825&height=16) 排版与渲染（+146）。字号拟合、字距压缩、水平吸附、面板字号统一 |
| `lama_onnx_adapter.py` | LaMa ONNX 推理，含 `LAMA_MODEL_FILENAME` 与 `LAMA_MODEL_SHA256` 常量 |
| `inpainting_process.py` | `ProcessLamaAdapter` — 子进程隔离推理 |
| `opencv_inpaint_adapter.py` | OpenCV Telea 兜底修复 |
| `rapidocr_adapter.py` | RapidOCR 推理封装 |
| `rapidocr_models.py` | 模型 ID 常量与按 profile 解析（`DETECTION_MODEL_ID`、`RECOGNITION_MODEL_IDS`、`CLASSIFICATION_MODEL_ID`） |
| `ocr_profiles.py` | 语言 → OCR profile 映射 |
| `model_delivery.py` | `FileModelRepository` — 模型安装、版本、校验 |
| `bundled_models.py` | 打包内置模型的读取 |
| `pillow_image_codec.py` / `pillow_image_cropper.py` | 图片编解码与裁剪 |
| `server_translation_adapter.py` | 走服务端的翻译 |
| `llm_adapter.py` / `llm_config.py` | LLM 调用与配置（OpenAI / Anthropic / GLM） |
| `server_llm_adapter.py` | 走服务端的 LLM |
| `mock_translator.py` | 确定性假翻译，测试与基准工具用 |
| `activation_client.py` / `quota_client.py` / `payment_client.py` | 激活、配额、支付的 HTTP 客户端 |
| `project_store.py` | 工程文件读写 |
| `batch_result_store.py` | 批量结果缓存 |
| `user_preferences.py` | 品牌词、术语等用户偏好 |
| `ecommerce_terms.py` | 电商术语表 |
| `image_limits_config.py` | 图片限额配置缓存 |
| `logging_config.py` | 日志配置 |

#### `src/ui/` — 20 个文件 + 3 个子包

| 位置 | 说明 |
| --- | --- |
| `main_window.py` | 主窗口、导航、购买入口 |
| `editor/` | `main_window.py`（编辑器主窗）、`editor_page.py`、`home_page.py`、`editor_model.py`、`undo_commands.py`、`theme.py`、`icons.py`、`error_handler.py` |
| `editor/canvas/` | `scene.py`、`view.py`、`image_item.py`、`layer_item.py`、`ocr_item.py` |
| `editor/widgets/` | `toolbar.py`、`top_bar.py`、`property_panel.py`、`ocr_result_panel.py`、`image_list_panel.py`、`layer_state_panel.py`、`translate_controls.py`、`export_settings_panel.py`、`tool_dialogs.py` |
| `editor/services/` | `editor_import_service.py`、`editor_export_service.py` |
| `product/` | `product_window.py`、`product_model.py`、`step_source.py`、`step_analysis.py`、`step_copywriting.py` |
| `toolbox/` | `tool_box_page.py`、`tool_box_model.py` |
| 各面板 | `ocr_panel` / `translation_panel` / `inpainting_panel` / `batch_panel` / `manual_region_panel` / `curved_text_panel` / `text_edit_panel` / `layer_style_panel` / `pipeline_panel` |
| 各对话框 | `activation_dialog` / `purchase_dialog` / `quota_dialog` / `help_dialog` / `ecommerce_settings_dialog` |
| `image_canvas.py` | 旧版画布 |
| `qt_task_runner.py` | 后台任务调度 |

#### `src/platform/` — 8 个文件

| 文件 | 说明 |
| --- | --- |
| `paths.py` | `PlatformPaths.discover()`、`discover_model_target()` — 各平台数据目录 |
| `fonts.py` / `font_candidates.py` | 字体解析与候选（跨平台字体差异的处理在这里） |
| `credentials.py` | 凭据存储 |
| `qt_runtime.py` | Qt 运行时配置 |
| `process_memory.py` | 进程内存与单实例锁 |
| `storage.py` | 存储抽象 |

#### `scripts/` — 8 个脚本

| 脚本 | 用途 |
| --- | --- |
| `install_local_e2e_models.py` | 把本地 ONNX 装进模型仓库（部署必用） |
| `prepare_bundled_models.py` | 把模型拷进打包目录 |
| `measure_erase_quality.py` | ![](https://api.iconify.design/mdi/star.svg?color=%23F9A825&height=16) 擦除质量量化基准（`run` / `compare`） |
| `build_desktop.py` / `build_macos.sh` | 构建桌面应用 |
| `verify_desktop_artifact.py` | 校验打包产物 |
| `release_hardening.py` | 发布加固检查 |
| `run_customer_image_e2e.py` | 客户图片端到端跑批 |
| `run_live_translation_check.py` | 真实翻译连通性检查 |
| `launch_desktop.py` | 启动辅助 |

### 5.4 服务端 API 清单

共 **60 个端点 / 54 个路径**（从 `app.openapi()` 导出，非人工整理）。启动后可在 `/docs` 交互查看。

#### 客户端调用（`/v1`，需 `IMGTRANS_CLIENT_API_TOKEN`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health/live` | 存活探针 |
| GET | `/health/ready` | 就绪探针（探数据库，不通返回 503） |
| GET | `/v1/service-info` | 服务与 API 版本 |
| GET | `/v1/client-config` | 客户端配置下发（含限额，有 TTL 缓存） |
| POST | `/v1/activations/validate` | 激活设备 |
| POST | `/v1/activations/unbind` | 解绑设备 |
| POST | `/v1/translations` | 文本翻译代理 |
| POST | `/v1/llm/chat` | LLM 对话代理（商品分析/文案） |
| GET | `/v1/usage` | 查询用量 |
| POST | `/v1/usage/consume` | 消耗额度 |
| GET | `/v1/payments/plans` | 可购套餐 |
| POST | `/v1/payments/orders` | 下单 |
| GET | `/v1/payments/orders/{order_id}` | 查单 |
| POST | `/v1/payments/notify` | 微信支付回调 |

#### 管理 API（`/v1/admin`，需 `IMGTRANS_ADMIN_TOKEN`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / POST | `/v1/admin/activation/codes` | 列出 / 签发激活码 |
| POST | `/v1/admin/activation/codes/{code_id}/disable` | 停用激活码 |
| GET / POST | `/v1/admin/activation/plans` | 列出 / 创建套餐 |
| PUT | `/v1/admin/activation/plans/{plan_id}` | 更新套餐 |
| POST | `/v1/admin/image-limits/drafts` | 新建限额草稿 |
| PUT | `/v1/admin/image-limits/drafts/{version}` | 更新草稿 |
| POST | `/v1/admin/image-limits/drafts/{version}/publish` | 发布 |
| GET | `/v1/admin/image-limits/versions` | 版本列表 |
| POST | `/v1/admin/image-limits/versions/{version}/rollback` | 回滚 |
| GET | `/v1/admin/payment/orders` | 订单列表 |

#### 后台控制台（`/admin`，34 个端点，会话登录）

页面：`/admin`（仪表盘）、`/admin/activation`、`/admin/image-limits`、`/admin/payments`、`/admin/translation`、`/admin/usage`、`/admin/users`、`/admin/audit`、`/admin/settings`、`/admin/login`、`/admin/change-password`

操作：激活码签发/停用/启用/续期、套餐增删改、限额草稿发布/回滚/删除、管理员增删改/禁用/启用/权限/重置密码、翻译连通性测试、设置保存、登录/登出。

---

<a id="6-模型清单与下载地址"></a>
## ![](https://api.iconify.design/mdi/brain.svg?color=%23EC407A&height=24) 6. 模型清单与下载地址

装完后位于平台数据目录的 `models/` 下，共 9 个、约 271 MB。

| 模型 ID | 文件 | 大小 | 来源 | 用途 |
| --- | --- | --- | --- | --- |
| `rapidocr-det-ppocrv6-small` | `PP-OCRv6_det_small.onnx` | 9.4 MB | 随 pip 包 | 文本检测 |
| `rapidocr-cls-angle-mobile` | `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | 0.5 MB | 随 pip 包 | 方向分类 |
| `rapidocr-rec-ppocrv6-common-small` | `PP-OCRv6_rec_small.onnx` | 20.2 MB | 随 pip 包 | 中英文识别 |
| `rapidocr-rec-ppocrv5-korean-mobile` | `korean_PP-OCRv5_rec_mobile.onnx` | 12.8 MB | ModelScope | 韩文 |
| `rapidocr-rec-ppocrv5-cyrillic-mobile` | `cyrillic_PP-OCRv5_rec_mobile.onnx` | 7.7 MB | ModelScope | 西里尔字母 |
| `rapidocr-rec-ppocrv5-arabic-mobile` | `arabic_PP-OCRv5_rec_mobile.onnx` | 7.6 MB | ModelScope | 阿拉伯文 |
| `rapidocr-rec-ppocrv5-devanagari-mobile` | `devanagari_PP-OCRv5_rec_mobile.onnx` | 7.5 MB | ModelScope | 天城文 |
| `rapidocr-rec-ppocrv5-thai-mobile` | `th_PP-OCRv5_rec_mobile.onnx` | 7.5 MB | ModelScope | 泰文 |
| `lama-inpainting` | `inpainting_lama_2025jan.onnx` | 198.4 MB | HuggingFace | 图像修复 |

### 下载地址

**RapidOCR 多语言识别模型** — ModelScope `RapidAI/RapidOCR`，tag `v3.9.1`，Apache-2.0

```
https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/onnx/PP-OCRv5/rec/<文件名>
```

仓库主页：<https://www.modelscope.cn/models/RapidAI/RapidOCR>

完整清单（PP-OCRv4/v5/v6 各语言各规格的直链）在 `rapidocr` 包内的 `default_models.yaml`。要加语言就从这里找地址。

**LaMa 修复模型** — HuggingFace `Carve/LaMa-ONNX`，Apache-2.0

```
https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx
```

模型页：<https://huggingface.co/Carve/LaMa-ONNX>

是原始 PyTorch big-lama 的 ONNX 移植。**只有 `lama_fp32.onnx` 的 SHA-256 与代码常量匹配**，同仓库的 `lama.onnx` 不行，详见 [3.2 第 3 步](#第-3-步下载-lama-修复模型)。

### 换模型要改哪里

1. `src/infrastructure/lama_onnx_adapter.py` 的 `LAMA_MODEL_FILENAME` 与 `LAMA_MODEL_SHA256`
2. `scripts/install_local_e2e_models.py` 的 `_RAPIDOCR_FILES`（OCR）或 `LAMA_MODEL_ID`
3. 重跑安装脚本，跑测试，**再过一遍[擦除质量基准](#42-擦除质量基准改蒙版逻辑前必读)**

模型选型的完整论证见[第 10 章](#10-关键决策记录)。

---

<a id="7-环境变量参考"></a>
## ![](https://api.iconify.design/mdi/cog.svg?color=%2378909C&height=24) 7. 环境变量参考

### 客户端

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `IMGTRANS_API_BASE_URL` | `https://imgtrans.rchtop.top` | 授权/翻译服务端地址 |
| `IMGTRANS_API_TOKEN` | 空 | 开发期直接注入客户端令牌 |
| `IMGTRANS_LAMA_MODEL` | 模型仓库中的路径 | 覆盖 LaMa 模型文件位置 |
| `IMGTRANS_TRANSLATION_MODE` | — | 翻译模式（如电商模式） |
| `IMGTRANS_BUILD_TARGET` | — | 打包目标平台标识 |

### 服务端

| 变量 | 默认 | 必需 | 说明 |
| --- | --- | --- | --- |
| `IMGTRANS_ENVIRONMENT` | `development` | | 设 `production` 会关闭 `/docs` |
| `IMGTRANS_DATABASE_URL` | `sqlite+pysqlite:///:memory:` | 生产必需 | 生产换 PostgreSQL |
| `IMGTRANS_SERVER_HOST` | `127.0.0.1` | | 监听地址 |
| `IMGTRANS_SERVER_PORT` | `8000` | | 监听端口 |
| `IMGTRANS_LOG_LEVEL` | `INFO` | | 日志级别 |
| `IMGTRANS_DOCS_ENABLED` | `true` | | OpenAPI 文档开关 |
| `IMGTRANS_ACTIVATION_SECRET` | — | ![](https://api.iconify.design/mdi/check-circle.svg?color=%232E7D32&height=16) | 激活令牌签名密钥 |
| `IMGTRANS_CLIENT_API_TOKEN` | — | ![](https://api.iconify.design/mdi/check-circle.svg?color=%232E7D32&height=16) | 客户端调用令牌 |
| `IMGTRANS_ADMIN_TOKEN` | — | ![](https://api.iconify.design/mdi/check-circle.svg?color=%232E7D32&height=16) | 管理接口令牌 |
| `IMGTRANS_SETTINGS_ENCRYPTION_KEY` | — | ![](https://api.iconify.design/mdi/check-circle.svg?color=%232E7D32&height=16) | 服务配置加密密钥 |
| `IMGTRANS_ADMIN_USERNAME` | — | 后台需要 | 后台用户名 |
| `IMGTRANS_ADMIN_PASSWORD_HASH` | — | 后台需要 | 后台密码哈希 |
| `IMGTRANS_ADMIN_SESSION_SECRET` | — | 后台需要 | 后台会话密钥 |
| `IMGTRANS_ADMIN_SESSION_TTL_SECONDS` | `28800` | | 后台会话时长 |
| `IMGTRANS_CLIENT_CONFIG_TTL_SECONDS` | `3600` | | 客户端配置缓存时长 |
| `IMGTRANS_TRANSLATOR_ENDPOINT` | 内置 | 翻译需要 | 微软翻译端点 |
| `IMGTRANS_TRANSLATOR_KEY` | — | 翻译需要 | 微软翻译密钥 |
| `IMGTRANS_TRANSLATOR_REGION` | — | | 微软翻译区域 |
| `IMGTRANS_TRANSLATOR_TIMEOUT_SECONDS` | `10.0` | | 超时 |
| `IMGTRANS_GLM_API_KEY` | — | GLM 需要 | 智谱 GLM 密钥 |
| `IMGTRANS_GLM_MODEL` | — | | GLM 模型名 |
| `IMGTRANS_WECHAT_APPID` | — | 支付需要 | 微信 AppID |
| `IMGTRANS_WECHAT_MCHID` | — | 支付需要 | 商户号 |
| `IMGTRANS_WECHAT_PRIVATE_KEY` | — | 支付需要 | 商户私钥 |
| `IMGTRANS_WECHAT_SERIAL_NO` | — | 支付需要 | 证书序列号 |
| `IMGTRANS_WECHAT_PLATFORM_CERT` | — | 支付需要 | 平台证书 |
| `IMGTRANS_WECHAT_APIV3` | — | 支付需要 | APIv3 密钥 |
| `IMGTRANS_WECHAT_NOTIFY_URL` | — | 支付需要 | 支付回调地址 |

密钥类变量不要写进代码或提交到仓库，用部署环境的密钥管理。

---

<a id="8-本次开发的文件"></a>
## ![](https://api.iconify.design/mdi/file-document-edit.svg?color=%2329B6F6&height=24) 8. 本次开发的文件

上一轮聚焦**擦除质量**（原文擦不干净 / 底色被误擦）和**译文排版**，另修复了 15 个既有失败测试。全部改动已通过 816 测试 + 60 张 / 1116 区域语料基准验证。

### 生产代码（3 个文件）

| 文件 | 变更 | 内容 |
| --- | --- | --- |
| `src/infrastructure/pillow_mask_rasterizer.py` | **+398** | 擦除蒙版生成，五处修复 |
| `src/infrastructure/text_renderer.py` | **+146** | 译文排版，两处修复 |
| `src/infrastructure/lama_onnx_adapter.py` | +4 / −1 | `LAMA_MODEL_SHA256` 更新为 `lama_fp32.onnx` 的哈希 |

<a id="pillow_mask_rasterizerpy-新增"></a>
#### `pillow_mask_rasterizer.py` 新增

| 函数 / 常量 | 解决的问题 |
| --- | --- |
| `_corrected_background` + `_BACKGROUND_*`（5 个常量） | **彩色横幅/圆角标签的底色被当文字擦掉**。背景色估计取多边形最外一圈的中位色，但 OCR 框比色块本体大一圈时，环采到的是框外颜色，中位数被带走，框内真正的底色反而被判成「距背景最远」而擦掉（实测橙色胶囊条覆盖率 98%，整条连圆角一起抹平）。纠偏三道门槛：环中位色框内占比 < 35%、候选底色与之相距 ≥ 60、候选底色主连通域占比 ≥ 75% |
| `_companion_foreground_mask` + `_COMPANION_*`（4 个常量） | **描边/双色艺术字只擦掉描边，字身原样留下**。对「另一个前景色」做同样的「距前景近且距背景远」筛选后并入。三重防误擦：补充色距背景 ≥ 80、距主前景 ≥ 60、补充蒙版 ≤ 框内 65% |
| `_extra_colour_text_masks` + `_grow_colour_mask` + `_EXTRA_*` / `_GROW_*`（10 个常量） | **同一行混排第三种颜色的文字被整段漏掉**（白字标题里夹一段红字）。dark/bright 只覆盖亮度两极，中间色调既不最暗也不最亮。改用双阈值区域生长：以严格蒙版为种子，把颜色宽松匹配（≤ 150）且距背景 ≥ 40 且与种子空间连通的像素并入 |
| `_looks_like_strokes` | 判别蒙版是「文字笔画」还是「实心色块」。主判据是笔画宽度（距离变换最大内切半径 / 框短边 ≤ 0.18） |
| `_merge_if_not_whole_box` / `_distance_to_segment` / `_enclosed_by` | 上述逻辑的辅助 |

#### `text_renderer.py` 新增

| 函数 / 常量 | 解决的问题 |
| --- | --- |
| `_HORIZONTAL_SNAP_DEGREES = 3.0`（在 `_text_box` 内使用） | **译文被误旋转**。检测框对水平文字常有 1~3 度歪斜，原样保留会让译文相对邻近文字明显倾斜。`\|rotation\| <= 3°` 归零。实测某区域 +1.65° → 0，全部 11 层现均为 0 |
| `_normalize_panel_grid_layers` + `_distinct_positions` + `_GRID_*`（3 个常量） | **重复面板字号不统一**。原 `_normalize_repeated_panel_rows` 要求同行（`center_y` 接近），多行多列的网格面板分不到一组，导致 6 个功能标签字号在 27.5~44.5 之间乱跳。新增网格识别（≥ 4 成员、≥ 2 行、≥ 2 列）后统一字号 |

### 测试代码（5 个文件，+90 / −127）

修复 15 个既有失败测试：

| 文件 | 处置 |
| --- | --- |
| `tests/ui/product/test_product_window.py`（4 个） | 移除已废弃的 `llm_config_store` 参数（客户端不再持有 LLM 密钥）；`_detail_regen_btns["specs"]` → `_detail_regen_btn` |
| `tests/ui/test_platform_runtime.py`（1 个） | 移除已废弃的 `update_models`；原断言依赖它派生的任务，改为验证真实契约（重入守卫完成后释放） |
| `tests/ui/editor/test_regression_translate_flow.py`（5 个 + 删 2 个） | 新增共享辅助 `_active_session()` 修复 3 个激活门禁失败；`_on_region_retranslated` 回调签名改为三元组；`ai_erase` 行为改为「框选松手即自动消除」；删除 2 个僵尸测试 |
| `tests/unit/test_basic_layout.py`（2 个） | 字体度量断言太临界（余量分别只有 0.25pt 和 −0.014），修正 fixture 拉开余量到 +4.3pt 和 +15.28 |
| `tests/integration/test_manual_region_workflow.py`（1 个） | 绝对字号断言改相对断言。根因：样式字体 Arial 无 CJK 字形，译文「促销」实走平台回退字体 |

**副产品**：修完之后整个测试套件不再需要任何脚手架，模态阻塞被根治。

### 新增工具

| 文件 | 说明 |
| --- | --- |
| `scripts/measure_erase_quality.py` | 擦除质量量化基准，`run` / `compare` 两个子命令。原为一次性脚本，本轮整理入库——后续任何蒙版改动都必须过这道验收 |

---

<a id="9-擦除质量完整技术背景"></a>
## ![](https://api.iconify.design/mdi/microscope.svg?color=%23EF5350&height=24) 9. 擦除质量：完整技术背景

**这一章是本文档最重要的部分。** 擦除质量是这个产品的核心竞争力，也是最容易踩坑的地方。上一轮在这上面花了绝大部分时间，其中三个方案是失败的。把这些写下来，是为了让你不用再走一遍。

### 9.1 问题的本质

客户反馈「翻译出来不对」。定位后发现**译文本身是正确的，问题全在擦除环节**。

而擦除环节的核心矛盾是：

> 当前架构在「文字像素级分割」这一环用的是**手写颜色阈值规则**（`_high_contrast_text_mask`），不是分割模型。这是通用能力的天花板，不是参数没调好。

`_high_contrast_text_mask` 的基本思路：取框内像素，按亮度找出最暗 3%（`dark`）和最亮 3%（`bright`）作为文字色候选，取多边形最外一圈的中位色作为背景色（`background`），然后按「距前景近 且 距背景远」筛出文字像素。

这个思路对「纯色字 + 素色背景」很有效，但电商图里描边字、渐变字、彩色底色条是**主流做法**，所以会高频失败。

按图片类型推演的预期表现：

| 图片类型 | 表现 | 瓶颈 |
| --- | --- | --- |
| 纯黑/纯白字 + 素色背景 | 良好 | — |
| 描边字 / 双色字 | 已修复（§9.2 #1） | 蒙版 |
| 第三色混排 | 已修复（§9.2 #2） | 蒙版 |
| 彩色横幅/圆角标签上的白字 | 已修复（§9.2 #4） | 蒙版 |
| 渐变填充字 | 不稳定 | 蒙版 |
| 半透明字 / 阴影字 | 不稳定 | 蒙版 |
| 复杂实拍背景上的文字 | 蒙版勉强，修补可能抹花 | 蒙版 + 修复 |
| 旋转/弧形/竖排文字 | 检测可能漏 | OCR + 蒙版 |
| 艺术字/字云 | 失败（V1 声明不保证） | OCR + 蒙版 |

### 9.2 四类失败模式与修复

| # | 失败模式 | 修复手段 | 结果 |
| --- | --- | --- | --- |
| 1 | 描边 / 双色字 | 补充前景色 + 孔洞包含判别（`_companion_foreground_mask`） | 成功，标题残留 31.2 → **5.6**（改善 5.6 倍），覆盖率 55.2% → 72.0% |
| 2 | 同行混排第三种颜色 | 颜色簇枚举 + 抗锯齿混色判别 + 双阈值区域生长（`_grow_colour_mask`） | 成功，红字「NS TO MEET」「满足」彻底消除。覆盖率 56.5 → 59.4 / 66.3 → 69.5 |
| 3 | 水平文字被误判弧形 | 二值化极性自适应 | 成功 |
| 4 | 彩色标签底色被擦毁 | **背景估计纠偏**（`_corrected_background`） | 成功，见 §9.4 |

修复 #1 之后有个意外收益：后端从 `lama-onnxruntime`（5431 ms）自动切到 `opencv-text-fill`（300 ms），**快了 18 倍**。因为蒙版准了之后，修复任务变简单，快路径就够用。

### 9.3 度量陷阱（必须理解）

**Sobel 残留指标会被「过度擦除」刷分。** 把整个文字框连背景一起填平后，边缘能量趋近于零，指标看起来极好，实际破坏了背景。

真实案例：某版实现显示 46 处改善、净收益 +483，看着远优于最终版。但其中多例覆盖率跳到 99.9%：

```
1.0k+人已采    覆盖 51.3% → 99.9%    残留 143.2 → 5.3      ← 整框误擦，指标却极好
拼             覆盖 89.5% → 100.0%   残留  73.2 → 212.4     ← 暴露真相
```

最终版改善数从 46 降到 4，是指标不再被刷分的结果，不是能力退步。

**结论：覆盖率与残留必须联合判读，覆盖率异常接近 100% 即应视为误擦而非改善。**

### 9.4 第 4 类失败：三次失败 + 一次成功

这是整个擦除工作里最曲折的部分，值得完整记录。

**现象**：白字压在彩色横幅/圆角标签/表格单元格上时，底色被当成文字擦掉。实测橙色圆角胶囊条覆盖率 98%，整条连圆角一起被抹平。

#### 尝试一（§14）：框内主色 + 几何形态判别 — 失败

用「框内主色 + 形态（笔画/包围/横贯）」判断哪块是底色。目标图片修好了，语料上 **8 个恶化 / 0 个改善**。撤回。

#### 尝试二（§15）：同色连通域是否溢出文字框 — 失败

换了个本质不同、看起来更可靠的信号：OCR 检测框天然把文字包在里面，所以文字笔画的同色连通域不会明显超出框；而横幅/标签底色一定延伸到框外。

实测分离度极大，看起来非常可信：

| 色簇 | 连通域宽/框宽 | 应判 |
| --- | --- | --- |
| 各图片的文字色 | 0.91 – 0.96 | 文字 |
| 圆角胶囊橙色底 | **2.16** | 底色 |
| 各类横幅底色 | 1.26 – 71 | 底色 |

所有文字色 ≤ 0.96，所有底色 ≥ 1.25，中间空档很大。目标 case 也修好了（86.2% / 98.0% → 68.1% / 73.1%）。

结果语料上 **7 个恶化 / 5 个改善，净 −80，覆盖 ≥99% 的区域由 5 增至 7**。撤回。

失败机理很关键：把背景色设为「底色结构」后，框内**其他所有颜色**（包括真正的图片背景）都变成「距背景远」→ 被判为文字 → 蒙版转向整框膨胀。恶化案例的覆盖率全都在上升：

```
拼                残留  73.2 → 187.8   覆盖 89.5% →  97.0%
x                 残留  12.2 →  65.8   覆盖 68.2% → 100.0%
0添加0致敏        残留   2.9 →  33.4   覆盖 67.2% →  92.6%
```

#### 尝试三（§16.1）：放开方向门槛 — 失败得最惨

`_colored_label_text_mask` 原本只认竖排细长标签，尝试放开成双向：

```python
elongated = (
    polygon_height >= polygon_width * 1.8
    or polygon_width >= polygon_height * 1.8   # 新增这一行
)
```

理由是后面还有三道判据兜着（饱和色占框 ≥ 25% / 单一主连通域 ≥ 75% / 中性文字对比 ≥ 65），以为影响面很窄。目标 case 修好了。

语料结果：**35 个恶化 / 2 个改善，净残留 +2047.8，189 个区域受影响**。

根因很直白：**横排文字行天然宽扁**，`polygon_width >= polygon_height * 1.8` 对绝大多数文字行都成立。那三道判据在真实电商图上太容易满足（彩色底色条 + 白字是电商设计的标准套路）。

**代码里已经留了注释禁止再次放开这一行。** 教训：判据的严格程度不能靠读代码估计，必须在语料上量化。

#### 尝试四（§16.3）：修正背景估计 — 成功

前三次都在**下游**打补丁（加判别分支、换判别信号）。第四次改为实测 `_high_contrast_text_mask` 的**输入**，发现背景色估计本身就是错的。

精确测量（橙色胶囊条 `自动清洁`）：

| 量 | 值 |
| --- | --- |
| 环中位背景色 | `(212,225,208)` 浅青 — **这是框外的颜色** |
| 该色在框内的占比 | **0.027** |
| 框内最大色桶 | `(157,56,8)` 橙 — 真正的底色 |
| 其占比 | 0.238 |
| `dark` | `(133,47,9)` chroma 124，距背景 278 |
| `bright` | `(254,255,247)` chroma 8，距背景 65 |

失败链条随之明确（此前记成「兜底分支」，实测更正为 `elif background_chroma <= 35` 分支）：

1. 背景 = 浅青，`background_chroma = 225 − 208 = 17`
2. `neutral_candidates` 为空：橙色 chroma 124 > 45 被中性色过滤排除；白字 chroma 8 合格但距背景 65 < 80 门槛不够
3. 于是走 `elif background_chroma <= 35`（17 满足），该分支**盲选距背景最远的那个当前景**
4. `max(278, 65)` → 选中橙色底色当文字
5. 整条橙色胶囊被擦掉，覆盖率 98%

**修复**：`_corrected_background` 三道门槛（见 [第 8 章](#pillow_mask_rasterizerpy-新增)）。判据用的是背景色的定义本身——文字只占框内少数像素，所以背景色一定在框内大量出现；环中位色在框内几乎找不到，环就是被污染的。

第三道门槛「候选底色须汇成单一连通块」是关键，它挡住了唯一的危险反例：**大号标题的笔画本身就能占满框内两成以上像素**。深蓝标题「无需洗马桶」框内最大色簇正是文字（0.211），只按占比取主色会把文字当背景，把这个已修好的区域搞崩。

连通性把两者分得很开：

| 区域 | 连通域数 | 主连通域占候选 | 判定 |
| --- | --- | --- | --- |
| 橙底 `自动清洁` | 11 | **0.915** | 采纳 |
| 橙底 `杀菌除臭` | 16 | **0.969** | 采纳 |
| 蓝字 `无需洗马桶` | 14 | **0.240** | 拒绝 |

**为什么不用现成的 `_looks_like_strokes` 做这道门槛**：实测区分不开。胶囊底色被白字切得很碎，最粗处只有框短边的 12.6%，与深蓝笔画的 7.7% 落在同一侧（都远低于阈值 0.18），于是一并被判成笔画。**形态粗细在这里区分不开，连通性才行。**

背景纠正后，下游一行代码都不用改就自然正确：橙底距新背景仅 25 不再是「最远」，白字距新背景 336 正确命中 `neutral_candidates`，橙底距白字前景 336 > `foreground_limit`(180) 所以不入蒙版，`_companion_foreground_mask` 的防误擦保护也自动生效（橙色距背景 25 < 80 门槛）。

#### 四轮对比

| 轮次 | 方案 | 改善 > 20 | 恶化 > 20 | 净残留 | 新增覆盖 ≥ 99% |
| --- | --- | --- | --- | --- | --- |
| §14 | 框内主色 + 形态 | 0 | 8 | — | — |
| §15 | 同色连通域溢出 | 5 | 7 | −80 | +2（5 → 7） |
| §16.1 | 放开方向门槛 | 2 | **35** | **+2047.8** | 0 |
| **§16.3** | **背景纠偏** | **5** | **1** | **−236.1** | **0**（5 → 4，少一个误擦） |

最终方案汇总指标：平均覆盖 59.9% → 59.9%（持平），平均残留 36.2 → **35.9**，受影响区域仅 **25 个**，其平均残留 **−11.0**。

**那唯一的「恶化」经视觉核实是误擦修正**：`AC ABC` 覆盖 97.7% → 86.2%、残留 27.2 → 56.1。开图看，该区域是感应电笔的**绿色 LCD 屏**——base 的 97.7% 覆盖意味着整块屏被填成机身深灰、屏幕在成品图里直接消失；修复后绿屏保留、屏内字符被擦。残留升高来自屏内字符没擦干净，不是回退。所以实际战绩是 **6 改善 / 0 真恶化**。

### 9.5 方法论沉淀

三轮失败换来的四条，改擦除代码时请遵守：

1. **目标 case 修好不构成修复成立**，必须语料配对对比。三次尝试全部在目标 case 上成功，其中两次在语料上净负
2. **判据的严格程度不能靠读代码估计**。§16.1 以为「三道判据兜得住」，实测 189 个区域受影响
3. **修 bug 前先实测输入是否正确**，而不是直接改判别逻辑。§14/§15 两轮都在下游打补丁，根因其实在上游一行背景估计
4. **覆盖率与残留必须联合判读**，且高覆盖率区域要开图核实

<a id="96-根治路线"></a>
### 9.6 根治路线

现有颜色规则的剩余短板是**擦除干净度**（如 LCD 屏内字符残留 56.1），而不再是**误擦底色**。若要根治：

**不要做**：继续往 `_high_contrast_text_mask` 加判别分支。四类失败已全部修复，边际收益很低。

**可行路线**：用合成数据训练小型笔画分割模型，替换整套颜色规则。

关键洞察是**标注成本为 0**：把文字渲染到背景图上时，**蒙版是渲染器免费给出的**，合成一张样本即同时得到图与像素级真值。

| 维度 | 人工标注（原估算） | 合成数据 |
| --- | --- | --- |
| 标注人力 | 800–2500 人时 | **0** |
| 数据量 | 受预算限制 | 可无限生成 |
| 覆盖面 | 受已有素材限制 | 可**定向覆盖已知失败模式**（本章 §9.2 逐一记录，可直接转成合成配方） |
| 许可 | 依赖公开数据集（多为非商业） | 自有素材 + 免费字体，许可自主 |

素材已就位：客户真实电商图作背景源，`packaging/assets` 与系统字体作字体源。模型规模不必大——任务是二分类像素分割，小型 U-Net 在 256×256 裁块上训练即可，导出 ONNX 后 CPU 推理，体积远小于 LaMa 的 198 MB。

验收标准应为「在覆盖 ≥ 99% 的区域数不增加的前提下，降低平均残留」，工具直接用 `scripts/measure_erase_quality.py`。

**短期兜底**：彩色横幅/圆角标签类图片走 UI 已有的手动擦除（框选 + 涂抹）。

---

<a id="10-关键决策记录"></a>
## ![](https://api.iconify.design/mdi/compass.svg?color=%23FFA726&height=24) 10. 关键决策记录

这一章记录「为什么不那样做」。都是实测或查证过的结论，不是偏好。

### D1. 不抄 manga-image-translator — 许可冲突

客户曾建议「这个开源的直接照抄」。**不可行**：该项目及其分割模型 `dmMaze/comic-text-detector` 均为 **GPL-3.0**。GPL-3.0 第 5(c) 条要求整个衍生作品同等授权并向每个客户提供源码，与激活码 / 时长包 / 微信支付的商业模式直接冲突。

架构思路可以参考（它做得好的原因是有一个**独立的像素级文字分割头**，在像素级文字标注上训练，直接输出笔画蒙版，而不是靠颜色规则反推），但**代码和权重都不能复制**。

### D2. 「找个现成的分割模型」可行性很低 — 数据集许可

| 资源 | 类型 | 许可 | 可商用 |
| --- | --- | --- | --- |
| manga-image-translator | 代码 | GPL-3.0 | 否（传染） |
| comic-text-detector | 代码 + 模型 | GPL-3.0 | 否（传染） |
| TextSeg | 数据集 | 学术限定 | 否 |
| BTS（腾讯，含中文） | 数据集 | 非商业研究/教育 | 否 |
| Hi-SAM 等 | 预训练模型 | 训练自 TextSeg | 大概率继承限制 |

**主流公开笔画级文字分割数据集均禁止商用，在其上训练的预训练权重同样受限。**

### D3. DBNet 概率图不能当笔画蒙版 — 已实测证伪

曾判断「PP-OCRv6 检测器基于 DBNet，其原始输出就是逐像素文字概率热图，当前实现丢弃了热图，复用它就能零成本得到蒙版」。**这个判断是错的，已实测推翻。**

直接取 `PP-OCRv6_det_small.onnx` 的概率图：

```
800x800 图：概率图 min=0.000 max=1.000 mean=0.126
  阈值 0.2 覆盖 12.88% / 0.3 覆盖 12.75% / 0.5 覆盖 12.56%
```

对阈值极不敏感，说明分割很干脆——但输出是**实心的文字区域块，不是笔画**。原因是 DBNet 的训练目标为文字区域多边形的收缩图（shrink map），本就不是字形。直接当擦除蒙版会把彩色底一起擦掉，正是要避免的问题。

### D4. LaMa 是「质量上限」而非「问题解法」

装上 LaMa 之前判断「补齐 inpainting 模型能解决擦除问题」。实测**不成立**：LaMa 装上后标题依然完整可见（残留度 78.8，甚至差于原图 67.9）。证明瓶颈在蒙版，蒙版错了再好的修复模型也没用。

顺带纠正另一个判断：原以为「OpenCV Telea 单张 35 秒」，实测 Telea 单次 **42 ms**。那 35 秒是 LaMa 缺失时的失败重试开销。

### D5. LaMa 分簇修复更差 — 保持单一全局裁剪

试过把蒙版分簇、每簇单独裁剪送 LaMa，以为能提高有效分辨率。实测**更差**：4764 ms → 6137 ms 且残留上升。

原因：LaMa 靠傅里叶卷积获得全图感受野，**上下文比分辨率更重要**，裁紧反而丢失可参考背景。全局裁剪框 800×800 → 512×512（0.64x）不是瓶颈。现有单一全局裁剪设计是合理的。

### D6. 不用 GPU — 产品约束

必须可导出 ONNX 且 `onnxruntime` **CPU** 可推理（无 CUDA 依赖）。目标平台 Win x64 / macOS arm64，用户机器不保证有独显。这排除了 SD-inpaint 这类方案。

### D7. 模型体积权衡

LaMa 198.4 MB 使安装包从 74 MB 增至约 272 MB。更小的 MI-GAN 是备选（面向移动端，体积/资源占用最小），但需要产品决策是否为了体积牺牲修复质量。**当前选择是保质量。**

### D8. 不为凑测试数重新实现被删除的功能

修失败测试时遇到两个测试引用了 `_region_box` 和 `_circular_path_for_retranslation`。用 `git log -S '符号名'` 查证，两者都在提交 `72e976b` 随二次翻译流程重构被**有意删除**，`src` 下已无等价实现。

处置：删除这 2 个僵尸测试，在原位留注释说明原因与恢复建议。**不是**把功能加回来凑数。

---

<a id="11-已知问题与路线图"></a>
## ![](https://api.iconify.design/mdi/map.svg?color=%2366BB6A&height=24) 11. 已知问题与路线图

### 环境类（不影响功能，但会浪费你时间）

| 问题 | 现象 | 处理 |
| --- | --- | --- |
| 单实例锁残留 | 强杀后再启动弹「客户端已在运行」 | `ipcs -mo` 找 NATTCH=0 的段，`ipcrm -m <ID>` |
| smoke-test 退出告警 | 打印 `RuntimeError: Signal source has been deleted` | **无害**，exit code 仍是 0。这是退出时的 Qt 信号竞态，既有行为 |
| 跨平台字体差异 | 同一段文字在 macOS/Windows 拟合出的字号不同 | 排版测试用相对断言，见 [4.4](#改排版渲染) |

### 功能类（按优先级）

| # | 问题 | 详情 | 建议 |
| --- | --- | --- | --- |
| 1 | **译文重复** | 同一段文字在结果里出现两次 | 属 OCR 分区或 LLM 去重问题，不在擦除链路上。需先定位是哪一环 |
| 2 | **擦除干净度** | 底色误擦已修复，但复杂背景上文字残留仍存在（如深色纹理背景上的标题、LCD 屏内字符残留 56.1） | 当前擦除质量的主要短板。根治见 [9.6](#96-根治路线) |
| 3 | **`_fill_text_mask` 刀锋阈值** | `fallback_inpaint_adapter` 依据 `_dominant_background_color()` 占比是否 `>= 0.6` 在「纯色就近取色」与「TELEA 纹理扩散」间二选一。实测 `描述图_17.jpg` 该值为 **0.6090**，仅高出 0.009。任何蒙版扰动都可能翻转策略导致质量大幅跳变 | 建议改为阈值附近加权混合或引入迟滞，避免二值化跳变 |
| 4 | **重复面板缺组间层级强制** | `_normalize_repeated_panel_rows` 只在组内统一字号（取组内拟合字号最小值），组间无约束。标题文案比正文长时，标题字号会被压到比正文还小，层级反转 | 需产品决策后再改。上一轮未擅自改生产代码 |
| 5 | **`测试数据/` 未纳入 `.gitignore`** | 客户图片语料（约 200 MB）目前靠手动避让 | 有误提交风险，建议尽快加上 |

### 路线图建议

**短期**（不改架构）
- 修译文重复（#1），影响用户直接感知
- `_fill_text_mask` 阈值改迟滞（#3），提升稳定性
- `.gitignore` 补 `测试数据/`（#5）

**中期**（需决策）
- 重复面板组间层级（#4）
- 是否为体积换 MI-GAN（D7）

**长期**（根治擦除）
- 合成数据训练笔画分割模型，替换 `_high_contrast_text_mask`（见 [9.6](#96-根治路线)）
- 先建评测基线（工具已有），再以「改善/恶化区域数」验收

---

<a id="12-许可合规红线"></a>
## ![](https://api.iconify.design/mdi/scale-balance.svg?color=%23D32F2F&height=24) 12. 许可合规红线

这是**商用闭源产品**。以下约束不可违反：

- **禁止并入任何 GPL / AGPL 代码或模型权重**。GPL-3.0 第 5(c) 条要求整个衍生作品同等授权并向每个客户提供源码，与激活码 / 时长包 / 微信支付的商业模式直接冲突
- 具体地，`manga-image-translator`（zyddnys）及其分割模型 `dmMaze/comic-text-detector` 均为 **GPL-3.0**，实现思路可以参考，**代码和权重都不能复制进来**
- **`TextSeg` / `BTS` 数据集禁止商用**，依赖它们训练的主流笔画分割模型（含 Hi-SAM）同样不可用
- 当前用的两个模型都是 **Apache-2.0**（RapidOCR、Carve/LaMa-ONNX），可商用
- **引入任何新依赖前先查许可**，`pip install` 之前查一遍 license

如果确实需要像素级文字分割能力，可行路线是用自有素材合成训练数据（标注成本为 0），训练小型 U-Net 并导出 ONNX。详见 [9.6](#96-根治路线)。

---

<a id="附-快速核对清单"></a>
## ![](https://api.iconify.design/mdi/clipboard-check.svg?color=%2343A047&height=24) 附. 快速核对清单

新环境配置完成后逐条确认，六条全过就可以开始开发：

```bash
# 1. Python 版本正确
.venv/bin/python --version                      # Python 3.11.x

# 2. 依赖装齐
.venv/bin/python -c "import PySide6, cv2, numpy, onnxruntime, rapidocr; print('deps ok')"

# 3. 模型装齐（应输出 9 个目录）
ls "$HOME/Library/Application Support/ImgTrans/models"        # macOS

# 4. LaMa 哈希正确
.venv/bin/python -c "
from pathlib import Path
from src.infrastructure.lama_onnx_adapter import LAMA_MODEL_SHA256
from src.infrastructure.model_delivery import FileModelRepository
from src.platform.paths import PlatformPaths
import hashlib
p = Path(FileModelRepository(PlatformPaths.discover().data_dir / 'models').active('lama-inpainting').path)
d = hashlib.sha256(p.read_bytes()).hexdigest()
print('lama ok' if d == LAMA_MODEL_SHA256 else f'MISMATCH {d}')
"

# 5. 全量测试通过
.venv/bin/python -m pytest -q                   # 816 passed, 6 skipped

# 6. 客户端能起来
.venv/bin/python -m src.main --smoke-test       # exit code 0
```

最后提醒一次：**改擦除逻辑前请读完[第 9 章](#9-擦除质量完整技术背景)**，那里有三次失败尝试的完整数据，能省下你几天时间。
