from flask import Flask, render_template, request , redirect, url_for , session , make_response
from datetime import datetime 
from werkzeug.security import check_password_hash 
from db import connect_db
from datetime import date, timedelta, datetime
import os
import csv
from werkzeug.utils import secure_filename
import io

from services.notices_service import list_notices, create_notice, delete_notice



app = Flask(__name__)
app.secret_key = "dev-only-secret-key-change-later"



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

ALLOWED_ROLES = {"student", "teacher", "head", "admin"}

ROLE_PAGES = {
    "student": [
        ("profile", "Profile"),
        ("fees", "Fees (Monthly)"),
        ("results", "Results"),
        ("attendance", "Attendance & Leave"),
        ("notices", "Notices"),
        ("routine", "Routine"),
    ],
    "teacher": [
        ("students", "Student List"),
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
        ("today_overview", "Today's Overview"),
        ("results", "Results Publish/Lock"),
        ("reports", "Reports"),
        ("notices", "Notices"),
    ],

    "admin": [
        ("settings", "School Settings"),
        ("users", "Users Management"),
        ("fees_setup", "Fees Setup"),
        ("payments", "Payments"),
        ("timetable", "Timetable"),
        ("notices", "Notices"),
        ("reports", "Reports"),
        ("schedule_upload", "Teacher Schedule Upload"),
    ],
}
NOTICES = []
NEXT_NOTICE_ID = 1








def normalize_role(role: str) -> str:
    if role in ALLOWED_ROLES:
        return role
    return "student"

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
@app.get("/dashboard/<role>")
def dashboard(role):
    role = normalize_role(role)

    if session.get("role") != role:
        return redirect(url_for("login", role=role))

    pages = ROLE_PAGES[role]
    profile = fetch_role_profile(session.get("user_id"), role)

    return render_template(
        "dashboard.html",
        role=role,
        pages=pages,
        phone=session.get("phone"),
        profile=profile,
    )

# DASHBOARD PAGE
@app.get("/dashboard/<role>/<page>")
def notices(role):
    role = normalize_role(role)
    if session.get("role") != role:
        return redirect(url_for("login", role=role))

    can_post = role in {"teacher", "head", "admin"}
    notices_latest_first = list_notices(limit=200)
    return render_template(
        "notices.html",
        role=role,
        phone=session.get("phone"),
        can_post=can_post,
        notices=notices_latest_first,
    )

############################## NOTICES PART NOTICES PART NOTICES PART NOTICES PART NOTICES PART ###########################################################
# NOTICES 

@app.get("/dashboard/<role>/notices")
def notices(role):
    role = normalize_role(role)

    if session.get("role") != role:
        return redirect(url_for("login", role=role))

    can_post = role in {"teacher", "head", "admin"}
    notices_latest_first = list(reversed(NOTICES))
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

    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()

    if title == "" or body == "":
        return render_template(
            "notices.html",
            role=role,
            phone=session.get("phone"),
            can_post=True,
            notices=list(reversed(NOTICES)),
            message="Title and body are required.",
            title=title,
            body=body,
        )
    global NEXT_NOTICE_ID

    create_notice(
        title=title,
        body=body,
        by_user_id=int(session.get("user_id")),
        by_role=role,
    )
    return redirect(url_for("notices", role=role))






@app.post("/dashboard/<role>/notices/<int:notice_id>/delete")
def notice_delete(role , notice_id):
    role = normalize_role(role)

    if session.get("role") != role:
        return redirect(url_for("login", role=role))

    ok = delete_notice(
        notice_id=int(notice_id),
        requester_user_id=int(session.get("user_id")),
        requester_role=role,
    )
    if not ok:
        return redirect(url_for("notices", role=role))
    return redirect(url_for("notices", role=role))






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
                message="✅ Attendance saved successfully!",
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




########################################### TEACHER PART TEACHER PART TEACHER PART ########################################
@app.get("/dashboard/teacher/daily-class")
def teacher_daily_class():
    # Only logged-in teachers can access
    if session.get("role") != "teacher":
        return redirect(url_for("login", role="teacher"))

    today = str(date.today())

    conn = connect_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # 1) Find teacher_id from logged in user_id
        cursor.execute("SELECT id FROM teachers WHERE user_id=%s", (session.get("user_id"),))
        t = cursor.fetchone()
        if not t:
            return render_template(
                "teacher_daily_class.html",
                today=today,
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
                today=today,
                class_no="-",
                section="-",
                periods=[],
                message="Class teacher assignment not found.",
            )

        class_no = int(a["class_no"])
        section = a["section"]  # 'A' or 'B'

        # 3) Find today’s day container (if exists)
        cursor.execute(
            """
            SELECT id
            FROM daily_class_days
            WHERE teacher_id=%s AND log_date=%s
            LIMIT 1
            """,
            (teacher_id, today),
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
            periods.append(
                {
                    "period_no": n,
                    "topic": row.get("topic", ""),
                    "homework": row.get("homework", ""),
                    "notes": row.get("notes", ""),
                }
            )

        return render_template(
            "teacher_daily_class.html",
            today=today,
            class_no=class_no,
            section=section,
            periods=periods,
            message=None,
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
            message = "✅ Saved!"
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
                    "status": "DONE ✅" if int(r["is_done"]) == 1 else "PENDING",
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
            message = "✅ Import completed."
        except Exception as e:
            message = f"❌ Import failed: {e}"

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
        return redirect(url_for("admin_schedule_upload", msg="❌ Not cleared. Please check confirm and type DELETE."))

    conn = connect_db()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM teacher_schedule_slots")
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("admin_schedule_upload", msg="✅ All teacher schedule slots cleared."))


@app.post("/dashboard/admin/today-logs-clear")
def admin_today_logs_clear():
    if session.get("role") != "admin":
        return redirect(url_for("login", role="admin"))

    confirm = request.form.get("confirm") == "on"
    confirm_text = (request.form.get("confirm_text") or "").strip().upper()

    if (not confirm) or (confirm_text != "CLEAR TODAY"):
        return redirect(
            url_for("admin_schedule_upload", msg="❌ Not cleared. Please check confirm and type CLEAR TODAY.")
        )

    today = str(date.today())

    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM teacher_lesson_logs WHERE log_date=%s", (today,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("admin_schedule_upload", msg="✅ Today's teacher lesson logs cleared."))







@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)


