from flask import Flask, render_template, request , redirect, url_for , session
from datetime import datetime 
from werkzeug.security import check_password_hash 
from db import connect_db




app = Flask(__name__)
app.secret_key = "dev-only-secret-key-change-later"


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
        ("marks", "Marks Entry"),
        ("notices", "Notices"),
        ("leaves", "Leave Approvals"),
    ],
    "head": [
        ("teachers", "Teachers Management"),
        ("approvals", "Approvals"),
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
def dashboard_page(role, page):
    role = normalize_role(role)

    pages_dict = {slug: label for slug, label in ROLE_PAGES[role]}
    if page not in pages_dict:
        return redirect(url_for("dashboard", role=role))

    return render_template(
    "page.html",
    role=role,
    page_title=pages_dict[page],
    phone=session.get("phone"),
)



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

    NOTICES.append(
        {
            "id": NEXT_NOTICE_ID,
            "title": title,
            "body": body,
            "by_role": role,
            "by_phone": session.get("phone"),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    )
    NEXT_NOTICE_ID += 1


    return redirect(url_for("notices", role=role))


@app.post("/dashboard/<role>/notices/<int:notice_id>/delete")
def notice_delete(role , notice_id):
    role = normalize_role(role)

    if session.get("rle") != role:
        return redirect(url_for("login" , role = role))
    
    if role not in {"teacher" , "head" , "admin"}:
        return redirect(url_for("notices" , role))
    
    for i , n in enumerate(NOTICES):
        if n["id"] == notice_id:
            NOTICES.pop(i)
            break
    
    return redirect(url_for("notices" , role = role))



@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)


