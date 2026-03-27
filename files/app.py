from flask import Flask, request, render_template
import subprocess

app = Flask(__name__)

# Home
@app.route('/')
def home():
    return render_template('index.html')

# Add page
@app.route('/add')
def add():
    return render_template('add.html')

# Submit form → call C writer
@app.route('/submit', methods=['POST'])
def submit():
    reg_no = request.form['reg_no']
    make = request.form['make']
    model = request.form['model']
    owner_name = request.form['owner_name']

    subprocess.run(
        ["file_handler.exe", reg_no, make, model, owner_name],
        capture_output=True,
        text=True
    )

    return "Jobcard added successfully <br><a href='/'>Go back</a>"

# View jobcards → call C reader
@app.route('/view')
def view():
    result = subprocess.run(
        ["read_b.exe"],
        capture_output=True,
        text=True
    )

    return result.stdout

if __name__ == '__main__':
    app.run(debug=True)