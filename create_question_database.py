import os
import posixpath
import re
import sqlite3
import unicodedata
import zipfile
import xml.etree.ElementTree as ET


BASE_DIR = r"C:\Users\lenovo\Documents\Hackathon 1 question"
INPUT_FILES = [
    os.path.join(BASE_DIR, "SuperAI_Exam_100Q_Reviewed.xlsx"),
    os.path.join(BASE_DIR, "Unit1_Answer_Key.xlsx"),
]
OUTPUT_DB = os.path.join(BASE_DIR, "question_bank_deduped.db")

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def col_to_number(ref: str) -> int:
    match = re.match(r"([A-Z]+)", ref or "")
    number = 0
    for char in match.group(1):
        number = number * 26 + ord(char) - 64
    return number


def normalize_target(target: str) -> str:
    target = target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return posixpath.normpath(posixpath.join("xl", target))


def normalize_question(text: str) -> str:
    text = unicodedata.normalize("NFKC", (text or "").strip().lower())
    text = text.replace("\u0e4d\u0e32", "\u0e33")
    text = text.translate(
        str.maketrans(
            {
                "‘": "'",
                "’": "'",
                "“": '"',
                "”": '"',
                "—": "-",
                "–": "-",
                "\u200b": "",
            }
        )
    )
    text = re.sub(r"[?？!！.。'\"`´:;,\-–—()\[\]{}]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def read_xlsx_rows(path: str):
    with zipfile.ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", NS):
                shared_strings.append(
                    "".join(text.text or "" for text in item.findall(".//m:t", NS))
                )

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        for sheet in workbook.findall("m:sheets/m:sheet", NS):
            sheet_name = sheet.attrib["name"]
            rel_id = sheet.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            sheet_path = normalize_target(rel_targets[rel_id])
            sheet_root = ET.fromstring(archive.read(sheet_path))

            rows = []
            for row in sheet_root.findall("m:sheetData/m:row", NS):
                values = {}
                for cell in row.findall("m:c", NS):
                    col = col_to_number(cell.attrib.get("r", ""))
                    cell_type = cell.attrib.get("t")
                    value_node = cell.find("m:v", NS)
                    inline_node = cell.find("m:is", NS)
                    value = ""
                    if cell_type == "s" and value_node is not None and value_node.text:
                        value = shared_strings[int(value_node.text)]
                    elif cell_type == "inlineStr" and inline_node is not None:
                        value = "".join(
                            text.text or "" for text in inline_node.findall(".//m:t", NS)
                        )
                    elif value_node is not None and value_node.text is not None:
                        value = value_node.text
                    values[col] = value

                if any(str(value).strip() for value in values.values()):
                    rows.append(values)

            yield sheet_name, rows


def cell(row, index):
    return str(row.get(index, "")).strip()


def parse_workbook(path: str):
    parsed = []
    skipped = []
    source_file = os.path.basename(path)

    for sheet_name, rows in read_xlsx_rows(path):
        if not rows:
            continue

        headers = [cell(rows[0], index).lower() for index in range(1, 20)]
        is_answer_key = "question (thai)" in headers

        for row in rows[1:]:
            question_no = cell(row, 1)
            if not re.fullmatch(r"\d+(\.0)?", question_no):
                continue

            if is_answer_key:
                question_text = cell(row, 2)
                choice_cols = {"A": 3, "B": 4, "C": 5, "D": 6, "E": 7}
                correct_answer = cell(row, 8)
                note = ""
                reason = cell(row, 9)
            else:
                question_text = cell(row, 2)
                choice_cols = {"A": 3, "B": 4, "C": 5, "D": 6, "E": 7, "F": 8}
                note = cell(row, 9)
                correct_answer = cell(row, 12) or cell(row, 10)
                reason = cell(row, 13) or cell(row, 11)

            if not question_text:
                skipped.append(
                    {
                        "source_file": source_file,
                        "source_sheet": sheet_name,
                        "source_question_no": int(float(question_no)),
                        "reason": "blank question text",
                        "raw_note": " | ".join(
                            value
                            for value in [cell(row, 8), cell(row, 11), cell(row, 13)]
                            if value
                        ),
                    }
                )
                continue

            choices = [
                (label, cell(row, col))
                for label, col in choice_cols.items()
                if cell(row, col)
            ]

            parsed.append(
                {
                    "source_file": source_file,
                    "source_sheet": sheet_name,
                    "source_question_no": int(float(question_no)),
                    "question_text": question_text,
                    "normalized_question": normalize_question(question_text),
                    "correct_answer": correct_answer,
                    "note": note,
                    "reason": reason,
                    "choices": choices,
                }
            )

    return parsed, skipped


def build_database(records, skipped_rows):
    if os.path.exists(OUTPUT_DB):
        os.remove(OUTPUT_DB)

    conn = sqlite3.connect(OUTPUT_DB)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            normalized_question TEXT NOT NULL UNIQUE,
            correct_answer TEXT,
            note TEXT,
            reason TEXT,
            source_file TEXT NOT NULL,
            source_sheet TEXT NOT NULL,
            source_question_no INTEGER NOT NULL
        );

        CREATE TABLE choices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            choice_label TEXT NOT NULL,
            choice_text TEXT NOT NULL,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
            UNIQUE (question_id, choice_label)
        );

        CREATE TABLE duplicate_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kept_question_id INTEGER NOT NULL,
            duplicate_source_file TEXT NOT NULL,
            duplicate_source_sheet TEXT NOT NULL,
            duplicate_source_question_no INTEGER NOT NULL,
            duplicate_question_text TEXT NOT NULL,
            FOREIGN KEY (kept_question_id) REFERENCES questions(id) ON DELETE CASCADE
        );

        CREATE TABLE skipped_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            source_sheet TEXT NOT NULL,
            source_question_no INTEGER NOT NULL,
            reason TEXT NOT NULL,
            raw_note TEXT
        );
        """
    )

    kept_by_normalized = {}
    duplicate_count = 0
    for record in records:
        existing_id = kept_by_normalized.get(record["normalized_question"])
        if existing_id:
            duplicate_count += 1
            conn.execute(
                """
                INSERT INTO duplicate_questions (
                    kept_question_id,
                    duplicate_source_file,
                    duplicate_source_sheet,
                    duplicate_source_question_no,
                    duplicate_question_text
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    existing_id,
                    record["source_file"],
                    record["source_sheet"],
                    record["source_question_no"],
                    record["question_text"],
                ),
            )
            continue

        cursor = conn.execute(
            """
            INSERT INTO questions (
                question_text,
                normalized_question,
                correct_answer,
                note,
                reason,
                source_file,
                source_sheet,
                source_question_no
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["question_text"],
                record["normalized_question"],
                record["correct_answer"],
                record["note"],
                record["reason"],
                record["source_file"],
                record["source_sheet"],
                record["source_question_no"],
            ),
        )
        question_id = cursor.lastrowid
        kept_by_normalized[record["normalized_question"]] = question_id

        conn.executemany(
            """
            INSERT INTO choices (question_id, choice_label, choice_text)
            VALUES (?, ?, ?)
            """,
            [
                (question_id, label, choice_text)
                for label, choice_text in record["choices"]
            ],
        )

    conn.executemany(
        """
        INSERT INTO skipped_questions (
            source_file,
            source_sheet,
            source_question_no,
            reason,
            raw_note
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                row["source_file"],
                row["source_sheet"],
                row["source_question_no"],
                row["reason"],
                row["raw_note"],
            )
            for row in skipped_rows
        ],
    )

    conn.commit()
    summary = {
        "input_question_rows_with_text": len(records),
        "unique_questions": conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
        "choices": conn.execute("SELECT COUNT(*) FROM choices").fetchone()[0],
        "duplicates_removed": duplicate_count,
        "duplicates_logged": conn.execute(
            "SELECT COUNT(*) FROM duplicate_questions"
        ).fetchone()[0],
        "skipped_blank_questions": conn.execute(
            "SELECT COUNT(*) FROM skipped_questions"
        ).fetchone()[0],
        "output_db": OUTPUT_DB,
    }
    conn.close()
    return summary


def main():
    records = []
    skipped = []
    for path in INPUT_FILES:
        parsed, skipped_rows = parse_workbook(path)
        records.extend(parsed)
        skipped.extend(skipped_rows)
    summary = build_database(records, skipped)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
