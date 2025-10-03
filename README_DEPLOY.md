# 猜数字 · Flask 强化版

功能：
- 表单校验（白名单/长度/数值范围）
- CSRF 保护（Flask-WTF）
- 排行榜存储：可选 SQLite（默认）或 JSON（带文件锁）
- Bootstrap 5 UI + 进度条（区间缩小可视化）
- 生产部署：gunicorn --preload

## 本地运行

```bash
pip install -r requirements.txt
# 推荐：设置自己的 SECRET_KEY
$env:SECRET_KEY="your-strong-secret"   # PowerShell
export SECRET_KEY="your-strong-secret" # bash/zsh

# 选择存储：sqlite 或 json（默认 sqlite）
export PERSIST_BACKEND=sqlite
# 可选：自定义数据库文件
export DATABASE_URL="scores.db"

python app.py
# 浏览器打开 http://127.0.0.1:5000
```

## 部署（Railway / Render）

1. 创建新项目，连到此仓库或上传文件。
2. 配置环境变量：
   - `SECRET_KEY`: 强随机字符串
   - `PERSIST_BACKEND`: `sqlite`（推荐）或 `json`
   - （可选）`DATABASE_URL`: SQLite 文件名，默认为 `scores.db`
3. 启动命令使用 Procfile：`web: gunicorn -w 2 -k gthread -t 120 app:app --preload`
4. **持久化存储**：
   - Railway：给服务添加 **Volume** 并把 `DATABASE_URL` 指向挂载路径，如 `/data/scores.db`。
   - Render：开启 **Persistent Disk**，例如挂载到 `/var/data`，设置 `DATABASE_URL=/var/data/scores.db`。
   - 如果使用 JSON 存储，同理将 `JSON_PATH` 指向持久卷路径。

## 安全提示
- 一定要自定义 `SECRET_KEY`（强随机值）。
- 生产环境请使用 `gunicorn` 等 WSGI 服务器，不要用 Flask 自带开发服务器。
- 如启用 JSON 后端，需安装 `filelock`（已在 requirements.txt 中），并确保持久卷可写。

## 目录
- app.py
- requirements.txt
- Procfile
- README_DEPLOY.md
