import os
import re
import csv
import io
import requests
from datetime import date
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, Response


from dotenv import load_dotenv

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore, auth





# Load environment variables from .env file
load_dotenv()

FIREBASE_WEB_API_KEY = os.environ.get('FIREBASE_WEB_API_KEY')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'default-dev-secret-key')


# Firebase Firestore Initialization
db = None
firebase_init_error = None

try:
    local_key = 'serviceAccountKey.json'
    env_key = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    env_json_str = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')

    cred = None

    if os.path.exists(local_key):
        cred = credentials.Certificate(local_key)
    elif env_key and os.path.exists(env_key):
        cred = credentials.Certificate(env_key)
    elif env_json_str:
        import json, base64
        try:
            dict_data = json.loads(env_json_str)
        except Exception:
            dict_data = json.loads(base64.b64decode(env_json_str).decode('utf-8'))
        cred = credentials.Certificate(dict_data)

    if not firebase_admin._apps:
        if cred:
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
            
    db = firestore.client()
except Exception as e:
    db = None
    firebase_init_error = f"Firebase Firestore Initialization Error: {str(e)}"



ALLOWED_BRANCHES = ['CSE', 'CSD', 'CSM', 'CAI', 'IT', 'ECE', 'EEE', 'ME', 'Civil']
ALLOWED_APPLICATION_STATUSES = ['Applied', 'Shortlisted', 'Interview', 'Selected', 'Rejected']
EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

# Helper Firestore Data Access Functions

def check_db_ready():
    if db is None:
        return False, firebase_init_error or "Firestore database client is not initialized."
    return True, None

def get_latest_student():
    if db is None:
        return None
    try:
        user_docs = list(db.collection('users').where('role', '==', 'student').stream())
        if not user_docs:
            return None
        latest_doc = user_docs[-1]
        student = latest_doc.to_dict()
        student['id'] = latest_doc.id
        return student
    except Exception as e:
        print(f"Error fetching latest student from Firestore: {e}")
        return None

def get_logged_in_student():
    user_id = session.get('user_id')
    if user_id and db is not None:
        try:
            doc = db.collection('users').document(user_id).get()
            if doc.exists:
                student = doc.to_dict()
                student['id'] = doc.id
                return student
        except Exception as e:
            print(f"Error fetching logged-in student profile from Firestore: {e}")
    return get_latest_student()


# Route Protection Decorators

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def student_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        if session.get('role') != 'student':
            return render_template('login.html', error="Access Denied: Student account required.", email=''), 403
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            return render_template('login.html', error="Access Denied: Admin privileges required.", email=''), 403
        return f(*args, **kwargs)
    return decorated_function



def get_all_companies():
    if db is None:
        return []
    try:
        docs = db.collection('companies').stream()
        return [{'id': doc.id, **doc.to_dict()} for doc in docs]
    except Exception as e:
        print(f"Error fetching companies from Firestore: {e}")
        return []

def get_all_drives():
    if db is None:
        return []
    try:
        docs = db.collection('placement_drives').stream()
        return [{'id': doc.id, **doc.to_dict()} for doc in docs]
    except Exception as e:
        print(f"Error fetching placement drives from Firestore: {e}")
        return []

def get_applications_for_student(student_id):
    if db is None or not student_id:
        return {}
    try:
        docs = db.collection('applications').where('student_id', '==', student_id).stream()
        return {doc.to_dict().get('drive_id'): doc.to_dict().get('status', 'Applied') for doc in docs}
    except Exception as e:
        print(f"Error fetching student applications from Firestore: {e}")
        return {}

def is_drive_open(application_deadline):
    """
    Safely determines whether a placement drive is currently open based on its deadline.
    Returns True if deadline >= date.today() or if deadline is missing/invalid (fallback).
    """
    if not application_deadline:
        return True  # Fallback for missing deadline: assume open
    try:
        deadline_str = str(application_deadline).strip()
        deadline_date = date.fromisoformat(deadline_str)
        return deadline_date >= date.today()
    except Exception:
        try:
            return str(application_deadline).strip() >= date.today().isoformat()
        except Exception:
            return True  # Fallback for unexpected format: assume open


def check_eligibility(student, drive):
    """
    Evaluates whether a student meets all eligibility criteria for a placement drive.
    Returns a tuple: (is_eligible: bool, failure_reasons: list[str])
    """
    reasons = []

    # Convert types to ensure accurate numerical comparisons
    student_cgpa = float(student.get('cgpa', 0.0))
    min_cgpa = float(drive.get('minimum_cgpa', 0.0))
    
    student_grad_year = int(student.get('graduation_year', 0))
    drive_grad_year = int(drive.get('graduation_year', 0))

    student_backlogs = int(student.get('backlogs', 0))
    drive_backlogs_allowed = int(drive.get('backlogs_allowed', 0))

    eligible_branches = drive.get('eligible_branches', [])

    # 1. CGPA Check
    if student_cgpa < min_cgpa:
        reasons.append(f"Your CGPA is {student_cgpa}, but the minimum required CGPA is {min_cgpa}.")

    # 2. Branch Check
    if student.get('branch') not in eligible_branches:
        reasons.append(f"Your branch ({student.get('branch')}) is not listed in the eligible branches ({', '.join(eligible_branches)}).")

    # 3. Graduation Year Check
    if student_grad_year != drive_grad_year:
        reasons.append(f"Your graduation year ({student_grad_year}) does not match the target year ({drive_grad_year}).")

    # 4. Backlogs Check
    if student_backlogs > drive_backlogs_allowed:
        reasons.append(f"Your backlogs ({student_backlogs}) exceed the maximum allowed ({drive_backlogs_allowed}).")

    is_eligible = (len(reasons) == 0)
    return is_eligible, reasons

