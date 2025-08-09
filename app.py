from flask import Flask, render_template, request, redirect,jsonify
from flask import redirect, url_for, request
import sqlite3
import os
import google.generativeai as genai
from flask_cors import CORS
app = Flask(__name__,template_folder='templates')
CORS(app) 

def get_db_connection():
    conn = sqlite3.connect('database/quickdocs.db')
    conn.row_factory = sqlite3.Row
    return conn

#Register part

@app.route('/register', methods=['GET', 'POST'])
def register():
    conn = get_db_connection()

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        process_id = request.form['process_id']

        
        conn.execute('INSERT INTO customers (name, email, phone) VALUES (?, ?, ?)',
                     (name, email, phone))
        customer_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]

        
        conn.execute('''
            INSERT INTO process_assignments (customer_id, process_id, status, completion_percentage)
            VALUES (?, ?, ?, ?)''',
            (customer_id, process_id, 'pending', 0))
        conn.commit()
        conn.close()

        
        return redirect(url_for('register', show_data=1))

    else:
        show_data = request.args.get('show_data', default=0, type=int)
        processes = conn.execute('SELECT * FROM processes').fetchall()

        customers = []
        if show_data == 1:
            customers = conn.execute('SELECT * FROM customers').fetchall()

        conn.close()

        
        return render_template('register.html', processes=processes, customers=customers, show_data=show_data)


# Submit part

@app.route('/submit', methods=['GET', 'POST'])
def submit():
    conn = get_db_connection()
    ocr_output = None

    if request.method == 'POST':
       
        customer_id = request.form['customer_id']
        process_id = request.form['process_id']
        document_type_id = request.form['document_type_id']
        file_name = request.form['file_url']

        
        try:
            with open(os.path.join("dummy_files", file_name), "r") as f:
                ocr_output = f.read()
        except FileNotFoundError:
            ocr_output = "[ERROR: File not found for OCR]"

       
        conn.execute('''
            INSERT INTO document_submissions
            (customer_id, process_id, document_type_id, upload_date, file_url, ocr_data, validation_status)
            VALUES (?, ?, ?, DATETIME("now","localtime"), ?, ?, ?)''',
            (customer_id, process_id, document_type_id, file_name, ocr_output, 'pending'))
        conn.commit()

        
        show_data = 1
    else:
        ocr_output = None
        show_data = 0

    customers = conn.execute('SELECT * FROM customers').fetchall()
    processes = conn.execute('SELECT * FROM processes').fetchall()
    doc_types = conn.execute('SELECT * FROM document_types').fetchall()

    submissions = []
    if show_data == 1:
        submissions = conn.execute('''
            SELECT ds.upload_date, c.name AS customer_name, p.name AS process_name,
                   dt.name AS document_type, ds.file_url, ds.ocr_data, ds.validation_status
            FROM document_submissions ds
            JOIN customers c ON ds.customer_id = c.id
            JOIN processes p ON ds.process_id = p.id
            JOIN document_types dt ON ds.document_type_id = dt.id
            ORDER BY ds.upload_date DESC
        ''').fetchall()

    conn.close()

    return render_template('submit.html',
                           customers=customers,
                           processes=processes,
                           doc_types=doc_types,
                           submissions=submissions,
                           ocr_output=ocr_output,
                           show_data=show_data)

 # Dashboard Part
@app.route('/dashboard')
def dashboard():
    conn = get_db_connection()
    dashboard_data = conn.execute('''
        SELECT c.name AS customer_name, p.name AS process_name,
               pa.status, pa.completion_percentage
        FROM process_assignments pa
        JOIN customers c ON pa.customer_id = c.id
        JOIN processes p ON pa.process_id = p.id
    ''').fetchall()
    conn.close()

    return render_template('dashboard.html', dashboard_data=dashboard_data)


# NLP part

DB_PATH = "../database/quickdocs.db"
SCHEMA_PATH = "../database/schema.sql"


genai.configure(api_key="AIzaSyCwEtH3a417Twls22umX4SXTQt_-5_NHRk")



def load_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return f.read()

def run_sql(sql):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description] if cur.description else []
    conn.close()
    return cols, [dict(r) for r in rows]


@app.route("/nl_query", methods=["POST"])
def nl_query():
    question = request.json.get("question", "").strip()
    if not question:
        return jsonify({"error": "No question provided"}), 400

    prompt = f"""
You are an SQL generator for SQLite.
Here is the schema:
{load_schema()}

Follow these examples exactly:

1. "Show all customers" → SELECT * FROM customers;
2. "List all pending processes" → SELECT * FROM processes WHERE status = 'pending';
3. "How many documents has [customer name] submitted?" → SELECT COUNT(*) FROM documents d JOIN customers c ON d.customer_id = c.id WHERE c.name = '[customer name]';
4. "Which process has the most documents?" → SELECT p.name, COUNT(*) AS total_docs FROM processes p JOIN documents d ON p.id = d.process_id GROUP BY p.name ORDER BY total_docs DESC LIMIT 1;
5. "Which customers are assigned to [process name]?" → SELECT c.* FROM customers c JOIN customer_process cp ON c.id = cp.customer_id JOIN processes p ON cp.process_id = p.id WHERE p.name = '[process name]';
-- Continue adding until all 10 cases are covered

Now, generate the SQL for this question (only return SQL):
{question}
"""

    model = genai.GenerativeModel("gemini-2.5-flash")
    sql = model.generate_content(prompt).text.strip()

    allowed_starts = ("select", "with")

    if not sql.lower().startswith(allowed_starts):
      return jsonify({
        "error": "Only read queries (SELECT/WITH) allowed",
        "sql": sql
    }), 400

    try:
        cols, rows = run_sql(sql)
        return jsonify({"sql": sql, "columns": cols, "rows": rows})
    except Exception as e:
        return jsonify({"error": str(e), "sql": sql}), 500

@app.route("/nl-query-ui")
def nl_query_ui():
    return render_template("index.html")



if __name__ == '__main__':
    app.run(debug=True)
