---
status: consumed
handoff_no: 001
created: 2026-10-05 18:10
project: F95-Downloader (AkinaSync)
---

# 交接包 · F95-Downloader (AkinaSync) · 第 1 次

## 0. 给新对话的指令
你正在接手一个进行中的任务。请先通读本文件，然后：
1. 用 3-5 句话复述：目标、当前进度、你将做的第一步。
2. 列出你认为不清楚或互相冲突的地方（没有就写"无"）。
3. 等我确认复述无误后再动手。
4. 严格遵守第 3 节规则；与之冲突时以本文件为准，并向我指出。
5. 不要重做第 2 节已完成的内容，除非我明确要求。

## 1. 任务目标
- 最终目标：基于 FastAPI + 现代深色 Web UI 的本地作者画师作品同步更新与自动归档管理工具（F95zone 论坛爬取、资源解密下载、智能 Diff、自动 7z 解压归档至 `H:\akinaclub` 库）。
- 验收条件（可检验）：
  1. 所有改动或新增功能必须在独立分支完成，提交前运行自动化测试，经用户审核并在 GitHub 确认点头后才能合入 `main`；
  2. 列表加载毫秒级秒开，后台平滑节流增量校验，支持素材库离线保护与路径防串；
  3. 彻底杜绝路径穿越、SSRF、Cookie 明文泄露、整目录误删、并发锁竞争及缓存污染等安全隐患。
- 约束（技术栈、规范、禁区）：
  - 技术栈：Python 3.10+ (FastAPI, uvicorn, requests, BeautifulSoup4), 原生 Vanilla JS/CSS (无臃肿前端框架).
  - 严禁直接在 `main` 上修改代码，每个任务先建分支：`fix/<简述>` 或 `feat/<简述>` 或 `perf/<简述>`.
  - 严禁任何导致数据丢失的操作（如 rmtree 整个子目录、误清离线缓存）.

## 2. 已完成事项
| 事项 | 结果/结论 | 产物位置（文件/Artifact/提交） |
|---|---|---|
| Windows 资源管理器穿透修复 | 解决 IDE 虚拟桌面 session 隔离，改用 Task Scheduler (`schtasks /it`) 弹出物理桌面资源管理器 | `server.py` (`launch_explorer_interactive`) / commit `c48496f` |
| 专楼解绑与论坛原帖直达 | 新增 `/api/authors/unbind` 接口，前端主面板增加解绑重选与直达论坛专楼超链接与按钮，增加异常链接解绑容错 | `server.py`, `static/index.html` / commit `076106e` |
| P0 安全与数据损坏修复 | 彻底解决缓存污染(副本返回)、条目版本号(`CACHE_VERSION=2`)、内存并发读写锁(`_cache_lock`)、Cookie明文脱敏、SSRF限制、Host/Origin跨站防护、路径穿越清洗、受限归档路径、递归合并目录废除rmtree | `scanner.py`, `server.py`, `diff_engine.py`, `ingest.py`, `extractor.py` / commit `40f6c1a`, PR #1 (`bff5dcf`) |
| 冷启动秒开与静默校验 (Claude 方案) | 列表接口改为纯内存+顶层 scandir 直读缓存（毫秒级秒开），后台单作者 30ms 节流静默比对，慢 I/O 移出锁外，素材库路径绑定与离线保护，前端状态指示徽章 | `fastcache.py`, `scanner.py`, `server.py`, `static/index.html` / commit `cf7e6d1`, PR #2 (`045c97d`) |
| P1 准确性与下载健壮性修复 | 月份与密码单词边界正则、hostname精准下载链接判断、7z分卷支持、Pixeldrain /l/ 支持、.part 临时文件流式下载校验、Bamh3D年度归档统计修复 | `diff_engine.py`, `downloader.py`, `extractor.py`, `scanner.py` / PR #3 (`a17338f`) |
| P2 工程规范与可维护性重构 | 彻底消除吞异常 pass 并接入 logging；配置集中化与隐私脱敏（杜绝私人盘符与本地用户绝对路径）；移除 AOMEI 路径与高危遗留文件；统一 IDM 目录为 download_dir 并新增 /api/idm/download 路由；User-Agent 配置化；一键补齐 1.5s 限速防风控排队；跨平台与 Python 3.12 docstring 转义警告修复；新增 test_p2_fixes.py | `config.py`, `diff_engine.py`, `downloader.py`, `extractor.py`, `idm_helper.py`, `ingest.py`, `scanner.py`, `server.py`, `static/index.html`, `test_p2_fixes.py` / 分支 `fix/p2-engineering-and-cleanup` |

