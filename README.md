# Smart Placement Tracker

A comprehensive, production-ready web application designed for colleges and universities to manage campus placement drives, evaluate academic eligibility automatically, track student applications in real time, and streamline administrative recruitment workflows.

---

## 🌟 Key Features

### 🎓 Student Features
- **Firebase Authentication:** Secure student registration and login with email/password verification.
- **Academic Profile Management:** Registered academic credentials (CGPA, Branch, Graduation Year, Backlog count).
- **Placement Drive Discovery:** Browse active placement opportunities with real-time academic eligibility breakdown (CGPA, branch matching, graduation year, backlog allowance).
- **One-Click Drive Application:** Apply directly to eligible drives with automatic duplicate application prevention.
- **Application Tracking:** Track application status updates (`Applied`, `Shortlisted`, `Interview`, `Selected`, `Rejected`) in real time.
- **Shareable Resume Link:** Save and update a shareable resume link (Google Drive, OneDrive, portfolio URL) directly on the student profile.

### 🛡️ Admin Features
- **Analytics Dashboard:** Real-time metrics for total registered companies, active placement drives, and candidate applications.
- **Company Management:** Register new corporate hiring partners and update existing company details.
- **Placement Drive Management:** Create and edit placement drives with customized academic eligibility criteria and application deadlines.
- **Application Management & Filtering:** Search candidates by name/job role and filter applications by company and recruitment status.
- **Detailed Candidate Evaluation:** Review comprehensive student academic metrics alongside job drive requirements side-by-side.
- **Candidate Status Workflow:** Advance candidates through recruitment stages (`Applied` ➔ `Shortlisted` ➔ `Interview` ➔ `Selected` / `Rejected`).
- **Filtered Candidate CSV Export:** Export candidate application records to CSV format with automatic formula injection security protection.

---

## 🛠️ Technology Stack & Architecture

- **Backend Framework:** Python 3 & Flask
- **Database:** Firebase Cloud Firestore (NoSQL document database)
- **Authentication:** Firebase Authentication & Identity Toolkit REST API
- **Frontend & Styling:** HTML5 & Vanilla CSS (Responsive, dark-mode glassmorphism theme)
- **Environment Management:** `python-dotenv`
- **WSGI Production Server:** `gunicorn`
- **Zero JavaScript:** Built entirely using server-rendered Flask templates for maximum security and simplicity.

---

## 📊 Academic Eligibility Logic

Placement drive eligibility is evaluated automatically on a per-student basis:

$$\text{Eligible} = (\text{Student CGPA} \ge \text{Drive Min CGPA}) \land (\text{Student Branch} \in \text{Drive Eligible Branches}) \land (\text{Student Grad Year} == \text{Drive Grad Year}) \land (\text{Student Backlogs} \le \text{Drive Max Backlogs})$$

If any criteria fails, the exact disqualification reasons are rendered on the drive details view.

---

## 📁 Project Structure

```text
SmartPlacementTracker/
├── app.py                      # Core Flask application, routes, and business logic
├── requirements.txt            # Runtime dependencies
├── Procfile                    # Production WSGI entry point
├── render.yaml                 # Deployment blueprint configuration
├── .env.example                # Template for environment variables
├── .gitignore                  # Excluded sensitive credentials & backups
├── templates/                  # Server-rendered HTML templates
│   ├── index.html              # Public landing page
│   ├── login.html              # Authentication login page
│   ├── register.html           # Student registration page
│   ├── student_drives.html     # Student drive catalog view
│   ├── student_drive_detail.html# Detailed drive view & eligibility check
│   ├── student_profile.html    # Student profile & resume link management
│   ├── student_applications.html# Student application tracking history
│   ├── admin_dashboard.html    # Admin metrics dashboard
│   ├── admin_companies.html    # Company management view
│   ├── admin_drives.html       # Drive management view
│   ├── admin_applications.html # Applications list & filter view
│   ├── admin_application_detail.html # Candidate evaluation detail view
│   ├── add_company.html        # Register company form
│   ├── edit_company.html       # Edit company profile form
│   ├── add_drive.html          # Create placement drive form
│   └── edit_drive.html         # Edit placement drive form
└── static/
    └── style.css               # Modern vanilla CSS styling
```

---

## 🚀 Local Setup & Development

### 1. Prerequisites
- Python 3.9 or higher
- Firebase Project with Firestore Database & Authentication enabled

### 2. Environment Variables (`.env`)
Create a `.env` file in the root directory:

```env
SECRET_KEY=your-custom-flask-secret-key
FIREBASE_WEB_API_KEY=your-firebase-web-api-key
GOOGLE_APPLICATION_CREDENTIALS=serviceAccountKey.json
```

### 3. Installation
```bash
# Clone the repository
git clone <your-repository-url>
cd SmartPlacementTracker

# Create and activate virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Running Locally
```bash
python app.py
```
Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your web browser.

---

## 🌐 Production Deployment

The project is configured for cloud deployment platforms such as **Render**, **Railway**, or **Heroku**.

### Deploying on Render:
1. Connect your GitHub repository to Render.
2. Select **Web Service** (Python runtime).
3. Set Build Command: `pip install -r requirements.txt`
4. Set Start Command: `gunicorn app:app`
5. Configure Environment Variables in Render Dashboard:
   - `SECRET_KEY`: Random secret string
   - `FIREBASE_WEB_API_KEY`: Web API key from Firebase Console settings
   - `FIREBASE_SERVICE_ACCOUNT_JSON`: Contents of `serviceAccountKey.json` (raw JSON or base64 string)

---

## 📄 License
This project is created for educational and portfolio demonstration purposes.
