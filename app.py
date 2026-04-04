from flask import Flask, redirect, render_template, request
import os, subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TMPL_DIR = os.path.join(BASE_DIR, "Frontend", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "Frontend", "static")
BACKEND_DIR = os.path.join(BASE_DIR, "Backend")

app = Flask(__name__,
            template_folder = TMPL_DIR,
            static_folder=STATIC_DIR)


def read_queue():
    queue = []

    try:
        queue_file = os.path.join(BACKEND_DIR, "data", "queue.txt")
        with open(queue_file, "r") as f:
            for line in f:
                data = line.strip().split("|")

                queue.append({
                    "token": int(data[0]),
                    "patient_id": int(data[1]),
                    "doctor_id": int(data[2]),
                    "priority": data[3],
                    "status": data[4]
                })
    except:
        pass

    return queue

def process_queue(queue):

    queue.sort(key=lambda x: (x["priority"] != "Urgent", x["token"]))

    waiting = []
    completed = []

    for q in queue:
        if q["status"] == "Waiting":
            waiting.append(q)
        elif q["status"] == "Completed":
            completed.append(q)

    next_patient = waiting[0] if waiting else None

    return queue, next_patient, len(waiting), len(completed)

# dashboard
@app.route("/")
def dashboard():
    queue = read_queue()
    queue, next_patient, waiting_count, completed_count = process_queue(queue)
    return render_template("dashboard.html", queue=queue, next_patient=next_patient, waiting_count=waiting_count, completed_count=completed_count)

#patient
@app.route("/patient")
def patient():
    return render_template("patient.html")


#queue
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
    department = request.form["department"]

    exe_path = os.path.join(BACKEND_DIR, "c_modules", "patient.exe")

    data_string = f"{name}|{age}|{gender}|{phone}|{address}|{symptoms}|{visit_type}|{priority}|{department}"
    
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

    queue_exe_path = os.path.join(BACKEND_DIR, "c_modules", "queue.exe")

    return render_template("add_patient.html", patient_id=id, visit_type=visit_type, department=department, priority=priority)

@app.route("/queue")
def queue_page():

    queue = read_queue()
    queue, next_patient, waiting_count, completed_count = process_queue(queue)

    return render_template("queue.html",queue=queue, next_patient=next_patient, waiting_count=waiting_count, completed_count=completed_count )


# Serve next patient
@app.route("/serve", methods=["POST"])
def serve():

    serve_exe = os.path.join(BACKEND_DIR, "c_modules", "serve.exe")

    serve_output = subprocess.run(
        [serve_exe],
        capture_output=True,
        text=True
    )

    serve_output = serve_output.stdout.strip()

    return redirect("/queue")


if __name__ == "__main__":
    app.run(debug=True, port=5000)