from flask import Flask, render_template, request, redirect, url_for, session, make_response
from datetime import date, timedelta, datetime
import calendar
from werkzeug.security import check_password_hash
from db import connect_db
import os
import csv
from werkzeug.utils import secure_filename
import io

from utils.db_helpers import get_student_id_by_user_id
from utils.web_helpers import normalize_role, get_academic_year
from utils.school_lookup import (
  find_student_class_section,
  get_class_teacher_for,
  get_schedule_teachers_for_class_day,
  parse_iso_date,
)

from services.notices_service import list_notices, create_notice, delete_notice
from services.fees_service import (
  create_fee_plan,
  create_fee_plans_for_year,
  list_fee_plans_for_class,
  get_fee_plan_id,
  get_student_id_by_phone,
  record_payment,
  get_fee_status_for_student,
  create_fee_payment_request,
  list_fee_payment_requests_for_student,
  list_fee_payment_requests_admin,
  get_fee_payment_request,
  update_fee_payment_request_status,
)
from services.fees_service import (
  list_payments_admin,
  list_payments_for_student,
  get_payment_receipt_admin,
  get_payment_receipt_student,
)
from services.results_service import (
  list_exams,
  create_exam,
  upsert_marks_bulk,
  get_marks_for_class_exam,
  set_publication,
  list_published_exams_for_student,
  get_student_result,
)
from services.leaves_service import (
  create_leave_request,
  list_student_leave_requests,
  list_teacher_pending_leaves,
  decide_leave_request,
)
from services.gemini_service import ask_gemini
from services.ai_cache import (
  load_auto_insights,
  save_auto_insight,
  build_risk_buckets,
  new_entry as new_auto_entry,
)
from services.ml_service import (
  get_ml_summary,
  predict_dropout,
  predict_exam_performance,
  DROPOUT_FORM_FIELDS,
  EXAM_FORM_FIELDS,
)



app = Flask(__name__)


@app.template_filter("month_name")
def month_name_filter(value):
  try:
    month_num = int(value)
  except (TypeError, ValueError):
    return value or ""
  if 1 <= month_num <= 12:
    return calendar.month_name[month_num]
  return str(value)



import logging
from logging.handlers import RotatingFileHandler

def setup_logging(app):
  app.logger.setLevel(logging.INFO)

  handler = RotatingFileHandler(
    "app.log",
    maxBytes=1_000_000,
    backupCount=3
  )
  formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s"
  )
  handler.setFormatter(formatter)
  handler.setLevel(logging.INFO)

  # Avoid duplicate handlers in Flask logger setup.
  if not app.logger.handlers:
    app.logger.addHandler(handler)
  else:
    app.logger.handlers.clear()
    app.logger.addHandler(handler)

# call it once
setup_logging(app)



@app.before_request
def log_request():
  try:
    app.logger.info(f"REQ {request.method} {request.path}")
  except Exception:
    pass


@app.errorhandler(404)
def not_found(e):
  app.logger.warning(f"404 NOT FOUND: {request.path}")
  return render_template(
    "error.html",
    title="Page not found (404)",
    message="This page doesn't exist. Please check the URL and try again.",
    role=session.get("role"),
    phone=session.get("phone"),
  ), 404



@app.get("/__routes")
def __routes():
  lines = []
  for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    methods = ",".join(sorted([m for m in rule.methods if m not in {"HEAD", "OPTIONS"}]))
    lines.append(f"{methods:10s}  {rule.rule:40s}  ->  {rule.endpoint}")
  return "<pre>" + "\n".join(lines) + "</pre>"

@app.get("/health")
def health():
  return {"status": "ok"}


app.secret_key = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY") or "dev-only-secret-key-change-later"

@app.errorhandler(500)
def server_error(e):
  app.logger.exception("500 SERVER ERROR")
  return render_template(
    "error.html",
    title="Server error (500)",
    message="Something went wrong on the server. Check app.log for details.",
    role=session.get("role"),
    phone=session.get("phone"),
  ), 500


#--------------------------------------------------- FETCH - FETCH - FETCH - FETCH - FETCH  ---------------------------------------------------------------
def fetch_user_by_phone(phone: str):
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, phone, password_hash, role, is_active FROM users WHERE phone=%s",
        (phone,),
    )   
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


#--------------------------------- FETCH ROLE PROFILE //// FETCH ROLE PROFILE
def fetch_role_profile(user_id: int, role: str):
    """
    Returns a dict of role-specific profile info.
    For students: also tries to find class/section/roll from class tables.
    """
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        if role == "student":
            cursor.execute("SELECT id, name FROM students WHERE user_id=%s", (user_id,))
            student = cursor.fetchone()
            if not student:
                return None

            student_id = student["id"]

            # Find which class table contains this student_id
            section_map = {"A": "01", "B": "02"}

            found = None
            for class_no in range(1, 11):
                for section_letter in ("A", "B"):
                    table = f"class_{class_no:02d}_section_{section_map[section_letter]}"
                    cursor.execute(f"SELECT roll FROM `{table}` WHERE student_id=%s LIMIT 1", (student_id,))
                    row = cursor.fetchone()
                    if row:
                        found = {
                            "name": student["name"],
                            "class_no": class_no,
                            "section": section_letter,
                            "roll": row["roll"],
                        }
                        break
                if found:
                    break

            # If not found in any class table, still return basic info
            if not found:
                return {"name": student["name"]}

            return found

        if role == "teacher":
            cursor.execute(
                """
                SELECT
                t.teacher_code,
                t.name,
                a.class_no,
                a.section
                FROM teachers t
                LEFT JOIN class_teacher_assignments a
                ON a.teacher_id = t.id
                WHERE t.user_id=%s
                ORDER BY a.academic_year DESC, a.id DESC
                LIMIT 1
                """,
                (user_id,),
            )
            t = cursor.fetchone()
            return t


        if role == "admin":
            cursor.execute("SELECT secret_id, name FROM admins WHERE user_id=%s", (user_id,))
            a = cursor.fetchone()
            return a

        if role == "head":
            cursor.execute("SELECT authentication_id, name FROM headmasters WHERE user_id=%s", (user_id,))
            h = cursor.fetchone()
            return h

        return None
    finally:
        cursor.close()
        conn.close()









# MAIN VARIABLES / LIST / DICTIONARY ////////////////////// ROLES / ROLES / ROLES / ROLES / ROLES / ROLES/ ROLES////////////////////////////// ROLES/ ROLES/ ROLES/ ROLES/

ROLE_PAGES = {
    "student": [
        ("profile", "Profile"),
        ("ai_assist", "AI Study Assistant"),
        ("fees", "Fees (Monthly)"),
        ("payments", "My Payments"),
        ("results", "Results"),
        ("attendance", "Attendance & Leave"),
        ("leaves", "Leave Requests"),
        ("notices", "Notices"),
        ("routine", "Routine"),
        ("daily_class", "Daily Diary"),
    ],
    "teacher": [
        ("students", "Student List"),
        ("ai_sheet", "AI Risk Sheet"),
        ("ai_insights", "AI Insights"),
        ("ai_auto", "Automated AI Insights"),
        ("attendance", "Take Attendance"),
        ("today_schedule", "Today's Schedule"),
        ("weekly_schedule", "Weekly Schedule"),
        ("daily_class", "Daily Class Update"),
        ("marks", "Marks Entry"),
        ("notices", "Notices"),
        ("leaves", "Leave Approvals"),
    ],
    "head": [
        ("teachers", "Teachers Management"),
        ("approvals", "Approvals"),
        ("ai_insights", "AI Insights"),
        ("ai_auto", "Automated AI Insights"),
        ("today_overview", "Today's Overview"),
        ("daily_class", "Class Diary"),
        ("results", "Results Publish/Lock"),
        ("reports", "Reports"),
        ("notices", "Notices"),
    ],

    "admin": [
        ("settings", "School Settings"),
        ("users", "Users Management"),
        ("ai_insights", "AI Insights"),
        ("fees_setup", "Fees Setup"),
        ("payments", "Payments"),
        ("payments_history", "Payments History"),
        ("timetable", "Timetable"),
        ("notices", "Notices"),
        ("reports", "Reports"),
        ("schedule_upload", "Teacher Schedule Upload"),
    ],
}

def build_nav_links(role: str) -> dict:
  role = normalize_role(role)
  links = {
    "profile": url_for("dashboard", role=role),
    "notices": url_for("notices", role=role),
  }

  if role == "student":
    links.update(
      {
        "ai_assist": url_for("student_ai_assist"),
        "fees": url_for("student_fees"),
        "payments": url_for("student_payments_history"),
        "results": url_for("student_results"),
        "attendance": url_for("student_attendance"),
        "routine": url_for("student_routine"),
        "leaves": url_for("student_leaves"),
        "daily_class": url_for("student_daily_class"),
      }
    )
  elif role == "teacher":
    links.update(
      {
        "ai_sheet": url_for("teacher_ai_sheet"),
        "ai_insights": url_for("ai_insights", role="teacher"),
        "ai_auto": url_for("ai_auto_insights", role="teacher"),
        "students": url_for("teacher_students", role="teacher"),
        "attendance": url_for("teacher_attendance", role="teacher"),
        "today_schedule": url_for("teacher_today_schedule"),
        "weekly_schedule": url_for("teacher_weekly_schedule"),
        "daily_class": url_for("teacher_daily_class"),
        "marks": url_for("teacher_marks"),
        "leaves": url_for("teacher_leaves"),
      }
    )
  elif role == "head":
    links.update(
      {
        "ai_insights": url_for("ai_insights", role="head"),
        "ai_auto": url_for("ai_auto_insights", role="head"),
        "today_overview": url_for("head_today_overview"),
        "teachers": url_for("head_teachers"),
        "results": url_for("head_results"),
        "approvals": url_for("head_approvals"),
        "reports": url_for("head_reports"),
        "daily_class": url_for("head_daily_class"),
      }
    )
  elif role == "admin":
    links.update(
      {
        "ai_insights": url_for("ai_insights", role="admin"),
        "settings": url_for("admin_settings"),
        "users": url_for("admin_users"),
        "fees_setup": url_for("admin_fees_setup"),
        "payments": url_for("admin_payments"),
        "payments_history": url_for("admin_payments_history"),
        "timetable": url_for("admin_timetable"),
        "reports": url_for("admin_reports"),
        "schedule_upload": url_for("admin_schedule_upload"),
      }
    )

  return links


@app.context_processor
def inject_layout_globals():
  role = session.get("role")
  role_norm = normalize_role(role) if role else None
  school_name = os.getenv("SCHOOL_NAME")
  if not school_name:
    try:
      conn = connect_db()
      cur = conn.cursor(dictionary=True)
      try:
        cur.execute("SELECT value FROM school_settings WHERE `key`='SCHOOL_NAME' LIMIT 1")
        row = cur.fetchone()
        school_name = (row or {}).get("value") or None
      finally:
        cur.close()
        conn.close()
    except Exception:
      school_name = None
  return {
    "app_name": school_name or "SchoolHub",
    "session_role": role_norm,
    "session_phone": session.get("phone"),
    "role_pages": ROLE_PAGES,
    "nav_links": build_nav_links(role_norm) if role_norm else {},
    "current_year": datetime.now().year,
  }








@app.get("/")
def home():
    return render_template("landing.html")



################################################## LOGIN PART - LOGIN PART - LOGIN PART ######################################################

# LOGIN
@app.get("/login")
def login():
    role = normalize_role(request.args.get("role", "student"))
    session["login_role"] = role

    if session.get("role") == role:
        return redirect(url_for("dashboard", role=role))

    return render_template("login.html", role=role)

# LOGIN POST
@app.post("/login")
def login_post():
    role = normalize_role(session.get("login_role", "student"))
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "")

    if phone == "" or password == "":
        return render_template("login.html", role=role, phone=phone, message="Phone and password are required.")

    user = fetch_user_by_phone(phone)

    if not user or user["is_active"] != 1:
        return render_template(
            "login.html",
            role=role,
            phone=phone,
            message="User not found or inactive.",
        )
    if user["role"] != role:
        return render_template(
            "login.html",
            role=role,
            phone=phone,
            message=f"Wrong role selected. This phone belongs to: {user['role']}",
        )
    
    if not check_password_hash(user["password_hash"], password):
        return render_template(
            "login.html",
            role=role,
            phone=phone,
            message="Invalid password.",
        )
    session["role"] = role
    session["phone"] = phone
    session["user_id"] = user["id"]
    session.pop("login_role", None)

    return redirect(url_for("dashboard", role=role))






############################################## DASHBOARD PART DASHBOARD PART DASHBOARD PART ########################################################################