def get_evaluated_drives(current_student):
    """
    Helper function to evaluate eligibility and application status for all placement drives stored in Firestore.
    """
    drives = get_all_drives()
    student_apps = get_applications_for_student(current_student['id']) if current_student else {}
    evaluated_drives = []

    for drive in drives:
        is_open = is_drive_open(drive.get('application_deadline'))

        if current_student:
            is_eligible, reasons = check_eligibility(current_student, drive)
            already_applied = drive['id'] in student_apps
            application_status = student_apps.get(drive['id']) if already_applied else None
        else:
            is_eligible, reasons = False, ["Please register as a student first."]
            already_applied = False
            application_status = None

        evaluated_drives.append({
            'drive': drive,
            'is_eligible': is_eligible,
            'is_open': is_open,
            'already_applied': already_applied,
            'application_status': application_status,
            'reasons': reasons
        })

    return evaluated_drives


def get_all_applications_with_student_details():
    if db is None:
        return []
    try:
        app_docs = db.collection('applications').stream()
        applications_data = []

        for doc in app_docs:
            app_data = doc.to_dict()
            app_id = doc.id
            student_id = app_data.get('student_id')

            student = None
            if student_id:
                try:
                    s_doc = db.collection('users').document(student_id).get()
                    if s_doc.exists:
                        student = s_doc.to_dict()
                except Exception:
                    student = None

            applications_data.append({
                'id': app_id,
                'student_id': student_id,
                'student_name': student.get('name') if student else app_data.get('student_name', 'N/A'),
                'student_email': student.get('email') if student else 'N/A',
                'student_branch': student.get('branch') if student else 'N/A',
                'drive_id': app_data.get('drive_id', 'N/A'),
                'company_name': app_data.get('company_name', 'N/A'),
                'job_role': app_data.get('job_role', 'N/A'),
                'applied_date': app_data.get('applied_date', 'N/A'),
                'status': app_data.get('status', 'Applied')
            })

        return applications_data
    except Exception as e:
        print(f"Error fetching applications data from Firestore: {e}")
        return []

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not email or not password:
            return render_template('login.html', error="Email and Password are required.", email=email)

        ready, err_msg = check_db_ready()
        if not ready:
            return render_template('login.html', error=err_msg, email=email)

        if not FIREBASE_WEB_API_KEY:
            return render_template('login.html', error="Firebase Web API Key is missing in environment (.env).", email=email)

        auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_WEB_API_KEY}"
        auth_payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True
        }

        try:
            auth_resp = requests.post(auth_url, json=auth_payload, timeout=10)
            auth_json = auth_resp.json()
        except Exception as req_err:
            return render_template('login.html', error=f"Network error connecting to Firebase Authentication: {str(req_err)}", email=email)

        if auth_resp.status_code != 200:
            err_info = auth_json.get('error', {})
            raw_msg = err_info.get('message', 'INVALID_LOGIN')

            if 'EMAIL_NOT_FOUND' in raw_msg:
                friendly_err = "No account found with this email address. Please register as a student first."
            elif 'INVALID_PASSWORD' in raw_msg:
                friendly_err = "Incorrect password. Please try again."
            elif 'USER_DISABLED' in raw_msg:
                friendly_err = "This user account has been disabled."
            elif 'INVALID_LOGIN_CREDENTIALS' in raw_msg:
                friendly_err = "Invalid email or password. Please check your credentials."
            elif 'INVALID_KEY' in raw_msg or 'API_KEY_INVALID' in raw_msg:
                friendly_err = "Invalid Firebase Web API Key in configuration."
            else:
                friendly_err = "Authentication failed. Please check your email and password."

            return render_template('login.html', error=friendly_err, email=email)

        id_token = auth_json.get('idToken')
        if not id_token:
            return render_template('login.html', error="Failed to retrieve authentication token from Firebase.", email=email)

        # Verify ID token server-side using Firebase Admin SDK
        try:
            decoded_token = auth.verify_id_token(id_token)
            verified_uid = decoded_token.get('uid')
        except Exception as token_err:

            return render_template('login.html', error=f"Firebase token verification failed: {str(token_err)}", email=email)

        # Retrieve user profile from Firestore users/{uid}
        try:
            user_doc = db.collection('users').document(verified_uid).get()
            if not user_doc.exists:
                return render_template('login.html', error="No user profile found for this account. Please register as a student first.", email=email)
            
            user_data = user_doc.to_dict()
        except Exception as doc_err:
            return render_template('login.html', error=f"Error fetching user profile from database: {str(doc_err)}", email=email)

        role = user_data.get('role', 'student')

        # Set Flask Session (Server-managed)
        session.clear()
        session['user_id'] = verified_uid
        session['role'] = role
        session['name'] = user_data.get('name', 'User')
        session['email'] = user_data.get('email', email)

        if role == 'admin':
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('student_drives'))


    return render_template('login.html', email='')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        branch = request.form.get('branch', '').strip()
        cgpa_str = request.form.get('cgpa', '').strip()
        grad_year_str = request.form.get('graduation_year', '').strip()
        backlogs_str = request.form.get('backlogs', '').strip()

        form_data = {
            'full_name': full_name,
            'email': email,
            'branch': branch,
            'cgpa': cgpa_str,
            'graduation_year': grad_year_str,
            'backlogs': backlogs_str
        }

        # Check DB Ready
        ready, err_msg = check_db_ready()
        if not ready:
            return render_template('register.html', error=err_msg, form_data=form_data)

        # 1. Full Name Validation: Non-empty & letters/spaces only
        if not full_name:
            return render_template('register.html', error="Full Name cannot be empty.", form_data=form_data)
        
        cleaned_name = full_name.replace(' ', '')
        if not cleaned_name.isalpha():
            return render_template('register.html', error="Full Name must contain only letters and spaces.", form_data=form_data)

        # 2. Email Validation: Non-empty & basic regex structure
        if not email:
            return render_template('register.html', error="Email Address cannot be empty.", form_data=form_data)
        
        if not re.match(EMAIL_REGEX, email):
            return render_template('register.html', error="Please enter a valid email address (e.g. student@example.com).", form_data=form_data)

        # 3. Password Validation: Minimum 6 characters & match confirmation
        if not password or len(password) < 6:
            return render_template('register.html', error="Password must be at least 6 characters long.", form_data=form_data)

        if password != confirm_password:
            return render_template('register.html', error="Passwords do not match.", form_data=form_data)

        # 4. Branch Validation: Must be in allowed short codes
        if branch not in ALLOWED_BRANCHES:
            return render_template('register.html', error="Please select a valid branch from the list.", form_data=form_data)

        # 5. CGPA Validation: Number between 0.0 and 10.0
        try:
            cgpa = float(cgpa_str)
            if cgpa < 0.0 or cgpa > 10.0:
                return render_template('register.html', error="CGPA must be between 0.0 and 10.0.", form_data=form_data)
        except ValueError:
            return render_template('register.html', error="CGPA must be a valid number.", form_data=form_data)

        # 6. Graduation Year Validation: Number between 2020 and 2035
        try:
            grad_year = int(grad_year_str)
            if grad_year < 2020 or grad_year > 2035:
                return render_template('register.html', error="Graduation Year must be between 2020 and 2035.", form_data=form_data)
        except ValueError:
            return render_template('register.html', error="Graduation Year must be a valid number.", form_data=form_data)

        # 7. Backlogs Validation: Number between 0 and 20
        try:
            backlogs = int(backlogs_str)
            if backlogs < 0 or backlogs > 20:
                return render_template('register.html', error="Number of backlogs must be between 0 and 20.", form_data=form_data)
        except ValueError:
            return render_template('register.html', error="Backlogs must be a valid number.", form_data=form_data)

        # 8. Firebase Authentication Account Creation (Identity Toolkit REST API)
        if not FIREBASE_WEB_API_KEY:
            return render_template('register.html', error="Firebase Web API Key is missing in environment (.env).", form_data=form_data)

        auth_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_WEB_API_KEY}"
        auth_payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True
        }

        try:
            auth_resp = requests.post(auth_url, json=auth_payload, timeout=10)
            auth_json = auth_resp.json()
        except Exception as req_err:
            return render_template('register.html', error=f"Network error connecting to Firebase Authentication: {str(req_err)}", form_data=form_data)

        if auth_resp.status_code != 200:
            err_info = auth_json.get('error', {})
            raw_msg = err_info.get('message', 'UNKNOWN_ERROR')

            if 'EMAIL_EXISTS' in raw_msg:
                friendly_err = "An account with this email address already exists. Please use a different email or log in."
            elif 'WEAK_PASSWORD' in raw_msg:
                friendly_err = "Password is too weak. Please use at least 6 characters."
            elif 'INVALID_KEY' in raw_msg or 'API_KEY_INVALID' in raw_msg:
                friendly_err = "Invalid Firebase Web API Key in configuration."
            elif 'TOO_MANY_ATTEMPTS' in raw_msg:
                friendly_err = "Too many failed registration attempts. Please try again later."
            else:
                friendly_err = f"Firebase Authentication Failed: {raw_msg}"

            return render_template('register.html', error=friendly_err, form_data=form_data)

        uid = auth_json.get('localId')
        if not uid:
            return render_template('register.html', error="Failed to retrieve user ID from Firebase Authentication.", form_data=form_data)

        # 9. Save student document to Firestore 'users/{uid}'
        try:
            db.collection('users').document(uid).set({
                'name': full_name,
                'email': email,
                'branch': branch,
                'cgpa': cgpa,
                'graduation_year': grad_year,
                'backlogs': backlogs,
                'role': 'student',
                'created_at': firestore.SERVER_TIMESTAMP
            })

            new_student = {
                'id': uid,
                'name': full_name,
                'email': email,
                'branch': branch,
                'cgpa': cgpa,
                'graduation_year': grad_year,
                'backlogs': backlogs
            }
            return render_template('register_success.html', student=new_student)
        except Exception as e:
            return render_template('register.html', error=f"Firestore Save Failed: {str(e)}", form_data=form_data)

    return render_template('register.html', form_data={})


