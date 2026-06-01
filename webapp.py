import json
import os
import sqlite3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "question_bank_deduped.db")
STATIC_DIR = os.path.join(BASE_DIR, "webapp_static")


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def parse_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


class QuestionBankHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
            return
        if path == "/styles.css":
            self.send_file(os.path.join(STATIC_DIR, "styles.css"), "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self.send_file(os.path.join(STATIC_DIR, "app.js"), "application/javascript; charset=utf-8")
            return
        if path == "/data.json":
            self.send_file(os.path.join(STATIC_DIR, "data.json"), "application/json; charset=utf-8")
            return
        if path == "/api/stats":
            self.send_json(self.get_stats())
            return
        if path == "/api/questions":
            self.send_json(self.get_questions(parse_qs(parsed.query)))
            return
        if path.startswith("/api/questions/"):
            question_id = parse_int(path.rsplit("/", 1)[-1], 0, minimum=1)
            self.send_json(self.get_question(question_id))
            return
        if path == "/api/duplicates":
            self.send_json(self.get_duplicates())
            return
        if path == "/api/skipped":
            self.send_json(self.get_skipped())
            return

        self.send_error(404, "Not found")

    def log_message(self, format, *args):
        return

    def send_file(self, path, content_type):
        if not os.path.exists(path):
            self.send_error(404, "Not found")
            return
        with open(path, "rb") as file:
            content = file.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, payload, status=200):
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def get_stats(self):
        with connect_db() as conn:
            sources = conn.execute(
                """
                SELECT source_file, COUNT(*) AS question_count
                FROM questions
                GROUP BY source_file
                ORDER BY source_file
                """
            ).fetchall()
            answers = conn.execute(
                """
                SELECT SUBSTR(TRIM(correct_answer), 1, 1) AS answer, COUNT(*) AS count
                FROM questions
                WHERE TRIM(COALESCE(correct_answer, '')) <> ''
                GROUP BY answer
                ORDER BY answer
                """
            ).fetchall()
            return {
                "questions": conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
                "choices": conn.execute("SELECT COUNT(*) FROM choices").fetchone()[0],
                "duplicates": conn.execute("SELECT COUNT(*) FROM duplicate_questions").fetchone()[0],
                "skipped": conn.execute("SELECT COUNT(*) FROM skipped_questions").fetchone()[0],
                "sources": rows_to_dicts(sources),
                "answers": rows_to_dicts(answers),
            }

    def get_questions(self, params):
        query = params.get("q", [""])[0].strip()
        source = params.get("source", [""])[0].strip()
        answer = params.get("answer", [""])[0].strip().upper()
        page = parse_int(params.get("page", ["1"])[0], 1, minimum=1)
        page_size = parse_int(params.get("page_size", ["20"])[0], 20, minimum=5, maximum=100)
        offset = (page - 1) * page_size

        where = []
        values = []
        if query:
            where.append(
                """
                (
                    q.question_text LIKE ?
                    OR q.note LIKE ?
                    OR EXISTS (
                        SELECT 1 FROM choices c
                        WHERE c.question_id = q.id AND c.choice_text LIKE ?
                    )
                )
                """
            )
            like = f"%{query}%"
            values.extend([like, like, like])
        if source:
            where.append("q.source_file = ?")
            values.append(source)
        if answer:
            where.append("UPPER(SUBSTR(TRIM(q.correct_answer), 1, 1)) = ?")
            values.append(answer)

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        with connect_db() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM questions q {where_sql}",
                values,
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT
                    q.id,
                    q.question_text,
                    q.correct_answer,
                    q.source_file,
                    q.source_question_no,
                    COUNT(c.id) AS choice_count
                FROM questions q
                LEFT JOIN choices c ON c.question_id = q.id
                {where_sql}
                GROUP BY q.id
                ORDER BY q.id
                LIMIT ? OFFSET ?
                """,
                values + [page_size, offset],
            ).fetchall()

        return {
            "items": rows_to_dicts(rows),
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size),
        }

    def get_question(self, question_id):
        with connect_db() as conn:
            question = conn.execute(
                "SELECT * FROM questions WHERE id = ?",
                (question_id,),
            ).fetchone()
            if question is None:
                return {"error": "Question not found"}
            choices = conn.execute(
                """
                SELECT choice_label, choice_text
                FROM choices
                WHERE question_id = ?
                ORDER BY choice_label
                """,
                (question_id,),
            ).fetchall()
            duplicates = conn.execute(
                """
                SELECT duplicate_source_file, duplicate_source_sheet,
                       duplicate_source_question_no, duplicate_question_text
                FROM duplicate_questions
                WHERE kept_question_id = ?
                ORDER BY id
                """,
                (question_id,),
            ).fetchall()
        return {
            "question": dict(question),
            "choices": rows_to_dicts(choices),
            "duplicates": rows_to_dicts(duplicates),
        }

    def get_duplicates(self):
        with connect_db() as conn:
            rows = conn.execute(
                """
                SELECT
                    d.id,
                    q.id AS kept_question_id,
                    q.source_file AS kept_source_file,
                    q.source_question_no AS kept_source_question_no,
                    d.duplicate_source_file,
                    d.duplicate_source_question_no,
                    d.duplicate_question_text
                FROM duplicate_questions d
                JOIN questions q ON q.id = d.kept_question_id
                ORDER BY d.id
                """
            ).fetchall()
        return {"items": rows_to_dicts(rows)}

    def get_skipped(self):
        with connect_db() as conn:
            rows = conn.execute(
                """
                SELECT source_file, source_sheet, source_question_no, reason, raw_note
                FROM skipped_questions
                ORDER BY source_file, source_question_no
                """
            ).fetchall()
        return {"items": rows_to_dicts(rows)}


def main():
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"Database not found: {DB_PATH}")
    server = ThreadingHTTPServer(("127.0.0.1", 8000), QuestionBankHandler)
    print("Question Bank web app running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
