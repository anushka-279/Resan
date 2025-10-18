import os 
import io
import re
import json
import base64
from datetime import datetime
from dateutil import parser
from flask import Flask, request, jsonify, send_file, session, render_template_string
from werkzeug.utils import secure_filename
from pymongo import MongoClient
from bson.objectid import ObjectId
import bcrypt

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

try:
    from pdfminer.high_level import extract_text as pdf_extract_text
except Exception:  # pragma: no cover
    pdf_extract_text = None


###############################################################################
# Configuration
###############################################################################

def get_env(name: str, default: str = "") -> str:
    value = os.environ.get(name, default)
    if value is None:
        return default
    return value


MONGODB_URI = get_env("MONGODB_URI", "mongodb://localhost:27017")
SECRET_KEY = get_env("SECRET_KEY", os.urandom(24))
MAX_CONTENT_LENGTH_MB = int(get_env("MAX_CONTENT_LENGTH_MB", "10"))

ALLOWED_EXTENSIONS = {"pdf", "txt"}


###############################################################################
# App and DB initialization
###############################################################################

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_MB * 1024 * 1024

mongo_client = MongoClient(MONGODB_URI)
db = mongo_client["resume_analyzer"]
users_col = db["users"]
analyses_col = db["analyses"]


###############################################################################
# Utility functions
###############################################################################

def hash_password(plain: str) -> bytes:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())


def check_password(plain: str, hashed: bytes) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed)
    except ValueError:
        return False


def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    return filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_file(file_storage) -> str:
    filename = file_storage.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    data = file_storage.read()
    file_storage.seek(0)
    if ext == "pdf":
        if pdf_extract_text is None:
            raise RuntimeError("pdfminer.six is not installed")
        # Use BytesIO to avoid saving to disk
        with io.BytesIO(data) as bio:
            text = pdf_extract_text(bio) or ""
        return text
    elif ext == "txt":
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return data.decode("latin-1", errors="ignore")
    else:
        raise ValueError("Unsupported file type")


