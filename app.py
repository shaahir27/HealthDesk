from flask import Flask, render_template, request
import os, subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TMPL_DIR = os.path.join(BASE_DIR, "Frontend", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "Frontend", "static")
BACKEND_DIR = os.path.join(BASE_DIR, "Backend")

app = Flask(__name__,
            template_folder = TMPL_DIR,
            static_folder=STATIC_DIR)



@app.route("/patient")
def patient():
    return render_template("patient.html")

@app.route("/add_patient", methods=["POST"])
def add_patient():

    name = request.form["name"]
    age = request.form["age"]
    gender = request.form["gender"]
    phone = request.form["phone"]    
    address = request.form["address"]
    symptoms = request.form["symptoms"]
    visit_type = request.form["visit_type"]
    priority = request.form["priority"]

    exe_path = os.path.join(BACKEND_DIR, "c_modules", "patient.exe")

    data_string = f"{name}|{age}|{gender}|{phone}|{address}|{symptoms}|{visit_type}|{priority}"
    
    patient_output = subprocess.run(
        [exe_path, data_string],
        capture_output=True,
        text=True
    )
    patient_output = patient_output.stdout.strip()
    data = patient_output.split("|")
    id = data[0]
    view_type = data[1]
    priority = data[2]
    return render_template("add_patient.html", patient_id=id, visit_type=visit_type, priority=priority)

@app.route("/test")
def test():
    exe_path = os.path.join("test.exe")
    result = subprocess.run(
        [exe_path, "hello"],
        capture_output=True,
        text=True
    )

    return result.stdout

if __name__ == "__main__":
    app.run(debug=True, port=5000)