@app.route('/student/drives')
@student_required
def student_drives():
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('student_drives.html', error=err_msg, student=None, drives=[])

    current_student = get_logged_in_student()
    return render_template('student_drives.html', student=current_student, drives=get_evaluated_drives(current_student))

@app.route('/student/drive/<drive_id>')
@student_required
def student_drive_detail(drive_id):
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('student_drive_detail.html', error=err_msg, drive=None), 503
    try:
        doc = db.collection('placement_drives').document(drive_id).get()
        if not doc.exists:
            return render_template('student_drive_detail.html', error='Placement drive not found.', drive=None), 404
        drive = doc.to_dict()
        drive['id'] = doc.id
        drive['is_open'] = is_drive_open(drive.get('application_deadline'))
        student = get_logged_in_student()
        if not student:
            return render_template('student_drive_detail.html', error='Student profile not found.', drive=None), 404
        eligible, reasons = check_eligibility(student, drive)
        applications = get_applications_for_student(student['id'])
        applied = drive_id in applications
        return render_template('student_drive_detail.html', drive=drive, is_eligible=eligible,
                               reasons=reasons, already_applied=applied,
                               application_status=applications.get(drive_id), student=student)
    except Exception as e:
        return render_template('student_drive_detail.html', error=f'Unable to load placement drive: {e}', drive=None), 500