def normalize_text(text: str) -> str:
    # Collapse extra whitespace and standardize bullets
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\t", " ", text)
    text = re.sub(r"\u2022|\u25CF|\u25A0|\*", "-", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_email(text: str) -> str:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else ""


def extract_phone(text: str) -> str:
    match = re.search(r'(\+?\d{1,3}[\s\-]?)?\(?\d{3,5}\)?[\s\-]?\d{3,5}[\s\-]?\d{3,5}', text)
    return match.group(0) if match else "Not Found"


def validate_name_format(name: str) -> bool:
    return bool(re.match(r'^([A-Z][a-z]+)(\s[A-Z][a-z]+){0,2}$', name.strip()))


def guess_name(text: str, email: str) -> str:
    lines = text.strip().split("\n")

    # Try first 5 lines (most resumes put name at top)
    for line in lines[:5]:
        cleaned = re.sub(r'[^A-Za-z\s\-\'\.]', '', line).strip()
        if cleaned and len(cleaned.split()) <= 4 and validate_name_format(cleaned):
            return cleaned

    # Fallback: derive from email
    if email:
        local = email.split("@")[0]
        parts = re.split(r"[._\-]", local)
        # Only return if it looks like a name
        if len(parts) >= 2:
            return " ".join([w.capitalize() for w in parts if w.isalpha()])

    return "Unknown"


# Minimal job role catalog and skills mapping
JOB_ROLES = {
    "Software Engineer": [
        "Python", "Java", "C++", "Javascript", "Cloud Computing", "React", "SQL", "Git", "Docker", "Communication", "IDEs", "Optimization", "OOP"
        "REST", "API", "Version Control", "Databases", "Teamwork", "Problem Solving", "CI/CD", "Algorithms", "Data Structures"
    ],
    "Data Scientist": [
        "Python", "R", "Statistics", "Probability", "Linear Algebra", "Calculus", "NLP", "Computer Vision",
        "Machine Learning", "SQL", "Matplotlib", "Data Cleaning", "Pandas", "NumPy", "TensorFlow", "Feature Engineering", "Deep Learning", "Experiment Tracking"
    ],
    "Data Analyst": [
        "Excel", "SQL", "Tableau", "Power BI", "Python", "Pandas", "Data Visualization",
        "Reporting", "Dashboards", "Data Visualization", "R", "Statistics", "Reporting", "Cleaning", "ETL", "Insights", "Presentation", "PivotTables", "Queries", "Communication", "Databases", "Accuracy", "Documentation"
    ],
    "Product Manager": [
        "Roadmap", "User Research", "Analytics", "Agile", "Scrum", "Stakeholder Management", "Wireframing",
        "SQL", "A/B Testing", "KPIs", "Strategy", "Prioritization", "Communication", "Leadership", "Planning", "Negotiation", "Marketing", "Analysis", "Feedback", "Collaboration", "Design", "Business", "Vision", "Empathy", "Execution", "Adaptability", "Decision Making"
    ],
    "DevOps Engineer": [
        "Linux", "Bash", "Docker", "Kubernetes", "Terraform", "Ansible", "AWS", "Azure", "GCP", "Monitoring",
        "Prometheus", "Grafana", "CI/CD", "Git", "Networking", "Automation", "Linux", "Containers", "Scripting", "Cloud", "Monitoring", "Jenkins", "Security", "Configuration", "Orchestration", "Logging", "Troubleshooting", "Scalability", "Reliability"
    ],
    "UI/UX Designer": [
        "Figma", "Sketch", "Adobe XD", "Wireframing", "Prototyping", "User Research",
        "Design Systems", "HTML", "CSS", "Typography", "Color", "Layout", "Research", "Empathy", "Animation", "Usability", "Testing", "Branding", "Accessibility", "Heuristics", "Creativity", "Responsiveness", "Visuals", "Consistency"
    ],
    "QA Engineer": [
        "Test Cases", "Cypress", "Jest", "Pytest", "Manual Testing", "Jira", "Testing", "Automation", "Selenium", "Bugs", "Regression", "Reporting", "Documentation", "Scripting", "Quality", "Frameworks", "Debugging", "Databases", "Performance", "Reliability", "Accuracy", "Verification", "Validation", "Analysis", "CI/CD", "Tools"
    ],
    "Mobile Developer": [
        "Android", "Kotlin", "Java", "iOS", "Swift", "React Native", "Flutter", "Mobile UI", "REST", "Firebase",  "Objective-C", "APIs", "UI", "UX", "Testing", "Deployment", "Security", "Databases", "Push Notifications", "Performance", "Debugging", "Store Submission"
    ],
    "AI/ML Engineer": [
        "Python", "PyTorch", "TensorFlow", "MLOps", "Docker", "Kubernetes", "AWS", "Feature Engineering", "Experiment Tracking", "Algorithms", "NLP", "Vision", "Neural Networks", "Optimization", "Data", "Training", "Testing", "Deployment", "Scalability", "Reinforcement", "Research", "Mathematics", "Probability", "Modeling", "Inference", "Automation"
    ],
    "Cloud Engineer": [
        "AWS", "Azure", "GCP", "Terraform", "IAC", "Networking", "Linux", "Containers", "Monitoring", "Security", "Security", "Virtualization", "Kubernetes", "Terraform", "CI/CD", "Docker", "IAM", "Load Balancing", "Scripting", "APIs", "Storage", "Databases", "Backup", "Migration"
    ],
    "Cybersecurity Analyst": [
        "SIEM", "SOC", "Incident Response", "Threat Hunting", "Vulnerability Management", "Linux", "Networking", "Cloud Security", "OWASP", "SAST", "Threats", "Firewalls", "Encryption", "Authentication", "Malware", "Forensics", "Auditing", "Compliance", "Risk", "Patching", "PenTesting", "IDS", "IPS", "Monitoring", "Awareness", "Phishing", "Incident", "Defense"
    ],
    "Business Analyst": [
         "Stakeholder Management", "Process Mapping", "Excel", "SQL", "Power BI", "Tableau", "User Stories", "Documentation", "Analytics", "Requirements Gathering", "Communication", "Documentation", "Modeling", "Diagrams", "Research", "Testing", "Analysis", "Planning", "Agile", "Feedback", "Reporting", "Data", "Collaboration", "Strategy", "Stakeholders", "Process", "Decision Making"
    ],
    "HR Generalist": [
        "Recruitment", "Onboarding", "Payroll", "Employee Relations", "Compliance", "ATS", "Performance Management", "Policies", "Benefits", "Training", "Policies", "Training", "Leaves","Retention", "Diversity", "Grievance", "Engagement", "Appraisal", "Counseling", "Negotiation", "Records", "Termination", "Development", "Culture"
    ],
    "Digital Marketer": [
        "SEO", "SEM", "Google Ads", "Facebook Ads", "Analytics", "Content", "Email Marketing", "Social Media", "Copywriting", "CRM", "PPC", "Branding", "Campaigns", "Strategy", "Keywords", "Tools", "Blogging", "Ads", "ROI", "Automation", "Outreach", "Tracking", "Optimization"
    ],
    "Content Writer": [
        "Copywriting", "Editing", "SEO", "Blogging", "Research", "Content Strategy", "WordPress", "Social Media", "AP Style", "Headlines", "Grammar", "Vocabulary", "Creativity", "Storytelling", "Persuasion", "Style", "Proofreading", "Audience", "Tone", "Headlines", "Clarity", "Originality", "Structure", "Consistency", "Marketing", "Drafting"
    ],
    "Sales Executive": [
        "Lead Generation", "CRM", "Prospecting", "Negotiation", "Pipeline", "Cold Calling", "Presentation", "Closing", "Target", "Reporting", "Pitching", "Negotiation", "Communication", "Closing", "Leads", "Targeting", "Networking", "Persuasion", "Follow Up", "Strategy", "Conversion", "Confidence", "Rapport", "Listening", "Forecasting"
    ],
    "Operations Manager": [
        "Process Improvement", "SOP", "KPI", "Scheduling", "Supply Chain", "Inventory", "Vendor Management", "Excel", "Forecasting", "Compliance", "Planning", "Logistics", "Coordination", "Efficiency", "Resources", "Monitoring", "Optimization", "Procurement", "Compliance", "Leadership", "Budgeting", "Reporting", "Risk", "Workflow", "Productivity", "Decision Making", "Delivery", "Quality"
    ],
    "Finance Analyst": [
        "Excel", "Financial Modeling", "Valuation", "Accounting", "Forecasting", "Budgeting", "Power BI", "SQL", "Reporting", "GAAP", "Accounting", "Valuation", "Modeling", "Reporting", "Auditing", "Ratios", "Taxation", "Compliance", "Cashflow", "Investment", "Risk", "Analytics", "Profitability", "Planning", "Insights", "Statements", "Accuracy"
    ],
    "Graphic Designer": [
        "Adobe Photoshop", "Illustrator", "InDesign", "Branding", "Typography", "Layout", "Social Media", "Figma", "Motion Graphics", "UI","Creativity","Branding", "Color", "Motion", "UX", "AdobeXD", "Illustration", "Sketching", "Animation", "Visuals", "Tools", "Composition", "Consistency", "Storytelling"
    ],
    "Project Manager": [
        "Project Planning", "Agile", "Scrum", "Kanban", "Jira", "Risk Management", "Stakeholder", "Reporting", "Scheduling", "Budgeting", "Leadership", "Communication", "Collaboration", "Negotiation", "Tracking", "Reporting", "Strategy", "Documentation", "Motivation", "Delegation", "Monitoring", "Goals", "Quality", "Delivery"
    ],
    "Customer Support": [
        "Ticketing", "Communication", "Troubleshooting", "Product Knowledge", "CRM", "Email Support", "Chat Support", "Documentation", "SLA", "Escalation", "Empathy", "Patience", "Listening", "Adaptability", "Multitasking", "Clarity", "Problem Solving", "Positive", "Feedback", "Calls", "Resolution", "Accuracy"
    ],
    "Technical Writer": [
        "Documentation", "API Docs", "Markdown", "Diagrams", "Editing", "Version Control", "SDK", "Tutorials", "Release Notes", "Information Architecture", "Grammar", "Clarity", "Research", "Accuracy", "Proofreading", "Tools", "Manuals", "Guides", "Structure", "Consistency", "Formatting", "Usability", "Standards", "Collaboration", "Drafting", "Audience"
    ],
    "Systems Administrator": [
        "Linux", "Windows Server", "Active Directory", "Networking", "Scripting", "Bash", "PowerShell", "Backups", "Monitoring", "Security", "Servers", "Recovery", "Patching", "Troubleshooting", "DNS", "DHCP", "Storage", "Firewalls", "Virtualization", "Cloud", "Performance", "Automation", "Configuration"
    ],
}


SKILL_SYNONYMS = {
    "mlops": {"ml ops", "ml-ops"},
    "ci/cd": {"cicd", "ci cd"},
    "a/b testing": {"ab testing", "a b testing"},
    "postgresql": {"postgres", "postgre"},
}


def normalize_skill(token: str) -> str:
    token = token.lower().strip()
    token = token.replace("_", " ")
    token = re.sub(r"\s+", " ", token)
    for canon, aliases in SKILL_SYNONYMS.items():
        if token in aliases:
            return canon
    return token


def extract_skills(text: str) -> set:
    tokens = set()
    # Simple split; include multiword skills by scanning phrases
    lower = text.lower()
    # First add multi-word skill phrases explicitly
    multi_phrases = set()
    for skills in JOB_ROLES.values():
        for s in skills:
            if " " in s and s in lower:
                multi_phrases.add(s)
    tokens |= {normalize_skill(s) for s in multi_phrases}

    # Single tokens
    for raw in re.findall(r"[a-zA-Z+#/.\-]{2,}", lower):
        tokens.add(normalize_skill(raw))

    # Common degree acronyms treated as skills/qualifications
    degree_tokens = {"btech", "b.e", "be", "bsc", "b.sc", "mtech", "m.tech", "msc", "m.sc", "bca", "mca"}
    tokens |= degree_tokens
    return tokens


def extract_education(text: str) -> dict:
    education = {"degrees": [], "highest_level": ""}

    # More flexible patterns
    degree_patterns = {
        "phd": r"(ph\.?d|doctor of philosophy)",
        "mba": r"(mba|master of business administration)",
        "mtech": r"(m\.?tech|master of technology|masters in technology)",
        "me": r"(m\.?e\.?|master of engineering|masters in engineering)",
        "msc": r"(m\.?sc|master of science|masters in science)",
        "mca": r"(mca|master of computer applications)",
        "btech": r"(b\.?tech|bachelor of technology|b tech)",
        "be": r"(b\.?e\.?|bachelor of engineering|b e)",
        "bsc": r"(b\.?sc|bachelor of science|b sc)",
        "bca": r"(bca|bachelor of computer applications)"
    }

    found = set()
    lower = text.lower()

    # Search all patterns
    for key, pat in degree_patterns.items():
        for m in re.finditer(pat, lower):
            found.add(key)  # store normalized key instead of raw text

    # Save all degrees found (normalized)
    education["degrees"] = sorted(found)

    # Define hierarchy
    hierarchy = ["phd", "mba", "mtech", "me", "msc", "mca", "btech", "be", "bsc", "bca"]

    # Pick highest degree
    highest = ""
    for h in hierarchy:
        if h in found:
            highest = h.upper()  # return clean format
            break

    education["highest_level"] = highest

    # Capture degree + institute lines
    lines = [l.strip() for l in re.split(r"\n", text) if l.strip()]
    degree_line_re = re.compile(r"(b\.?tech|m\.?tech|b\.?e\.?|m\.?e\.?|b\.?sc|m\.?sc|bca|mca|mba|ph\.?d)[^\n]{0,120}", re.IGNORECASE)
    details = []
    for l in lines:
        m = degree_line_re.search(l)
        if m:
            details.append(l[:180])
    if details:
        education["details"] = details[:5]
        
    return education



def extract_experience_years(text: str) -> float:
    lower = text.lower()
    years = []

    # 1. Explicit "X years" or "X yrs"
    for m in re.finditer(r"(\d{1,2})\+?\s*(?:years|yrs|year)", lower):
        years.append(int(m.group(1)))

    # 2. Date ranges like "2019-2022", "Jan 2020 - Present"
    date_patterns = re.findall(r"([a-z]{3,9}\s*\d{4}|\d{4})\s*[-–to]+\s*(present|[a-z]{3,9}\s*\d{4}|\d{4})", lower, flags=re.IGNORECASE)

    for start_str, end_str in date_patterns:
        try:
            start = parser.parse(start_str, default=datetime(1900,1,1)).year if not start_str.isdigit() else int(start_str)
            end = datetime.utcnow().year if "present" in end_str.lower() else (parser.parse(end_str, default=datetime(1900,1,1)).year if not end_str.isdigit() else int(end_str))
            
            if end >= start:
                years.append(end - start)
        except Exception:
            continue

    # Pick the **max** rather than sum (prevents double counting overlapping jobs)
    return max(years) if years else 0.0



def extract_projects(text: str) -> list:
    projects = []
    lines = [l.strip() for l in re.split(r"\n", text)]
    capture = False
    buffer = []

    for line in lines:
        # 1. Detect project headings
        if re.search(r"(project[s]?|academic project|major project|mini project|capstone)", line, re.IGNORECASE):
            if buffer:
                projects.append(" ".join(buffer))
                buffer = []
            capture = True
            continue

        # 2. Capture content until a new section starts
        if capture:
            if line == "" or re.match(r"^[A-Z\s]{3,}$", line):
                if buffer:
                    projects.append(" ".join(buffer))
                    buffer = []
                capture = False
            else:
                buffer.append(line)

    # Final buffer flush
    if buffer:
        projects.append(" ".join(buffer))

    # 3. Post-process → split into bullet points if needed
    clean_projects = []
    for proj in projects:
        # Split by bullets, numbers, or semicolons
        parts = re.split(r"(?:•|\*|-|\d+\.)", proj)
        for p in parts:
            p = p.strip(" :;-")
            if len(p) > 5:  # avoid junk
                clean_projects.append(p)

    return clean_projects[:5]  # limit to 5 projects



def score_resume(skills_found: set, role: str, experience_years: float, education: dict) -> dict:
    # Take up to 10 mandatory required skills for the selected role
    role_skills = JOB_ROLES.get(role, [])
    required_list = []
    seen = set()
    for s in role_skills:
        ns = normalize_skill(s)
        if ns not in seen:
            seen.add(ns)
            required_list.append(ns)
        if len(required_list) >= 10:
            break
    required = set(required_list)

    matched = sorted(required & skills_found)
    unmatched = sorted(required - skills_found)

    # Simple scoring: 70% skills, 20% experience, 10% education
    skill_score = 100.0 * (len(matched) / len(required)) if required else 0.0
    exp_score = min(experience_years / 8.0, 1.0) * 100.0  # Cap at 8 years for full score
    edu_bonus = 0.0
    if education.get("highest_level") in {"phd", "m.tech", "m.e", "m.sc", "mba"}:
        edu_bonus = 10.0
    elif education.get("highest_level") in {"b.tech", "b.e", "b.sc", "bca", "mca"}:
        edu_bonus = 5.0
    total = 0.7 * skill_score + 0.2 * exp_score + 0.1 * edu_bonus
    total = round(total, 2)

    return {
        "required_skills": sorted(required),
        "matched_skills": matched,
        "unmatched_skills": unmatched,
        "skill_match_percent": round(skill_score, 2),
        "experience_years": experience_years,
        "education": education,
        "overall_score": total,
    }


def alternative_roles(skills_found: set, primary_role: str) -> list:
    suggestions = []
    for role, reqs in JOB_ROLES.items():
        if role == primary_role:
            continue
        reqs_norm = {normalize_skill(s) for s in reqs}
        overlap = len(reqs_norm & skills_found)
        percent = 100.0 * overlap / max(1, len(reqs_norm))
        if overlap:
            suggestions.append({"role": role, "match_percent": round(percent, 1)})
    # If too few suggestions due to low overlap, include low matches too
    if len(suggestions) < 3:
        for role, reqs in JOB_ROLES.items():
            if role == primary_role or any(s["role"] == role for s in suggestions):
                continue
            reqs_norm = {normalize_skill(s) for s in reqs}
            overlap = len(reqs_norm & skills_found)
            percent = 100.0 * overlap / max(1, len(reqs_norm))
            suggestions.append({"role": role, "match_percent": round(percent, 1)})
            if len(suggestions) >= 3:
                break
    suggestions.sort(key=lambda x: x["match_percent"], reverse=True)
    return suggestions[:5]


###############################################################################
# REST API
###############################################################################


@app.route("/api/signup", methods=["POST"])
def api_signup():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    full_name = (data.get("full_name") or "").strip()
    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
    if users_col.find_one({"email": email}):
        return jsonify({"error": "Email already registered"}), 409
    password_hash = hash_password(password)
    user_doc = {
        "email": email,
        "password_hash": password_hash,
        "full_name": full_name,
        "created_at": datetime.utcnow(),
    }
    res = users_col.insert_one(user_doc)
    session["user_id"] = str(res.inserted_id)
    return jsonify({"message": "Signup successful"})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = (data.get("password") or "").strip()
    user = users_col.find_one({"email": email})
    if not user or not check_password(password, user.get("password_hash", b"")):
        return jsonify({"error": "Invalid credentials"}), 401
    session["user_id"] = str(user["_id"])
    return jsonify({"message": "Login successful", "full_name": user.get("full_name", "")})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"message": "Logged out"})


