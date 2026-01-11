import csv
import os
import sys
from typing import Dict, Any, Optional, Tuple

from db import connect_db


def parse_args() -> Tuple[str, bool]:
    """
    Returns:
      csv_path: path to CSV file
      dry_run: if True, do not write to DB
    """
    dry_run = "--dry-run" in sys.argv

    csv_path = os.path.join("Database", "teacher_schedule.csv")
    if "--csv" in sys.argv:
        idx = sys.argv.index("--csv")
        if idx + 1 >= len(sys.argv):
            raise ValueError("Missing value after --csv")
        csv_path = sys.argv[idx + 1]

    return csv_path, dry_run


def main() -> None:
    csv_path, dry_run = parse_args()

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    # Counters
    processed = 0
    upserted = 0          # actual DB writes (insert/update)
    would_import = 0      # dry-run count
    skipped = 0
    duplicate_rows = 0
    teacher_not_found = 0

    allowed_weekdays = {"sun", "mon", "tue", "wed", "thu", "fri", "sat"}
    required_headers = {"teacher_phone", "weekday", "period_no", "class_no", "section"}

    # Skip reasons summary
    skip_reasons = {
        "bad_int": 0,
        "invalid_weekday": 0,
        "invalid_section": 0,
        "invalid_period": 0,
        "invalid_class": 0,
        "teacher_not_found": 0,
        "duplicate": 0,
        "header_mismatch": 0,
    }

    # Keep up to 3 examples per reason
    skip_examples = {k: [] for k in skip_reasons.keys()}

    def remember_example(reason: str, row_num: int, row_data: Dict[str, Any]) -> None:
        if len(skip_examples[reason]) < 3:
            skip_examples[reason].append({"row": row_num, "data": row_data})

    # Detect duplicates inside CSV: same (teacher_phone, weekday, period_no)
    seen_slots = set()

    # Cache teacher lookup: phone -> teacher_id (or None)
    teacher_cache: Dict[str, Optional[int]] = {}

    conn = connect_db()
    cursor = conn.cursor()

    try:
        # IMPORTANT: utf-8-sig removes BOM so header reads correctly
        with open(csv_path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            print("Detected CSV headers:", reader.fieldnames)

            if not reader.fieldnames:
                skip_reasons["header_mismatch"] += 1
                raise ValueError("CSV has no header row.")

            normalized_headers = set(h.strip() for h in reader.fieldnames)
            if not required_headers.issubset(normalized_headers):
                skip_reasons["header_mismatch"] += 1
                raise ValueError(
                    "CSV header mismatch. Expected: teacher_phone,weekday,period_no,class_no,section"
                )

            for i, row in enumerate(reader, start=1):
                processed += 1

                # 1) Read + normalize
                teacher_phone = (row.get("teacher_phone") or "").strip()
                weekday = (row.get("weekday") or "").strip().lower()
                section = (row.get("section") or "").strip().upper()

                # 2) Convert ints
                try:
                    period_no = int((row.get("period_no") or "").strip())
                    class_no = int((row.get("class_no") or "").strip())
                except ValueError:
                    skip_reasons["bad_int"] += 1
                    remember_example("bad_int", i, row)
                    skipped += 1
                    continue

                # 3) Validate
                if weekday not in allowed_weekdays:
                    skip_reasons["invalid_weekday"] += 1
                    remember_example("invalid_weekday", i, row)
                    skipped += 1
                    continue

                if section not in {"A", "B"}:
                    skip_reasons["invalid_section"] += 1
                    remember_example("invalid_section", i, row)
                    skipped += 1
                    continue

                if not (1 <= period_no <= 6):
                    skip_reasons["invalid_period"] += 1
                    remember_example("invalid_period", i, row)
                    skipped += 1
                    continue

                if not (1 <= class_no <= 10):
                    skip_reasons["invalid_class"] += 1
                    remember_example("invalid_class", i, row)
                    skipped += 1
                    continue

                if not teacher_phone:
                    skip_reasons["teacher_not_found"] += 1
                    remember_example("teacher_not_found", i, row)
                    teacher_not_found += 1
                    skipped += 1
                    continue

                # 4) CSV duplicate detection (slot identity)
                slot_key = (teacher_phone, weekday, period_no)
                if slot_key in seen_slots:
                    skip_reasons["duplicate"] += 1
                    remember_example("duplicate", i, row)
                    duplicate_rows += 1
                    skipped += 1
                    continue
                seen_slots.add(slot_key)

                # 5) Lookup teacher_id (cached)
                if teacher_phone in teacher_cache:
                    teacher_id = teacher_cache[teacher_phone]
                else:
                    cursor.execute(
                        """
                        SELECT te.id
                        FROM teachers te
                        JOIN users u ON u.id = te.user_id
                        WHERE u.phone = %s
                        LIMIT 1
                        """,
                        (teacher_phone,),
                    )
                    t = cursor.fetchone()
                    teacher_id = t[0] if t else None
                    teacher_cache[teacher_phone] = teacher_id

                if not teacher_id:
                    skip_reasons["teacher_not_found"] += 1
                    remember_example("teacher_not_found", i, row)
                    teacher_not_found += 1
                    skipped += 1
                    continue

                # 6) Write / Dry-run
                if dry_run:
                    would_import += 1
                else:
                    cursor.execute(
                        """
                        INSERT INTO teacher_schedule_slots (teacher_id, weekday, period_no, class_no, section)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                          class_no = VALUES(class_no),
                          section = VALUES(section)
                        """,
                        (teacher_id, weekday, period_no, class_no, section),
                    )
                    upserted += 1

        if not dry_run:
            conn.commit()

        mode = "DRY-RUN" if dry_run else "WRITE"
        print(f"Mode: {mode}")
        print(
            f"✅ Processed: {processed} | Upserted: {upserted} | Would import: {would_import} "
            f"| Skipped: {skipped} | Duplicate rows: {duplicate_rows} | Teacher not found: {teacher_not_found}"
        )
        print("Skip reasons:", skip_reasons)

        # Show examples only when needed
        for reason, count in skip_reasons.items():
            if count > 0:
                print(f"\nExamples for {reason} (showing up to 3):")
                for ex in skip_examples[reason]:
                    print(f"  - row {ex['row']}: {ex['data']}")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