@app.route('/student/profile')
@student_required
def student_profile():
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('student_profile.html', error=err_msg, student=None)

    current_student = get_logged_in_student()
    if not current_student:
        return render_template('student_profile.html', error="Student profile not found.", student=None)

    return render_template('student_profile.html', student=current_student)


@app.route('/student/profile/resume', methods=['POST'])
@student_required
def save_resume_link():
    ready, err_msg = check_db_ready()
    current_student = get_logged_in_student()
    if not ready:
        return render_template('student_profile.html', error=err_msg, student=current_student)

    if not current_student:
        return render_template('student_profile.html', error="Student profile not found.", student=None)

    user_id = session.get('user_id')
    if not user_id:
        return render_template('student_profile.html', error="Authentication error. Please log in again.", student=current_student)

    resume_link = request.form.get('resume_link', '').strip()

    if not resume_link:
        return render_template('student_profile.html', error="Resume link cannot be empty.", student=current_student)

    if not re.match(r'^https?://[^\s]+$', resume_link, re.IGNORECASE):
        return render_template('student_profile.html', error="Please enter a valid resume URL starting with http:// or https://.", student=current_student)

    try:
        db.collection('users').document(user_id).update({
            'resume_link': resume_link
        })
        updated_student = get_logged_in_student()
        return render_template('student_profile.html', success="Resume link saved successfully.", student=updated_student)
    except Exception as e:
        print(f"Resume link update error: {e}")
        return render_template('student_profile.html', error=f"Firestore error saving resume link: {str(e)}", student=current_student)



@app.route('/student/applications')
@student_required
def student_applications():
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('student_applications.html', error=err_msg, applications_data=[])

    user_id = session.get('user_id')
    if not user_id or db is None:
        return render_template('student_applications.html', error="User not authenticated.", applications_data=[])

    try:
        app_docs = list(db.collection('applications').where('student_id', '==', user_id).stream())
        applications_data = []
        for doc in app_docs:
            data = doc.to_dict()
            applications_data.append({
                'id': doc.id,
                'company_name': data.get('company_name', 'N/A'),
                'job_role': data.get('job_role', 'N/A'),
                'applied_date': data.get('applied_date', 'N/A'),
                'status': data.get('status', 'Applied')
            })
        return render_template('student_applications.html', applications_data=applications_data)
    except Exception as e:
        return render_template('student_applications.html', error=f"Firestore error fetching applications: {str(e)}", applications_data=[])


@app.route('/student/apply/<drive_id>', methods=['POST'])
@student_required
def apply_drive(drive_id):
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('student_drives.html', error=err_msg, student=None, drives=[])

    # 1. Identify current student
    current_student = get_logged_in_student()
    if not current_student:
        return render_template('student_drives.html', error="Please register as a student first before applying.", student=None, drives=[])

    # 2. Identify target placement drive from Firestore
    try:
        drive_doc = db.collection('placement_drives').document(drive_id).get()
        if not drive_doc.exists:
            return render_template('student_drives.html', error="The requested placement drive was not found.", student=current_student, drives=get_evaluated_drives(current_student))
        drive = {'id': drive_doc.id, **drive_doc.to_dict()}
    except Exception as e:
        return render_template('student_drives.html', error=f"Firestore error fetching drive: {str(e)}", student=current_student, drives=get_evaluated_drives(current_student))

    # 3. Server-side Eligibility Re-check
    is_eligible, reasons = check_eligibility(current_student, drive)
    if not is_eligible:
        error_msg = f"Application Blocked: You are not eligible for this drive. Reason: {' '.join(reasons)}"
        return render_template('student_drives.html', error=error_msg, student=current_student, drives=get_evaluated_drives(current_student))

    # 4. Server-side Deadline Enforcement Check
    if not is_drive_open(drive.get('application_deadline')):
        return render_template('student_drives.html', error="Application deadline for this drive has passed.", student=current_student, drives=get_evaluated_drives(current_student))

    # 5. Duplicate Application Check in Firestore
    try:
        existing_apps = list(db.collection('applications').where('student_id', '==', current_student['id']).where('drive_id', '==', drive_id).stream())
        if existing_apps:
            return render_template('student_drives.html', error="You have already applied for this placement drive.", student=current_student, drives=get_evaluated_drives(current_student))
    except Exception as e:
        return render_template('student_drives.html', error=f"Firestore error checking existing application: {str(e)}", student=current_student, drives=get_evaluated_drives(current_student))

    # 6. Create & Store Application in Firestore 'applications' collection
    try:
        doc_ref = db.collection('applications').add({
            'student_id': current_student['id'],
            'student_name': current_student['name'],
            'drive_id': drive['id'],
            'company_name': drive['company_name'],
            'job_role': drive['job_role'],
            'applied_date': date.today().isoformat(),
            'status': 'Applied'
        })[1]

        new_application = {
            'id': doc_ref.id,
            'student_name': current_student['name'],
            'company_name': drive['company_name'],
            'job_role': drive['job_role'],
            'applied_date': date.today().isoformat(),
            'status': 'Applied'
        }
        return render_template('application_success.html', application=new_application)
    except Exception as e:
        return render_template('student_drives.html', error=f"Firestore error saving application: {str(e)}", student=current_student, drives=get_evaluated_drives(current_student))