@app.route("/api/jobs", methods=["GET"])
def api_jobs():
    roles = sorted(JOB_ROLES.keys())
    return jsonify({"roles": roles})


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    job_role = (request.form.get("job_role") or "").strip()
    if job_role not in JOB_ROLES:
        return jsonify({"error": "Invalid job role"}), 400

    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file. Please upload PDF or TXT"}), 400

    try:
        raw_text = extract_text_from_file(file)
        text = normalize_text(raw_text)
    except Exception as e:
        return jsonify({"error": f"Failed to extract text: {str(e)}"}), 400

    email = extract_email(text)
    phone = extract_phone(text)
    name = guess_name(text, email)
    name_is_valid = validate_name_format(name) if name else False

    skills_found = extract_skills(text)
    education = extract_education(raw_text)
    experience_years = extract_experience_years(raw_text)
    scoring = score_resume(skills_found, job_role, experience_years, education)
    alternatives = alternative_roles(skills_found, job_role)

    # Extract additional data for comprehensive analysis
    projects = extract_projects(raw_text)

    analysis = {
        "user_id": session["user_id"],
        "uploaded_filename": secure_filename(file.filename),
        "job_role": job_role,
        "personal_info": {
            "name": name,
            "email": email,
            "phone": phone,
            "name_is_valid": name_is_valid
        },
        "skills": {
            "needed": scoring["required_skills"],
            "matched": scoring["matched_skills"],
            "unmatched": scoring["unmatched_skills"],
            "total_found": len(skills_found),
            "match_percentage": round((len(scoring["matched_skills"]) / len(scoring["required_skills"]) * 100) if scoring["required_skills"] else 0, 1)
        },
        "experience": {
            "years": experience_years,
            "level": "Senior" if experience_years >= 5 else "Mid-level" if experience_years >= 2 else "Entry-level" if experience_years > 0 else "No experience"
        },
        "education": education,
        "projects": projects[:5],  # Top 5 projects
        "accuracy": scoring["overall_score"],
        "alternatives": alternatives,
        "analysis_metadata": {
            "text_length": len(text),
            "skills_detected": len(skills_found),
            "projects_found": len(projects),
            "analysis_timestamp": datetime.utcnow().isoformat()
        },
        "created_at": datetime.utcnow(),
    }

    res = analyses_col.insert_one(analysis)
    analysis_id = str(res.inserted_id)

    # Prepare JSON-safe response
    response_analysis = dict(analysis)
    if "_id" in response_analysis:
        try:
            response_analysis["_id"] = str(response_analysis["_id"])  # in case PyMongo added it in-place
        except Exception:
            response_analysis.pop("_id", None)
    ca = response_analysis.get("created_at")
    if isinstance(ca, datetime):
        response_analysis["created_at"] = ca.isoformat() + "Z"

    return jsonify({"analysis_id": analysis_id, "analysis": response_analysis})


@app.route("/api/report/<analysis_id>", methods=["GET"])
def api_report(analysis_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        doc = analyses_col.find_one({"_id": ObjectId(analysis_id), "user_id": session["user_id"]})
    except Exception:
        return jsonify({"error": "Not found"}), 404
    if not doc:
        return jsonify({"error": "Not found"}), 404

    # Generate PDF
    pdf_bytes = generate_pdf_report(doc)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"resume_analysis_{analysis_id}.pdf",
    )


@app.route("/api/analyses", methods=["GET"])
def api_analyses():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Get user's analysis history
    analyses = list(analyses_col.find(
        {"user_id": session["user_id"]}, 
        {"_id": 1, "job_role": 1, "accuracy": 1, "created_at": 1, "uploaded_filename": 1}
    ).sort("created_at", -1).limit(10))
    
    # Convert ObjectId to string for JSON serialization
    for analysis in analyses:
        analysis["_id"] = str(analysis["_id"])
        if isinstance(analysis.get("created_at"), datetime):
            analysis["created_at"] = analysis["created_at"].isoformat() + "Z"
    
    return jsonify({"analyses": analyses})


@app.route("/api/stats", methods=["GET"])
def api_stats():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Calculate user statistics
    total_analyses = analyses_col.count_documents({"user_id": session["user_id"]})
    
    if total_analyses == 0:
        return jsonify({
            "total_analyses": 0,
            "avg_score": 0,
            "best_score": 0,
            "most_analyzed_role": None,
            "recent_analyses": []
        })
    
    # Get all analyses for this user
    analyses = list(analyses_col.find(
        {"user_id": session["user_id"]}, 
        {"accuracy": 1, "job_role": 1, "created_at": 1}
    ))
    
    scores = [a["accuracy"] for a in analyses]
    avg_score = sum(scores) / len(scores)
    best_score = max(scores)
    
    # Most analyzed role
    role_counts = {}
    for analysis in analyses:
        role = analysis.get("job_role", "Unknown")
        role_counts[role] = role_counts.get(role, 0) + 1
    
    most_analyzed_role = max(role_counts.items(), key=lambda x: x[1])[0] if role_counts else None
    
    # Recent analyses (last 5)
    recent_analyses = sorted(analyses, key=lambda x: x.get("created_at", datetime.min), reverse=True)[:5]
    for analysis in recent_analyses:
        if isinstance(analysis.get("created_at"), datetime):
            analysis["created_at"] = analysis["created_at"].isoformat() + "Z"
    
    return jsonify({
        "total_analyses": total_analyses,
        "avg_score": round(avg_score, 1),
        "best_score": best_score,
        "most_analyzed_role": most_analyzed_role,
        "recent_analyses": recent_analyses
    })


