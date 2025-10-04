# 猜数字游戏（Flask + JSON 排行榜）

适配 **Railway 免费部署**：排行榜写入到 `/tmp/leaderboard.json`（重启会清空）。
如需持久化，请改用卷并切换到数据库或挂载持久目录。

## 本地运行
```bash
pip install -r requirements.txt
python app.py  # 访问 http://127.0.0.1:5000
```

## 生产（Railway）
Start Command（建议在 Railway 设置）：
```
gunicorn app:app -b 0.0.0.0:$PORT -w 2 -k gthread -t 120
```

## Railway 变量
- `SECRET_KEY` = 任意随机字符串
- （可选）`JSON_PATH` = `/tmp/leaderboard.json`（默认已是这个路径）

## 路由
- `/` 首页
- `/start` 开始/选择难度
- `/game` 游戏过程
- `/scoreboard` 排行榜
- `/healthz` 健康检查（返回 JSON）