@app.route('/admin')
@admin_required
def admin():
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('admin_dashboard.html', error=err_msg, companies_count=0, drives_count=0, apps_count=0)

    try:
        companies_count = len(list(db.collection('companies').stream()))
        all_drives = get_all_drives()
        drives_count = len([d for d in all_drives if is_drive_open(d.get('application_deadline'))])
        apps_count = len(list(db.collection('applications').stream()))
    except Exception as e:
        print(f"Error calculating counts from Firestore: {e}")
        companies_count, drives_count, apps_count = 0, 0, 0

    return render_template('admin_dashboard.html', 
                           companies_count=companies_count, 
                           drives_count=drives_count, 
                           apps_count=apps_count)

@app.route('/admin/companies')
@admin_required
def admin_companies():
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('admin_companies.html', error=err_msg, companies_data=[])

    try:
        companies_list = get_all_companies()
        return render_template('admin_companies.html', companies_data=companies_list)
    except Exception as e:
        return render_template('admin_companies.html', error=f"Firestore error fetching companies: {str(e)}", companies_data=[])

@app.route('/admin/drives')
@admin_required
def admin_drives():
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('admin_drives.html', error=err_msg, drives_data=[])

    try:
        drives_list = get_all_drives()
        for d in drives_list:
            d['is_open'] = is_drive_open(d.get('application_deadline'))
        return render_template('admin_drives.html', drives_data=drives_list)
    except Exception as e:
        return render_template('admin_drives.html', error=f"Firestore error fetching placement drives: {str(e)}", drives_data=[])


@app.route('/admin/applications')
@admin_required
def admin_applications():
    ready, err_msg = check_db_ready()
    companies_list = get_all_companies() if ready else []
    if not ready:
        return render_template('admin_applications.html', error=err_msg, applications_data=[], allowed_statuses=ALLOWED_APPLICATION_STATUSES, companies_list=[], selected_status='All', selected_company='All', search_q='')

    search_q = request.args.get('q', '').strip()
    selected_status = request.args.get('status', 'All').strip()
    selected_company = request.args.get('company', 'All').strip()

    all_apps = get_all_applications_with_student_details()
    filtered_apps = []
    search_lower = search_q.lower()

    for app_item in all_apps:
        status_match = (selected_status == 'All' or not selected_status or app_item.get('status') == selected_status)
        company_match = (selected_company == 'All' or not selected_company or app_item.get('company_name') == selected_company)

        if search_lower:
            name_text = app_item.get('student_name', '').lower()
            role_text = app_item.get('job_role', '').lower()
            q_match = (search_lower in name_text or search_lower in role_text)
        else:
            q_match = True

        if status_match and company_match and q_match:
            filtered_apps.append(app_item)

    return render_template(
        'admin_applications.html', 
        applications_data=filtered_apps, 
        allowed_statuses=ALLOWED_APPLICATION_STATUSES,
        companies_list=companies_list,
        selected_status=selected_status,
        selected_company=selected_company,
        search_q=search_q
    )

@app.route('/admin/application/<application_id>')
@admin_required
def admin_application_detail(application_id):
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('admin_application_detail.html', error=err_msg, application=None, student=None, drive=None, allowed_statuses=ALLOWED_APPLICATION_STATUSES)

    try:
        app_doc = db.collection('applications').document(application_id).get()
        if not app_doc.exists:
            return render_template('admin_application_detail.html', error="Application not found.", application=None, student=None, drive=None, allowed_statuses=ALLOWED_APPLICATION_STATUSES), 404

        app_data = app_doc.to_dict()
        app_data['id'] = app_doc.id

        # Safely fetch linked student document
        student_data = None
        student_id = app_data.get('student_id')
        if student_id:
            try:
                s_doc = db.collection('users').document(student_id).get()
                if s_doc.exists:
                    student_data = s_doc.to_dict()
            except Exception:
                student_data = None

        # Safely fetch linked placement drive document
        drive_data = None
        drive_id = app_data.get('drive_id')
        if drive_id:
            try:
                d_doc = db.collection('placement_drives').document(drive_id).get()
                if d_doc.exists:
                    drive_data = d_doc.to_dict()
            except Exception:
                drive_data = None

        return render_template(
            'admin_application_detail.html',
            application=app_data,
            student=student_data,
            drive=drive_data,
            allowed_statuses=ALLOWED_APPLICATION_STATUSES
        )
    except Exception as e:
        return render_template('admin_application_detail.html', error=f"Firestore error fetching application details: {str(e)}", application=None, student=None, drive=None, allowed_statuses=ALLOWED_APPLICATION_STATUSES)

