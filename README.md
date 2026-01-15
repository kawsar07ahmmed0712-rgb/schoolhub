# SchoolHub (Student Management System)

Learning project using **Python + Flask + MySQL**.

## Quick links
- Video narration script: `VIDEO_TUTORIAL_SCRIPT.txt`
- AI Insights (new): `/dashboard/<role>/ai-insights`
- Automated AI (teacher/head): `/dashboard/<role>/ai-automated`
- Student Gemini tutor: `/dashboard/student/ai-assist`

## Prerequisites
- Python 3.10+
- MySQL Server (local)

## Step-by-step setup (Windows / PowerShell)
### 1) Create & activate venv
```bash
python -m venv .venv
.\.venv\Scripts\activate
```

### 2) Install dependencies
```bash
pip install -r requirements.txt
```

### 2.5) Train the bundled ML models (optional but recommended)
Trains two Kaggle-based models (dropout risk, score forecaster) and saves artifacts under `services/ml_artifacts/`.
```bash
python manage.py train-ml
```

### 2.6) (Students) Gemini study assistant
Set `GEMINI_API_KEY` in `.env` (already present). The student-only AI tutor lives at `/dashboard/student/ai-assist` and uses Gemini 1.5 Flash.

### 3) Configure environment
Create a `.env` file in the project root:

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=SchoolHub

# Optional (recommended)
SECRET_KEY=change-me
ACADEMIC_YEAR=2026
DATABASE_ROOT=Database
STUDENTS_DATA_DIR=Database/Data
```

### 4) Initialize database & tables
Run these once (creates DB + tables if missing):

```bash
python manage.py init-db
python manage.py init-tables
```

### 5) Import sample data (accounts, students, schedules)
```bash
python manage.py import-accounts
python manage.py import-students
python manage.py import-teacher-schedule --csv Database/teacher_schedule.csv
```

### 6) Run the app
```bash
python manage.py run --debug
```

Open: `http://127.0.0.1:5000/`

## Quick demo credentials (copy/paste)
These accounts come from the repo CSVs under `Database/` and `Database/Data/`.

**Student (Class 2-A)**
- Phone: `01767988230`
- Password: `yPsmXbufQn`

**Teacher (Class teacher: Class 2-A)**
- Phone: `01761857073`
- Password: `LniPzv18s0`

**Head Teacher**
- Phone: `01536479627`
- Password: `38VFxzKNfgm8`

**Admin**
- Phone: `01551253871`
- Password: `zQEtG6g0W9U1`

## walkthrough (end-to-end)
Use this flow to verify the project step-by-step.

### A) Student: login and explore dashboard
1. Open `http://127.0.0.1:5000/`
2. Click **Continue as Student**
3. Paste the **Student** credentials above and sign in
4. From the sidebar:
   - **Routine**: opens the weekly routine for the student's class (if schedule is imported)
   - **Fees (Monthly)**: shows fee plans / due (needs fee plans to exist)
   - **Attendance & Leave**: shows attendance history (starts empty until teacher records)
   - **Notices**: shows school notices
   - **Daily Diary**: shows topic/homework/notes by period (filled by class teacher)

### B) Teacher: publish a notice
1. Logout
2. Go to `http://127.0.0.1:5000/login?role=teacher`
3. Paste the **Teacher** credentials above and sign in
4. Open **Notices**
5. Post a notice (example):
   - Title: `Test Notice`
   - Body: `This notice was posted by a teacher.`

### C) AI Insights (all roles)
1. Login as any role (student/teacher/head/admin)
2. Open **AI Insights** from the sidebar or dashboard quick actions
3. Use the **Dropout risk** form (numeric fields) or **Score forecaster** form (select inputs) to get predictions
4. Review the probability bars / grade band

### D) Automated AI Insights (teacher -> head workflow)
1. Login as **Teacher** -> open **Automated AI Insights**
2. Fill the dropout fields + student name -> submit (saved to shared list)
3. Login as **Head** -> open **Automated AI Insights** to see buckets: High (Dropout), Risk (Enrolled), Good (Graduate)
4. Use it to prioritize parent calls/interventions

### E) Student AI tutor (Gemini)
1. Login as **Student**
2. Open **AI Study Assistant**
3. Ask short, specific questions; answers come from Gemini with 2–4 sentence tips

### C) Student: confirm the notice is visible
1. Logout
2. Login again as **Student**
3. Open **Notices** -> confirm you can see `Test Notice`

### D) Teacher: take attendance for today
1. Logout -> login as **Teacher**
2. Open **Take Attendance**
3. Pick today's date -> keep a few students marked present -> **Save Attendance**

### E) Student: view attendance
1. Logout -> login as **Student**
2. Open **Attendance & Leave**
3. Confirm today's record appears in the table and summary changes

### F) Admin: setup fees + record a payment
1. Logout -> login as **Admin**
2. Open **Fees Setup**
3. Create a fee plan (example):
   - Class: `2`, Section: `A`, Year: `2026`, Month: `1`, Amount: `500`
4. Open **Payments** and record a payment (example):
   - Student Phone: `01767988230`
   - Class: `2`, Section: `A`, Year: `2026`, Month: `1`
   - Paid Amount: `200`
5. Logout -> login as **Student**
6. Open **Fees (Monthly)** and **My Payments** -> confirm due + payment history

### G) Teacher + Head: daily progress overview
1. Logout -> login as **Teacher**
2. Open **Today's Schedule**
3. For period 1: set a topic and check **Mark as done** -> save
4. Logout -> login as **Head Teacher**
5. Open **Today's Overview** -> confirm the row shows as DONE and topic appears

### H) Daily diary: teacher -> student/head view
1. Login as **Teacher**
2. Open **Daily Class Update**
3. Pick a date -> add Topic/Homework/Notes for period 1 -> **Save**
4. Logout -> login as **Student**
5. Open **Daily Diary** -> pick the same date -> confirm the content appears
6. Logout -> login as **Head Teacher**
7. Open **Class Diary** -> select class/section and date -> confirm the same content appears

## Troubleshooting
- "Database not initialized" pages: run `python manage.py init-tables`
- No student routine: run `python manage.py import-teacher-schedule --csv Database/teacher_schedule.csv`
- Login fails: re-run `python manage.py import-accounts` / `python manage.py import-students`
- ML not loading: run `python manage.py train-ml` to regenerate artifacts; ensure `ML-Dataset/` zipped files are present