# DASHBOARD
@app.get("/dashboard/<role>/")
def dashboard(role):
    role = normalize_role(role)

    if session.get("role") != role:
        return redirect(url_for("login", role=role))

    profile = fetch_role_profile(session.get("user_id"), role)
    pages = ROLE_PAGES.get(role, [])
    app.logger.info(f"DASH role={role} pages={pages}")
    return render_template(
        "dashboard.html",
        role=role,
        pages=pages,
        phone=session.get("phone"),
        profile=profile,
    )

@app.get("/dashboard/<role>/<page>")
def dashboard_page(role, page):

  app.logger.info(f"MENU role={role} page={page}")
  role = normalize_role(role)

  if session.get("role") != role:
    return redirect(url_for("login", role=role))


  page_routes = build_nav_links(role)

  target = page_routes.get(page)
  app.logger.info(f"MENU target={target}")

  if target:
    return redirect(target)


  return render_template(
    "coming_soon.html",
    role=role,
    phone=session.get("phone"),
    page=page,
  )

@app.route("/dashboard/<role>/ai-insights", methods=["GET", "POST"])
def ai_insights(role):
  role = normalize_role(role)

  if session.get("role") != role:
    return redirect(url_for("login", role=role))

  if role not in {"teacher", "head", "admin"}:
    return redirect(url_for("dashboard", role=role))

  summary = get_ml_summary()
  dropout_result = None
  exam_result = None
  message = None

  if request.method == "POST":
    form_kind = request.form.get("form_kind")
    try:
      if form_kind == "dropout":
        payload = {f["name"]: request.form.get(f["name"]) for f in DROPOUT_FORM_FIELDS}
        dropout_result = predict_dropout(payload)
      elif form_kind == "exam":
        payload = {f["name"]: request.form.get(f["name"]) for f in EXAM_FORM_FIELDS}
        exam_result = predict_exam_performance(payload)
      else:
        message = "Unknown form submission."
    except Exception as exc:
      app.logger.exception("AI Insights form error")
      message = f"Could not score the request: {exc}"

  return render_template(
    "ai_insights.html",
    role=role,
    phone=session.get("phone"),
    summary=summary,
    dropout_result=dropout_result,
    exam_result=exam_result,
    message=message,
  )


@app.route("/dashboard/<role>/ai-automated", methods=["GET", "POST"])
def ai_auto_insights(role):
  role = normalize_role(role)
  if session.get("role") != role:
    return redirect(url_for("login", role=role))
  if role not in {"teacher", "head"}:
    return redirect(url_for("dashboard", role=role))

  submissions = load_auto_insights()
  buckets = build_risk_buckets(submissions)
  message = None

  if role == "teacher" and request.method == "POST":
    student_name = (request.form.get("student_name") or "").strip()
    payload = {f["name"]: request.form.get(f["name"]) for f in DROPOUT_FORM_FIELDS}
    try:
      result = predict_dropout(payload)
      entry = new_auto_entry(
        student_name=student_name or "Unnamed student",
        label=result["label"],
        confidence=result["confidence"],
        submitted_by=session.get("phone") or "unknown",
        role=role,
        features=result.get("used_features", {}),
      )
      save_auto_insight(entry)
      submissions = load_auto_insights()
      buckets = build_risk_buckets(submissions)
      message = f"Saved for {entry.student_name} ({entry.label}, {(entry.confidence*100):.1f}%)."
    except Exception as exc:
      app.logger.exception("ai_auto_insights teacher submit failed")
      message = f"Could not score entry: {exc}"

  return render_template(
    "ai_automated.html",
    role=role,
    phone=session.get("phone"),
    buckets=buckets,
    submissions=submissions,
    message=message,
    fields=DROPOUT_FORM_FIELDS,
  )


############################## NOTICES PART NOTICES PART NOTICES PART NOTICES PART NOTICES PART ###########################################################
# NOTICES 

@app.get("/dashboard/<role>/notices")
def notices(role):
  role = normalize_role(role)
  if session.get("role") != role:
    return redirect(url_for("login", role=role))

  can_post = role in {"teacher", "head", "admin"}
  notices_latest_first = list_notices()

  return render_template(
    "notices.html",
    role=role,
    phone=session.get("phone"),
    can_post=can_post,
    notices=notices_latest_first,
  )

@app.post("/dashboard/<role>/notices")
def notices_post(role):
  role = normalize_role(role)
  if session.get("role") != role:
    return redirect(url_for("login", role=role))

  if role not in {"teacher", "head", "admin"}:
    return redirect(url_for("notices", role=role))

  title = request.form.get("title", "")
  body = request.form.get("body", "")

  try:
    create_notice(
      title=title,
      body=body,
      by_user_id=int(session.get("user_id")),
      by_role=role,
      by_phone=session.get("phone"),
    )
    return redirect(url_for("notices", role=role))
  except ValueError as e:
    # validation error: same page show message + old input
    return render_template(
      "notices.html",
      role=role,
      phone=session.get("phone"),
      can_post=True,
      notices=list_notices(),
      message=str(e),
      title=title,
      body=body,
    )

@app.post("/dashboard/<role>/notices/<int:notice_id>/delete")
def notice_delete(role, notice_id):
  role = normalize_role(role)

  if session.get("role") != role:
    return redirect(url_for("login", role=role))

  if role not in {"teacher", "head", "admin"}:
    return redirect(url_for("notices", role=role))

  requester_user_id = session.get("user_id")
  if requester_user_id is None:
    return redirect(url_for("login", role=role))

  delete_notice(
    notice_id=notice_id,
    requester_role=role,
    requester_user_id=int(requester_user_id),
  )
  return redirect(url_for("notices", role=role))


@app.post("/dashboard/<role>/notices/gemini")
def notice_gemini(role):
  role = normalize_role(role)
  if session.get("role") != role:
    return redirect(url_for("login", role=role))
  if role != "teacher":
    return redirect(url_for("notices", role=role))

  prompt = (request.form.get("prompt") or "").strip()
  draft_title = ""
  draft_body = ""
  message = None

  if not prompt:
    message = "Write a short prompt first."
  else:
    try:
      reply = ask_gemini(
        "Write a short school notice for students and parents. "
        "Return the title on the first line, then the body on the next lines.\n"
        f"Topic: {prompt}"
      )
      lines = [line.strip() for line in reply.splitlines() if line.strip()]
      if lines:
        draft_title = lines[0].replace("Title:", "").strip()[:120]
        draft_body = "\n".join(lines[1:]).strip()
      if not draft_body:
        draft_body = reply.strip()
    except Exception as exc:
      message = f"Gemini failed to generate a draft: {exc}"

  return render_template(
    "notices.html",
    role=role,
    phone=session.get("phone"),
    can_post=True,
    notices=list_notices(),
    message=message,
    title=draft_title,
    body=draft_body,
    gemini_prompt=prompt,
  )








@app.get("/dashboard/student/fees")
def student_fees():
  if session.get("role") != "student":
    return redirect(url_for("login", role="student"))

  message = request.args.get("msg")
  profile = fetch_role_profile(session.get("user_id"), "student")
  if not profile or "class_no" not in profile:
    return render_template(
      "fees.html",
      role="student",
      phone=session.get("phone"),
      rows=[],
      academic_year=get_academic_year(),
      message=message or "Class not assigned yet.",
      overdue_months=[],
      overdue_total=0,
      request_rows=[],
      available_months=[],
      current_month=date.today().month,
    )

  student_user_id = session.get("user_id")
  if student_user_id is None:
    return redirect(url_for("login", role="student"))

  student_id = get_student_id_by_user_id(int(student_user_id))
  if not student_id:
    return render_template(
      "fees.html",
      role="student",
      phone=session.get("phone"),
      rows=[],
      academic_year=get_academic_year(),
      message=message or "Student profile not found.",
      overdue_months=[],
      overdue_total=0,
      request_rows=[],
      available_months=[],
      current_month=date.today().month,
    )

  academic_year = get_academic_year()
  rows = get_fee_status_for_student(
    student_id=student_id,
    class_no=int(profile["class_no"]),
    section=str(profile["section"]),
    academic_year=academic_year,
  )

  current_month = date.today().month
  overdue_months = []
  overdue_total = 0
  for r in rows:
    fee_month = int(r.get("fee_month") or 0)
    due = int(r.get("due") or 0)
    if fee_month < current_month and due > 0:
      overdue_months.append(str(fee_month))
      overdue_total += due

  request_rows = list_fee_payment_requests_for_student(student_id=student_id, limit=200)
  available_months = [int(r.get("fee_month") or 0) for r in rows]

  return render_template(
    "fees.html",
    role="student",
    phone=session.get("phone"),
    rows=rows,
    academic_year=academic_year,
    message=message,
    overdue_months=overdue_months,
    overdue_total=overdue_total,
    request_rows=request_rows,
    available_months=available_months,
    current_month=current_month,
  )

@app.post("/dashboard/student/fees/request")
def student_fee_request():
  if session.get("role") != "student":
    return redirect(url_for("login", role="student"))

  profile = fetch_role_profile(session.get("user_id"), "student")
  if not profile or "class_no" not in profile:
    return redirect(url_for("student_fees", msg="Class not assigned yet."))

  student_user_id = session.get("user_id")
  if student_user_id is None:
    return redirect(url_for("login", role="student"))

  student_id = get_student_id_by_user_id(int(student_user_id))
  if not student_id:
    return redirect(url_for("student_fees", msg="Student profile not found."))

  try:
    fee_month = int(request.form.get("fee_month", "0"))
    requested_amount = int(request.form.get("requested_amount", "0"))
    note = request.form.get("note", "")
    academic_year = get_academic_year()

    plans = list_fee_plans_for_class(
      class_no=int(profile["class_no"]),
      section=str(profile["section"]),
      academic_year=academic_year,
    )
    plan = next((p for p in plans if int(p.get("fee_month") or 0) == fee_month), None)
    if not plan:
      raise ValueError("Fee plan not found. Ask admin to publish the plan first.")

    create_fee_payment_request(
      student_id=student_id,
      class_no=int(profile["class_no"]),
      section=str(profile["section"]),
      academic_year=academic_year,
      fee_month=fee_month,
      requested_amount=requested_amount,
      note=note,
    )
    return redirect(url_for("student_fees", msg="Payment request sent."))
  except ValueError as e:
    return redirect(url_for("student_fees", msg=str(e)))




@app.get("/dashboard/student/payments")
def student_payments_history():
  if session.get("role") != "student":
    return redirect(url_for("login", role="student"))

  user_id = session.get("user_id")
  if user_id is None:
    return redirect(url_for("login", role="student"))

  student_id = get_student_id_by_user_id(int(user_id))
  if not student_id:
    return render_template("student_payments.html", role="student", phone=session.get("phone"), rows=[], message="Student profile not found.")

  rows = list_payments_for_student(student_id=student_id, limit=200)
  return render_template("student_payments.html", role="student", phone=session.get("phone"), rows=rows)

@app.get("/dashboard/student/payments/<int:payment_id>")
def student_payment_receipt(payment_id):
  if session.get("role") != "student":
    return redirect(url_for("login", role="student"))

  user_id = session.get("user_id")
  if user_id is None:
    return redirect(url_for("login", role="student"))

  student_id = get_student_id_by_user_id(int(user_id))
  if not student_id:
    return redirect(url_for("student_payments_history"))

  receipt = get_payment_receipt_student(payment_id=payment_id, student_id=student_id)
  if not receipt:
    return render_template("payment_receipt.html", role="student", phone=session.get("phone"), receipt=None, message="Receipt not found.")

  return render_template("payment_receipt.html", role="student", phone=session.get("phone"), receipt=receipt)
















def class_table_name(class_no: int, section_letter: str) -> str:
    # Section A -> section_01, Section B -> section_02 (your DB naming)
    section_code = "01" if section_letter == "A" else "02"
    return f"class_{class_no:02d}_section_{section_code}"



@app.get("/dashboard/<role>/students")
def teacher_students(role):
    role = normalize_role(role)

    # Allow only teacher
    if role != "teacher":
        return redirect(url_for("dashboard", role=role))

    # Must be logged in as teacher
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    q = request.args.get("q", "").strip()

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1) Find teacher_id from logged in user_id
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return render_template(
                "teacher_students.html",
                role="teacher",
                class_no="-",
                section="-",
                students=[],
                q=q,
                message="Teacher profile not found in DB.",
            )

        teacher_id = t["id"]

        # 2) Find assigned class/section (latest)
        cursor.execute(
            """
            SELECT class_no, section
            FROM class_teacher_assignments
            WHERE teacher_id=%s
            ORDER BY academic_year DESC, id DESC
            LIMIT 1
            """,
            (teacher_id,),
        )
        a = cursor.fetchone()
        if not a:
            return render_template(
                "teacher_students.html",
                role="teacher",
                class_no="-",
                section="-",
                students=[],
                q=q,
                message="Class teacher assignment not found. Run/import assignments first.",
            )

        class_no = int(a["class_no"])
        section = a["section"]  # 'A' or 'B'
        table = class_table_name(class_no, section)

        # 3) Fetch students from the class table + join for name/phone
        base_sql = f"""
            SELECT c.roll, s.name, u.phone
            FROM `{table}` c
            JOIN students s ON s.id = c.student_id
            JOIN users u ON u.id = s.user_id
        """

        params = []
        if q:
            base_sql += " WHERE s.name LIKE %s OR u.phone LIKE %s"
            like = f"%{q}%"
            params.extend([like, like])

        base_sql += " ORDER BY c.roll ASC"

        cursor.execute(base_sql, tuple(params))
        students = cursor.fetchall()

        return render_template(
            "teacher_students.html",
            role="teacher",
            class_no=class_no,
            section=section,
            students=students,
            q=q,
            message=None if students else "No students found.",
        )
    finally:
        cursor.close()
        conn.close()


