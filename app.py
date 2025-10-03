#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask Web 猜数字 · 强化版
- 表单校验（白名单/长度/数值范围）
- CSRF 保护（Flask-WTF）
- 排行榜：可选 SQLite（默认）或 JSON（带文件锁）
- Bootstrap 5 UI + 进度条（随区间缩小而增长）
- 生产部署：支持 gunicorn --preload
环境变量：
  SECRET_KEY            Flask会话与CSRF密钥（强烈建议设置）
  PERSIST_BACKEND       'sqlite'（默认）或 'json'
  DATABASE_URL          SQLite 文件路径（默认 'scores.db'）
"""

import os
import json
import random
import sqlite3
from datetime import datetime
from contextlib import contextmanager

from flask import Flask, request, render_template_string, session, redirect, url_for, abort, flash
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import IntegerField, StringField, HiddenField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Length, Regexp, Optional
try:
    from filelock import FileLock
except Exception:
    FileLock = None  # 仅当使用 JSON 后端且未安装 filelock 时会报错

# ==== 配置 ====
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
PERSIST_BACKEND = os.getenv("PERSIST_BACKEND", "sqlite").lower()
DB_PATH = os.getenv("DATABASE_URL", "scores.db")
JSON_PATH = os.getenv("JSON_PATH", "web_leaderboard.json")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["WTF_CSRF_TIME_LIMIT"] = None  # 方便本地开发
csrf = CSRFProtect(app)

# ==== 表单 ====
class DifficultyForm(FlaskForm):
    difficulty = HiddenField()  # easy / normal / hard / custom
    low = IntegerField("最小", validators=[Optional()])
    high = IntegerField("最大", validators=[Optional()])
    submit = SubmitField("开始")


class GuessForm(FlaskForm):
    guess = IntegerField("猜测", validators=[DataRequired(message="请输入数字"), NumberRange(min=1, max=10**7)])
    reset = SubmitField("重开")


class ScoreForm(FlaskForm):
    name = StringField(
        "昵称",
        validators=[
            Optional(),
            Length(min=0, max=20, message="名字最多20个字符"),
            Regexp(r"^[\u4e00-\u9fa5A-Za-z0-9_\- ]*$", message="仅允许中英文、数字、空格、-_")
        ]
    )
    submit = SubmitField("提交成绩")


# ==== 数据持久化（SQLite 或 JSON+文件锁）====
def init_sqlite():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                label TEXT NOT NULL,
                range_low INTEGER NOT NULL,
                range_high INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


if PERSIST_BACKEND == "sqlite":
    init_sqlite()


def add_record_sqlite(name, attempts, label, low, high):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO scores (name, attempts, label, range_low, range_high, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name or "匿名玩家", attempts, label, low, high, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
    finally:
        conn.close()


def load_board_sqlite():
    """返回 {label: [ {name, attempts, range, date}, ... ]}，每组Top 10（按 attempts 升序）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # 取所有 label
        labels = [row["label"] for row in conn.execute("SELECT DISTINCT label FROM scores")]
        board = {}
        for lbl in labels:
            rows = conn.execute(
                "SELECT name, attempts, range_low, range_high, created_at FROM scores WHERE label=? ORDER BY attempts ASC, id ASC LIMIT 10",
                (lbl,)
            ).fetchall()
            board[lbl] = [
                {
                    "name": r["name"],
                    "attempts": r["attempts"],
                    "range": f"{r['range_low']}~{r['range_high']}",
                    "date": r["created_at"]
                } for r in rows
            ]
        return board
    finally:
        conn.close()


@contextmanager
def json_locked(path):
    if FileLock is None:
        raise RuntimeError("需要安装 filelock 才能使用 JSON 持久化。请改用 SQLite 或安装 filelock。")
    lock = FileLock(path + ".lock")
    with lock:
        yield