@app.route('/admin/application/<application_id>/status', methods=['POST'])
@admin_required
def update_application_status(application_id):
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('admin_applications.html', error=err_msg, applications_data=[], allowed_statuses=ALLOWED_APPLICATION_STATUSES)

    new_status = request.form.get('status', '').strip()
    redirect_to = request.form.get('redirect_to', '').strip()

    # 1. Validate status against ALLOWED_APPLICATION_STATUSES
    if new_status not in ALLOWED_APPLICATION_STATUSES:
        if redirect_to == 'detail':
            return redirect(url_for('admin_application_detail', application_id=application_id))
        return render_template(
            'admin_applications.html', 
            error=f"Invalid status '{new_status}'. Allowed statuses are: {', '.join(ALLOWED_APPLICATION_STATUSES)}",
            applications_data=get_all_applications_with_student_details(),
            allowed_statuses=ALLOWED_APPLICATION_STATUSES
        )

    # 2. Find target application in Firestore
    try:
        app_ref = db.collection('applications').document(application_id)
        app_doc = app_ref.get()
        if not app_doc.exists:
            if redirect_to == 'detail':
                return redirect(url_for('admin_application_detail', application_id=application_id))
            return render_template(
                'admin_applications.html', 
                error=f"Application ID #{application_id} was not found in Firestore.",
                applications_data=get_all_applications_with_student_details(),
                allowed_statuses=ALLOWED_APPLICATION_STATUSES
            )

        # 3. Update status in Firestore document
        app_ref.update({'status': new_status})

        if redirect_to == 'detail':
            return redirect(url_for('admin_application_detail', application_id=application_id))
        return redirect(url_for('admin_applications'))
    except Exception as e:
        if redirect_to == 'detail':
            return redirect(url_for('admin_application_detail', application_id=application_id))
        return render_template(
            'admin_applications.html', 
            error=f"Firestore update error: {str(e)}",
            applications_data=get_all_applications_with_student_details(),
            allowed_statuses=ALLOWED_APPLICATION_STATUSES
        )


@app.route('/admin/company/add', methods=['GET', 'POST'])
@admin_required
def add_company():
    if request.method == 'POST':
        company_name = request.form.get('company_name', '').strip()
        description = request.form.get('description', '').strip()
        website = request.form.get('website', '').strip()

        form_data = {
            'company_name': company_name,
            'description': description,
            'website': website
        }

        ready, err_msg = check_db_ready()
        if not ready:
            return render_template('add_company.html', error=err_msg, form_data=form_data)

        # 1. Company Name Validation: Must not be empty
        if not company_name:
            return render_template('add_company.html', error="Company Name cannot be empty.", form_data=form_data)

        # 2. Company Description Validation: Must not be empty
        if not description:
            return render_template('add_company.html', error="Company Description cannot be empty.", form_data=form_data)

        # 3. Company Website Validation: Optional, but if provided must start with http:// or https://
        if website:
            if not (website.startswith('http://') or website.startswith('https://')):
                return render_template('add_company.html', error="Website URL must start with http:// or https://", form_data=form_data)

        # Save company to Firestore 'companies' collection
        try:
            doc_ref = db.collection('companies').add({
                'company_name': company_name,
                'description': description,
                'website': website
            })[1]

            new_company = {
                'id': doc_ref.id,
                'company_name': company_name,
                'description': description,
                'website': website
            }
            return render_template('add_company_success.html', company=new_company)
        except Exception as e:
            return render_template('add_company.html', error=f"Firestore error saving company: {str(e)}", form_data=form_data)

    return render_template('add_company.html', form_data={})