## 3. 已确认规则与决策（用户明确拍板，不得擅自更改）
- 规则/偏好：
  1. **Git 规则**：
     - 不要直接在 `main` 上改代码。每个任务先新建分支：`fix/<简述>` 或 `feat/<简述>` 或 `perf/<简述>`；
     - 改动前先运行 `git status`，确认工作区干净；有未提交改动先向用户汇报；
     - 小步提交：一个 commit 只做一件事，信息规范写成“动词+对象+原因”；
     - 提交前必须运行测试/构建，失败先修，不要提交；
     - 禁止 force push、reset --hard、删除分支，严禁提交密钥、token、.env、个人数据；
     - `git push` 前必须先展示 `git diff --stat` 和提交列表，等用户确认后再推；
     - 推送后提供分支名与 PR 链接，由用户在 GitHub 上亲自核对 diff 并合并 PR，用户点头确认才算合入。
  2. **交接规则**：新对话发现 `handoff/LATEST.md` 处于 `status: pending` 时必须走接续流程（复述、列疑点、等用户确认）；对话长或大阶段完成主动断点提醒。
- 关键决策及原因：
  - 缓存采用持久化 JSON (`data/library_cache.json`) 结合内存锁与顶层平铺缓存优先（`fastcache.list_cached`），彻底规避机械硬盘冷启动磁头高频随机寻道。
  - 敏感 Cookie (`xf_user`) 在 `GET /api/config` 永远脱敏剔除，前端仅展示脱敏占位符且留空不覆盖。
  - 批量下载与 F95zone 反代跳转解密强制 1.2s~1.5s 串行与节流间隔，防止触发论坛 429 与账号封禁。
- 用户曾纠正过的错误（不得重犯）：
  - 严禁在未获用户确认许可前私自将代码合并至 main；
  - 严禁在解压归档合并时对已有子目录执行 `shutil.rmtree`；
  - 严禁在锁内执行长时间的目录扫描与签名计算；
  - 严禁使用未加日志保护的静默 pass 吞没异常。

## 4. 工作区状态（交接时采集）
- 分支 / 最近提交：`fix/p2-engineering-and-cleanup` @ `cb4abc2`
- 未提交改动：无（所有代码已规范 commit）
- 自动化测试结果：
  - `python test_fastcache.py`: 全部通过
  - `python test_p0_fixes.py`: 全部通过
  - `python test_p1_fixes.py`: 全部通过
  - `python test_p2_fixes.py`: 全部通过 (7 tests passed in 2.51s)
- 运行中服务：uvicorn dev server 运行在 `http://127.0.0.1:8899`，状态为 200 OK。

## 5. 待解决问题清单（源自 Claude 架构审阅 P1 ~ P2）

