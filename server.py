import json
import random
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'dev_secret_key_123'

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db_connection() as conn:
        # Таблица пользователей
        conn.execute('''CREATE TABLE IF NOT EXISTS users 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, 
             password TEXT, role TEXT, expiry_date DATE)''')
        # Таблица результатов
        conn.execute('''CREATE TABLE IF NOT EXISTS results 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
             score INTEGER, total INTEGER, percentage REAL, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        try:
            admin_pw = generate_password_hash('admin123')
            conn.execute("INSERT INTO users (username, password, role, expiry_date) VALUES (?, ?, ?, ?)",
                         ('admin', admin_pw, 'admin', '2099-12-31'))
            conn.commit()
        except sqlite3.IntegrityError: pass

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = get_db_connection().execute('SELECT * FROM users WHERE username = ?', (request.form['username'],)).fetchone()
        if user and check_password_hash(user['password'], request.form['password']):
            if datetime.now() > datetime.strptime(user['expiry_date'], '%Y-%m-%d'):
                return "Срок действия аккаунта истек", 403
            session.update({'user_id': user['id'], 'role': user['role'], 'username': user['username']})
            return redirect(url_for('admin' if user['role'] == 'admin' else 'test_page'))
        return "Ошибка входа"
    return render_template('login.html')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if session.get('role') != 'admin': return redirect(url_for('login'))
    conn = get_db_connection()
    if request.method == 'POST':
        pw = generate_password_hash(request.form['password'])
        conn.execute("INSERT INTO users (username, password, role, expiry_date) VALUES (?, ?, ?, ?)",
                     (request.form['username'], pw, 'student', request.form['expiry_date']))
        conn.commit()
    users = conn.execute('SELECT * FROM users WHERE role = "student"').fetchall()
    return render_template('admin.html', users=users)

@app.route('/api/questions')
def get_questions():
    if 'user_id' not in session: return jsonify([]), 403
    with open('questions.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    themes = {}
    for q in data:
        t_id = q['theme']['id']
        if t_id not in themes: themes[t_id] = {'pick': q['theme']['pick_count'], 'qs': []}
        themes[t_id]['qs'].append(q)
    final = []
    for t in themes.values():
        final.extend(random.sample(t['qs'], min(t['pick'], len(t['qs']))))
    random.shuffle(final)
    return jsonify(final)

@app.route('/api/save_result', methods=['POST'])
def save_result():
    d = request.json
    conn = get_db_connection()
    conn.execute("INSERT INTO results (user_id, score, total, percentage) VALUES (?, ?, ?, ?)",
                 (session['user_id'], d['score'], d['total'], d['percentage']))
    conn.commit()
    return jsonify({"status": "ok"})

@app.route('/api/history')
def get_history():
    rows = get_db_connection().execute('SELECT * FROM results WHERE user_id = ? ORDER BY date DESC', (session['user_id'],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/test')
def test_page():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('test.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)