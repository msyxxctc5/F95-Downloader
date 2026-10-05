# F95 Downloader (AkinaSync)

<p align="center">
  <b>一站式 F95zone 创作者收藏库全自动增量更新、查缺补漏与多线程归档工具</b>
</p>

---

## 🌟 核心特性 (Features)

1. **泛用型智能 Diff 对比引擎 (`diff_engine.py`)**：
   - **多类型专楼结构兼容**：
     - **月度更新型**（如 *Kidmo*）：精准提取 `YYYY-MM` / `MM-YYYY` 格式。
     - **Patreon Term / Pack 型**（如 *Axsens*）：提取 150+ 期的 `Term XX`、`Pack XX` 标签。
     - **独立作品 / 标题型**（如 *Maplestar*）：智能识别带标点与编号的作品（如 `Kaiju No. 8:`、`Sono Bisque Doll Part 03:` 等）。
   - **本地资产感知与模糊比对**：自动扫描并规整本地数百个创作者目录，对比 F95 专楼实时发布，精准高亮标注 `待下载 (MISSING)` 与 `已归档 (DOWNLOADED)`。

2. **全域 22+ 常见网盘镜像智能识别**：
   - 全面支持 F95zone 内部反代掩码链接 (`/masked/`) 以及外部主流直链网盘：
     - *Pixeldrain, Mega, Gofile, Workupload, Buzzheavier (bzzhr), Datanodes, UploadHaven, Vikingfile, Bunkr, Mediafire, Files.fm, Mixdrop, Terminal, Bowfile 等*。
   - 自动过滤论坛内置头像、表情包及缩略图干扰。

3. **双轨下载引擎 (IDM 32 线程集成 + 内置流式下载)**：
   - **IDM 极速接管**：通过 Pixeldrain 直链 API 与 Chrome 浏览器扩展无缝联动，点击即可唤起 Internet Download Manager 享受 32 线程满速下载。
   - **内置异步下载管线**：支持单任务后台静默下载、实时速度与百分比进度追踪。

4. **自动化解压与分类归档流水线 (`extractor.py`)**：
   - 依托 7-Zip 引擎，支持 `.zip`、`.rar`、`.7z` 多种主流压缩格式。
   - **多重解压密码瀑布回退**：自动从帖子正文中提取密码，辅以 `f95zone`、作者名等备选字典，秒级静默解包。
   - 解压成功后自动归入 `<Library_Root>/<作者名>/<更新标识>/`，并按设置自动清理临时压缩包。

5. **Downloads 文件夹一键归档助手 (`ingest.py`)**：
   - 针对通过浏览器直接下载到系统的压缩包，提供一键扫描检测。
   - 自动基于压缩包文件名智能识别匹配的创作者与发布月份，一键解压入库。

6. **沉浸式现代极客 Web UI (`static/index.html`)**：
   - 采用纯 Vanilla CSS 打造的精美暗黑磨砂玻璃界面（Glassmorphism）。
   - 支持快捷搜索检索、一键补齐所有缺失、多网盘镜像跳转、全局下载任务悬浮抽屉。

---

## 📸 界面预览

* **创作者看板与智能查缺**：直观展示本地已归档数、专楼发布总数、缺失待补总数，差异卡片一目了然。
* **多网盘镜像与 IDM 调度**：提供每个发布版本的所有网盘镜像标签，支持直跳与 IDM 调度。
* **本地下载目录吸纳抽屉**：自动将系统 `Downloads` 目录内的零散文件快速解包收纳。

---

## 🛠️ 安装与快速上手 (Quick Start)

### 1. 克隆项目与安装依赖
```bash
git clone https://github.com/msyxxctc5/f95-downloader.git
cd f95-downloader
pip install -r requirements.txt
```

### 2. 基础配置
将 `config.example.json` 复制为 `config.json`：
```json
{
  "library_root": "H:\\akinaclub",
  "download_dir": "./downloads",
  "seven_zip_path": "7z",
  "xf_user": "YOUR_XF_USER_COOKIE_HERE",
  "delete_archive_after_extract": false
}
```
* **`library_root`**：您的本地创作者收藏总目录（如 `H:\akinaclub`）。
* **`xf_user`**：您的 F95zone 登录凭证 Cookie（进入 F95zone 网页后，按 F12 打开开发者工具 -> Application -> Cookies -> 复制 `xf_user` 的值）。

### 3. 启动服务
双击运行 `start.bat`，或者在终端运行：
```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8899 --reload
```

在浏览器中打开：
👉 **http://127.0.0.1:8899**

---

## 📁 目录架构说明

```
.
├── config.py              # 配置管理与 Cookie 加载器
├── config.example.json    # 配置文件模板示例
├── fastcache.py           # 内存直读极速缓存与后台静默增量校验器
├── diff_engine.py         # 专楼全格式解析、通用标签提取与 Diff 对比引擎
├── downloader.py          # Pixeldrain 直链解析与异步下载流处理器
├── extractor.py           # 7-Zip 多密码静默解压与分类归位管道
├── f95_search.py          # F95zone 站内专楼快速检索
├── idm_helper.py          # IDM 安装检测与命令行接管适配
├── ingest.py              # 系统 Downloads 目录自动扫描与归档吸纳
├── scanner.py             # 本地收藏库扫描与历史月份归一化工具
├── server.py              # FastAPI 后端服务入口与路由调度
├── start.bat              # Windows 平台快速启动脚本
├── requirements.txt       # Python 依赖项清单
└── static/
    └── index.html         # 单页面 Web 前端交互控制台
```

---

## 🛡️ 免责声明 (Disclaimer)

本项目仅供个人对已合法拥有或公开发布的媒体资料进行本地分类整理与学习交流之用。请遵守所在地区的法律法规及相关网站的服务条款。

---

## 📄 License
MIT License © 2026
