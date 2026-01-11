import csv
import os
import re

IN_PATH = os.path.join("Database", "schoolhub_teachers_20_class_teachers.csv")
OUT_PATH = os.path.join("Database", "teacher_schedule.csv")

# Typical BD school week (change if you want)
DAYS = ["sun", "mon", "tue", "wed", "thu"]
PERIODS = [1, 2, 3, 4, 5, 6]


def parse_class_section(class_teacher_for: str) -> tuple[int, str]:
    """
    Expected: 'Class 3-A' or 'Class 10-B'
    Returns: (class_no, section)
    """
    m = re.search(r"Class\s*(\d+)\s*-\s*([AB])", class_teacher_for.strip(), re.IGNORECASE)
    if not m:
        raise ValueError(f"Invalid class_teacher_for format: {class_teacher_for}")
    return int(m.group(1)), m.group(2).upper()


def main() -> None:
    if not os.path.exists(IN_PATH):
        raise FileNotFoundError(f"Input file not found: {IN_PATH}")

    with open(IN_PATH, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        teachers = list(reader)

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["teacher_phone", "weekday", "period_no", "class_no", "section"])

        for t in teachers:
            phone = t["phone"].strip()
            class_no, section = parse_class_section(t["class_teacher_for"])

            for day in DAYS:
                for p in PERIODS:
                    # Simple demo schedule: teacher teaches own class all 6 periods
                    writer.writerow([phone, day, p, class_no, section])

    total_rows = len(teachers) * len(DAYS) * len(PERIODS)
    print(f"✅ Created: {OUT_PATH}")
    print(f"✅ Teachers: {len(teachers)} | Days: {len(DAYS)} | Periods: {len(PERIODS)} | Rows: {total_rows}")


if __name__ == "__main__":
    main()
