import json
import os
import sqlite3


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "question_bank_deduped.db")
OUTPUT_PATH = os.path.join(BASE_DIR, "webapp_static", "data.json")


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    questions = rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM questions
            ORDER BY id
            """
        ).fetchall()
    )
    choices = rows_to_dicts(
        conn.execute(
            """
            SELECT question_id, choice_label, choice_text
            FROM choices
            ORDER BY question_id, choice_label
            """
        ).fetchall()
    )
    duplicates = rows_to_dicts(
        conn.execute(
            """
            SELECT
                d.id,
                d.kept_question_id,
                q.source_file AS kept_source_file,
                q.source_question_no AS kept_source_question_no,
                d.duplicate_source_file,
                d.duplicate_source_sheet,
                d.duplicate_source_question_no,
                d.duplicate_question_text
            FROM duplicate_questions d
            JOIN questions q ON q.id = d.kept_question_id
            ORDER BY d.id
            """
        ).fetchall()
    )
    skipped = rows_to_dicts(
        conn.execute(
            """
            SELECT source_file, source_sheet, source_question_no, reason, raw_note
            FROM skipped_questions
            ORDER BY source_file, source_question_no
            """
        ).fetchall()
    )
    conn.close()

    choices_by_question = {}
    for choice in choices:
        choices_by_question.setdefault(str(choice["question_id"]), []).append(
            {
                "choice_label": choice["choice_label"],
                "choice_text": choice["choice_text"],
            }
        )

    duplicates_by_question = {}
    for duplicate in duplicates:
        duplicates_by_question.setdefault(str(duplicate["kept_question_id"]), []).append(
            duplicate
        )

    sources = {}
    answers = {}
    for question in questions:
        sources[question["source_file"]] = sources.get(question["source_file"], 0) + 1
        answer = (question["correct_answer"] or "").strip()[:1].upper()
        if answer:
            answers[answer] = answers.get(answer, 0) + 1

    payload = {
        "stats": {
            "questions": len(questions),
            "choices": len(choices),
            "duplicates": len(duplicates),
            "skipped": len(skipped),
            "sources": [
                {"source_file": key, "question_count": value}
                for key, value in sorted(sources.items())
            ],
            "answers": [
                {"answer": key, "count": value}
                for key, value in sorted(answers.items())
            ],
        },
        "questions": questions,
        "choicesByQuestion": choices_by_question,
        "duplicates": duplicates,
        "duplicatesByQuestion": duplicates_by_question,
        "skipped": skipped,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