@app.route("/dashboard/teacher/ai-sheet", methods=["GET", "POST"])
def teacher_ai_sheet():
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    predictions = {}
    values = {}
    message = None

    def risk_label(raw_label: str) -> str:
        label = (raw_label or "").lower()
        if "dropout" in label:
            return "High risk"
        if "enrolled" in label or "risk" in label:
            return "Risk"
        return "Good"

    try:
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return render_template(
                "teacher_ai_sheet.html",
                role="teacher",
                class_no="-",
                section="-",
                students=[],
                fields=DROPOUT_FORM_FIELDS,
                values={},
                predictions={},
                message="Teacher profile not found.",
            )

        teacher_id = t["id"]
        cursor.execute(
            """
            SELECT class_no, section
            FROM class_teacher_assignments
            WHERE teacher_id=%s
            ORDER BY academic_year DESC, id DESC
            LIMIT 1
            """,
            (teacher_id,),
        )
        a = cursor.fetchone()
        if not a:
            return render_template(
                "teacher_ai_sheet.html",
                role="teacher",
                class_no="-",
                section="-",
                students=[],
                fields=DROPOUT_FORM_FIELDS,
                values={},
                predictions={},
                message="Class teacher assignment not found.",
            )

        class_no = int(a["class_no"])
        section = a["section"]
        table = class_table_name(class_no, section)

        cursor.execute(
            f"""
            SELECT c.roll, s.id AS student_id, s.name, u.phone
            FROM `{table}` c
            JOIN students s ON s.id = c.student_id
            JOIN users u ON u.id = s.user_id
            ORDER BY c.roll ASC
            """
        )
        students = cursor.fetchall() or []

        if request.method == "POST":
            values = {k: v for k, v in request.form.items()}
            action = values.get("action", "")
            send_to_head = values.get("send_to_head") == "1"

            def run_prediction(student_id: int):
                features = {}
                for f in DROPOUT_FORM_FIELDS:
                    key = f"{f['name']}_{student_id}"
                    features[f["name"]] = values.get(key)
                result = predict_dropout(features)
                predictions[student_id] = {
                    "label": risk_label(result["label"]),
                    "raw_label": result["label"],
                    "confidence": result["confidence"],
                }
                if send_to_head:
                    entry = new_auto_entry(
                        student_name=next((s["name"] for s in students if int(s["student_id"]) == student_id), "Unknown"),
                        label=result["label"],
                        confidence=result["confidence"],
                        submitted_by=session.get("phone") or "unknown",
                        role="teacher",
                        features=result.get("used_features", {}),
                    )
                    save_auto_insight(entry)

            if action == "predict_all":
                any_scored = False
                for s in students:
                    sid = int(s["student_id"])
                    # Only score if at least one field is filled.
                    if any(values.get(f"{f['name']}_{sid}") for f in DROPOUT_FORM_FIELDS):
                        run_prediction(sid)
                        any_scored = True
                message = "Predictions updated for filled rows." if any_scored else "No filled rows to score."
            elif action.startswith("predict:"):
                try:
                    target_id = int(action.split(":", 1)[1])
                    run_prediction(target_id)
                    message = "Prediction updated."
                except Exception:
                    message = "Could not score the selected row."

        return render_template(
            "teacher_ai_sheet.html",
            role="teacher",
            class_no=class_no,
            section=section,
            students=students,
            fields=DROPOUT_FORM_FIELDS,
            values=values,
            predictions=predictions,
            message=message,
        )
    finally:
        cursor.close()
        conn.close()


@app.get("/dashboard/teacher/marks")
def teacher_marks():
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    academic_year = get_academic_year()

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return render_template(
                "teacher_marks.html",
                academic_year=academic_year,
                class_no="-",
                section="-",
                exams=[],
                selected_exam_id=None,
                subject="",
                max_marks=100,
                students=[],
                existing_marks={},
                message="Teacher profile not found in DB.",
            )

        teacher_id = int(t["id"])
        cursor.execute(
            """
            SELECT class_no, section
            FROM class_teacher_assignments
            WHERE teacher_id=%s
            ORDER BY academic_year DESC, id DESC
            LIMIT 1
            """,
            (teacher_id,),
        )
        a = cursor.fetchone()
        if not a:
            return render_template(
                "teacher_marks.html",
                academic_year=academic_year,
                class_no="-",
                section="-",
                exams=[],
                selected_exam_id=None,
                subject="",
                max_marks=100,
                students=[],
                existing_marks={},
                message="Class teacher assignment not found.",
            )

        class_no = int(a["class_no"])
        section = str(a["section"])
        table = class_table_name(class_no, section)

        exams = list_exams(academic_year=academic_year)

        selected_exam_id = request.args.get("exam_id", "").strip()
        subject = (request.args.get("subject") or "").strip()
        max_marks_raw = (request.args.get("max_marks") or "100").strip()

        exam_id_int = None
        if selected_exam_id:
            try:
                exam_id_int = int(selected_exam_id)
            except Exception:
                exam_id_int = None

        try:
            max_marks = float(max_marks_raw)
        except Exception:
            max_marks = 100.0

        cursor.execute(
            f"""
            SELECT c.roll, s.id AS student_id, s.name, u.phone
            FROM `{table}` c
            JOIN students s ON s.id = c.student_id
            JOIN users u ON u.id = s.user_id
            ORDER BY c.roll ASC
            """
        )
        students = cursor.fetchall() or []

        existing_marks = {}
        if exam_id_int and subject:
            existing_marks = get_marks_for_class_exam(exam_id=exam_id_int, class_no=class_no, section=section, subject=subject)

        return render_template(
            "teacher_marks.html",
            academic_year=academic_year,
            class_no=class_no,
            section=section,
            exams=exams,
            selected_exam_id=exam_id_int,
            subject=subject,
            max_marks=max_marks,
            students=students,
            existing_marks=existing_marks,
            message=request.args.get("msg"),
        )
    finally:
        cursor.close()
        conn.close()


@app.post("/dashboard/teacher/marks/exams")
def teacher_marks_exam_create():
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    academic_year = get_academic_year()
    name = request.form.get("name", "")
    try:
        exam_id = create_exam(academic_year=academic_year, name=name)
        return redirect(url_for("teacher_marks", exam_id=exam_id, msg="Exam created."))
    except ValueError as e:
        return redirect(url_for("teacher_marks", msg=str(e)))


@app.post("/dashboard/teacher/marks/save")
def teacher_marks_save():
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    exam_id = int(request.form.get("exam_id", "0") or "0")
    subject = (request.form.get("subject") or "").strip()
    max_marks_raw = (request.form.get("max_marks") or "100").strip()
    try:
        max_marks = float(max_marks_raw)
    except Exception:
        max_marks = 100.0

    # Find assigned class/section
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return redirect(url_for("teacher_marks", msg="Teacher profile not found."))
        teacher_id = int(t["id"])

        cursor.execute(
            """
            SELECT class_no, section
            FROM class_teacher_assignments
            WHERE teacher_id=%s
            ORDER BY academic_year DESC, id DESC
            LIMIT 1
            """,
            (teacher_id,),
        )
        a = cursor.fetchone()
        if not a:
            return redirect(url_for("teacher_marks", msg="Class teacher assignment not found."))
        class_no = int(a["class_no"])
        section = str(a["section"])
    finally:
        cursor.close()
        conn.close()

    marks_by_student_id = {}
    for k, v in request.form.items():
        if not k.startswith("mark_"):
            continue
        sid = k.replace("mark_", "").strip()
        if sid == "":
            continue
        if (v or "").strip() == "":
            continue
        try:
            marks_by_student_id[int(sid)] = float(v)
        except Exception:
            continue

    try:
        count = upsert_marks_bulk(
            exam_id=exam_id,
            class_no=class_no,
            section=section,
            subject=subject,
            max_marks=max_marks,
            marks_by_student_id=marks_by_student_id,
            entered_by_user_id=int(session.get("user_id")),
        )
        return redirect(url_for("teacher_marks", exam_id=exam_id, subject=subject, max_marks=max_marks, msg=f"Saved marks for {count} students."))
    except ValueError as e:
        return redirect(url_for("teacher_marks", exam_id=exam_id, subject=subject, max_marks=max_marks, msg=str(e)))


@app.get("/dashboard/teacher/leaves")
def teacher_leaves():
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    academic_year = get_academic_year()
    rows = list_teacher_pending_leaves(teacher_user_id=int(session.get("user_id")), academic_year=academic_year, limit=300)
    return render_template("teacher_leaves.html", rows=rows, message=request.args.get("msg"))


@app.post("/dashboard/teacher/leaves/decide")
def teacher_leave_decide():
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    leave_id = int(request.form.get("leave_id", "0") or "0")
    status = (request.form.get("status") or "").strip()
    try:
        decide_leave_request(leave_id=leave_id, status=status, decided_by_user_id=int(session.get("user_id")))
        return redirect(url_for("teacher_leaves", msg="Decision saved."))
    except ValueError as e:
        return redirect(url_for("teacher_leaves", msg=str(e)))


@app.route("/dashboard/<role>/attendance", methods=["GET", "POST"])
def teacher_attendance(role):
    role = normalize_role(role)

    # Only teachers can use this page
    if role != "teacher":
        return redirect(url_for("dashboard", role=role))

    # Must be logged in as teacher
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1) Find teacher_id for logged-in user
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return render_template(
                "teacher_attendance.html",
                role="teacher",
                class_no="-",
                section="-",
                students=[],
                date_str=str(date.today()),
                status_map={},
                message="Teacher profile not found in DB.",
            )
        teacher_id = t["id"]

        # 2) Find assigned class/section
        cursor.execute(
            """
            SELECT class_no, section
            FROM class_teacher_assignments
            WHERE teacher_id=%s
            ORDER BY academic_year DESC, id DESC
            LIMIT 1
            """,
            (teacher_id,),
        )
        a = cursor.fetchone()
        if not a:
            return render_template(
                "teacher_attendance.html",
                role="teacher",
                class_no="-",
                section="-",
                students=[],
                date_str=str(date.today()),
                status_map={},
                message="Class teacher assignment not found.",
            )

        class_no = int(a["class_no"])
        section = a["section"]  # 'A' or 'B'
        table = class_table_name(class_no, section)

        # 3) Decide date (GET -> query param, POST -> form)
        if request.method == "POST":
            attendance_date = request.form.get("date", str(date.today()))
        else:
            attendance_date = request.args.get("date", str(date.today()))

        # 4) Fetch students for that class table
        cursor.execute(
            f"""
            SELECT c.roll, s.id AS student_id, s.name, u.phone
            FROM `{table}` c
            JOIN students s ON s.id = c.student_id
            JOIN users u ON u.id = s.user_id
            ORDER BY c.roll ASC
            """
        )
        students = cursor.fetchall()

        # 5) If already saved for this date, load status_map
        status_map = {}
        cursor.execute(
            """
            SELECT id FROM attendance_sessions
            WHERE class_no=%s AND section=%s AND attendance_date=%s
            LIMIT 1
            """,
            (class_no, section, attendance_date),
        )
        sess = cursor.fetchone()
        if sess:
            cursor.execute(
                "SELECT student_id, status FROM attendance_records WHERE session_id=%s",
                (sess["id"],),
            )
            for r in cursor.fetchall():
                status_map[r["student_id"]] = r["status"]

        # 6) POST: Save attendance
        if request.method == "POST":
            present_ids = set(request.form.getlist("present_ids"))
            # present_ids are strings; compare as strings to avoid type issues
            all_ids = [str(s["student_id"]) for s in students]

            # Upsert session (one per class/section/date)
            cursor.execute(
                """
                INSERT INTO attendance_sessions (teacher_id, class_no, section, attendance_date)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE teacher_id=VALUES(teacher_id)
                """,
                (teacher_id, class_no, section, attendance_date),
            )
            cursor.execute(
                """
                SELECT id FROM attendance_sessions
                WHERE class_no=%s AND section=%s AND attendance_date=%s
                """,
                (class_no, section, attendance_date),
            )
            session_id = cursor.fetchone()["id"]

            # Replace records (simple & clear)
            cursor.execute("DELETE FROM attendance_records WHERE session_id=%s", (session_id,))

            rows = []
            for sid in all_ids:
                status = "present" if sid in present_ids else "absent"
                rows.append((session_id, int(sid), status))

            cursor.executemany(
                "INSERT INTO attendance_records (session_id, student_id, status) VALUES (%s, %s, %s)",
                rows,
            )

            conn.commit()

            # Refresh status_map after save
            status_map = {int(sid): ("present" if sid in present_ids else "absent") for sid in all_ids}

            return render_template(
                "teacher_attendance.html",
                role="teacher",
                class_no=class_no,
                section=section,
                students=students,
                date_str=attendance_date,
                status_map=status_map,
                message="Attendance saved successfully.",
            )

        # GET: Just show page
        return render_template(
            "teacher_attendance.html",
            role="teacher",
            class_no=class_no,
            section=section,
            students=students,
            date_str=attendance_date,
            status_map=status_map,
            message=None,
        )
    finally:
        cursor.close()
        conn.close()