def add_record_json(name, attempts, label, low, high):
    os.makedirs(os.path.dirname(JSON_PATH) or ".", exist_ok=True)
    with json_locked(JSON_PATH):
        data = {}
        if os.path.exists(JSON_PATH):
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        rec = {
            "name": name or "匿名玩家",
            "attempts": attempts,
            "range": f"{low}~{high}",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        data.setdefault(label, []).append(rec)
        data[label] = sorted(data[label], key=lambda r: r["attempts"])[:10]
        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def load_board_json():
    if not os.path.exists(JSON_PATH):
        return {}
    with json_locked(JSON_PATH):
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def add_record(name, attempts, label, low, high):
    if PERSIST_BACKEND == "sqlite":
        return add_record_sqlite(name, attempts, label, low, high)
    return add_record_json(name, attempts, label, low, high)


def load_board():
    if PERSIST_BACKEND == "sqlite":
        return load_board_sqlite()
    return load_board_json()


# ==== 游戏状态 ====
def ensure_game_state(reset=False, low=1, high=100, label="普通"):
    """初始化或重置一局游戏；同时维护动态可行区间 minp/maxp 用于进度条"""
    if reset or "target" not in session:
        session["low0"] = low
        session["high0"] = high
        session["label"] = label
        session["target"] = random.randint(low, high)
        session["attempts"] = 0
        session["minp"] = low       # 当前可能的最小值
        session["maxp"] = high      # 当前可能的最大值


def progress_ratio():
    """根据初始区间与当前可行区间计算进度百分比"""
    low0, high0 = session["low0"], session["high0"]
    minp, maxp = session["minp"], session["maxp"]
    total = high0 - low0 + 1
    remain = maxp - minp + 1
    done = max(0, total - remain)
    return round(100.0 * done / total, 2)


# ==== 视图 ====
BOOTSTRAP = "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"

BASE_HTML = """
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title or "猜数字" }}</title>
  <link href='""" + BOOTSTRAP + """' rel="stylesheet">
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, PingFang SC, Noto Sans CJK, sans-serif; }
    .card { border-radius: 16px; }
    .container-narrow { max-width: 860px; }
    .fade-enter { transition: all .3s ease; }
    .progress { height: 14px; }
  </style>
</head>
<body class="bg-light">
  <div class="container container-narrow py-4">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        <div class="alert alert-warning">{{ messages[0] }}</div>
      {% endif %}
    {% endwith %}
    <div class="card shadow-sm">
      <div class="card-body">
        {% block content %}{% endblock %}
      </div>
    </div>
    <p class="text-center text-muted mt-3"><small>
      后端：Flask · 表单校验 + CSRF · {{ backend|upper }} 存储
    </small></p>
  </div>
</body>
</html>
"""

from flask import render_template_string

@app.route("/", methods=["GET", "POST"])
def index():
    form = DifficultyForm()
    if request.method == "POST":
        choice = request.form.get("difficulty", "normal")
        if choice == "easy":
            ensure_game_state(reset=True, low=1, high=10, label="简单")
            return redirect(url_for("play"))
        elif choice == "normal":
            ensure_game_state(reset=True, low=1, high=100, label="普通")
            return redirect(url_for("play"))
        elif choice == "hard":
            ensure_game_state(reset=True, low=1, high=1000, label="困难")
            return redirect(url_for("play"))
        elif choice == "custom":
            # 服务器端校验：1 <= low < high <= 10^7
            try:
                low = int(request.form.get("low", 1))
                high = int(request.form.get("high", 100))
            except ValueError:
                low, high = 1, 100
            if not (1 <= low < high <= 10**7):
                flash("自定义范围无效，已回退到 1~100")
                low, high = 1, 100
            ensure_game_state(reset=True, low=low, high=high, label=f"自定义({low}~{high})")
            return redirect(url_for("play"))
        else:
            abort(400)

    html = render_template_string(
        BASE_HTML + """
        {% block content %}
          <h3 class="mb-3">猜数字 · 选择难度</h3>
          <form method="post" class="row gy-2">
            <div class="col-12 d-flex gap-2">
              <button name="difficulty" value="easy" class="btn btn-outline-primary">简单（1~10）</button>
              <button name="difficulty" value="normal" class="btn btn-outline-primary">普通（1~100）</button>
              <button name="difficulty" value="hard" class="btn btn-outline-primary">困难（1~1000）</button>
            </div>
            <div class="col-12 mt-2">
              <label class="form-label">或自定义范围</label>
              <div class="d-flex align-items-center gap-2">
                <input class="form-control" style="max-width:140px" type="number" name="low" placeholder="最小" value="1" min="1" max="10000000">
                <input class="form-control" style="max-width:140px" type="number" name="high" placeholder="最大" value="100" min="2" max="10000000">
                <button class="btn btn-primary" name="difficulty" value="custom">开始</button>
              </div>
              <div class="form-text">范围必须满足 1 ≤ 最小值 &lt; 最大值 ≤ 10⁷</div>
            </div>
          </form>
          <hr>
          <a class="btn btn-link p-0" href="{{ url_for('leaderboard') }}">查看排行榜</a>
        {% endblock %}
        """,
        backend=PERSIST_BACKEND,
        title="选择难度"
    )
    return html


@app.route("/play", methods=["GET", "POST"])
def play():
    ensure_game_state()  # 如用户直接访问，默认普通模式
    form = GuessForm()
    low0, high0, label = session["low0"], session["high0"], session["label"]
    minp, maxp = session["minp"], session["maxp"]
    msg = ""
    done = False

    if form.validate_on_submit():
        if form.reset.data:
            ensure_game_state(reset=True, low=low0, high=high0, label=label)
            return redirect(url_for("play"))

        guess = form.guess.data
        # 服务器端范围校验：必须在当前可行区间内（更严格）
        if not (minp <= guess <= maxp):
            msg = f"请输入 {minp} ~ {maxp} 范围内的整数"
        else:
            session["attempts"] += 1
            target = session["target"]
            if guess < target:
                msg = "小了 📉"
                session["minp"] = max(minp, guess + 1)
            elif guess > target:
                msg = "大了 📈"
                session["maxp"] = min(maxp, guess - 1)
            else:
                msg = f"🎉 猜对了！答案是 {target}，共用了 {session['attempts']} 次！"
                done = True

    # 计算进度
    prog = progress_ratio()
    # 渲染
    html = render_template_string(
        BASE_HTML + """
        {% block content %}
          <div class="d-flex justify-content-between align-items-center">
            <h3 class="mb-0">猜数字 · 游戏中</h3>
            <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('index') }}">返回首页</a>
          </div>
          <div class="text-muted mt-1">难度：{{ label }} · 初始范围：{{ low0 }} ~ {{ high0 }} · 当前可行：{{ minp }} ~ {{ maxp }} · 尝试：{{ attempts }} 次</div>

          <div class="my-3">
            <div class="progress">
              <div class="progress-bar" role="progressbar" style="width: {{ prog }}%; transition: width .25s ease;" aria-valuenow="{{ prog }}" aria-valuemin="0" aria-valuemax="100">{{ prog }}%</div>
            </div>
            <div class="form-text">进度表示「你已缩小的区间比例」。</div>
          </div>

          {% if not done %}
            <form method="post" class="row g-2 align-items-center">
              {{ form.csrf_token }}
              <div class="col-auto">
                {{ form.guess(class_="form-control", placeholder="请输入数字") }}
              </div>
              <div class="col-auto">
                <button class="btn btn-primary" type="submit">提交</button>
              </div>
              <div class="col-auto">
                {{ form.reset(class_="btn btn-outline-secondary") }}
              </div>
            </form>
            {% if form.errors %}
              <div class="alert alert-warning mt-2">
                {{ form.errors }}
              </div>
            {% endif %}
            <p class="mt-2">{{ msg }}</p>
          {% else %}
            <div class="alert alert-success">{{ msg }}</div>
            <form method="post" action="{{ url_for('submit_score') }}" class="row g-2 align-items-center">
              {{ score_form.csrf_token }}
              <div class="col-auto">
                {{ score_form.name(class_="form-control", placeholder="留名上榜（可空）") }}
              </div>
              <div class="col-auto">
                {{ score_form.submit(class_="btn btn-success") }}
              </div>
            </form>
            <p class="mt-2"><a href="{{ url_for('leaderboard') }}">查看排行榜</a> · <a href="{{ url_for('play') }}">重开一局</a></p>
          {% endif %}
        {% endblock %}
        """,
        backend=PERSIST_BACKEND,
        title="游戏中",
        form=form,
        score_form=ScoreForm(),
        label=label, low0=low0, high0=high0,
        minp=session["minp"], maxp=session["maxp"],
        attempts=session.get("attempts", 0),
        msg=msg, done=done, prog=prog
    )
    return html


@app.route("/submit_score", methods=["POST"])
def submit_score():
    if "target" not in session:
        return redirect(url_for("index"))
    form = ScoreForm()
    if not form.validate_on_submit():
        flash("昵称不合法或表单失效，请重试。")
        return redirect(url_for("play"))
    name = form.name.data or "匿名玩家"
    attempts = session.get("attempts", 0)
    low0, high0, label = session["low0"], session["high0"], session["label"]
    add_record(name, attempts, label, low0, high0)
    # 清空当前局
    session.clear()
    return redirect(url_for("leaderboard"))


@app.route("/leaderboard")
def leaderboard():
    board = load_board()
    groups = sorted(board.items(), key=lambda kv: kv[0]) if board else []
    html = render_template_string(
        BASE_HTML + """
        {% block content %}
          <div class="d-flex justify-content-between align-items-center">
            <h3 class="mb-0">排行榜</h3>
            <a class="btn btn-outline-secondary btn-sm" href="{{ url_for('index') }}">返回首页</a>
          </div>
          {% if not groups %}
            <p class="text-muted mt-2">暂无记录，去开始一局吧～</p>
          {% else %}
            {% for label, records in groups %}
              <h5 class="mt-3">【{{ label }}】Top {{ records|length }}</h5>
              <div class="table-responsive">
                <table class="table table-sm align-middle">
                  <thead><tr><th>#</th><th>玩家</th><th>尝试次数</th><th>范围</th><th>日期</th></tr></thead>
                  <tbody>
                    {% for r in records %}
                    <tr>
                      <td>{{ loop.index }}</td>
                      <td>{{ r.name if r.name else r["name"] }}</td>
                      <td>{{ r.attempts if r.attempts is defined else r["attempts"] }}</td>
                      <td>{{ r.range if r.range is defined else r["range"] }}</td>
                      <td>{{ r.date if r.date is defined else r["date"] }}</td>
                    </tr>
                    {% endfor %}
                  </tbody>
                </table>
              </div>
            {% endfor %}
          {% endif %}
        {% endblock %}
        """,
        backend=PERSIST_BACKEND,
        title="排行榜",
        groups=groups
    )
    return html


# 健康检查（可用于部署监控）
@app.get("/healthz")
def healthz():
    return {"ok": True, "backend": PERSIST_BACKEND}, 200


if __name__ == "__main__":
    # 本地开发
    app.run(debug=True, host="127.0.0.1", port=5000)