### P1：识别准确性与下载健壮性
1. **月份正则词边界**：`normalize_month` 的月份名当前使用子串匹配（如 `'mar' in 'summary'`、`'dec' in 'decided'`），文本含年份时会被误识别，需改用带 `\b` 单词边界的正则。
2. **解压密码提取精准度**：密码正则 `"pass"` 缺少词边界，`bypass`、`passed` 等会被误命中，且仅取首个匹配。
3. **本地匹配算法调优**：`check_local_existence` 当前偏向误判为已拥有（子串匹配和数字提取偏宽，容易误判漏掉真正缺失的内容），需提高置信度或增加手动标记核验机制。
4. **下载链接过滤后缀匹配**：`is_download_link` 改用 `urlparse(href).hostname` 做后缀匹配，避免子串命中无关 URL。
5. **专楼标题解析启发式黑名单**：`Bonus:`、`Extras:`、`Patreon:` 等非月份标签需统一黑名单过滤，避免产生假标签。
6. **镜像链接去重**：同一标签重复出现时按 URL 进行去重。
7. **Pixeldrain 文件夹支持**：当前仅支持 `/u/` 单文件链接，常见 `/l/`（Folder 列表）尚未支持批量解析。
8. **下载完整性保障**：下载中途缺乏 `.part` 临时文件过渡、断点续传、失败重试与 Content-Length 大小校验（断网可能导致残缺包被归档识别）。
9. **7z 状态码精细区分与分卷支持**：细分密码错误（"Wrong password"）与磁盘满/文件损坏，增加分卷压缩包（`.part1.rar`、`.001`）的关联识别与提取。
10. **搜索接口硬编码 ID**：`f95_search.py` 中写死了过期搜索会话 ID，失败时与“空结果”混淆。
11. **数据存储进阶演进**：库体积继续膨胀后，将 `library_cache.json` 拆分（摘要 vs 资产）或平滑迁移至 SQLite。

### P2：工程规范、可维护性与冗余清理
1. **统一日志体系与异常透传**：消除满屏 `except Exception: pass`，引入标准 `logging`，并将底层失败原因（Cookie 失效、403 防火墙、网络超时）直观上报给前端 UI。
2. **配置集中化与隐私脱敏**：清理多处散落的私有盘符、绝对路径与测试种子数据，统一由 `config.py` 管理。
3. **冗余/高危遗留文件清理**：
   - `cookie_helper.py`：未被引用，且内存提取 DPAPI 会被安全软件（如 Defender）误判为窃密木马，且无法解密新版 Chrome v20 App-Bound，建议清理；
   - `check_hosts.py`：单次调试脚本，已无保留必要；
   - `f95_parser.py`：为 `diff_engine` 的早期原型，功能重复且会残留 `kidmo_sample.json`，建议清理。
4. **IDM 集成规范化**：`idm_helper.py` 尚未接入主下载路由，且保存目录与 `DownloadJob` 不一致。
5. **User-Agent 联动**：将固定写死的 Chrome/120 改为配置项，确保与用户浏览器获取 `cf_clearance` 时的 UA 保持严格一致。
6. **一键补齐批量限流保护**：增加排队并发上限与请求间隔，避免批量高频调用 `/masked/` 触发 F95 论坛 429 限流或账号风控。

## 6. 下一步起点
- 立即要做（具体到动作）：
  1. 通读本交接包，向用户复述当前目标、进度与下一步；
  2. 询问用户下一阶段先处理哪项（建议优先攻坚 **P1 的月份/密码正则边界修复与下载 .part 校验**，或 **P2 的废弃文件与硬编码清理**）；
  3. 创建新的独立功能分支（如 `feat/<功能名>` 或 `fix/<简述>`），并在分支内开展工作。
- 需要用户提供的输入：新会话中用户指定的优先修复/功能项。

## 7. 关键产物与引用
- 核心服务: [server.py](../server.py)
- 高性能缓存管理器: [fastcache.py](../fastcache.py)
- 目录扫描引擎: [scanner.py](../scanner.py)
- F95 论坛比对与解析: [diff_engine.py](../diff_engine.py)
- 安全解压模块: [extractor.py](../extractor.py)
- 归档入库模块: [ingest.py](../ingest.py)
- 前端单页应用: [static/index.html](../static/index.html)
- 自动化测试: `test_fastcache.py`, `test_p0_fixes.py`
- 本地数据: `data/artists.json`, `data/library_cache.json`