@app.get("/dashboard/student/attendance")
def student_attendance():
    # Only logged-in students can view this page
    if session.get("role") != "student":
        return redirect(url_for("login", role="student"))

    user_id = session.get("user_id")

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1) Find student profile
        cursor.execute("SELECT id, name FROM students WHERE user_id=%s", (user_id,))
        stu = cursor.fetchone()
        if not stu:
            return render_template(
                "student_attendance.html",
                student_name=None,
                rows=[],
                summary={"total": 0, "present": 0, "absent": 0, "percent": 0},
                from_date=None,
                to_date=None,
                message="Student profile not found in DB.",
            )

        student_id = stu["id"]
        student_name = stu["name"]

        # 2) Read filter dates (optional)
        from_date = request.args.get("from", "").strip()
        to_date = request.args.get("to", "").strip()

        # Default: last 30 days if user did not provide filters
        if not from_date and not to_date:
            from_date = str(date.today() - timedelta(days=30))
            to_date = str(date.today())

        # 3) Build query safely (parameterized)
        sql = """
            SELECT s.attendance_date, r.status
            FROM attendance_records r
            JOIN attendance_sessions s ON s.id = r.session_id
            WHERE r.student_id=%s
        """
        params = [student_id]

        if from_date:
            sql += " AND s.attendance_date >= %s"
            params.append(from_date)

        if to_date:
            sql += " AND s.attendance_date <= %s"
            params.append(to_date)

        sql += " ORDER BY s.attendance_date DESC"

        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()

        # 4) Summary (simple counting)
        total = len(rows)
        present = sum(1 for x in rows if x["status"] == "present")
        absent = total - present
        percent = int((present * 100) / total) if total > 0 else 0

        return render_template(
            "student_attendance.html",
            student_name=student_name,
            rows=rows,
            summary={"total": total, "present": present, "absent": absent, "percent": percent},
            from_date=from_date,
            to_date=to_date,
            message=None,
        )
    finally:
        cursor.close()
        conn.close()


