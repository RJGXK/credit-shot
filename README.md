# 企业信用一键截图工具

在政府/司法公开平台上按单位或人员统一检索、批量截图的桌面工具。

- **8 个**政府/司法公开平台 · **30 类**信用记录 · 单位 / 人员**双模式**
- 浏览器内操作真实站点（Playwright 接管本机 Edge），**截图带信息条**（平台名称与 URL、单位名称、查询日期、查询页面）
- 四种截图方式：原图 / 原图+信息条 / 原图+日期弹窗 / 原图+日期弹窗+信息条
- 账号密码本地加密保存、账号日志脱敏；打码服务（YesCaptcha 兼容接口）可留空，缺题型自动回落人工
- 界面为浏览器 + 桌面双形态，网页端与软件端**自适应**布局

## 覆盖平台

| # | 平台 | 采集内容 |
|---|---|---|
| 1 | 信用中国 | 企业信用记录、失信被执行人、行政处罚等 10 项 |
| 2 | 中国政府采购网 | 严重违法失信记录 |
| 3 | 全国建筑市场监管公共服务平台 | 企业资质资格、不良行为、 blacklist、失信联合惩戒 |
| 4 | 全国法院被执行人 | 失信被执行人 |
| 5 | 国家企业信用信息公示系统 | 经营异常名录 |
| 6 | 中国裁判文书网 | 诉讼/仲裁、行贿（单位 + 人员） |
| 7 | 全国认证认可信息公共服务平台（CNCA） | 认证证书列表、认证详细信息 |

> 完整采集项清单见 [`使用说明.md`](使用说明.md)。

## 快速开始

```bat
:: 源码运行（双击 启动.vbs 亦可）
python main.py
```

启动后浏览器自动打开 `http://127.0.0.1:8760`。

**依赖**：Python 3.13 + FastAPI ≥ 0.121 + Playwright。
本机未装 Playwright 自带浏览器时，工具会自动改用本机 Edge（`msedge.exe`）并通过 CDP 接管。

## 目录结构

```
main.py        入口：起服务 + 开浏览器
engine.py      编排器：组装部件、调度「主体 × 采集项」、汇总结果
config.py      站点与采集项配置
core/          通用能力：browser/page/capture/captcha/subject/control/result/errors
platforms/     8 个平台各一模块 + base.py（处理器基类 + 分派表）
auth/          凭据读写 + 自动登录
web/           server/api/events(SSE)/models/static（原生 HTML+CSS+JS）
tools/         自检、探针、打包脚本
```

规矩：`platforms/` 只写站点知识，`core/` 只写通用能力，`engine.py` 只写编排。
界面 ↔ 引擎只有两个接口：REST 下指令、SSE 收日志。

## 打包

```bat
python tools/build_exe.py        :: 生成 dist/企业信用截图工具/
python tools/build_installer.py  :: 生成 dist/企业信用一键截图工具_安装包.exe
```

`build/` 与 `dist/` 都是**构建输出目录，不入版本库**；对外发布的成品归档在
`release/` 下（安装包走 Git LFS）。

## 自检

```bat
python selftest.py               :: 20 项逻辑自检，无需浏览器与 API Key
python tools/check_modules.py    :: AST 静态扫描（未定义名字 / 控制流异常继承 / 残留 time.sleep）
python tools/web_smoke.py        :: 起真服务，22 项 API 挨个打一遍
python tools/verify_skip.py      :: 5 项验「跳过此步」链路
python tools/verify_cnca_logic.py:: 11 项 CNCA 处理器逻辑验证
```

## 安全说明

- 凭据存于 `%APPDATA%\企业信用截图工具\凭据.ini`（明文，仅本机），**不入版本库**。
- 日志中账号脱敏，**密码绝不进日志**。
- 极验 / 天艾点选等官方打码服务不提供的题型，一律回落人工介入。

## 已知限制

- 站点改版后需重新核对选择器；`tools/probe_*.py` 系列提供了逐站探针脚本。
- 认监委等站点需**从上级目录跳转进入**，直连易被判异常 IP。

## 许可

[MIT](LICENSE) · Copyright (c) 2026 RJGXK

## 下载

Releases 页提供 Windows 安装包（NSIS 打包，含全部运行时依赖）：

```
企业信用一键截图工具_安装包.exe
```

安装后双击运行即可，只监听 `127.0.0.1`，浏览器界面与软件窗口均可用。

> 仓库 `release/` 下的安装包走 [Git LFS](https://git-lfs.com/) 存储，
> 直接 clone 需执行 `git lfs pull` 才能取到真实文件；
> 不想装 LFS 客户端的话，直接从 Releases 下载更省事。

