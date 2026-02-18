from fastapi import FastAPI, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from io import StringIO
import csv, json, time
from datetime import datetime, timezone
from contextlib import asynccontextmanager


from db import Base, engine, get_db, SessionLocal
from models import User, Question, Attempt, AttemptDetail
from auth import make_serializer, set_session, clear_session, get_session_user_id, hash_password, verify_password
from quiz_logic import select_questions_strict, parse_correct, is_correct, TEST_SIZE

Base.metadata.create_all(bind=engine)

def ensure_admin(db: Session):
    # auto-create admin if none exists (first run)
    if db.query(User).filter(User.is_admin == True).count() == 0:
        admin = User(username="admin", password_hash=hash_password("admin123"), is_admin=True)
        db.add(admin)
        db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = SessionLocal()
    try:
        ensure_admin(db)   # создаст admin при первом запуске
        yield
    finally:
        db.close()

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SECRET = "CHANGE_ME_TO_RANDOM_SECRET"
serializer = make_serializer(SECRET)

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def get_current_user(request: Request, db: Session) -> User | None:
    uid = get_session_user_id(request, serializer)
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()

def require_login(request: Request, db: Session) -> User:
    user = get_current_user(request, db)
    if not user:
        raise RedirectResponse("/login", status_code=303)
    return user

def require_admin(request: Request, db: Session) -> User:
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise RedirectResponse("/dashboard", status_code=303)
    return user

@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return RedirectResponse("/login", status_code=303)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверный логин или пароль"}, status_code=401)
    resp = RedirectResponse("/dashboard", status_code=303)
    set_session(resp, serializer, user.id)
    return resp

@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    clear_session(resp)
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    total_questions = db.query(Question).count()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "total_questions": total_questions,
        "test_size": TEST_SIZE,
        "duration_minutes": TEST_SIZE
    })

# ---------- Admin: manage users ----------
@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse("/dashboard", status_code=303)
    users = db.query(User).order_by(User.username.asc()).all()
    return templates.TemplateResponse("admin_users.html", {"request": request, "user": user, "users": users, "msg": None})

@app.post("/admin/users/create")
def admin_create_user(request: Request, username: str = Form(...), password: str = Form(...), is_admin: str = Form("0"), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse("/dashboard", status_code=303)

    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse("admin_users.html", {
            "request": request,
            "user": user,
            "users": db.query(User).order_by(User.username.asc()).all(),
            "msg": "Такой пользователь уже существует"
        }, status_code=400)

    u = User(username=username, password_hash=hash_password(password), is_admin=(is_admin == "1"))
    db.add(u)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)

