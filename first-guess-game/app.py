from flask import Flask, session, request, redirect, url_for, render_template, jsonify
import os, json, random

app = Flask(__name__)
# 建议在 Railway 的 Variables 中设置 SECRET_KEY；未设置则使用开发默认
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

# 排行榜 JSON 存储路径：默认写到 /tmp（Railway 免费环境可写，重启会清空）
JSON_PATH = os.environ.get('JSON_PATH', '/tmp/leaderboard.json')

def load_scoreboard():
    """读取排行榜；若文件不存在/损坏则返回空结构"""
    try:
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("bad json structure")
    except Exception:
        data = {"easy": [], "medium": [], "hard": []}
    # 确保三类难度键都存在
    for k in ("easy", "medium", "hard"):
        data.setdefault(k, [])
    return data

def save_scoreboard(data):
    """写入排行榜到 JSON 文件"""
    os.makedirs(os.path.dirname(JSON_PATH) or ".", exist_ok=True)
    with open(JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.get("/healthz")
def healthz():
    return jsonify(ok=True, backend="json", path=JSON_PATH), 200

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['GET', 'POST'])
def start_game():
    if request.method == 'POST':
        name = (request.form.get('name') or 'Anonymous').strip() or 'Anonymous'
        difficulty = request.form.get('difficulty') or 'easy'
        if difficulty not in ('easy', 'medium', 'hard'):
            difficulty = 'easy'

        if difficulty == 'easy':
            max_num, max_attempts = 20, 5
        elif difficulty == 'medium':
            max_num, max_attempts = 50, 7
        else:
            max_num, max_attempts = 100, 10

        session['name'] = name
        session['difficulty'] = difficulty
        session['target'] = random.randint(1, max_num)
        session['max_attempts'] = max_attempts
        session['attempts'] = 0
        session['last_message'] = ''
        session['range_max'] = max_num
        return redirect(url_for('game'))
    return render_template('start.html')

@app.route('/game', methods=['GET', 'POST'])
def game():
    if 'target' not in session:
        return redirect(url_for('start_game'))

    diff = session.get('difficulty', 'easy')
    labels = {'easy': '简单', 'medium': '中等', 'hard': '困难'}
    range_max = session.get('range_max', 20)
    msg = session.get('last_message', '')

    if request.method == 'POST':
        guess_text = (request.form.get('guess') or '').strip()
        if not guess_text.isdigit():
            msg = "请输入一个有效的数字！"
            session['last_message'] = msg
            return render_template('game.html',
                                   diff_label=labels.get(diff, diff),
                                   range_max=range_max,
                                   message=msg,
                                   attempts_left=session['max_attempts'] - session['attempts'])
        guess = int(guess_text)
        session['attempts'] += 1
        target = session['target']

        if guess == target:
            attempts_used = session['attempts']
            name = session.get('name', 'Anonymous')
            scoreboard = load_scoreboard()
            scoreboard.setdefault(diff, [])
            scoreboard[diff].append({'name': name, 'attempts': attempts_used})
            scoreboard[diff] = sorted(scoreboard[diff], key=lambda x: x.get('attempts', 10**9))[:50]
            save_scoreboard(scoreboard)

            # 清理游戏状态
            for k in ('target', 'max_attempts', 'attempts', 'last_message', 'range_max'):
                session.pop(k, None)

            result_msg = f"恭喜，{name} 猜中了数字 {target}！您共用了 {attempts_used} 次尝试。"
            return render_template('result.html', result=result_msg, win=True)

        else:
            msg = "太低了！" if guess < target else "太高了！"
            session['last_message'] = msg

            if session['attempts'] >= session['max_attempts']:
                answer = target
                for k in ('target', 'max_attempts', 'attempts', 'last_message', 'range_max'):
                    session.pop(k, None)
                result_msg = f"游戏结束！您已用尽所有机会。正确答案是 {answer}。"
                return render_template('result.html', result=result_msg, win=False)

    return render_template('game.html',
                           diff_label=labels.get(diff, diff),
                           range_max=session.get('range_max', 20),
                           message=msg,
                           attempts_left=session['max_attempts'] - session['attempts'])

@app.route('/scoreboard')
def view_scoreboard():
    data = load_scoreboard()
    # 确保排序
    for k in ('easy', 'medium', 'hard'):
        data[k] = sorted(data[k], key=lambda x: x.get('attempts', 10**9))
    return render_template('scoreboard.html', scoreboard=data)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
