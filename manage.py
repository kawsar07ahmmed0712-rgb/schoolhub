import argparse
import subprocess
import sys


def cmd_init_db(_args: argparse.Namespace) -> int:
    import init_db

    init_db.main()
    return 0


def cmd_init_tables(_args: argparse.Namespace) -> int:
    import init_all_tables
    import init_attendance_tables
    import init_daily_class_tables
    import init_teacher_schedule_tables

    init_all_tables.main()
    init_attendance_tables.main()
    init_daily_class_tables.main()
    init_teacher_schedule_tables.main()
    return 0


def cmd_import_accounts(_args: argparse.Namespace) -> int:
    import import_accounts

    import_accounts.main()
    return 0


def cmd_import_students(_args: argparse.Namespace) -> int:
    import import_students

    import_students.import_all_students()
    return 0


def cmd_import_teacher_schedule(args: argparse.Namespace) -> int:
    cmd = [sys.executable, "import_teacher_schedule.py"]
    if args.csv:
        cmd += ["--csv", args.csv]
    if args.dry_run:
        cmd += ["--dry-run"]
    return subprocess.call(cmd)


def cmd_run(args: argparse.Namespace) -> int:
    import os

    os.environ.setdefault("FLASK_DEBUG", "1" if args.debug else "0")
    os.environ.setdefault("HOST", args.host)
    os.environ.setdefault("PORT", str(args.port))

    import run

    run.app.run(debug=args.debug, host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SchoolHub management commands")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db", help="Create the MySQL database (if missing)")
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("init-tables", help="Create all required tables (if missing)")
    p.set_defaults(func=cmd_init_tables)

    p = sub.add_parser("import-accounts", help="Import teachers/admin/headmaster accounts from CSV")
    p.set_defaults(func=cmd_import_accounts)

    p = sub.add_parser("import-students", help="Import students into class tables from CSV files")
    p.set_defaults(func=cmd_import_students)

    p = sub.add_parser("import-teacher-schedule", help="Import teacher schedule slots from CSV")
    p.add_argument("--csv", help="Path to teacher schedule CSV")
    p.add_argument("--dry-run", action="store_true", help="Validate only; do not write to DB")
    p.set_defaults(func=cmd_import_teacher_schedule)

    p = sub.add_parser("run", help="Run the Flask development server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