@app.route("/api/insights/<analysis_id>", methods=["GET"])
def api_insights(analysis_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        doc = analyses_col.find_one({"_id": ObjectId(analysis_id), "user_id": session["user_id"]})
    except Exception:
        return jsonify({"error": "Not found"}), 404
    
    if not doc:
        return jsonify({"error": "Not found"}), 404
    
    # Generate detailed insights
    skills = doc.get("skills", {})
    accuracy = doc.get("accuracy", 0)
    
    insights = {
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "market_insights": {}
    }
    
    # Strengths
    if accuracy >= 80:
        insights["strengths"].append("Excellent overall match for the target role")
    elif accuracy >= 60:
        insights["strengths"].append("Good foundation with room for improvement")
    
    matched_skills = skills.get("matched", [])
    if len(matched_skills) >= 8:
        insights["strengths"].append(f"Strong skill set with {len(matched_skills)} required skills")
    elif len(matched_skills) >= 5:
        insights["strengths"].append(f"Solid skill foundation with {len(matched_skills)} required skills")
    
    # Weaknesses
    unmatched_skills = skills.get("unmatched", [])
    if len(unmatched_skills) > 5:
        insights["weaknesses"].append(f"Missing {len(unmatched_skills)} critical skills for this role")
    elif len(unmatched_skills) > 2:
        insights["weaknesses"].append(f"Need to develop {len(unmatched_skills)} additional skills")
    
    if accuracy < 50:
        insights["weaknesses"].append("Significant skill gap requires focused development")
    
    # Recommendations
    if unmatched_skills:
        insights["recommendations"].append(f"Prioritize learning: {', '.join(unmatched_skills[:3])}")
    
    if accuracy < 70:
        insights["recommendations"].append("Consider gaining more relevant work experience")
    
    insights["recommendations"].append("Highlight your matched skills prominently in your resume")
    insights["recommendations"].append("Consider the alternative career paths suggested")
    
    # Market insights
    role = doc.get("job_role", "")
    insights["market_insights"] = {
        "role_demand": "High" if role in ["Software Engineer", "Data Scientist", "Product Manager"] else "Medium",
        "skill_competition": "High" if len(matched_skills) < 5 else "Medium",
        "experience_requirement": "5+ years" if accuracy > 80 else "3+ years"
    }
    
    return jsonify({"insights": insights})


###############################################################################
# Frontend (single-page): Login -> Upload & Role -> Results
###############################################################################


HERO_IMG = "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?w=1200&q=80&auto=format&fit=crop"
SEC_IMG1 = "https://images.unsplash.com/photo-1512758017271-d7b84c2113f1?w=800&q=80&auto=format&fit=crop"
SEC_IMG2 = "https://images.unsplash.com/photo-1551836022-4c4c79ecde51?w=800&q=80&auto=format&fit=crop"


INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Resan AI - Gamified Resume Analyzer</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
  <style>
    :root { 
      --primary: #2d5a27; --primary-dark: #1e3d1a; --secondary: #4a7c59; 
      --bg: #0f0f23; --card: #1a1a2e; --card-hover: #16213e; 
      --text: #e2e8f0; --muted: #94a3b8; --accent: #20b2aa; 
      --success: #10b981; --warning: #f59e0b; --error: #ef4444;
      --navy-green: #2d5a27; --aqua-marine: #20b2aa;
      --gradient: linear-gradient(135deg, #2d5a27 0%, #20b2aa 100%);
      --glass: rgba(255, 255, 255, 0.1);
      --shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
    }
    :root.light { 
      --bg: #f8fafc; --card: #ffffff; --card-hover: #f1f5f9; 
      --text: #1e293b; --muted: #64748b; --accent: #0891b2;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { 
      font-family: 'Inter', system-ui, -apple-system, sans-serif; 
      background: var(--bg); color: var(--text); 
      min-height: 100vh;
      background-image: 
        radial-gradient(circle at 20% 80%, rgba(120, 119, 198, 0.3) 0%, transparent 50%),
        radial-gradient(circle at 80% 20%, rgba(255, 119, 198, 0.3) 0%, transparent 50%),
        radial-gradient(circle at 40% 40%, rgba(120, 219, 255, 0.2) 0%, transparent 50%);
    }
    .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
    .glass-card { 
      background: var(--glass); backdrop-filter: blur(10px); 
      border: 1px solid rgba(255, 255, 255, 0.2); 
      border-radius: 20px; padding: 32px; 
      box-shadow: var(--shadow);
      transition: all 0.3s ease;
    }
    .glass-card:hover { transform: translateY(-2px); box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25); }
    .btn { 
      background: var(--gradient); color: white; border: none; 
      padding: 14px 28px; border-radius: 12px; cursor: pointer; 
      font-weight: 600; font-size: 16px; transition: all 0.3s ease;
      position: relative; overflow: hidden;
    }
    .btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(0,0,0,0.2); }
    .btn:active { transform: translateY(0); }
    .btn.secondary { background: var(--card-hover); }
    .btn.success { background: linear-gradient(135deg, #10b981, #059669); }
    .btn.warning { background: linear-gradient(135deg, #f59e0b, #d97706); }
    .btn.error { background: linear-gradient(135deg, #ef4444, #dc2626); }
    .btn::before {
      content: '';
      position: absolute;
      top: 0; left: -100%;
      width: 100%; height: 100%;
      background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
      transition: left 0.5s;
    }
    .btn:hover::before { left: 100%; }
    .hidden { display: none !important; }
    .fade-in { animation: fadeIn 0.6s ease-in-out; }
    .slide-up { animation: slideUp 0.6s ease-out; }
    .bounce { animation: bounce 0.6s ease-in-out; }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    @keyframes slideUp { from { transform: translateY(30px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    @keyframes bounce { 0%, 20%, 50%, 80%, 100% { transform: translateY(0); } 40% { transform: translateY(-10px); } 60% { transform: translateY(-5px); } }
    .progress-bar { 
      width: 100%; height: 8px; background: rgba(255,255,255,0.1); 
      border-radius: 4px; overflow: hidden; margin: 20px 0;
    }
    .progress-fill { 
      height: 100%; background: var(--gradient); 
      border-radius: 4px; transition: width 0.3s ease;
      position: relative;
    }
    .progress-fill::after {
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
      animation: shimmer 2s infinite;
    }
    @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
    .score-display { 
      font-size: 4rem; font-weight: 800; 
      background: var(--gradient); -webkit-background-clip: text; 
      -webkit-text-fill-color: transparent; text-align: center;
      margin: 20px 0;
    }
    .skill-pill { 
      display: inline-block; padding: 8px 16px; margin: 4px; 
      border-radius: 20px; font-size: 14px; font-weight: 500;
      transition: all 0.3s ease; cursor: pointer;
    }
    .skill-pill.matched { background: linear-gradient(135deg, #10b981, #059669); color: white; }
    .skill-pill.unmatched { background: linear-gradient(135deg, #ef4444, #dc2626); color: white; }
    .skill-pill.needed { background: linear-gradient(135deg, #6366f1, #4f46e5); color: white; }
    .skill-pill:hover { transform: scale(1.05); box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
    .achievement { 
      background: var(--card); border: 2px solid var(--accent); 
      border-radius: 12px; padding: 16px; margin: 8px 0;
      display: flex; align-items: center; gap: 12px;
      transition: all 0.3s ease;
    }
    .achievement:hover { transform: translateX(5px); border-color: var(--success); }
    .achievement i { font-size: 24px; color: var(--accent); }
    .level-badge { 
      background: var(--gradient); color: white; 
      padding: 4px 12px; border-radius: 20px; 
      font-size: 12px; font-weight: 600;
    }
    .stats-grid { 
      display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
      gap: 20px; margin: 20px 0;
    }
    .stat-card { 
      background: var(--card); border-radius: 12px; padding: 20px; 
      text-align: center; transition: all 0.3s ease;
    }
    .stat-card:hover { transform: translateY(-5px); }
    .stat-number { font-size: 2rem; font-weight: 700; color: var(--accent); }
    .stat-label { color: var(--muted); font-size: 14px; margin-top: 8px; }
    .input-group { margin-bottom: 20px; }
    .input-group label { 
      display: block; margin-bottom: 8px; 
      font-weight: 500; color: var(--text);
    }
    .input-group input, .input-group select { 
      width: 100%; padding: 14px 16px; 
      border: 2px solid rgba(255,255,255,0.1); 
      border-radius: 12px; background: rgba(255,255,255,0.05);
      color: var(--text); font-size: 16px;
      transition: all 0.3s ease;
    }
    .input-group select option {
      color: #000000; background: #ffffff;
    }
    .input-group input:focus, .input-group select:focus { 
      outline: none; border-color: var(--accent); 
      box-shadow: 0 0 0 3px rgba(6, 182, 212, 0.1);
    }
    .hero-section { 
      text-align: center; padding: 60px 0; 
      background: linear-gradient(135deg, var(--navy-green) 0%, var(--aqua-marine) 50%, var(--primary) 100%); 
      border-radius: 20px; 
      margin-bottom: 40px; position: relative; overflow: hidden;
    }
    .hero-section::before {
      content: '';
      position: absolute;
      top: -50%; left: -50%;
      width: 200%; height: 200%;
      background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
      animation: rotate 20s linear infinite;
    }
    @keyframes rotate { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    .hero-title { 
      font-size: 3.5rem; font-weight: 800; 
      margin-bottom: 20px; position: relative; z-index: 1;
    }
    .hero-subtitle { 
      font-size: 1.25rem; color: rgba(255,255,255,0.9); 
      margin-bottom: 30px; position: relative; z-index: 1;
    }
    .floating-elements {
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      pointer-events: none;
    }
    .floating-element {
      position: absolute;
      background: rgba(255,255,255,0.1);
      border-radius: 50%;
      animation: float 6s ease-in-out infinite;
    }
    .floating-element:nth-child(1) { width: 60px; height: 60px; top: 20%; left: 10%; animation-delay: 0s; }
    .floating-element:nth-child(2) { width: 40px; height: 40px; top: 60%; right: 15%; animation-delay: 2s; }
    .floating-element:nth-child(3) { width: 80px; height: 80px; bottom: 20%; left: 20%; animation-delay: 4s; }
    @keyframes float { 0%, 100% { transform: translateY(0px); } 50% { transform: translateY(-20px); } }
    .toolbar { 
      display: flex; justify-content: space-between; 
      align-items: center; margin-bottom: 30px;
    }
    .theme-toggle { 
      background: var(--glass); border: 1px solid rgba(255,255,255,0.2);
      color: var(--text); padding: 10px 16px; 
      border-radius: 10px; cursor: pointer; transition: all 0.3s ease;
    }
    .theme-toggle:hover { background: var(--card-hover); }
    .loading-spinner {
      width: 40px; height: 40px; border: 4px solid rgba(255,255,255,0.1);
      border-left: 4px solid var(--accent); border-radius: 50%;
      animation: spin 1s linear infinite; margin: 20px auto;
    }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="container">
    <!-- Toolbar -->
    <div class="toolbar">
      <div style="display: flex; align-items: center; gap: 20px;">
        <h1 style="margin: 0; font-size: 1.5rem; background: var(--gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
          <i class="fas fa-robot"></i> Resan AI
        </h1>
        <div id="user-level" class="level-badge hidden">Level 1</div>
        <div id="user-points" class="level-badge hidden">0 Points</div>
    </div>
      <button class="theme-toggle" onclick="toggleTheme()">
        <i class="fas fa-moon"></i> Theme
      </button>
    </div>

    <!-- Hero Section -->
    <div class="hero-section">
      <div class="floating-elements">
        <div class="floating-element"></div>
        <div class="floating-element"></div>
        <div class="floating-element"></div>
          </div>
      <h1 class="hero-title">Resan AI Resume Analyzer</h1>
      <p class="hero-subtitle">AI-powered analysis with comprehensive insights and detailed reporting</p>
      <div class="stats-grid" style="max-width: 600px; margin: 0 auto;">
        <div class="stat-card">
          <div class="stat-number" id="total-analyses">0</div>
          <div class="stat-label">Resumes Analyzed</div>
        </div>
        <div class="stat-card">
          <div class="stat-number" id="avg-score">0%</div>
          <div class="stat-label">Average Score</div>
          </div>
        <div class="stat-card">
          <div class="stat-number" id="achievements">0</div>
          <div class="stat-label">Achievements</div>
        </div>
      </div>
    </div>

    <!-- Login View -->
    <div id="view-login" class="glass-card fade-in">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 40px; align-items: center;">
        <div>
          <h2 style="font-size: 2.5rem; margin-bottom: 20px; background: var(--gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
            Welcome to the Future
          </h2>
          <p style="color: var(--muted); font-size: 1.1rem; line-height: 1.6; margin-bottom: 30px;">
            Transform your resume analysis into an engaging experience. Get instant AI feedback, 
            earn achievements, and level up your career prospects.
          </p>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
            <div style="text-align: center; padding: 20px; background: var(--card); border-radius: 12px;">
              <i class="fas fa-file-pdf" style="font-size: 2rem; color: var(--accent); margin-bottom: 10px;"></i>
              <h4>Smart Analysis</h4>
              <p style="color: var(--muted); font-size: 0.9rem;">AI-powered resume parsing</p>
            </div>
            <div style="text-align: center; padding: 20px; background: var(--card); border-radius: 12px;">
              <i class="fas fa-trophy" style="font-size: 2rem; color: var(--warning); margin-bottom: 10px;"></i>
              <h4>Gamified Experience</h4>
              <p style="color: var(--muted); font-size: 0.9rem;">Earn points and achievements</p>
            </div>
          </div>
        </div>
        <div>
          <div class="input-group">
            <label><i class="fas fa-user"></i> Full Name (for signup)</label>
            <input id="full_name" placeholder="Enter your full name" />
        </div>
          <div class="input-group">
            <label><i class="fas fa-envelope"></i> Email</label>
            <input id="email" type="email" placeholder="your.email@example.com" />
      </div>
          <div class="input-group">
            <label><i class="fas fa-lock"></i> Password</label>
            <input id="password" type="password" placeholder="Create a strong password" />
      </div>
          <div style="display: flex; gap: 12px; margin-top: 24px;">
            <button class="btn" onclick="signup()">
              <i class="fas fa-user-plus"></i> Sign Up
            </button>
            <button class="btn secondary" onclick="login()">
              <i class="fas fa-sign-in-alt"></i> Log In
            </button>
          </div>
          <div id="auth_msg" style="margin-top: 16px; padding: 12px; border-radius: 8px; text-align: center;"></div>
        </div>
      </div>
    </div>

    <!-- Upload View -->
    <div id="view-upload" class="glass-card hidden">
      <div style="text-align: center; margin-bottom: 30px;">
        <h2 style="font-size: 2rem; margin-bottom: 10px;">
          <i class="fas fa-upload"></i> Upload Your Resume
        </h2>
        <p style="color: var(--muted);">Let our AI analyze your resume and provide detailed insights</p>
      </div>
      
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-bottom: 30px;">
        <div class="input-group">
          <label><i class="fas fa-file"></i> Resume File (PDF or TXT)</label>
          <input type="file" id="resume_file" accept=".pdf,.txt" style="padding: 20px; border: 2px dashed rgba(255,255,255,0.3); background: rgba(255,255,255,0.05);" />
        </div>
        <div class="input-group">
          <label><i class="fas fa-briefcase"></i> Target Job Role</label>
          <select id="job_role" style="padding: 20px;">
            <option value="">Select a job role...</option>
          </select>
        </div>
      </div>

      <div style="text-align: center;">
        <button class="btn" onclick="analyze()" style="margin-right: 12px;">
          <i class="fas fa-magic"></i> Analyze Resume
        </button>
        <button class="btn secondary" onclick="logout()">
          <i class="fas fa-sign-out-alt"></i> Logout
        </button>
      </div>
      
      <div id="upload_msg" style="margin-top: 20px; padding: 16px; border-radius: 12px; text-align: center;"></div>
      
      <!-- Progress Bar -->
      <div id="progress-container" class="hidden">
        <div class="progress-bar">
          <div class="progress-fill" id="progress-fill" style="width: 0%;"></div>
        </div>
        <p id="progress-text" style="text-align: center; margin-top: 10px; color: var(--muted);">Analyzing your resume...</p>
      </div>
    </div>

    <!-- Results View -->
    <div id="view-results" class="glass-card hidden">
      <div style="text-align: center; margin-bottom: 30px;">
        <h2 style="font-size: 2rem; margin-bottom: 10px;">
          <i class="fas fa-chart-line"></i> Analysis Results
        </h2>
        <p style="color: var(--muted);">Your personalized resume analysis and recommendations</p>
      </div>
      
      <div id="results_area"></div>
      
      <!-- Achievements Showcase -->
      <div id="achievements-showcase" style="margin: 30px 0; padding: 20px; background: var(--card); border-radius: 12px; border-left: 4px solid var(--accent);">
        <h3 style="margin-bottom: 15px; color: var(--accent); display: flex; align-items: center; gap: 10px;">
          <i class="fas fa-trophy"></i> Your Achievements
        </h3>
        <div id="achievements-display" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px;">
          <!-- Achievements will be populated here -->
      </div>
    </div>

      <!-- Download PDF Section -->
      <div style="margin: 30px 0; padding: 25px; background: linear-gradient(135deg, var(--navy-green), var(--aqua-marine)); border-radius: 15px; text-align: center;">
        <h3 style="color: white; margin-bottom: 15px; font-size: 1.5rem;">
          <i class="fas fa-file-pdf"></i> Download Your Analysis Report
        </h3>
        <p style="color: rgba(255,255,255,0.9); margin-bottom: 20px; font-size: 1.1rem;">
          Get a comprehensive PDF report with detailed insights, recommendations, and visual analysis
        </p>
        <div style="display: flex; gap: 15px; justify-content: center; flex-wrap: wrap;">
          <a id="download_link" class="btn" href="#" download style="background: white; color: var(--navy-green); font-weight: 600; padding: 15px 30px; font-size: 1.1rem;">
            <i class="fas fa-download"></i> Download PDF Report
          </a>
          <button class="btn secondary" onclick="backToUpload()" style="background: rgba(255,255,255,0.2); color: white; border: 2px solid rgba(255,255,255,0.3);">
            <i class="fas fa-redo"></i> Analyze Another Resume
          </button>
        </div>
      </div>
    </div>

    <!-- Achievements Section -->
    <div id="achievements-section" class="glass-card hidden" style="margin-top: 30px;">
      <h3 style="text-align: center; margin-bottom: 20px;">
        <i class="fas fa-trophy"></i> Your Achievements
      </h3>
      <div id="achievements-list"></div>
    </div>
  </div>

<script>
// Global state
let userStats = {
  totalAnalyses: 0,
  avgScore: 0,
  achievements: 0,
  level: 1,
  points: 0
};

let currentAnalysis = null;

// API helper
async function api(path, opts) {
  const res = await fetch(path, opts);
  const ct = res.headers.get('content-type') || '';
  if (!ct.includes('application/json')) return { ok: res.ok, status: res.status, data: null };
  const data = await res.json();
  return { ok: res.ok, status: res.status, data };
}

// Authentication functions
async function signup() {
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value.trim();
  const full_name = document.getElementById('full_name').value.trim();
  
  if (!email || !password) {
    showMessage('Please fill in all required fields', 'error');
    return;
  }
  
  const res = await api('/api/signup', { 
    method: 'POST', 
    headers: { 'Content-Type': 'application/json' }, 
    body: JSON.stringify({ email, password, full_name }) 
  });
  
  if (res.ok) { 
    showMessage('Signup successful! Welcome to Resan AI!', 'success');
    await loadJobs(); 
    showUpload(); 
    updateUserStats();
  } else { 
    showMessage((res.data && res.data.error) || 'Signup failed', 'error'); 
  }
}

async function login() {
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value.trim();
  
  if (!email || !password) {
    showMessage('Please enter your email and password', 'error');
    return;
  }
  
  const res = await api('/api/login', { 
    method: 'POST', 
    headers: { 'Content-Type': 'application/json' }, 
    body: JSON.stringify({ email, password }) 
  });
  
  if (res.ok) { 
    showMessage('Login successful! Welcome back!', 'success');
    await loadJobs(); 
    showUpload(); 
    updateUserStats();
  } else { 
    showMessage((res.data && res.data.error) || 'Login failed', 'error'); 
  }
}

async function logout() {
  await api('/api/logout', { method: 'POST' });
  showLogin();
  resetUserStats();
}

// View management
function showLogin() {
  document.getElementById('view-login').classList.remove('hidden');
  document.getElementById('view-upload').classList.add('hidden');
  document.getElementById('view-results').classList.add('hidden');
  document.getElementById('achievements-section').classList.add('hidden');
}

function showUpload() {
  document.getElementById('view-login').classList.add('hidden');
  document.getElementById('view-upload').classList.remove('hidden');
  document.getElementById('view-results').classList.add('hidden');
  document.getElementById('achievements-section').classList.add('hidden');
}

function showResults() {
  document.getElementById('view-login').classList.add('hidden');
  document.getElementById('view-upload').classList.add('hidden');
  document.getElementById('view-results').classList.remove('hidden');
  document.getElementById('achievements-section').classList.remove('hidden');
}

// Job roles loading
async function loadJobs() {
  const res = await api('/api/jobs');
  const select = document.getElementById('job_role');
  select.innerHTML = '<option value="">Select a job role...</option>';
  if (res.ok && res.data.roles) {
    for (const r of res.data.roles) {
      const opt = document.createElement('option');
      opt.value = r; 
      opt.textContent = r; 
      select.appendChild(opt);
    }
  }
}

// Analysis with progress
async function analyze() {
  const f = document.getElementById('resume_file').files[0];
  const role = document.getElementById('job_role').value;
  
  if (!f) { 
    showMessage('Please select a resume file', 'error');
    return; 
  }
  if (!role) { 
    showMessage('Please select a target job role', 'error');
    return; 
  }
  
  // Show progress
  const progressContainer = document.getElementById('progress-container');
  const progressFill = document.getElementById('progress-fill');
  const progressText = document.getElementById('progress-text');
  
  progressContainer.classList.remove('hidden');
  
  // Simulate progress
  let progress = 0;
  const progressInterval = setInterval(() => {
    progress += Math.random() * 15;
    if (progress > 90) progress = 90;
    progressFill.style.width = progress + '%';
    
    if (progress < 30) progressText.textContent = 'Reading your resume...';
    else if (progress < 60) progressText.textContent = 'Analyzing skills and experience...';
    else if (progress < 90) progressText.textContent = 'Generating insights...';
  }, 200);
  
  const form = new FormData(); 
  form.append('file', f); 
  form.append('job_role', role);
  
  try {
  const res = await fetch('/api/analyze', { method: 'POST', body: form });
  const data = await res.json();
    
    clearInterval(progressInterval);
    progressFill.style.width = '100%';
    progressText.textContent = 'Analysis complete!';
    
    setTimeout(() => {
      progressContainer.classList.add('hidden');
      if (!res.ok) { 
        showMessage(data.error || 'Analysis failed', 'error');
        return; 
      }
      
      console.log('Analysis data received:', data); // Debug log
      
      if (!data.analysis) {
        showMessage('Invalid analysis data received. Please try again.', 'error');
        return;
      }
      
      if (!data.analysis_id) {
        showMessage('Analysis ID missing. Please try again.', 'error');
        return;
      }
      
      currentAnalysis = data.analysis;
      currentAnalysis.analysis_id = data.analysis_id;
      displayResults(data.analysis);
      updateUserStats();
      showResults();
    }, 500);
    
  } catch (error) {
    clearInterval(progressInterval);
    progressContainer.classList.add('hidden');
    console.error('Analysis error:', error); // Debug log
    showMessage('Network error. Please try again.', 'error');
  }
}

// Enhanced results display
function displayResults(analysis) {
  console.log('Displaying results for analysis:', analysis); // Debug log
  
  const results = document.getElementById('results_area');
  const skills = analysis.skills || { needed: [], matched: [], unmatched: [] };
  
  // Calculate additional metrics
  const skillMatchPercent = skills.match_percentage || (skills.needed.length > 0 ? Math.round((skills.matched.length / skills.needed.length) * 100) : 0);
  const experienceYears = analysis.experience?.years || 0;
  const experienceLevel = analysis.experience?.level || 'Not specified';
  const educationLevel = analysis.education?.highest_level || 'Not specified';
  const projects = analysis.projects || [];
  const personalInfo = analysis.personal_info || {};
  
  // Create skill pills
  const neededPills = skills.needed.map(s => 
    `<span class="skill-pill needed" title="Required skill">${s}</span>`
  ).join('');
  
  const matchedPills = skills.matched.map(s => 
    `<span class="skill-pill matched" title="You have this skill!">${s}</span>`
  ).join('');
  
  const unmatchedPills = skills.unmatched.map(s => 
    `<span class="skill-pill unmatched" title="Missing skill">${s}</span>`
  ).join('');
  
  const altRoles = (analysis.alternatives || []).map(x => 
    `<span class="skill-pill needed" title="Alternative career path">${x.role} (${x.match_percent}%)</span>`
  ).join('');
  
  // Determine score color
  let scoreColor = 'var(--error)';
  if (analysis.accuracy >= 80) scoreColor = 'var(--success)';
  else if (analysis.accuracy >= 60) scoreColor = 'var(--warning)';
  
  results.innerHTML = `
    <!-- Overall Score Section -->
    <div style="text-align: center; margin-bottom: 40px; padding: 30px; background: linear-gradient(135deg, var(--card), var(--card-hover)); border-radius: 20px; border: 2px solid ${scoreColor};">
      <div style="font-size: 5rem; font-weight: 800; color: ${scoreColor}; margin-bottom: 10px;">
        ${analysis.accuracy}%
      </div>
      <div style="font-size: 1.5rem; color: var(--text); margin-bottom: 10px;">
        Match with ${analysis.job_role}
      </div>
      <div style="color: var(--muted); font-size: 1.1rem;">
        ${analysis.accuracy >= 80 ? 'Excellent Match!' : analysis.accuracy >= 60 ? 'Good Match' : analysis.accuracy >= 40 ? 'Moderate Match' : 'Needs Improvement'}
      </div>
    </div>
    
    <!-- Personal Information Section -->
    ${personalInfo.name ? `
    <div style="margin: 30px 0; padding: 20px; background: var(--card); border-radius: 12px; border-left: 4px solid var(--accent);">
      <h3 style="margin-bottom: 15px; display: flex; align-items: center; gap: 10px; color: var(--accent);">
        <i class="fas fa-user"></i> Personal Information
      </h3>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
        <div><strong>Name:</strong> ${personalInfo.name} ${personalInfo.name_is_valid ? '✅' : '⚠️'}</div>
        <div><strong>Email:</strong> ${personalInfo.email || 'Not found'}</div>
        <div><strong>Phone:</strong> ${personalInfo.phone || 'Not found'}</div>
      </div>
    </div>
    ` : ''}
    
    <!-- Detailed Stats Grid -->
    <div class="stats-grid" style="margin-bottom: 40px;">
      <div class="stat-card">
        <div class="stat-number" style="color: var(--success);">${skillMatchPercent}%</div>
        <div class="stat-label">Skills Match</div>
      </div>
      <div class="stat-card">
        <div class="stat-number" style="color: var(--accent);">${experienceYears}</div>
        <div class="stat-label">Years Experience</div>
      </div>
      <div class="stat-card">
        <div class="stat-number" style="color: var(--primary);">${skills.matched.length}/${skills.needed.length}</div>
        <div class="stat-label">Skills Found</div>
      </div>
      <div class="stat-card">
        <div class="stat-number" style="color: var(--navy-green);">${experienceLevel}</div>
        <div class="stat-label">Experience Level</div>
      </div>
    </div>
    
    <!-- Education & Projects Section -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-bottom: 40px;">
      <!-- Education -->
      <div style="padding: 20px; background: var(--card); border-radius: 12px; border-left: 4px solid var(--primary);">
        <h4 style="color: var(--primary); margin-bottom: 15px; display: flex; align-items: center; gap: 8px;">
          <i class="fas fa-graduation-cap"></i> Education
        </h4>
        <div style="color: var(--text);">
          <div><strong>Highest Level:</strong> ${educationLevel}</div>
          ${analysis.education?.degrees ? `<div><strong>Degrees:</strong> ${analysis.education.degrees.join(', ')}</div>` : ''}
        </div>
      </div>
      
      <!-- Projects -->
      <div style="padding: 20px; background: var(--card); border-radius: 12px; border-left: 4px solid var(--warning);">
        <h4 style="color: var(--warning); margin-bottom: 15px; display: flex; align-items: center; gap: 8px;">
          <i class="fas fa-project-diagram"></i> Projects (${projects.length})
        </h4>
        <div style="color: var(--text); max-height: 150px; overflow-y: auto;">
          ${projects.length > 0 ? projects.map(project => `<div style="margin-bottom: 8px; padding: 8px; background: var(--card-hover); border-radius: 6px; font-size: 0.9rem;">• ${project}</div>`).join('') : '<div style="color: var(--muted); font-style: italic;">No projects detected</div>'}
        </div>
      </div>
    </div>
    
    <!-- Skills Analysis Section -->
    <div style="margin: 40px 0;">
      <h3 style="margin-bottom: 25px; display: flex; align-items: center; gap: 10px; font-size: 1.5rem;">
        <i class="fas fa-cogs" style="color: var(--accent);"></i> Skills Analysis
      </h3>
      
      <!-- Matched Skills -->
      <div style="margin-bottom: 25px; padding: 20px; background: var(--card); border-radius: 12px; border-left: 4px solid var(--success);">
        <h4 style="color: var(--success); margin-bottom: 15px; display: flex; align-items: center; gap: 8px;">
          <i class="fas fa-check-circle"></i> Your Skills (${skills.matched.length} matched)
        </h4>
        <div style="min-height: 50px;">${matchedPills || '<span style="color: var(--muted); font-style: italic;">No skills matched yet</span>'}</div>
      </div>
      
      <!-- Missing Skills -->
      <div style="margin-bottom: 25px; padding: 20px; background: var(--card); border-radius: 12px; border-left: 4px solid var(--error);">
        <h4 style="color: var(--error); margin-bottom: 15px; display: flex; align-items: center; gap: 8px;">
          <i class="fas fa-times-circle"></i> Skills to Develop (${skills.unmatched.length} missing)
        </h4>
        <div style="min-height: 50px;">${unmatchedPills || '<span style="color: var(--success); font-style: italic;">All required skills found! 🎉</span>'}</div>
      </div>
      
      <!-- All Required Skills -->
      <div style="margin-bottom: 25px; padding: 20px; background: var(--card); border-radius: 12px; border-left: 4px solid var(--accent);">
        <h4 style="color: var(--accent); margin-bottom: 15px; display: flex; align-items: center; gap: 8px;">
          <i class="fas fa-star"></i> All Required Skills for ${analysis.job_role}
        </h4>
        <div style="min-height: 50px;">${neededPills}</div>
      </div>
    </div>
    
    <!-- Alternative Career Paths -->
    ${altRoles ? `
    <div style="margin: 40px 0;">
      <h3 style="margin-bottom: 20px; display: flex; align-items: center; gap: 10px; font-size: 1.5rem;">
        <i class="fas fa-lightbulb" style="color: var(--warning);"></i> Alternative Career Paths
      </h3>
      <div style="padding: 20px; background: var(--card); border-radius: 12px; border-left: 4px solid var(--warning);">
        <p style="color: var(--muted); margin-bottom: 15px;">Based on your current skills, consider these roles:</p>
        <div>${altRoles}</div>
      </div>
    </div>
    ` : ''}
    
    <!-- AI Recommendations -->
    <div style="margin: 40px 0; padding: 25px; background: linear-gradient(135deg, var(--navy-green), var(--aqua-marine)); border-radius: 15px; color: white;">
      <h3 style="margin-bottom: 20px; display: flex; align-items: center; gap: 10px; font-size: 1.5rem;">
        <i class="fas fa-robot"></i> AI Recommendations
      </h3>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px;">
      <div>
          <h4 style="color: rgba(255,255,255,0.9); margin-bottom: 10px;">🎯 Immediate Actions</h4>
          <ul style="color: rgba(255,255,255,0.8); line-height: 1.6; margin: 0; padding-left: 20px;">
            <li>Focus on developing the ${skills.unmatched.length} missing skills</li>
            <li>Highlight your ${skills.matched.length} matched skills prominently</li>
            <li>Quantify your ${experienceYears} years of experience with specific achievements</li>
          </ul>
      </div>
        <div>
          <h4 style="color: rgba(255,255,255,0.9); margin-bottom: 10px;">📈 Long-term Goals</h4>
          <ul style="color: rgba(255,255,255,0.8); line-height: 1.6; margin: 0; padding-left: 20px;">
            <li>Gain more experience in ${analysis.job_role} to increase your score</li>
            <li>Consider pursuing ${educationLevel === 'Not specified' ? 'relevant education' : 'advanced education'}</li>
            <li>Build a portfolio showcasing your skills</li>
          </ul>
    </div>
      </div>
    </div>
  `;
  
  // Update download link
  const dl = document.getElementById('download_link');
  dl.href = '/api/report/' + (currentAnalysis.analysis_id || analysis.analysis_id);
  
  // Show achievements
  checkAchievements(analysis);
  displayAchievementsInResults(analysis);
}

// Achievement system
function checkAchievements(analysis) {
  const achievements = [];
  
  if (analysis.accuracy >= 90) {
    achievements.push({
      icon: 'fas fa-trophy',
      title: 'Resume Master',
      description: 'Achieved 90%+ match score!',
      color: 'var(--warning)'
    });
  }
  
  if (analysis.accuracy >= 70) {
    achievements.push({
      icon: 'fas fa-medal',
      title: 'Strong Match',
      description: 'Great job! 70%+ match achieved',
      color: 'var(--success)'
    });
  }
  
  if (analysis.skills.matched.length >= 8) {
    achievements.push({
      icon: 'fas fa-star',
      title: 'Skill Champion',
      description: 'Matched 8+ required skills',
      color: 'var(--accent)'
    });
  }
  
  if (analysis.experience_years >= 5) {
    achievements.push({
      icon: 'fas fa-briefcase',
      title: 'Experienced Professional',
      description: '5+ years of experience detected',
      color: 'var(--primary)'
    });
  }
  
  displayAchievements(achievements);
}

function displayAchievements(achievements) {
  const container = document.getElementById('achievements-list');
  if (achievements.length === 0) return;
  
  container.innerHTML = achievements.map(achievement => `
    <div class="achievement">
      <i class="${achievement.icon}" style="color: ${achievement.color};"></i>
      <div>
        <h4 style="margin: 0; color: var(--text);">${achievement.title}</h4>
        <p style="margin: 5px 0 0 0; color: var(--muted);">${achievement.description}</p>
      </div>
    </div>
  `).join('');
  
  userStats.achievements += achievements.length;
  updateUserStats();
}

function displayAchievementsInResults(analysis) {
  const achievements = [];
  
  if (analysis.accuracy >= 90) {
    achievements.push({
      icon: 'fas fa-trophy',
      title: 'Resume Master',
      description: 'Achieved 90%+ match score!',
      color: 'var(--warning)'
    });
  }
  
  if (analysis.accuracy >= 70) {
    achievements.push({
      icon: 'fas fa-medal',
      title: 'Strong Match',
      description: 'Great job! 70%+ match achieved',
      color: 'var(--success)'
    });
  }
  
  if (analysis.skills.matched.length >= 8) {
    achievements.push({
      icon: 'fas fa-star',
      title: 'Skill Champion',
      description: 'Matched 8+ required skills',
      color: 'var(--accent)'
    });
  }
  
  if (analysis.experience_years >= 5) {
    achievements.push({
      icon: 'fas fa-briefcase',
      title: 'Experienced Professional',
      description: '5+ years of experience detected',
      color: 'var(--primary)'
    });
  }
  
  if (analysis.accuracy >= 50) {
    achievements.push({
      icon: 'fas fa-thumbs-up',
      title: 'Good Start',
      description: 'Solid foundation for improvement',
      color: 'var(--navy-green)'
    });
  }
  
  const container = document.getElementById('achievements-display');
  if (achievements.length === 0) {
    container.innerHTML = '<p style="color: var(--muted); text-align: center; grid-column: 1 / -1;">Complete more analyses to unlock achievements!</p>';
    return;
  }
  
  container.innerHTML = achievements.map(achievement => `
    <div style="background: var(--card-hover); border-radius: 10px; padding: 15px; text-align: center; border: 2px solid ${achievement.color};">
      <i class="${achievement.icon}" style="font-size: 2rem; color: ${achievement.color}; margin-bottom: 10px;"></i>
      <h4 style="margin: 0 0 8px 0; color: var(--text); font-size: 1.1rem;">${achievement.title}</h4>
      <p style="margin: 0; color: var(--muted); font-size: 0.9rem;">${achievement.description}</p>
    </div>
  `).join('');
}

// User stats management
function updateUserStats() {
  userStats.totalAnalyses++;
  if (currentAnalysis) {
    userStats.avgScore = Math.round((userStats.avgScore * (userStats.totalAnalyses - 1) + currentAnalysis.accuracy) / userStats.totalAnalyses);
    userStats.points += Math.round(currentAnalysis.accuracy / 10);
    userStats.level = Math.floor(userStats.points / 100) + 1;
  }
  
  document.getElementById('total-analyses').textContent = userStats.totalAnalyses;
  document.getElementById('avg-score').textContent = userStats.avgScore + '%';
  document.getElementById('achievements').textContent = userStats.achievements;
  document.getElementById('user-level').textContent = `Level ${userStats.level}`;
  document.getElementById('user-points').textContent = `${userStats.points} Points`;
  
  // Show user stats when logged in
  if (userStats.totalAnalyses > 0) {
    document.getElementById('user-level').classList.remove('hidden');
    document.getElementById('user-points').classList.remove('hidden');
  }
}

function resetUserStats() {
  userStats = { totalAnalyses: 0, avgScore: 0, achievements: 0, level: 1, points: 0 };
  document.getElementById('user-level').classList.add('hidden');
  document.getElementById('user-points').classList.add('hidden');
}

// Utility functions
function showMessage(text, type = 'info') {
  const msg = document.getElementById('auth_msg') || document.getElementById('upload_msg');
  if (!msg) return;
  
  msg.textContent = text;
  msg.className = '';
  
  switch(type) {
    case 'success':
      msg.style.background = 'var(--success)';
      msg.style.color = 'white';
      break;
    case 'error':
      msg.style.background = 'var(--error)';
      msg.style.color = 'white';
      break;
    case 'warning':
      msg.style.background = 'var(--warning)';
      msg.style.color = 'white';
      break;
    default:
      msg.style.background = 'var(--accent)';
      msg.style.color = 'white';
  }
}

function backToUpload() {
  showUpload();
  document.getElementById('resume_file').value = '';
  document.getElementById('job_role').value = '';
  document.getElementById('upload_msg').textContent = '';
}

// Theme management
function saveTheme(theme) { 
  try { localStorage.setItem('theme', theme); } catch(e) {} 
}

function loadTheme() { 
  try { return localStorage.getItem('theme'); } catch(e) { return null; } 
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'light') { 
    root.classList.add('light'); 
  } else { 
    root.classList.remove('light'); 
  }
}

function toggleTheme() { 
  const next = document.documentElement.classList.contains('light') ? 'dark' : 'light'; 
  applyTheme(next); 
  saveTheme(next); 
}

// Initialize app
async function init() { 
  const t = loadTheme(); 
  if (t) applyTheme(t); 
  await loadJobs(); 
}

// Start the app
init();
</script>

</body>
</html>
""".replace('%HERO_IMG%', HERO_IMG).replace('%SEC_IMG1%', SEC_IMG1).replace('%SEC_IMG2%', SEC_IMG2)


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


###############################################################################
# Entry
###############################################################################

MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


# Enhanced name extraction
def guess_name(text: str, email: str) -> str:
    lines = [l.strip() for l in re.split(r"\n", text) if l.strip()][:20]
    # skip obvious headings
    blacklist = {"resume", "curriculum vitae", "cv", "profile"}
    candidates = []
    for line in lines:
        plain = re.sub(r"[^A-Za-z'\-\s]", "", line).strip()
        if not plain:
            continue
        if plain.lower() in blacklist:
            continue
        if 2 <= len(plain.split()) <= 5 and validate_name_format(plain):
            candidates.append(plain)
    if candidates:
        return candidates[0]
    # Fallback to email if no name found
    if email:
        local = email.split("@")[0]
        parts = re.split(r"[._\-]", local)
        if len(parts) >= 2:
            return " ".join([w.capitalize() for w in parts if w.isalpha()])
    return "Unknown"


def parse_month_year_range(s: str):
    s = s.lower()
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\s*(\d{4})\s*[-–]\s*(present|current|now|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\s*\d{4})",
                   s)
    if not m:
        return None
    sm_name, sy, end_part = m.group(1), m.group(2), m.group(3)
    sm = MONTHS.get(sm_name, None)
    sy = int(sy)
    if end_part in {"present", "current", "now"}:
        ey = datetime.utcnow().year
        em = datetime.utcnow().month
    else:
        parts = re.findall(r"([a-z]+)\s*(\d{4})", end_part)
        if not parts:
            return None
        em_name, ey = parts[0]
        em = MONTHS.get(em_name, None)
        ey = int(ey)
    if not sm or not em:
        return None
    months = (ey - sy) * 12 + (em - sm)
    return max(0, months) / 12.0


def extract_experience_years(text: str) -> float:
    # Try month-year ranges first
    total = 0.0
    for line in re.split(r"\n", text):
        # NOTE: The helper function parse_month_year_range is missing. 
        # Assuming it returns a float or 0.0.
        dur = parse_month_year_range(line)
        if dur:
            total += dur
    if total > 0:
        return round(total, 1)

    # Fallback to previous heuristic to find years directly.
    lower = text.lower()
    years = []
    # 1. Explicit "X years" or "X yrs"
    for m in re.finditer(r"(\d{1,2})\+?\s*(?:years|yrs|year)", lower):
        years.append(int(m.group(1)))
    # 2. Date ranges like "2019-2022", "Jan 2020 - Present"
    date_patterns = re.findall(r"([a-z]{3,9}\s*\d{4}|\d{4})\s*[-–to]+\s*(present|[a-z]{3,9}\s*\d{4}|\d{4})", lower, flags=re.IGNORECASE)
    for start_str, end_str in date_patterns:
        try:
            start = parser.parse(start_str, default=datetime(1900,1,1)).year if not start_str.isdigit() else int(start_str)
            end = datetime.utcnow().year if "present" in end_str.lower() else (parser.parse(end_str, default=datetime(1900,1,1)).year if not end_str.isdigit() else int(end_str))
            if end >= start:
                years.append(end - start)
        except Exception:
            continue
    # Pick the max rather than sum (prevents double counting)
    return max(years) if years else 0.0




def extract_projects(text: str) -> list:
    # Look for a Projects section and collect bullet-like lines
    lines = [l.rstrip() for l in text.splitlines()]
    projects = []
    in_section = False
    for l in lines:
        if re.search(r"^\s*projects?\b", l, re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if re.match(r"^\s*[A-Z][A-Za-z\s]{3,}$", l) and len(l.strip().split()) < 6:
                # likely a new uppercase heading; stop
                break
            if re.match(r"^\s*[-•\u2022]", l) or len(l.strip()) > 0:
                projects.append(l.strip())
    if not projects:
        # Fallback: first 3 bullet-like lines anywhere
        bullets = [l.strip() for l in lines if re.match(r"^\s*[-•\u2022]", l)]
        projects = bullets[:5]
    # Clean bullets
    projects = [re.sub(r"^[-•\u2022]\s*", "", p) for p in projects]
    return [p for p in projects if p][:5]


def generate_pdf_report(doc: dict) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=LETTER)
    width, height = LETTER
    x, y = 50, height - 50

    def write_line(text, font="Helvetica", size=11, leading=16, bold=False):
        nonlocal y
        if bold:
            c.setFont(f"{font}-Bold", size)
        else:
            c.setFont(font, size)
        # wrap lines
        lines = simpleSplit(text, f"{font}-Bold" if bold else font, size, width - 2 * x)
        for line in lines:
            c.drawString(x, y, line)
            y -= leading
            if y < 60:
                c.showPage()
                y = height - 50
                c.setFont(f"{font}-Bold" if bold else font, size)

    def draw_rectangle(x1, y1, x2, y2, fill=0):
        c.setFillColorRGB(fill, fill, fill)
        c.rect(x1, y1, x2-x1, y2-y1, fill=1, stroke=0)

    def draw_score_circle(center_x, center_y, radius, score, max_score=100):
        # Background circle
        c.setFillColorRGB(0.9, 0.9, 0.9)
        c.circle(center_x, center_y, radius, fill=1, stroke=0)
        
        # Score arc
        if score > 0:
            # Green for high scores, yellow for medium, red for low
            if score >= 80:
                c.setFillColorRGB(0.2, 0.8, 0.2)  # Green
            elif score >= 60:
                c.setFillColorRGB(0.9, 0.6, 0.1)  # Orange
            else:
                c.setFillColorRGB(0.8, 0.2, 0.2)  # Red
            
            # Draw arc based on score percentage
            arc_angle = (score / max_score) * 360
            c.circle(center_x, center_y, radius, fill=0, stroke=1)
            # Note: ReportLab doesn't have direct arc drawing, so we'll use a filled circle
            c.circle(center_x, center_y, radius * 0.8, fill=1, stroke=0)

    # Header
    c.setFillColorRGB(0.2, 0.4, 0.8)
    draw_rectangle(0, height - 100, width, height, 0.1)
    
    write_line("RESAN AI - RESUME ANALYSIS REPORT", size=18, bold=True)
    write_line(f"Generated on: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", size=10)
    write_line("")

    # Resume info
    write_line(f"Resume File: {doc.get('uploaded_filename', 'Unknown')}", size=12, bold=True)
    write_line(f"Target Job Role: {doc.get('job_role', 'Not specified')}", size=12, bold=True)
    write_line("")

    # Overall Score Section
    write_line("OVERALL ANALYSIS SCORE", size=14, bold=True)
    accuracy = doc.get('accuracy', 0)
    
    # Draw score visualization
    score_x = width - 150
    score_y = y + 20
    draw_score_circle(score_x, score_y, 40, accuracy)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(score_x - 15, score_y - 5, f"{accuracy}%")
    
    write_line(f"Match Score: {accuracy}%", size=12, bold=True)
    
    # Score interpretation
    if accuracy >= 90:
        write_line("EXCELLENT MATCH - You're highly qualified for this role!", size=11)
    elif accuracy >= 70:
        write_line("GOOD MATCH - Strong candidate with room for improvement", size=11)
    elif accuracy >= 50:
        write_line("MODERATE MATCH - Consider developing missing skills", size=11)
    else:
        write_line("NEEDS IMPROVEMENT - Focus on skill development", size=11)
    
    write_line("")
    
    # Skills Analysis
    skills = doc.get("skills", {})
    needed_skills = skills.get('needed', [])
    matched_skills = skills.get('matched', [])
    unmatched_skills = skills.get('unmatched', [])
    
    write_line("SKILLS ANALYSIS", size=14, bold=True)
    write_line("")

    # Skills summary
    write_line(f"Required Skills: {len(needed_skills)}", size=12, bold=True)
    write_line(f"Matched Skills: {len(matched_skills)} ({len(matched_skills)/max(len(needed_skills), 1)*100:.1f}%)", size=11)
    write_line(f"Missing Skills: {len(unmatched_skills)}", size=11)
    write_line("")
    
    # Matched skills
    if matched_skills:
        write_line("✓ SKILLS YOU HAVE:", size=12, bold=True)
        for skill in matched_skills[:10]:  # Limit to first 10
            write_line(f"  • {skill}", size=10)
        write_line("")
    
    # Missing skills
    if unmatched_skills:
        write_line("⚠ SKILLS TO DEVELOP:", size=12, bold=True)
        for skill in unmatched_skills[:10]:  # Limit to first 10
            write_line(f"  • {skill}", size=10)
        write_line("")
    
    # All required skills
    write_line("📋 ALL REQUIRED SKILLS:", size=12, bold=True)
    for i, skill in enumerate(needed_skills[:15], 1):  # Limit to first 15
        status = "✓" if skill in matched_skills else "○"
        write_line(f"  {i:2d}. {status} {skill}", size=10)
    write_line("")
    
    # Alternative Roles
    alts = doc.get("alternatives", [])
    if alts:
        write_line("ALTERNATIVE CAREER PATHS", size=14, bold=True)
        write_line("Based on your current skills, consider these roles:", size=11)
        write_line("")
        for i, alt in enumerate(alts[:5], 1):  # Top 5 alternatives
            role = alt.get('role', 'Unknown')
            match = alt.get('match_percent', 0)
            write_line(f"{i}. {role} ({match}% match)", size=11, bold=True)
        write_line("")
    
    # Recommendations
    write_line("RECOMMENDATIONS", size=14, bold=True)
    write_line("")
    
    recommendations = [
        f"Focus on developing the {len(unmatched_skills)} missing skills to improve your match percentage",
        f"Highlight your {len(matched_skills)} matched skills prominently in your resume",
        "Consider gaining more experience in your target field to increase your score",
        "Explore the alternative career paths that match your current skills",
        "Regularly update your resume with new skills and experiences"
    ]
    
    for i, rec in enumerate(recommendations, 1):
        write_line(f"{i}. {rec}", size=10)
    
    write_line("")
    
    # Footer
    write_line("=" * 60, size=10)
    write_line("This report was generated by Resan AI - Your AI Resume Analyzer", size=10)
    write_line("For more insights and career guidance, visit our platform", size=10)

    c.showPage()
    c.save()
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    