@app.route('/admin/drive/add', methods=['GET', 'POST'])
@admin_required
def add_drive():

    companies_list = get_all_companies()

    if request.method == 'POST':
        company_id_str = request.form.get('company_id', '').strip()
        job_role = request.form.get('job_role', '').strip()
        job_description = request.form.get('job_description', '').strip()
        ctc = request.form.get('ctc', '').strip()
        min_cgpa_str = request.form.get('minimum_cgpa', '').strip()
        eligible_branches = request.form.getlist('eligible_branches')
        grad_year_str = request.form.get('graduation_year', '').strip()
        backlogs_allowed_str = request.form.get('backlogs_allowed', '').strip()
        app_deadline = request.form.get('application_deadline', '').strip()

        form_data = {
            'company_id': company_id_str,
            'job_role': job_role,
            'job_description': job_description,
            'ctc': ctc,
            'minimum_cgpa': min_cgpa_str,
            'eligible_branches': eligible_branches,
            'graduation_year': grad_year_str,
            'backlogs_allowed': backlogs_allowed_str,
            'application_deadline': app_deadline
        }

        ready, err_msg = check_db_ready()
        if not ready:
            return render_template('add_drive.html', error=err_msg, form_data=form_data, companies=companies_list)

        # 1. Company Selection Validation
        if not company_id_str:
            return render_template('add_drive.html', error="Please select a company.", form_data=form_data, companies=companies_list)
        
        selected_company = next((c for c in companies_list if str(c['id']) == company_id_str), None)
        if not selected_company:
            return render_template('add_drive.html', error="Selected company does not exist in Firestore.", form_data=form_data, companies=companies_list)

        # 2. Job Role Validation
        if not job_role:
            return render_template('add_drive.html', error="Job Role cannot be empty.", form_data=form_data, companies=companies_list)

        # 3. Job Description Validation
        if not job_description:
            return render_template('add_drive.html', error="Job Description cannot be empty.", form_data=form_data, companies=companies_list)

        # 4. CTC Validation
        if not ctc:
            return render_template('add_drive.html', error="CTC / Package cannot be empty.", form_data=form_data, companies=companies_list)

        # 5. Minimum CGPA Validation
        try:
            minimum_cgpa = float(min_cgpa_str)
            if minimum_cgpa < 0.0 or minimum_cgpa > 10.0:
                return render_template('add_drive.html', error="Minimum CGPA must be between 0.0 and 10.0.", form_data=form_data, companies=companies_list)
        except ValueError:
            return render_template('add_drive.html', error="Minimum CGPA must be a valid number.", form_data=form_data, companies=companies_list)

        # 6. Eligible Branches Validation
        if not eligible_branches:
            return render_template('add_drive.html', error="Please select at least one eligible branch.", form_data=form_data, companies=companies_list)

        for b in eligible_branches:
            if b not in ALLOWED_BRANCHES:
                return render_template('add_drive.html', error=f"Invalid branch '{b}' selected.", form_data=form_data, companies=companies_list)

        # 7. Graduation Year Validation
        try:
            grad_year = int(grad_year_str)
            if grad_year < 2020 or grad_year > 2035:
                return render_template('add_drive.html', error="Graduation Year must be between 2020 and 2035.", form_data=form_data, companies=companies_list)
        except ValueError:
            return render_template('add_drive.html', error="Graduation Year must be a valid number.", form_data=form_data, companies=companies_list)

        # 8. Backlogs Allowed Validation
        try:
            backlogs_allowed = int(backlogs_allowed_str)
            if backlogs_allowed < 0 or backlogs_allowed > 20:
                return render_template('add_drive.html', error="Backlogs allowed must be between 0 and 20.", form_data=form_data, companies=companies_list)
        except ValueError:
            return render_template('add_drive.html', error="Backlogs allowed must be a valid number.", form_data=form_data, companies=companies_list)

        # 9. Application Deadline Validation
        if not app_deadline:
            return render_template('add_drive.html', error="Application Deadline cannot be empty.", form_data=form_data, companies=companies_list)

        try:
            deadline_date = date.fromisoformat(app_deadline)
            if deadline_date < date.today():
                return render_template('add_drive.html', error="Application deadline cannot be in the past.", form_data=form_data, companies=companies_list)
        except ValueError:
            return render_template('add_drive.html', error="Please enter a valid application deadline.", form_data=form_data, companies=companies_list)

        # Save placement drive to Firestore 'placement_drives' collection
        try:
            doc_ref = db.collection('placement_drives').add({
                'company_id': company_id_str,
                'company_name': selected_company['company_name'],
                'job_role': job_role,
                'job_description': job_description,
                'ctc': ctc,
                'minimum_cgpa': minimum_cgpa,
                'eligible_branches': eligible_branches,
                'graduation_year': grad_year,
                'backlogs_allowed': backlogs_allowed,
                'application_deadline': app_deadline
            })[1]

            new_drive = {
                'id': doc_ref.id,
                'company_id': company_id_str,
                'company_name': selected_company['company_name'],
                'job_role': job_role,
                'job_description': job_description,
                'ctc': ctc,
                'minimum_cgpa': minimum_cgpa,
                'eligible_branches': eligible_branches,
                'graduation_year': grad_year,
                'backlogs_allowed': backlogs_allowed,
                'application_deadline': app_deadline
            }
            return render_template('add_drive_success.html', drive=new_drive)
        except Exception as e:
            return render_template('add_drive.html', error=f"Firestore error saving drive: {str(e)}", form_data=form_data, companies=companies_list)

    return render_template('add_drive.html', form_data={}, companies=companies_list)


def _edit_drive_values(form, existing, companies_list):
    """Validate a drive edit and return a schema-compatible update dictionary."""
    company_id = form.get('company_id', '').strip()
    company = next((c for c in companies_list if str(c['id']) == company_id), None)
    if not company:
        return None, 'Please select a registered company.'
    role = form.get('job_role', '').strip()
    description = form.get('job_description', '').strip()
    ctc = form.get('ctc', '').strip()
    branches = list(dict.fromkeys(form.getlist('eligible_branches')))
    deadline = form.get('application_deadline', '').strip()
    if not role or not description or not ctc:
        return None, 'Job role, description, and CTC are required.'
    if not branches or any(branch not in ALLOWED_BRANCHES for branch in branches):
        return None, 'Select at least one valid eligible branch.'
    try:
        cgpa = float(form.get('minimum_cgpa', '').strip())
        grad_year = int(form.get('graduation_year', '').strip())
        backlogs = int(form.get('backlogs_allowed', '').strip())
        deadline_date = date.fromisoformat(deadline)
    except (TypeError, ValueError):
        return None, 'Enter valid CGPA, graduation year, backlog count, and application deadline.'
    if not 0 <= cgpa <= 10:
        return None, 'Minimum CGPA must be between 0.0 and 10.0.'
    if not 2020 <= grad_year <= 2035:
        return None, 'Graduation year must be between 2020 and 2035.'
    if not 0 <= backlogs <= 20:
        return None, 'Backlogs allowed must be between 0 and 20.'
    old_deadline = existing.get('application_deadline')
    if deadline_date < date.today() and deadline != old_deadline:
        return None, 'A changed application deadline cannot be in the past.'
    return {
        'company_id': company_id, 'company_name': company['company_name'],
        'job_role': role, 'job_description': description, 'ctc': ctc,
        'minimum_cgpa': cgpa, 'eligible_branches': branches,
        'graduation_year': grad_year, 'backlogs_allowed': backlogs,
        'application_deadline': deadline
    }, None


