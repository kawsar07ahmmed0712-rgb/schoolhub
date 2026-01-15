import csv
import os
import re

IN_PATH = os.path.join("Database", "schoolhub_teachers_20_class_teachers.csv")
OUT_PATH = os.path.join("Database", "teacher_schedule.csv")

# School week (change if you want)
DAYS = ["sun", "mon", "tue", "wed", "thu"]
PERIODS = [1, 2, 3, 4, 5, 6]

SECTIONS = ["A", "B"]
ALL_CLASS_SLOTS = [(c, s) for c in range(1, 11) for s in SECTIONS]  # 20 combos


def parse_class_section(class_teacher_for: str) -> tuple[int, str]:
    """
    Expected: 'Class 3-A' or 'Class 10-B'
    Returns: (class_no, section)
    """
    m = re.search(r"Class\s*(\d+)\s*-\s*([AB])", class_teacher_for.strip(), re.IGNORECASE)
    if not m:
        raise ValueError(f"Invalid class_teacher_for format: {class_teacher_for}")
    return int(m.group(1)), m.group(2).upper()


def pick_rotating_class(home: tuple[int, str], teacher_idx: int, day_idx: int, period_no: int) -> tuple[int, str]:
    """
    Deterministic rotation:
    - Uses teacher index + day index + period to choose another class/section (not home).
    """
    base = (teacher_idx * 7 + day_idx * 3 + period_no * 5) % len(ALL_CLASS_SLOTS)
    cand = ALL_CLASS_SLOTS[base]
    if cand == home:
        cand = ALL_CLASS_SLOTS[(base + 1) % len(ALL_CLASS_SLOTS)]
    return cand


def main() -> None:
    if not os.path.exists(IN_PATH):
        raise FileNotFoundError(f"Input file not found: {IN_PATH}")

    with open(IN_PATH, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        teachers = list(reader)

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["teacher_phone", "weekday", "period_no", "class_no", "section"])

        for teacher_idx, t in enumerate(teachers):
            phone = t["phone"].strip()
            home_class_no, home_section = parse_class_section(t["class_teacher_for"])
            home = (home_class_no, home_section)

            for day_idx, day in enumerate(DAYS):
                # 1 free period/day to look realistic (different per teacher/day)
                free_period = ((teacher_idx + day_idx) % 6) + 1

                for p in PERIODS:
                    if p == free_period:
                        # No row => UI will show '-' for this period
                        continue

                    # First 3 periods = home class (class teacher duty)
                    if p <= 3:
                        class_no, section = home
                    else:
                        # Last periods rotate to other classes (subject/support duty)
                        class_no, section = pick_rotating_class(home, teacher_idx, day_idx, p)

                    writer.writerow([phone, day, p, class_no, section])

    total_rows = sum(1 for _ in open(OUT_PATH, "r", encoding="utf-8"))
    print(f"OK. Created: {OUT_PATH}")
    print(f"OK. Teachers: {len(teachers)} | Days: {len(DAYS)} | Periods: {len(PERIODS)}")
    print(f"OK. CSV lines (including header): {total_rows}")


if __name__ == "__main__":
    main()