@app.post("/admin/users/reset")
def admin_reset_password(request: Request, user_id: int = Form(...), new_password: str = Form(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse("/dashboard", status_code=303)
    u = db.query(User).filter(User.id == user_id).first()
    if u:
        u.password_hash = hash_password(new_password)
        db.commit()
    return RedirectResponse("/admin/users", status_code=303)

# ---------- Admin: upload questions JSON ----------
@app.get("/admin/upload", response_class=HTMLResponse)
def admin_upload_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse("admin_upload.html", {"request": request, "user": user, "msg": None})

@app.post("/admin/upload")
async def admin_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse("/dashboard", status_code=303)

    content = await file.read()
    try:
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON must be list")
    except Exception:
        return templates.TemplateResponse("admin_upload.html", {"request": request, "user": user, "msg": "Ошибка: неверный JSON"}, status_code=400)

    # Replace bank полностью (проще и чище)
    db.query(Question).delete()
    db.commit()

    try:
        for item in data:
            q = Question(
                id=int(item["id"]),
                theme_id=int(item["theme"]["id"]),
                theme_title=str(item["theme"]["title"]),
                pick_count=int(item["theme"]["pick_count"]),
                qtype=str(item["type"]),
                text=str(item["question"]),
                opt0=str(item["options"][0]),
                opt1=str(item["options"][1]),
                opt2=str(item["options"][2]),
                opt3=str(item["options"][3]),
                correct_json=json.dumps(item["correct"], ensure_ascii=False),
            )
            db.add(q)
        db.commit()
    except Exception:
        db.rollback()
        return templates.TemplateResponse("admin_upload.html", {"request": request, "user": user, "msg": "Ошибка: структура вопросов неверная"}, status_code=400)

    return templates.TemplateResponse("admin_upload.html", {"request": request, "user": user, "msg": "Загружено успешно"})

# ---------- Quiz session (server-side in cookie: attempt_id only) ----------
# Мы создаём "черновик попытки" в БД, храним порядок вопросов в AttemptDetail (до ответа).
# Это проще, чем хранить всё в cookie.

@app.post("/quiz/start")
def quiz_start(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    bank = db.query(Question).all()
    try:
        selected = select_questions_strict(bank)
    except ValueError as e:
        # без раскрытия pick_count
        return templates.TemplateResponse("dashboard.html", {
            "request": request, "user": user,
            "total_questions": db.query(Question).count(),
            "test_size": TEST_SIZE, "duration_minutes": TEST_SIZE,
            "error": "Тест не может быть сформирован из текущей базы вопросов."
        }, status_code=400)

    attempt = Attempt(
        user_id=user.id,
        total_questions=TEST_SIZE,
        duration_minutes=TEST_SIZE,
        score=0,
        percent=0
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    # сохраняем порядок и “пустые” ответы
    for q in selected:
        d = AttemptDetail(
            attempt_id=attempt.id,
            question_id=q.id,
            theme_id=q.theme_id,
            qtype=q.qtype,
            selected_json="[]",
            correct_json=q.correct_json,
            is_correct=False
        )
        db.add(d)
    db.commit()

    # start time stored as epoch in cookie (чтобы таймер продолжался при F5)
    resp = RedirectResponse(f"/quiz/{attempt.id}/1", status_code=303)
    resp.set_cookie("quiz_started_at", str(int(time.time())), httponly=True, samesite="lax")
    return resp

@app.get("/quiz/{attempt_id}/{n}", response_class=HTMLResponse)
def quiz_question(request: Request, attempt_id: int, n: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
    if not attempt:
        return RedirectResponse("/dashboard", status_code=303)

    details = db.query(AttemptDetail).filter(AttemptDetail.attempt_id == attempt_id).order_by(AttemptDetail.id.asc()).all()
    if n < 1 or n > len(details):
        return RedirectResponse(f"/quiz/{attempt_id}/1", status_code=303)

    d = details[n-1]
    q = db.query(Question).filter(Question.id == d.question_id).first()

    selected = json.loads(d.selected_json)
    correct = json.loads(d.correct_json)

    # таймер
    started_at = request.cookies.get("quiz_started_at")
    try:
        started_at = int(started_at) if started_at else int(time.time())
    except Exception:
        started_at = int(time.time())
    elapsed = int(time.time()) - started_at
    remaining = max(0, attempt.duration_minutes * 60 - elapsed)

    return templates.TemplateResponse("quiz.html", {
        "request": request,
        "user": user,
        "attempt_id": attempt_id,
        "n": n,
        "total": attempt.total_questions,
        "theme_title": q.theme_title if q else "",
        "q": q,
        "qtype": d.qtype,
        "selected": selected,
        "correct": correct,
        "confirmed": (d.selected_json != "[]"),  # простое: если отвечал/подтверждал
        "remaining_seconds": remaining,
    })

@app.post("/quiz/{attempt_id}/{n}/confirm")
def quiz_confirm(
    request: Request,
    attempt_id: int,
    n: int,
    db: Session = Depends(get_db),
    selected: list[int] = Form(default=[])
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
    if not attempt:
        return RedirectResponse("/dashboard", status_code=303)

    details = db.query(AttemptDetail).filter(AttemptDetail.attempt_id == attempt_id).order_by(AttemptDetail.id.asc()).all()
    d = details[n-1]
    q = db.query(Question).filter(Question.id == d.question_id).first()

    # сохранить выбранное
    selected_sorted = sorted({int(x) for x in selected if int(x) in (0,1,2,3)})
    d.selected_json = json.dumps(selected_sorted)
    d.is_correct = is_correct(q, selected_sorted) if q else False
    db.commit()

    return RedirectResponse(f"/quiz/{attempt_id}/{n}", status_code=303)

@app.post("/quiz/{attempt_id}/{n}/skip")
def quiz_skip(request: Request, attempt_id: int, n: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
    if not attempt:
        return RedirectResponse("/dashboard", status_code=303)
    # skip = keep empty []
    return RedirectResponse(f"/quiz/{attempt_id}/{min(n+1, TEST_SIZE)}", status_code=303)

@app.post("/quiz/{attempt_id}/finish")
def quiz_finish(request: Request, attempt_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
    if not attempt:
        return RedirectResponse("/dashboard", status_code=303)

    details = db.query(AttemptDetail).filter(AttemptDetail.attempt_id == attempt_id).all()
    score = sum(1 for d in details if d.is_correct)
    attempt.score = score
    attempt.percent = int(round(score / attempt.total_questions * 100))
    db.commit()

    resp = RedirectResponse(f"/result/{attempt_id}", status_code=303)
    resp.delete_cookie("quiz_started_at")
    return resp

@app.get("/result/{attempt_id}", response_class=HTMLResponse)
def result_page(request: Request, attempt_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
    if not attempt:
        return RedirectResponse("/dashboard", status_code=303)

    # per-theme stats
    details = db.query(AttemptDetail).filter(AttemptDetail.attempt_id == attempt_id).all()
    # map theme_id -> title
    theme_titles = {q.theme_id: q.theme_title for q in db.query(Question).all()}
    per = {}
    for d in details:
        tid = d.theme_id
        if tid not in per:
            per[tid] = {"title": theme_titles.get(tid, f"id={tid}"), "correct": 0, "total": 0}
        per[tid]["total"] += 1
        per[tid]["correct"] += (1 if d.is_correct else 0)

    return templates.TemplateResponse("result.html", {"request": request, "user": user, "attempt": attempt, "per": per})

@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)

    attempts = db.query(Attempt).filter(Attempt.user_id == user.id).order_by(Attempt.timestamp.desc()).all()
    return templates.TemplateResponse("history.html", {"request": request, "user": user, "attempts": attempts})

@app.get("/history/{attempt_id}/csv")
def export_csv(request: Request, attempt_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
    if not attempt:
        return RedirectResponse("/history", status_code=303)
    details = db.query(AttemptDetail).filter(AttemptDetail.attempt_id == attempt_id).order_by(AttemptDetail.id.asc()).all()

    sio = StringIO()
    w = csv.writer(sio, delimiter=";")
    w.writerow(["timestamp", attempt.timestamp.isoformat()])
    w.writerow(["score", attempt.score])
    w.writerow(["total_questions", attempt.total_questions])
    w.writerow(["percent", attempt.percent])
    w.writerow([])
    w.writerow(["question_id", "theme_id", "type", "selected_indices", "correct_indices", "is_correct"])
    for d in details:
        w.writerow([d.question_id, d.theme_id, d.qtype, d.selected_json, d.correct_json, d.is_correct])

    data = sio.getvalue().encode("utf-8")
    filename = f"attempt_{attempt.timestamp.isoformat().replace(':','-')}.csv"
    return StreamingResponse(iter([data]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