@app.route('/admin/company/<company_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_company(company_id):
    ready, err_msg = check_db_ready()
    if not ready:
        return render_template('edit_company.html', error=err_msg, form_data={}), 503
    ref = db.collection('companies').document(company_id)
    try:
        doc = ref.get()
        if not doc.exists:
            return render_template('edit_company.html', error='Company not found.', form_data={}), 404
        existing = doc.to_dict()
        if request.method == 'GET':
            return render_template('edit_company.html', form_data=existing, company_id=company_id)
        form_data = {key: request.form.get(key, '').strip() for key in ('company_name', 'description', 'website')}
        if not form_data['company_name'] or not form_data['description']:
            return render_template('edit_company.html', error='Company name and description are required.', form_data=form_data, company_id=company_id)
        website = form_data['website']
        if website and not re.match(r'^https?://[^\s]+$', website, re.IGNORECASE):
            return render_template('edit_company.html', error='Enter a valid website beginning with http:// or https://.', form_data=form_data, company_id=company_id)
        ref.update(form_data)
        # Keep the existing drive company-name snapshot consistent with the company record.
        for drive_doc in db.collection('placement_drives').where('company_id', '==', company_id).stream():
            drive_doc.reference.update({'company_name': form_data['company_name']})
        return redirect(url_for('admin_companies'))
    except Exception as e:
        return render_template('edit_company.html', error=f'Unable to update company: {e}', form_data=request.form, company_id=company_id), 500


@app.route('/admin/drive/<drive_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_drive(drive_id):
    ready, err_msg = check_db_ready()
    companies_list = get_all_companies() if ready else []
    if not ready:
        return render_template('edit_drive.html', error=err_msg, form_data={}, companies=companies_list, allowed_branches=ALLOWED_BRANCHES), 503
    try:
        ref = db.collection('placement_drives').document(drive_id)
        doc = ref.get()
        if not doc.exists:
            return render_template('edit_drive.html', error='Placement drive not found.', form_data={}, companies=companies_list, allowed_branches=ALLOWED_BRANCHES), 404
        existing = doc.to_dict()
        if request.method == 'GET':
            return render_template('edit_drive.html', form_data=existing, companies=companies_list, drive_id=drive_id, allowed_branches=ALLOWED_BRANCHES)
        form_data = {key: request.form.get(key, '').strip() for key in
                     ('company_id', 'job_role', 'job_description', 'ctc', 'minimum_cgpa', 'graduation_year', 'backlogs_allowed', 'application_deadline')}
        form_data['eligible_branches'] = request.form.getlist('eligible_branches')
        update_data, validation_error = _edit_drive_values(request.form, existing, companies_list)
        if validation_error:
            return render_template('edit_drive.html', error=validation_error, form_data=form_data, companies=companies_list, drive_id=drive_id, allowed_branches=ALLOWED_BRANCHES)
        ref.update(update_data)
        return redirect(url_for('admin_drives'))
    except Exception as e:
        return render_template('edit_drive.html', error=f'Unable to update placement drive: {e}', form_data=request.form, companies=companies_list, drive_id=drive_id, allowed_branches=ALLOWED_BRANCHES), 500


@app.route('/admin/applications/export.csv')
@admin_required
def export_applications_csv():
    ready, err_msg = check_db_ready()
    if not ready:
        return err_msg, 503
    search_q = request.args.get('q', '').strip().lower()
    selected_status = request.args.get('status', 'All').strip()
    selected_company = request.args.get('company', 'All').strip()
    if selected_status not in ['All'] + ALLOWED_APPLICATION_STATUSES:
        selected_status = 'All'
    applications = get_all_applications_with_student_details()
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Application ID', 'Student ID', 'Student Name', 'Email', 'Branch', 'Company', 'Job Role', 'Drive ID', 'Applied Date', 'Status'])
    for item in applications:
        if selected_status != 'All' and item.get('status') != selected_status:
            continue
        if selected_company not in ('', 'All') and item.get('company_name') != selected_company:
            continue
        searchable = ' '.join((item.get('student_name', ''), item.get('job_role', ''))).lower()
        if search_q and search_q not in searchable:
            continue
        values = [item.get('id', ''), item.get('student_id', ''), item.get('student_name', ''),
                  item.get('student_email', ''), item.get('student_branch', ''), item.get('company_name', ''),
                  item.get('job_role', ''), item.get('drive_id', ''), item.get('applied_date', ''), item.get('status', '')]
        # Prevent spreadsheet formulas from executing when a CSV is opened.
        writer.writerow([("'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@')) else value) for value in values])
    return Response(output.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=placement_application_results.csv'})

if __name__ == '__main__':
    app.run(debug=True)
