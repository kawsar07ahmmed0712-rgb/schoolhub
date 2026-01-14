# schoolhub

# SchoolHub (Student Management System)

Learning project using **Python + Flask + Database**.

## Prerequisites
- Python 3.10+
- MySQL Server (local)

## Setup (Windows)
### 1) Create & activate venv
```bash
python -m venv .venv
.\.venv\Scripts\activate
```

### 2) Install dependencies
```bash
pip install -r requirements.txt
```

### 3) Configure environment
Create a `.env` file in the project root (or edit your existing one):

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

## Initialize database & tables
Run these once (creates DB + all tables if missing):

```bash
python manage.py init-db
python manage.py init-tables
```

## Import sample data
The repo includes CSV files under `Database/`.

```bash
python manage.py import-accounts
python manage.py import-students
python manage.py import-teacher-schedule --csv Database/teacher_schedule.csv
```

## Run the app
```bash
python manage.py run --debug
```

Then open `http://127.0.0.1:5000/`.