@app.get("/dashboard/student/routine")
def student_routine():
    if session.get("role") != "student":
        return redirect(url_for("login", role="student"))

    profile = fetch_role_profile(session.get("user_id"), "student")
    if not profile or "class_no" not in profile or "section" not in profile:
        return render_template(
            "student_routine.html",
            class_no=None,
            section=None,
            days=[],
            periods=[],
            grid={},
            message="Class/section not found for this student yet.",
        )

    class_no = int(profile["class_no"])
    section = str(profile["section"]).upper()

    days = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
    periods = [1, 2, 3, 4, 5, 6]

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
              s.weekday,
              s.period_no,
              t.name AS teacher_name,
              u.phone AS teacher_phone
            FROM teacher_schedule_slots s
            JOIN teachers t ON t.id = s.teacher_id
            JOIN users u ON u.id = t.user_id
            WHERE s.class_no=%s AND s.section=%s
            ORDER BY FIELD(s.weekday,'sun','mon','tue','wed','thu','fri','sat'), s.period_no
            """,
            (class_no, section),
        )
        rows = cursor.fetchall() or []

        grid = {}
        for r in rows:
            key = f"{r['weekday']}-{int(r['period_no'])}"
            grid[key] = {"teacher_name": r.get("teacher_name") or "-", "teacher_phone": r.get("teacher_phone") or "-"}

        message = None if rows else "No routine found yet for your class/section."

        return render_template(
            "student_routine.html",
            class_no=class_no,
            section=section,
            days=days,
            periods=periods,
            grid=grid,
            message=message,
        )
    except Exception:
        app.logger.exception("student_routine failed")
        return render_template(
            "student_routine.html",
            class_no=class_no,
            section=section,
            days=[],
            periods=[],
            grid={},
            message="Could not load routine. Make sure schedule tables are initialized and schedule is imported.",
        )
    finally:
        cursor.close()
        conn.close()


@app.get("/dashboard/student/daily-class")
def student_daily_class():
    if session.get("role") != "student":
        return redirect(url_for("login", role="student"))

    selected_date_str = (request.args.get("date") or "").strip()
    try:
        selected_date_obj = parse_iso_date(selected_date_str) if selected_date_str else date.today()
    except Exception:
        selected_date_obj = date.today()
    selected_date = str(selected_date_obj)
    weekday = get_weekday_slug(selected_date_obj)

    user_id = session.get("user_id")
    if user_id is None:
        return redirect(url_for("login", role="student"))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, name FROM students WHERE user_id=%s", (int(user_id),))
        stu = cursor.fetchone()
        if not stu:
            return render_template(
                "student_daily_class.html",
                date=selected_date,
                weekday=weekday,
                student_name=None,
                class_no=None,
                section=None,
                roll=None,
                class_teacher=None,
                periods=[],
                message="Student profile not found in DB.",
            )

        student_id = int(stu["id"])
        student_name = stu["name"]

        class_info = find_student_class_section(cursor, student_id=student_id)
        if not class_info:
            return render_template(
                "student_daily_class.html",
                date=selected_date,
                weekday=weekday,
                student_name=student_name,
                class_no=None,
                section=None,
                roll=None,
                class_teacher=None,
                periods=[],
                message="Class/section not found for this student yet.",
            )

        class_no = int(class_info["class_no"])
        section = str(class_info["section"])
        roll = int(class_info["roll"])

        academic_year = get_academic_year()
        class_teacher = get_class_teacher_for(cursor, class_no=class_no, section=section, academic_year=academic_year)
        if not class_teacher:
            return render_template(
                "student_daily_class.html",
                date=selected_date,
                weekday=weekday,
                student_name=student_name,
                class_no=class_no,
                section=section,
                roll=roll,
                class_teacher=None,
                periods=[],
                message="Class teacher assignment not found for this class/year.",
            )

        try:
            schedule_map = get_schedule_teachers_for_class_day(cursor, class_no=class_no, section=section, weekday=weekday)
        except Exception:
            schedule_map = {}

        cursor.execute(
            """
            SELECT id
            FROM daily_class_days
            WHERE teacher_id=%s AND log_date=%s
            LIMIT 1
            """,
            (int(class_teacher["teacher_id"]), selected_date),
        )
        day = cursor.fetchone()

        period_map = {}
        if day:
            cursor.execute(
                """
                SELECT period_no, topic, homework, notes
                FROM daily_class_periods
                WHERE day_id=%s
                """,
                (int(day["id"]),),
            )
            for row in cursor.fetchall() or []:
                period_map[int(row["period_no"])] = row

        periods = []
        for n in range(1, 7):
            row = period_map.get(n, {})
            sch = schedule_map.get(n, {})
            periods.append(
                {
                    "period_no": n,
                    "teacher_name": sch.get("teacher_name") or "-",
                    "teacher_phone": sch.get("teacher_phone") or "-",
                    "topic": (row.get("topic") or "").strip(),
                    "homework": (row.get("homework") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                    "has_update": bool((row.get("topic") or "").strip() or (row.get("homework") or "").strip() or (row.get("notes") or "").strip()),
                }
            )

        message = None
        if not day:
            message = "No daily diary found for this date yet."
        elif not any(p["has_update"] for p in periods):
            message = "Daily diary is empty for this date."

        return render_template(
            "student_daily_class.html",
            date=selected_date,
            weekday=weekday,
            student_name=student_name,
            class_no=class_no,
            section=section,
            roll=roll,
            class_teacher=class_teacher,
            periods=periods,
            message=message,
        )
    except Exception:
        app.logger.exception("student_daily_class failed")
        return render_template(
            "error.html",
            title="Database not initialized",
            message="Please run `python manage.py init-tables` to create required tables, then refresh this page.",
            role="student",
            phone=session.get("phone"),
        ), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/dashboard/student/ai-assist", methods=["GET", "POST"])
def student_ai_assist():
    if session.get("role") != "student":
        return redirect(url_for("login", role="student"))

    answer = None
    error = None
    question = ""
    if request.method == "POST":
        question = (request.form.get("question") or "").strip()
        if question:
            try:
                answer = ask_gemini(question, student_name=session.get("phone") or "Student")
            except Exception as exc:
                error = f"Could not contact Gemini: {exc}"
        else:
            error = "Ask a question first."

    return render_template(
        "ai_assist.html",
        role="student",
        phone=session.get("phone"),
        question=question,
        answer=answer,
        error=error,
    )


@app.get("/dashboard/student/results")
def student_results():
    if session.get("role") != "student":
        return redirect(url_for("login", role="student"))

    user_id = session.get("user_id")
    if user_id is None:
        return redirect(url_for("login", role="student"))

    student_id = get_student_id_by_user_id(int(user_id))
    if not student_id:
        return render_template(
            "student_results.html",
            exams=[],
            selected_exam_id=None,
            result={"rows": [], "total": 0, "max_total": 0, "published": False},
            message="Student profile not found.",
        )

    exams = list_published_exams_for_student(student_id=student_id)

    selected_exam_id = request.args.get("exam_id", "").strip()
    exam_id_int = None
    if selected_exam_id:
        try:
            exam_id_int = int(selected_exam_id)
        except Exception:
            exam_id_int = None

    result = {"rows": [], "total": 0, "max_total": 0, "published": False}
    if exam_id_int:
        result = get_student_result(exam_id=exam_id_int, student_id=student_id)

    return render_template(
        "student_results.html",
        exams=exams,
        selected_exam_id=exam_id_int,
        result=result,
        message=request.args.get("msg"),
    )


@app.route("/dashboard/student/leaves", methods=["GET", "POST"])
def student_leaves():
    if session.get("role") != "student":
        return redirect(url_for("login", role="student"))

    user_id = session.get("user_id")
    if user_id is None:
        return redirect(url_for("login", role="student"))

    student_id = get_student_id_by_user_id(int(user_id))
    if not student_id:
        return render_template("student_leaves.html", rows=[], message="Student profile not found."), 400

    if request.method == "POST":
        from_date = request.form.get("from_date", "").strip()
        to_date = request.form.get("to_date", "").strip()
        reason = request.form.get("reason", "").strip()
        try:
            create_leave_request(student_id=student_id, from_date=from_date, to_date=to_date, reason=reason)
            return redirect(url_for("student_leaves", msg="Leave request submitted."))
        except ValueError as e:
            rows = list_student_leave_requests(student_id=student_id)
            return render_template("student_leaves.html", rows=rows, message=str(e)), 400

    rows = list_student_leave_requests(student_id=student_id)
    return render_template("student_leaves.html", rows=rows, message=request.args.get("msg"))


########################################### TEACHER PART TEACHER PART TEACHER PART ########################################
@app.route("/dashboard/teacher/daily-class", methods=["GET", "POST"])
def teacher_daily_class():
    # Only logged-in teachers can access
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    raw_date = (request.form.get("log_date") if request.method == "POST" else request.args.get("date")) or ""
    raw_date = raw_date.strip()
    gemini_output = None
    gemini_prompt = ""

    try:
        selected_date_obj = parse_iso_date(raw_date) if raw_date else date.today()
    except Exception:
        selected_date_obj = date.today()

    selected_date = str(selected_date_obj)
    weekday = get_weekday_slug(selected_date_obj)

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1) Find teacher_id from logged in user_id
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return render_template(
                "teacher_daily_class.html",
                date=selected_date,
                weekday=weekday,
                class_no="-",
                section="-",
                periods=[],
                message="Teacher profile not found in DB.",
            )

        teacher_id = t["id"]

        # 2) Find assigned class/section (latest)
        cursor.execute(
            """
            SELECT class_no, section
            FROM class_teacher_assignments
            WHERE teacher_id=%s
            ORDER BY academic_year DESC, id DESC
            LIMIT 1
            """,
            (teacher_id,),
        )
        a = cursor.fetchone()
        if not a:
            return render_template(
                "teacher_daily_class.html",
                date=selected_date,
                weekday=weekday,
                class_no="-",
                section="-",
                periods=[],
                message="Class teacher assignment not found.",
            )

        class_no = int(a["class_no"])
        section = a["section"]  # 'A' or 'B'

        try:
            schedule_map = get_schedule_teachers_for_class_day(cursor, class_no=class_no, section=section, weekday=weekday)
        except Exception:
            schedule_map = {}

        if request.method == "POST" and request.form.get("action") == "gemini_daily":
            gemini_prompt = (request.form.get("gemini_prompt") or "").strip()
            if gemini_prompt:
                try:
                    reply = ask_gemini(
                        "Create a daily class update with Topic, Homework, and Notes. "
                        "Return three lines starting with 'Topic:', 'Homework:', 'Notes:'. "
                        f"Class {class_no} section {section}. Prompt: {gemini_prompt}"
                    )
                    lines = [line.strip() for line in reply.splitlines() if line.strip()]
                    parsed = {"topic": "", "homework": "", "notes": "", "raw": reply}
                    for line in lines:
                        lower = line.lower()
                        if lower.startswith("topic"):
                            parsed["topic"] = line.split(":", 1)[-1].strip()
                        elif lower.startswith("homework"):
                            parsed["homework"] = line.split(":", 1)[-1].strip()
                        elif lower.startswith("notes"):
                            parsed["notes"] = line.split(":", 1)[-1].strip()
                    gemini_output = parsed
                except Exception as exc:
                    gemini_output = {"topic": "", "homework": "", "notes": "", "raw": f"Gemini error: {exc}"}
            else:
                gemini_output = {"topic": "", "homework": "", "notes": "", "raw": "Write a prompt first."}
        elif request.method == "POST":
            try:
                period_no = int(request.form.get("period_no", "0"))
            except Exception:
                period_no = 0
            if period_no < 1 or period_no > 6:
                return redirect(url_for("teacher_daily_class", date=selected_date))

            topic = (request.form.get("topic") or "").strip()[:255]
            homework = (request.form.get("homework") or "").strip()
            notes = (request.form.get("notes") or "").strip()

            cursor.execute(
                """
                INSERT INTO daily_class_days (teacher_id, class_no, section, log_date)
                VALUES (%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  class_no=VALUES(class_no),
                  section=VALUES(section)
                """,
                (teacher_id, class_no, section, selected_date),
            )
            cursor.execute(
                "SELECT id FROM daily_class_days WHERE teacher_id=%s AND log_date=%s LIMIT 1",
                (teacher_id, selected_date),
            )
            day_id = int(cursor.fetchone()["id"])

            cursor.execute(
                """
                INSERT INTO daily_class_periods (day_id, period_no, topic, homework, notes)
                VALUES (%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  topic=VALUES(topic),
                  homework=VALUES(homework),
                  notes=VALUES(notes)
                """,
                (day_id, period_no, topic, homework, notes),
            )

            conn.commit()
            return redirect(url_for("teacher_daily_class", date=selected_date, saved="1"))

        # 3) Find today's day container (if exists)
        cursor.execute(
            """
            SELECT id
            FROM daily_class_days
            WHERE teacher_id=%s AND log_date=%s
            LIMIT 1
            """,
            (teacher_id, selected_date),
        )
        day = cursor.fetchone()

        period_map = {}
        if day:
            day_id = day["id"]
            cursor.execute(
                """
                SELECT period_no, topic, homework, notes
                FROM daily_class_periods
                WHERE day_id=%s
                """,
                (day_id,),
            )
            for row in cursor.fetchall():
                period_map[int(row["period_no"])] = row

        # 4) Always build 1..6 periods list for UI
        periods = []
        for n in range(1, 7):
            row = period_map.get(n, {})
            sch = schedule_map.get(n, {})
            periods.append(
                {
                    "period_no": n,
                    "teacher_name": sch.get("teacher_name") or "-",
                    "teacher_phone": sch.get("teacher_phone") or "-",
                    "topic": (row.get("topic") or "").strip(),
                    "homework": (row.get("homework") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                    "has_update": bool((row.get("topic") or "").strip() or (row.get("homework") or "").strip() or (row.get("notes") or "").strip()),
                }
            )

        return render_template(
            "teacher_daily_class.html",
            date=selected_date,
            weekday=weekday,
            class_no=class_no,
            section=section,
            periods=periods,
            message="Saved." if request.args.get("saved") == "1" else None,
            gemini_output=gemini_output,
            gemini_prompt=gemini_prompt,
        )
    finally:
        cursor.close()
        conn.close()






def get_weekday_slug(d: date) -> str:
    # Python weekday(): Mon=0 ... Sun=6
    # Our DB enum: sun, mon, tue, wed, thu, fri, sat
    mapping = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    return mapping[d.weekday()]


def import_teacher_schedule_csv_to_db(csv_path: str, dry_run: bool = False) -> dict:
    allowed_weekdays = {"sun", "mon", "tue", "wed", "thu", "fri", "sat"}
    required_headers = {"teacher_phone", "weekday", "period_no", "class_no", "section"}

    report = {
        "mode": "DRY-RUN" if dry_run else "WRITE",
        "processed": 0,
        "upserted": 0,
        "would_import": 0,
        "skipped": 0,
        "duplicate_rows": 0,
        "teacher_not_found": 0,
        "skip_reasons": {
            "bad_int": 0,
            "invalid_weekday": 0,
            "invalid_section": 0,
            "invalid_period": 0,
            "invalid_class": 0,
            "teacher_not_found": 0,
            "duplicate": 0,
            "header_mismatch": 0,
        },
        "examples": {
            "bad_int": [],
            "invalid_weekday": [],
            "invalid_section": [],
            "invalid_period": [],
            "invalid_class": [],
            "teacher_not_found": [],
            "duplicate": [],
            "header_mismatch": [],
        },
    }

    def remember(reason: str, row_num: int, row_data: dict) -> None:
        if len(report["examples"][reason]) < 3:
            report["examples"][reason].append({"row": row_num, "data": row_data})

    seen_slots = set()
    teacher_cache = {}

    conn = connect_db()
    cursor = conn.cursor()

    try:
        with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            if not reader.fieldnames:
                report["skip_reasons"]["header_mismatch"] += 1
                remember("header_mismatch", 0, {"error": "No header row"})
                raise ValueError("CSV has no header row.")

            headers = set(h.strip() for h in reader.fieldnames)
            if not required_headers.issubset(headers):
                report["skip_reasons"]["header_mismatch"] += 1
                remember("header_mismatch", 0, {"headers": reader.fieldnames})
                raise ValueError("CSV header mismatch.")

            for i, row in enumerate(reader, start=1):
                report["processed"] += 1

                teacher_phone = (row.get("teacher_phone") or "").strip()
                weekday = (row.get("weekday") or "").strip().lower()
                section = (row.get("section") or "").strip().upper()

                try:
                    period_no = int((row.get("period_no") or "").strip())
                    class_no = int((row.get("class_no") or "").strip())
                except ValueError:
                    report["skip_reasons"]["bad_int"] += 1
                    remember("bad_int", i, row)
                    report["skipped"] += 1
                    continue

                if weekday not in allowed_weekdays:
                    report["skip_reasons"]["invalid_weekday"] += 1
                    remember("invalid_weekday", i, row)
                    report["skipped"] += 1
                    continue

                if section not in {"A", "B"}:
                    report["skip_reasons"]["invalid_section"] += 1
                    remember("invalid_section", i, row)
                    report["skipped"] += 1
                    continue

                if not (1 <= period_no <= 6):
                    report["skip_reasons"]["invalid_period"] += 1
                    remember("invalid_period", i, row)
                    report["skipped"] += 1
                    continue

                if not (1 <= class_no <= 10):
                    report["skip_reasons"]["invalid_class"] += 1
                    remember("invalid_class", i, row)
                    report["skipped"] += 1
                    continue

                slot_key = (teacher_phone, weekday, period_no)
                if slot_key in seen_slots:
                    report["skip_reasons"]["duplicate"] += 1
                    remember("duplicate", i, row)
                    report["duplicate_rows"] += 1
                    report["skipped"] += 1
                    continue
                seen_slots.add(slot_key)

                # teacher_id lookup (cached)
                if teacher_phone in teacher_cache:
                    teacher_id = teacher_cache[teacher_phone]
                else:
                    cursor.execute(
                        """
                        SELECT te.id
                        FROM teachers te
                        JOIN users u ON u.id = te.user_id
                        WHERE u.phone=%s
                        LIMIT 1
                        """,
                        (teacher_phone,),
                    )
                    t = cursor.fetchone()
                    teacher_id = t[0] if t else None
                    teacher_cache[teacher_phone] = teacher_id

                if not teacher_id:
                    report["skip_reasons"]["teacher_not_found"] += 1
                    remember("teacher_not_found", i, row)
                    report["teacher_not_found"] += 1
                    report["skipped"] += 1
                    continue

                if dry_run:
                    report["would_import"] += 1
                else:
                    cursor.execute(
                        """
                        INSERT INTO teacher_schedule_slots (teacher_id, weekday, period_no, class_no, section)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          class_no=VALUES(class_no),
                          section=VALUES(section)
                        """,
                        (teacher_id, weekday, period_no, class_no, section),
                    )
                    report["upserted"] += 1

        if not dry_run:
            conn.commit()

        return report

    finally:
        cursor.close()
        conn.close()

def get_schedule_stats() -> dict:
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute("SELECT COUNT(*) AS total_slots FROM teacher_schedule_slots")
        total_slots = int(cursor.fetchone()["total_slots"])

        cursor.execute(
            """
            SELECT COUNT(DISTINCT teacher_id) AS teacher_count
            FROM teacher_schedule_slots
            """
        )
        teacher_count = int(cursor.fetchone()["teacher_count"])

        cursor.execute(
            """
            SELECT weekday, COUNT(*) AS cnt
            FROM teacher_schedule_slots
            GROUP BY weekday
            ORDER BY FIELD(weekday,'sun','mon','tue','wed','thu','fri','sat')
            """
        )
        by_weekday_rows = cursor.fetchall()

        by_weekday = {r["weekday"]: int(r["cnt"]) for r in by_weekday_rows}
        today = str(date.today())

        cursor.execute(
            "SELECT COUNT(*) AS total_today_logs FROM teacher_lesson_logs WHERE log_date=%s",
            (today,),
        )
        total_today_logs = int(cursor.fetchone()["total_today_logs"])

        cursor.execute(
            "SELECT COUNT(*) AS done_today_logs FROM teacher_lesson_logs WHERE log_date=%s AND is_done=1",
            (today,),
        )
        done_today_logs = int(cursor.fetchone()["done_today_logs"])

        cursor.execute(
            "SELECT COUNT(DISTINCT teacher_id) AS teachers_updated_today FROM teacher_lesson_logs WHERE log_date=%s",
            (today,),
        )
        teachers_updated_today = int(cursor.fetchone()["teachers_updated_today"])

        return {
            "total_slots": total_slots,
            "teacher_count": teacher_count,
            "by_weekday": by_weekday,
            "total_today_logs": total_today_logs,
            "done_today_logs": done_today_logs,
            "teachers_updated_today": teachers_updated_today,

        }
    finally:
        cursor.close()
        conn.close()


@app.route("/dashboard/teacher/today-schedule", methods=["GET", "POST"])
def teacher_today_schedule():
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    today_obj = date.today()
    today = str(today_obj)
    weekday = get_weekday_slug(today_obj)

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1) teacher_id find
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return render_template(
                "teacher_today_schedule.html",
                today=today,
                weekday=weekday,
                periods=[],
                message="Teacher profile not found in DB.",
            )
        teacher_id = t["id"]

        # 2) On POST: save one period update
        if request.method == "POST":
            period_no = int(request.form.get("period_no", "0"))
            topic = request.form.get("topic", "").strip()
            homework = request.form.get("homework", "").strip()
            notes = request.form.get("notes", "").strip()
            is_done = 1 if request.form.get("is_done") == "on" else 0
            done_at = datetime.now() if is_done == 1 else None

            # Validate period range
            if period_no < 1 or period_no > 6:
                return redirect(url_for("teacher_today_schedule"))

            # Find scheduled class for this teacher+weekday+period
            cursor.execute(
                """
                SELECT class_no, section
                FROM teacher_schedule_slots
                WHERE teacher_id=%s AND weekday=%s AND period_no=%s
                LIMIT 1
                """,
                (teacher_id, weekday, period_no),
            )
            slot = cursor.fetchone()
            if not slot:
                return redirect(url_for("teacher_today_schedule"))

            class_no = int(slot["class_no"])
            section = slot["section"]

            # Upsert log row (unique: teacher_id + log_date + period_no)
            cursor.execute(
                """
                INSERT INTO teacher_lesson_logs
                (teacher_id, log_date, period_no, class_no, section, topic, homework, notes, is_done, done_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  class_no=VALUES(class_no),
                  section=VALUES(section),
                  topic=VALUES(topic),
                  homework=VALUES(homework),
                  notes=VALUES(notes),
                  is_done=VALUES(is_done),
                  done_at=VALUES(done_at)
                """,
                (teacher_id, today, period_no, class_no, section, topic, homework, notes, is_done, done_at),
            )

            conn.commit()
            return redirect(url_for("teacher_today_schedule", saved="1"))

        # 3) GET: load schedule slots
        cursor.execute(
            """
            SELECT period_no, class_no, section
            FROM teacher_schedule_slots
            WHERE teacher_id=%s AND weekday=%s
            ORDER BY period_no ASC
            """,
            (teacher_id, weekday),
        )
        slots = cursor.fetchall()

        slot_map = {}
        for s in slots:
            slot_map[int(s["period_no"])] = {"class_no": s["class_no"], "section": s["section"]}

        # 4) GET: load today logs (if any)
        cursor.execute(
            """
            SELECT period_no, topic, homework, notes, is_done
            FROM teacher_lesson_logs
            WHERE teacher_id=%s AND log_date=%s
            """,
            (teacher_id, today),
        )
        logs = cursor.fetchall()

        log_map = {}
        for r in logs:
            log_map[int(r["period_no"])] = {
                "topic": r.get("topic") or "",
                "homework": r.get("homework") or "",
                "notes": r.get("notes") or "",
                "is_done": int(r.get("is_done") or 0),
            }

        # 5) Build fixed 1..6 list for UI
        periods = []
        for n in range(1, 7):
            slot = slot_map.get(n, {})
            log = log_map.get(n, {})

            periods.append(
                {
                    "period_no": n,
                    "class_no": slot.get("class_no", "-"),
                    "section": slot.get("section", "-"),
                    "topic": log.get("topic", ""),
                    "homework": log.get("homework", ""),
                    "notes": log.get("notes", ""),
                    "is_done": log.get("is_done", 0),
                }
            )

        message = None
        if request.args.get("saved") == "1":
            message = "Saved."
        elif not slots:
            message = "No schedule found for today. (Add schedule slots first.)"

        return render_template(
            "teacher_today_schedule.html",
            today=today,
            weekday=weekday,
            periods=periods,
            message=message,
        )
    finally:
        cursor.close()
        conn.close()





@app.get("/dashboard/teacher/weekly-schedule")
def teacher_weekly_schedule():
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1) Find teacher_id from logged-in user_id
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return render_template(
                "teacher_weekly_schedule.html",
                days=[],
                periods=[],
                grid={},
                message="Teacher profile not found in DB.",
            )
        teacher_id = t["id"]

        # 2) Load weekly slots for this teacher
        cursor.execute(
            """
            SELECT weekday, period_no, class_no, section
            FROM teacher_schedule_slots
            WHERE teacher_id=%s
            ORDER BY FIELD(weekday,'sun','mon','tue','wed','thu','fri','sat'), period_no
            """,
            (teacher_id,),
        )
        slots = cursor.fetchall()

        # 3) Build grid: key = "sun-1" -> value = "Class 3-A"
        grid = {}
        for s in slots:
            key = f"{s['weekday']}-{int(s['period_no'])}"
            grid[key] = f"Class {int(s['class_no'])}-{s['section']}"

        days = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
        periods = [1, 2, 3, 4, 5, 6]

        msg = None
        if not slots:
            msg = "No weekly schedule found for this teacher. (Import schedule first.)"

        return render_template(
            "teacher_weekly_schedule.html",
            days=days,
            periods=periods,
            grid=grid,
            message=msg,
        )
    finally:
        cursor.close()
        conn.close()



########################################### HEAD TEACHER PART - HEAD TEACHER PART - HEAD TEACHER PART - HEAD TEACHER PART ########################################

@app.get("/dashboard/head/approvals")
def head_approvals():
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    selected_status = (request.args.get("status") or "pending").strip().lower()
    if selected_status not in {"pending", "approved", "rejected", "all"}:
        selected_status = "pending"

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = """
          SELECT
            lr.id,
            lr.student_id,
            s.name AS student_name,
            u.phone AS student_phone,
            lr.from_date,
            lr.to_date,
            lr.reason,
            lr.status
          FROM leave_requests lr
          JOIN students s ON s.id = lr.student_id
          JOIN users u ON u.id = s.user_id
          WHERE 1=1
        """
        params = []
        if selected_status != "all":
            sql += " AND lr.status=%s"
            params.append(selected_status)
        sql += " ORDER BY lr.created_at DESC, lr.id DESC LIMIT 500"

        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall() or []

        def find_class_label(student_id: int) -> str:
            for class_no in range(1, 11):
                for section_letter, section_code in (("A", "01"), ("B", "02")):
                    table = f"class_{class_no:02d}_section_{section_code}"
                    try:
                        cursor.execute(f"SELECT 1 FROM `{table}` WHERE student_id=%s LIMIT 1", (student_id,))
                        if cursor.fetchone():
                            return f"{class_no}-{section_letter}"
                    except Exception:
                        continue
            return "-"

        for r in rows:
            r["class_label"] = find_class_label(int(r["student_id"]))

        return render_template(
            "head_approvals.html",
            rows=rows,
            selected_status=selected_status,
            message=request.args.get("msg"),
        )
    except Exception:
        app.logger.exception("head_approvals failed")
        return render_template(
            "error.html",
            title="Database not initialized",
            message="Please run `python manage.py init-tables` to create required tables, then refresh this page.",
            role="head",
            phone=session.get("phone"),
        ), 500
    finally:
        cursor.close()
        conn.close()


@app.post("/dashboard/head/approvals/decide")
def head_approvals_decide():
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    leave_id = int(request.form.get("leave_id", "0") or "0")
    status = (request.form.get("status") or "").strip()
    try:
        decide_leave_request(leave_id=leave_id, status=status, decided_by_user_id=int(session.get("user_id")))
        return redirect(url_for("head_approvals", msg="Decision saved."))
    except ValueError as e:
        return redirect(url_for("head_approvals", msg=str(e)))


@app.get("/dashboard/head/results")
def head_results():
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    academic_year = get_academic_year()
    exams = list_exams(academic_year=academic_year)

    selected_exam_id = request.args.get("exam_id", "").strip()
    exam_id_int = None
    if selected_exam_id:
        try:
            exam_id_int = int(selected_exam_id)
        except Exception:
            exam_id_int = None

    pub_map = {}
    if exam_id_int:
        conn = connect_db()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT class_no, section, is_published FROM exam_publications WHERE exam_id=%s",
                (exam_id_int,),
            )
            for r in cursor.fetchall() or []:
                pub_map[(int(r["class_no"]), str(r["section"]))] = int(r.get("is_published") or 0) == 1
        except Exception:
            pub_map = {}
        finally:
            cursor.close()
            conn.close()

    classes = []
    for class_no in range(1, 11):
        for sec in ("A", "B"):
            classes.append(
                {
                    "class_no": class_no,
                    "section": sec,
                    "is_published": bool(pub_map.get((class_no, sec), False)),
                }
            )

    return render_template(
        "head_results.html",
        exams=exams,
        selected_exam_id=exam_id_int,
        classes=classes,
        message=request.args.get("msg"),
    )


@app.route("/dashboard/head/reports", methods=["GET", "POST"])
def head_reports():
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    today = str(date.today())
    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    gemini_output = None
    gemini_prompt = ""
    try:
        cursor.execute("SELECT COUNT(*) AS c FROM teacher_lesson_logs WHERE log_date=%s", (today,))
        today_logs_total = int((cursor.fetchone() or {}).get("c") or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM teacher_lesson_logs WHERE log_date=%s AND is_done=1", (today,))
        today_logs_done = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute("SELECT COUNT(*) AS c FROM attendance_sessions")
        attendance_sessions_total = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute("SELECT COUNT(*) AS c FROM leave_requests WHERE status='pending'")
        leaves_pending = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute("SELECT COUNT(*) AS c FROM exams")
        exams_total = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute("SELECT COUNT(*) AS c FROM exam_publications WHERE is_published=1")
        publications_published = int((cursor.fetchone() or {}).get("c") or 0)

        if request.method == "POST":
            gemini_prompt = (request.form.get("gemini_prompt") or "").strip()
            if gemini_prompt:
                try:
                    summary_context = (
                        f"Today logs total: {today_logs_total}, done: {today_logs_done}. "
                        f"Attendance sessions: {attendance_sessions_total}. "
                        f"Pending leaves: {leaves_pending}. Exams: {exams_total}. "
                        f"Published results: {publications_published}."
                    )
                    gemini_output = ask_gemini(
                        "You are advising a head teacher. Provide 2-4 short, actionable bullet points. "
                        f"Context: {summary_context}\nQuestion: {gemini_prompt}"
                    )
                except Exception as exc:
                    gemini_output = f"Gemini error: {exc}"
            else:
                gemini_output = "Write a short prompt first."

        return render_template(
            "head_reports.html",
            stats={
                "today_logs_total": today_logs_total,
                "today_logs_done": today_logs_done,
                "attendance_sessions_total": attendance_sessions_total,
                "leaves_pending": leaves_pending,
                "exams_total": exams_total,
                "publications_published": publications_published,
            },
            message=request.args.get("msg"),
            gemini_prompt=gemini_prompt,
            gemini_output=gemini_output,
        )
    except Exception:
        app.logger.exception("head_reports failed")
        return render_template(
            "error.html",
            title="Database not initialized",
            message="Please run `python manage.py init-tables` to create required tables, then refresh this page.",
            role="head",
            phone=session.get("phone"),
        ), 500
    finally:
        cursor.close()
        conn.close()


@app.get("/dashboard/head/daily-class")
def head_daily_class():
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    selected_date_str = (request.args.get("date") or "").strip()
    try:
        selected_date_obj = parse_iso_date(selected_date_str) if selected_date_str else date.today()
    except Exception:
        selected_date_obj = date.today()
    selected_date = str(selected_date_obj)
    weekday = get_weekday_slug(selected_date_obj)

    class_no_raw = (request.args.get("class_no") or "").strip()
    section = (request.args.get("section") or "").strip().upper()

    class_no_int = None
    if class_no_raw:
        try:
            class_no_int = int(class_no_raw)
        except Exception:
            class_no_int = None

    # Render empty state with filter UI
    if class_no_int is None or class_no_int < 1 or class_no_int > 10 or section not in {"A", "B"}:
        return render_template(
            "head_daily_class.html",
            date=selected_date,
            weekday=weekday,
            selected={"class_no": class_no_raw, "section": section},
            class_teacher=None,
            periods=[],
            message="Select a class and section to view the daily diary.",
        )

    academic_year = get_academic_year()

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        class_teacher = get_class_teacher_for(cursor, class_no=class_no_int, section=section, academic_year=academic_year)

        try:
            schedule_map = get_schedule_teachers_for_class_day(cursor, class_no=class_no_int, section=section, weekday=weekday)
        except Exception:
            schedule_map = {}

        period_map = {}
        if class_teacher:
            cursor.execute(
                """
                SELECT id
                FROM daily_class_days
                WHERE teacher_id=%s AND log_date=%s
                LIMIT 1
                """,
                (int(class_teacher["teacher_id"]), selected_date),
            )
            day = cursor.fetchone()
            if day:
                cursor.execute(
                    """
                    SELECT period_no, topic, homework, notes
                    FROM daily_class_periods
                    WHERE day_id=%s
                    """,
                    (int(day["id"]),),
                )
                for row in cursor.fetchall() or []:
                    period_map[int(row["period_no"])] = row

        periods = []
        for n in range(1, 7):
            row = period_map.get(n, {})
            sch = schedule_map.get(n, {})
            periods.append(
                {
                    "period_no": n,
                    "teacher_name": sch.get("teacher_name") or "-",
                    "teacher_phone": sch.get("teacher_phone") or "-",
                    "topic": (row.get("topic") or "").strip(),
                    "homework": (row.get("homework") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                    "has_update": bool((row.get("topic") or "").strip() or (row.get("homework") or "").strip() or (row.get("notes") or "").strip()),
                }
            )

        message = None
        if not class_teacher:
            message = "Class teacher assignment not found for this class/year."
        elif not any(p["has_update"] for p in periods):
            message = "No diary updates found for this date yet."

        return render_template(
            "head_daily_class.html",
            date=selected_date,
            weekday=weekday,
            selected={"class_no": str(class_no_int), "section": section},
            class_teacher=class_teacher,
            periods=periods,
            message=message,
        )
    except Exception:
        app.logger.exception("head_daily_class failed")
        return render_template(
            "error.html",
            title="Database not initialized",
            message="Please run `python manage.py init-tables` to create required tables, then refresh this page.",
            role="head",
            phone=session.get("phone"),
        ), 500
    finally:
        cursor.close()
        conn.close()


@app.post("/dashboard/head/results/exams")
def head_results_exam_create():
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    academic_year = get_academic_year()
    name = request.form.get("name", "")
    try:
        exam_id = create_exam(academic_year=academic_year, name=name)
        return redirect(url_for("head_results", exam_id=exam_id, msg="Exam created."))
    except ValueError as e:
        return redirect(url_for("head_results", msg=str(e)))


@app.post("/dashboard/head/results/publish")
def head_results_publish():
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    exam_id = int(request.form.get("exam_id", "0") or "0")
    class_no = int(request.form.get("class_no", "0") or "0")
    section = (request.form.get("section") or "").strip()
    is_published = (request.form.get("is_published") or "0").strip() == "1"

    try:
        set_publication(
            exam_id=exam_id,
            class_no=class_no,
            section=section,
            is_published=is_published,
            published_by_user_id=int(session.get("user_id")),
        )
        return redirect(url_for("head_results", exam_id=exam_id, msg="Publication updated."))
    except ValueError as e:
        return redirect(url_for("head_results", exam_id=exam_id, msg=str(e)))


@app.get("/dashboard/head/teachers")
def head_teachers():
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
              t.id AS teacher_id,
              t.name AS teacher_name,
              t.teacher_code,
              u.phone AS teacher_phone,
              a.class_no,
              a.section,
              a.academic_year,
              (SELECT COUNT(*) FROM teacher_schedule_slots s WHERE s.teacher_id = t.id) AS schedule_slots
            FROM teachers t
            JOIN users u ON u.id = t.user_id
            LEFT JOIN (
              SELECT c1.teacher_id, c1.class_no, c1.section, c1.academic_year
              FROM class_teacher_assignments c1
              WHERE c1.id = (
                SELECT MAX(c2.id) FROM class_teacher_assignments c2 WHERE c2.teacher_id = c1.teacher_id
              )
            ) a ON a.teacher_id = t.id
            ORDER BY t.name ASC
            """
        )
        rows = cursor.fetchall() or []
        return render_template("head_teachers.html", rows=rows, message=request.args.get("msg"))
    except Exception:
        app.logger.exception("head_teachers failed")
        return render_template(
            "error.html",
            title="Database not initialized",
            message="Please run `python manage.py init-tables` to create required tables, then refresh this page.",
            role="head",
            phone=session.get("phone"),
        ), 500
    finally:
        cursor.close()
        conn.close()


@app.get("/dashboard/head/today-overview")
def head_today_overview():
    # Only logged-in head can access
    if session.get("role") != "head":
        return redirect(url_for("login", role="head"))

    today_obj = date.today()
    today = str(today_obj)
    weekday = get_weekday_slug(today_obj)

    # Read filters from URL query params (strings)
    selected_teacher_id = request.args.get("teacher_id", "").strip()
    selected_class_no = request.args.get("class_no", "").strip()
    selected_section = request.args.get("section", "").strip()
    selected_status = request.args.get("status", "pending").strip()  # default pending

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # Load today's schedule slots + today's logs (if any)
        cursor.execute(
            """
            SELECT
              te.name AS teacher_name,
              u.phone AS teacher_phone,
              s.teacher_id,
              s.period_no,
              s.class_no,
              s.section,
              COALESCE(l.topic, '') AS topic,
              COALESCE(l.is_done, 0) AS is_done
            FROM teacher_schedule_slots s
            JOIN teachers te ON te.id = s.teacher_id
            JOIN users u ON u.id = te.user_id
            LEFT JOIN teacher_lesson_logs l
              ON l.teacher_id = s.teacher_id
             AND l.log_date = %s
             AND l.period_no = s.period_no
            WHERE s.weekday = %s
            ORDER BY te.name ASC, s.period_no ASC
            """,
            (today, weekday),
        )
        data = cursor.fetchall()

        # Build dropdown options (unique lists) from today's data
        teacher_options = {}
        class_options = {}

        for r in data:
            tid_int = int(r["teacher_id"])
            teacher_options[tid_int] = f'{r["teacher_name"]} ({r["teacher_phone"]})'

            key = (int(r["class_no"]), str(r["section"]))
            class_options[key] = f"Class {key[0]} - {key[1]}"

        # Teacher-wise summary:
        # Apply class/section filters, BUT ignore teacher/status filter
        # so head can still see overall progress for that class/section.
        teacher_summary_map = {}

        for r in data:
            cno = str(int(r["class_no"]))
            sec = str(r["section"])

            if selected_class_no and cno != selected_class_no:
                continue
            if selected_section and sec != selected_section:
                continue

            tid = int(r["teacher_id"])
            if tid not in teacher_summary_map:
                teacher_summary_map[tid] = {
                    "teacher_name": r["teacher_name"],
                    "teacher_phone": r["teacher_phone"],
                    "total": 0,
                    "done": 0,
                }

            teacher_summary_map[tid]["total"] += 1
            if int(r["is_done"]) == 1:
                teacher_summary_map[tid]["done"] += 1

        teacher_summary = []
        for tid, info in teacher_summary_map.items():
            total = info["total"]
            done = info["done"]
            pending = total - done
            percent = int((done * 100) / total) if total > 0 else 0

            teacher_summary.append(
                {
                    "teacher_id": tid,
                    "teacher_name": info["teacher_name"],
                    "teacher_phone": info["teacher_phone"],
                    "total": total,
                    "done": done,
                    "pending": pending,
                    "percent": percent,
                }
            )

        teacher_summary.sort(key=lambda x: (x["pending"], x["teacher_name"]), reverse=True)
        # Class-wise summary (respects teacher/class/section filters, ignores status filter)
        class_summary_map = {}

        for r in data:
            tid = str(int(r["teacher_id"]))
            cno = str(int(r["class_no"]))
            sec = str(r["section"])
            is_done = int(r["is_done"]) == 1

            # apply teacher/class/section filters (but NOT status)
            if selected_teacher_id and tid != selected_teacher_id:
                continue
            if selected_class_no and cno != selected_class_no:
                continue
            if selected_section and sec != selected_section:
                continue

            key = (int(r["class_no"]), sec)

            if key not in class_summary_map:
                class_summary_map[key] = {"total": 0, "done": 0}

            class_summary_map[key]["total"] += 1
            if is_done:
                class_summary_map[key]["done"] += 1

        class_summary = []
        for (class_no, sec), info in class_summary_map.items():
            total = info["total"]
            done = info["done"]
            pending = total - done
            percent = int((done * 100) / total) if total > 0 else 0

            class_summary.append(
                {
                    "class_no": class_no,
                    "section": sec,
                    "total": total,
                    "done": done,
                    "pending": pending,
                    "percent": percent,
                }
            )

        class_summary.sort(key=lambda x: (x["pending"], x["class_no"], x["section"]), reverse=True)
        
        # Apply ALL filters for main table (teacher/class/section/status)
        filtered = []
        for r in data:
            tid = str(int(r["teacher_id"]))
            cno = str(int(r["class_no"]))
            sec = str(r["section"])
            is_done = int(r["is_done"]) == 1

            if selected_teacher_id and tid != selected_teacher_id:
                continue
            if selected_class_no and cno != selected_class_no:
                continue
            if selected_section and sec != selected_section:
                continue
            if selected_status == "done" and not is_done:
                continue
            if selected_status == "pending" and is_done:
                continue

            filtered.append(r)

        # Summary for current filtered view (same as table)
        total_count = len(filtered)
        done_count = sum(1 for r in filtered if int(r["is_done"]) == 1)
        pending_count = total_count - done_count
        done_percent = int((done_count * 100) / total_count) if total_count > 0 else 0

        summary = {
            "total": total_count,
            "done": done_count,
            "pending": pending_count,
            "percent": done_percent,
        }

        # Build rows for template (IMPORTANT: use filtered, not data)
        rows = []
        for r in filtered:
            rows.append(
                {
                    "teacher_name": r["teacher_name"],
                    "teacher_phone": r["teacher_phone"],
                    "teacher_id": int(r["teacher_id"]),
                    "period_no": r["period_no"],
                    "class_no": r["class_no"],
                    "section": r["section"],
                    "status": "DONE" if int(r["is_done"]) == 1 else "PENDING",
                    "topic": r["topic"],
                    
                }
            )

        # Message logic
        message = None
        if not data:
            message = "No schedule found for today."
        elif not rows:
            message = "No results for current filters."

        return render_template(
            "head_today_overview.html",
            today=today,
            weekday=weekday,
            rows=rows,
            message=message,
            teacher_options=teacher_options,
            class_options=class_options,
            selected_teacher_id=selected_teacher_id,
            selected_class_no=selected_class_no,
            selected_section=selected_section,
            selected_status=selected_status,
            summary=summary,
            teacher_summary=teacher_summary,
            class_summary=class_summary,
        )
    finally:
        cursor.close()
        conn.close()



################################################ ADMIN PART ADMIN PART ADMIN PART ADMIN PART #############################################
@app.get("/dashboard/admin/timetable")
def admin_timetable():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    class_no_raw = (request.args.get("class_no") or "1").strip()
    section = (request.args.get("section") or "A").strip().upper()
    try:
        class_no = int(class_no_raw)
    except Exception:
        class_no = 1

    if class_no < 1 or class_no > 10:
        class_no = 1
    if section not in {"A", "B"}:
        section = "A"

    days = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
    periods = [1, 2, 3, 4, 5, 6]

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
              s.weekday,
              s.period_no,
              t.name AS teacher_name,
              u.phone AS teacher_phone
            FROM teacher_schedule_slots s
            JOIN teachers t ON t.id = s.teacher_id
            JOIN users u ON u.id = t.user_id
            WHERE s.class_no=%s AND s.section=%s
            ORDER BY FIELD(s.weekday,'sun','mon','tue','wed','thu','fri','sat'), s.period_no
            """,
            (class_no, section),
        )
        rows = cursor.fetchall() or []

        grid = {}
        for r in rows:
            key = f"{r['weekday']}-{int(r['period_no'])}"
            grid[key] = {"teacher_name": r.get("teacher_name") or "-", "teacher_phone": r.get("teacher_phone") or "-"}

        message = None if rows else "No timetable found. Upload/import schedule first."

        return render_template(
            "admin_timetable.html",
            selected={"class_no": class_no, "section": section},
            days=days,
            periods=periods,
            grid=grid,
            message=message,
        )
    except Exception:
        app.logger.exception("admin_timetable failed")
        return render_template(
            "error.html",
            title="Database not initialized",
            message="Please run `python manage.py init-tables` and import schedule, then refresh this page.",
            role="admin",
            phone=session.get("phone"),
        ), 500
    finally:
        cursor.close()
        conn.close()


@app.get("/dashboard/admin/reports")
def admin_reports():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT COUNT(*) AS c FROM users")
        users_total = int((cursor.fetchone() or {}).get("c") or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM students")
        students_total = int((cursor.fetchone() or {}).get("c") or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM teachers")
        teachers_total = int((cursor.fetchone() or {}).get("c") or 0)

        cursor.execute("SELECT COUNT(*) AS c FROM notices")
        notices_total = int((cursor.fetchone() or {}).get("c") or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM fee_payments")
        payments_total = int((cursor.fetchone() or {}).get("c") or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM leave_requests WHERE status='pending'")
        leaves_pending = int((cursor.fetchone() or {}).get("c") or 0)

        return render_template(
            "admin_reports.html",
            stats={
                "users_total": users_total,
                "students_total": students_total,
                "teachers_total": teachers_total,
                "notices_total": notices_total,
                "payments_total": payments_total,
                "leaves_pending": leaves_pending,
            },
            message=request.args.get("msg"),
        )
    except Exception:
        app.logger.exception("admin_reports failed")
        return render_template(
            "error.html",
            title="Database not initialized",
            message="Please run `python manage.py init-tables` to create required tables, then refresh this page.",
            role="admin",
            phone=session.get("phone"),
        ), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/dashboard/admin/settings", methods=["GET", "POST"])
def admin_settings():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    settings = {"school_name": None, "academic_year": None}

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        if request.method == "POST":
            school_name = (request.form.get("school_name") or "").strip()
            academic_year = (request.form.get("academic_year") or "").strip()

            if school_name:
                cursor.execute(
                    """
                    INSERT INTO school_settings (`key`, `value`) VALUES ('SCHOOL_NAME', %s)
                    ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)
                    """,
                    (school_name[:120],),
                )
            else:
                cursor.execute("DELETE FROM school_settings WHERE `key`='SCHOOL_NAME'")

            if academic_year:
                try:
                    int(academic_year)
                except ValueError:
                    return render_template(
                        "admin_settings.html",
                        settings=settings,
                        message="Academic year must be a number.",
                    )
                cursor.execute(
                    """
                    INSERT INTO school_settings (`key`, `value`) VALUES ('ACADEMIC_YEAR', %s)
                    ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)
                    """,
                    (academic_year,),
                )
            else:
                cursor.execute("DELETE FROM school_settings WHERE `key`='ACADEMIC_YEAR'")

            conn.commit()
            message = "Settings saved."
        else:
            message = request.args.get("msg")

        cursor.execute("SELECT `key`, `value` FROM school_settings WHERE `key` IN ('SCHOOL_NAME','ACADEMIC_YEAR')")
        for r in cursor.fetchall() or []:
            if r["key"] == "SCHOOL_NAME":
                settings["school_name"] = r["value"]
            if r["key"] == "ACADEMIC_YEAR":
                settings["academic_year"] = r["value"]

        return render_template("admin_settings.html", settings=settings, message=message)
    except Exception:
        app.logger.exception("admin_settings failed")
        return render_template(
            "error.html",
            title="Database not initialized",
            message="Please run `python manage.py init-tables` to create required tables, then refresh this page.",
            role="admin",
            phone=session.get("phone"),
        ), 500
    finally:
        cursor.close()
        conn.close()


@app.get("/dashboard/admin/users")
def admin_users():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    role = (request.args.get("role") or "").strip()
    active = (request.args.get("active") or "").strip()
    phone = (request.args.get("phone") or "").strip()

    sql = "SELECT id, phone, role, is_active, DATE_FORMAT(created_at, '%Y-%m-%d %H:%i') AS created_at FROM users WHERE 1=1"
    params = []

    if role in {"student", "teacher", "head", "admin"}:
        sql += " AND role=%s"
        params.append(role)
    if active in {"0", "1"}:
        sql += " AND is_active=%s"
        params.append(int(active))
    if phone:
        sql += " AND phone LIKE %s"
        params.append(f"%{phone}%")

    sql += " ORDER BY created_at DESC, id DESC LIMIT 500"

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall() or []
        return render_template(
            "admin_users.html",
            rows=rows,
            filters={"role": role, "active": active, "phone": phone},
            session_user_id=int(session.get("user_id") or 0),
            message=request.args.get("msg"),
        )
    finally:
        cursor.close()
        conn.close()


@app.post("/dashboard/admin/users/<int:user_id>/toggle")
def admin_user_toggle(user_id: int):
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    me = int(session.get("user_id") or 0)
    if user_id == me:
        return redirect(url_for("admin_users", msg="You cannot change your own account status."))

    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET is_active = 1 - is_active WHERE id=%s", (int(user_id),))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    redirect_to = request.form.get("redirect") or url_for("admin_users")
    if "msg=" in redirect_to:
        return redirect(redirect_to)
    sep = "&" if "?" in redirect_to else "?"
    return redirect(f"{redirect_to}{sep}msg=User status updated.")


@app.route("/dashboard/admin/schedule-upload", methods=["GET", "POST"])
def admin_schedule_upload():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    report = None
    message = None
    # If redirected with a message (e.g., after clearing schedule)
    if request.method == "GET" and not message:
        message = request.args.get("msg")

    if request.method == "POST":
        f = request.files.get("csv_file")
        dry_run = True if request.form.get("dry_run") == "on" else False

        if not f or not f.filename:
            message = "No file selected."
            return render_template("admin_schedule_upload.html", report=None, message=message)

        if not f.filename.lower().endswith(".csv"):
            message = "Only .csv files are allowed."
            return render_template("admin_schedule_upload.html", report=None, message=message)

        os.makedirs(os.path.join("Database", "uploads"), exist_ok=True)
        filename = secure_filename(f.filename)
        save_path = os.path.join("Database", "uploads", filename)
        f.save(save_path)

        try:
            report = import_teacher_schedule_csv_to_db(save_path, dry_run=dry_run)
            message = "Import completed."
        except Exception as e:
            message = f"Import failed: {e}"

    stats = get_schedule_stats()
    return render_template("admin_schedule_upload.html", report=report, message=message, stats=stats)


@app.get("/dashboard/admin/schedule-sample.csv")
def admin_schedule_sample_csv():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    output = io.StringIO()
    writer = csv.writer(output)

    # Header (must match importer)
    writer.writerow(["teacher_phone", "weekday", "period_no", "class_no", "section"])

    # Sample rows (replace teacher_phone with real teacher phone from your DB)
    writer.writerow(["01664967554", "sun", "1", "3", "A"])
    writer.writerow(["01664967554", "sun", "2", "3", "A"])

    csv_text = output.getvalue()
    output.close()

    resp = make_response(csv_text)
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=teacher_schedule_sample.csv"
    return resp

@app.post("/dashboard/admin/schedule-clear")
def admin_schedule_clear():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    confirm = request.form.get("confirm") == "on"
    confirm_text = (request.form.get("confirm_text") or "").strip().upper()

    # Strong safety check
    if (not confirm) or (confirm_text != "DELETE"):
        return redirect(url_for("admin_schedule_upload", msg="Not cleared. Please check confirm and type DELETE."))

    conn = connect_db()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM teacher_schedule_slots")
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("admin_schedule_upload", msg="All teacher schedule slots cleared."))


@app.post("/dashboard/admin/today-logs-clear")
def admin_today_logs_clear():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    confirm = request.form.get("confirm") == "on"
    confirm_text = (request.form.get("confirm_text") or "").strip().upper()

    if (not confirm) or (confirm_text != "CLEAR TODAY"):
        return redirect(url_for("admin_schedule_upload", msg="Not cleared. Please check confirm and type CLEAR TODAY."))

    today = str(date.today())

    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM teacher_lesson_logs WHERE log_date=%s", (today,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("admin_schedule_upload", msg="Today's teacher lesson logs cleared."))


@app.get("/dashboard/admin/fees_setup")
def admin_fees_setup():
  if session.get("role") != "admin":
    return redirect(url_for("login", role="admin"))
  return render_template("fees_setup.html", role="admin", phone=session.get("phone"), academic_year=get_academic_year())

@app.post("/dashboard/admin/fees_setup")
def admin_fees_setup_post():
  if session.get("role") != "admin":
    return redirect(url_for("login", role="admin"))

  try:
    action = (request.form.get("action") or "single").strip().lower()
    class_no = int(request.form.get("class_no", "0"))
    section = request.form.get("section", "A").strip()
    academic_year = int(request.form.get("academic_year", str(get_academic_year())))
    amount = int(request.form.get("amount", "0"))

    if action == "yearly":
      start_month = int(request.form.get("start_month", "1"))
      end_month = int(request.form.get("end_month", "12"))
      count = create_fee_plans_for_year(
        class_no=class_no,
        section=section,
        academic_year=academic_year,
        amount=amount,
        start_month=start_month,
        end_month=end_month,
      )
      return render_template(
        "fees_setup.html",
        role="admin",
        phone=session.get("phone"),
        message=f"Published fee plans for {count} months.",
      )

    fee_month = int(request.form.get("fee_month", "0"))
    create_fee_plan(class_no, section, academic_year, fee_month, amount)
    return render_template("fees_setup.html", role="admin", phone=session.get("phone"), message="Fee plan saved!")
  except ValueError as e:
    return render_template("fees_setup.html", role="admin", phone=session.get("phone"), message=f"{e}")


@app.get("/dashboard/admin/payments")
def admin_payments():
  if session.get("role") != "admin":
    return redirect(url_for("login", role="admin"))
  request_rows = list_fee_payment_requests_admin(status="pending", limit=200)
  return render_template(
    "payments.html",
    role="admin",
    phone=session.get("phone"),
    academic_year=get_academic_year(),
    request_rows=request_rows,
    message=request.args.get("msg"),
  )

@app.post("/dashboard/admin/payments")
def admin_payments_post():
  if session.get("role") != "admin":
    return redirect(url_for("login", role="admin"))

  try:
    student_phone = request.form.get("student_phone", "").strip()
    class_no = int(request.form.get("class_no", "0"))
    section = request.form.get("section", "A").strip()
    academic_year = int(request.form.get("academic_year", str(get_academic_year())))
    fee_month = int(request.form.get("fee_month", "0"))
    paid_amount = int(request.form.get("paid_amount", "0"))
    note = request.form.get("note", "")

    student_id = get_student_id_by_phone(student_phone)
    if not student_id:
      raise ValueError("Student not found for this phone.")

    plans = list_fee_plans_for_class(class_no, section, academic_year)
    plan = next((p for p in plans if int(p["fee_month"]) == fee_month), None)
    if not plan:
      raise ValueError("Fee plan not found. Set fee plan first.")

    record_payment(
      fee_plan_id=int(plan["id"]),
      student_id=int(student_id),
      paid_amount=paid_amount,
      received_by_user_id=int(session.get("user_id")),
      note=note,
    )
    request_rows = list_fee_payment_requests_admin(status="pending", limit=200)
    return render_template(
      "payments.html",
      role="admin",
      phone=session.get("phone"),
      message="Payment recorded!",
      academic_year=academic_year,
      request_rows=request_rows,
    )
  except ValueError as e:
    request_rows = list_fee_payment_requests_admin(status="pending", limit=200)
    return render_template(
      "payments.html",
      role="admin",
      phone=session.get("phone"),
      message=f"{e}",
      academic_year=get_academic_year(),
      request_rows=request_rows,
    )

@app.post("/dashboard/admin/payment-requests/<int:request_id>/approve")
def admin_payment_request_approve(request_id: int):
  if session.get("role") != "admin":
    return redirect(url_for("login", role="admin"))

  req = get_fee_payment_request(request_id=request_id)
  if not req:
    return redirect(url_for("admin_payments", msg="Payment request not found."))
  if req.get("status") != "pending":
    return redirect(url_for("admin_payments", msg="Payment request already processed."))

  plan_id = get_fee_plan_id(
    class_no=int(req["class_no"]),
    section=str(req["section"]),
    academic_year=int(req["academic_year"]),
    fee_month=int(req["fee_month"]),
  )
  if not plan_id:
    return redirect(url_for("admin_payments", msg="Fee plan not found. Publish the plan first."))

  try:
    note = (req.get("note") or "").strip()
    if note:
      note = f"Request #{request_id}: {note}"
    else:
      note = f"Request #{request_id}"
    record_payment(
      fee_plan_id=int(plan_id),
      student_id=int(req["student_id"]),
      paid_amount=int(req["requested_amount"]),
      received_by_user_id=int(session.get("user_id")),
      note=note,
    )
    update_fee_payment_request_status(
      request_id=request_id,
      status="approved",
      decided_by_user_id=int(session.get("user_id")),
    )
    return redirect(url_for("admin_payments", msg="Request approved and payment recorded."))
  except ValueError as e:
    return redirect(url_for("admin_payments", msg=str(e)))

@app.post("/dashboard/admin/payment-requests/<int:request_id>/reject")
def admin_payment_request_reject(request_id: int):
  if session.get("role") != "admin":
    return redirect(url_for("login", role="admin"))

  req = get_fee_payment_request(request_id=request_id)
  if not req:
    return redirect(url_for("admin_payments", msg="Payment request not found."))
  if req.get("status") != "pending":
    return redirect(url_for("admin_payments", msg="Payment request already processed."))

  update_fee_payment_request_status(
    request_id=request_id,
    status="rejected",
    decided_by_user_id=int(session.get("user_id")),
  )
  return redirect(url_for("admin_payments", msg="Request rejected."))

@app.get("/dashboard/admin/payments_history")
def admin_payments_history():
  if session.get("role") != "admin":
    return redirect(url_for("login", role="admin"))

  # optional filters from query string
  class_no = request.args.get("class_no", "").strip()
  section = request.args.get("section", "").strip().upper()
  academic_year = request.args.get("academic_year", "").strip()
  fee_month = request.args.get("fee_month", "").strip()
  student_phone = request.args.get("student_phone", "").strip()

  def to_int_or_none(s):
    try:
      return int(s)
    except Exception:
      return None

  rows = list_payments_admin(
    limit=300,
    class_no=to_int_or_none(class_no),
    section=section if section in {"A", "B"} else None,
    academic_year=to_int_or_none(academic_year),
    fee_month=to_int_or_none(fee_month),
    student_phone=student_phone or None,
  )

  return render_template(
    "admin_payments_history.html",
    role="admin",
    phone=session.get("phone"),
    rows=rows,
    filters={
      "class_no": class_no,
      "section": section,
      "academic_year": academic_year,
      "fee_month": fee_month,
      "student_phone": student_phone,
    },
  )

@app.get("/dashboard/admin/payments/<int:payment_id>")
def admin_payment_receipt(payment_id):
  if session.get("role") != "admin":
    return redirect(url_for("login", role="admin"))

  receipt = get_payment_receipt_admin(payment_id=payment_id)
  if not receipt:
    return render_template("payment_receipt.html", role="admin", phone=session.get("phone"), receipt=None, message="Receipt not found.")
  return render_template("payment_receipt.html", role="admin", phone=session.get("phone"), receipt=receipt)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))





if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0").strip() == "1"
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug, host=host, port=port)


