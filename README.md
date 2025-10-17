# Resan AI - Gamified Resume Analyzer 🚀

A modern, interactive AI-powered resume analyzer with gamification features, comprehensive analysis, and beautiful visualizations. Transform your resume analysis into an engaging experience with points, achievements, and detailed insights.

## ✨ Key Features

### 🎮 Gamification
- **Points System**: Earn points based on analysis scores
- **Achievement System**: Unlock badges for milestones
- **Level Progression**: Level up as you improve your resume
- **Progress Tracking**: Visual progress bars and real-time feedback
- **User Statistics**: Track your analysis history and improvements

### 🔍 Comprehensive Analysis
- **Smart Resume Parsing**: Extract text from PDF and TXT files
- **Skills Matching**: Compare your skills against 20+ job roles
- **Experience Analysis**: Calculate years of experience from date ranges
- **Education Detection**: Identify degrees and qualifications
- **Project Extraction**: Find and analyze project descriptions
- **Alternative Career Paths**: Discover roles that match your skills

### 🎨 Modern UI/UX
- **Glass Morphism Design**: Beautiful glassmorphic interface
- **Dark/Light Themes**: Toggle between themes
- **Responsive Design**: Works on all devices
- **Smooth Animations**: Engaging micro-interactions
- **Real-time Progress**: Live analysis progress with status updates
- **Interactive Elements**: Hover effects and visual feedback

### 📊 Enhanced Reporting
- **Interactive PDF Reports**: Comprehensive analysis with visualizations
- **Detailed Insights**: Strengths, weaknesses, and recommendations
- **Market Intelligence**: Role demand and competition analysis
- **Skill Breakdown**: Visual skill matching with color coding
- **Career Recommendations**: Personalized advice for improvement

### 🔧 Technical Features
- **MongoDB Integration**: Secure user data and analysis history
- **Session Management**: Secure authentication with bcrypt
- **File Processing**: Support for PDF and TXT resume formats
- **RESTful API**: Clean API endpoints for all functionality
- **Error Handling**: Comprehensive error management
- **Performance Optimized**: Fast analysis and responsive UI

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- MongoDB Atlas (or local MongoDB)
- Modern web browser

### Installation

1. **Clone and Setup**
```bash
git clone <your-repo>
cd resan-ai
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. **Install Dependencies**
```bash
pip install -r requirements.txt
```

3. **Configure Environment**
```bash
export MONGODB_URI="your_mongodb_connection_string"
export SECRET_KEY="your_secret_key"
```

4. **Run the Application**
```bash
python app.py
```

5. **Open in Browser**
```
http://localhost:5000
```

## 📱 How to Use

### 1. **Sign Up / Login**
- Create an account or log in with existing credentials
- Your progress and achievements are saved

### 2. **Upload Resume**
- Select your resume file (PDF or TXT)
- Choose your target job role from 20+ options
- Watch the real-time analysis progress

### 3. **View Results**
- See your overall match score with visual indicators
- Explore matched and missing skills
- Discover alternative career paths
- Earn points and unlock achievements

### 4. **Download Report**
- Get a comprehensive PDF report
- Includes detailed insights and recommendations
- Perfect for sharing with mentors or career advisors

## 🎯 Job Roles Supported

- Software Engineer
- Data Scientist
- Data Analyst
- Product Manager
- DevOps Engineer
- UI/UX Designer
- QA Engineer
- Mobile Developer
- AI/ML Engineer
- Cloud Engineer
- Cybersecurity Analyst
- Business Analyst
- HR Generalist
- Digital Marketer
- Content Writer
- Sales Executive
- Operations Manager
- Finance Analyst
- Graphic Designer
- Project Manager
- Customer Support
- Technical Writer
- Systems Administrator

## 🔌 API Endpoints

### Authentication
- `POST /api/signup` - Create new account
- `POST /api/login` - User login
- `POST /api/logout` - User logout

### Analysis
- `POST /api/analyze` - Analyze resume (multipart form)
- `GET /api/jobs` - Get available job roles
- `GET /api/report/{id}` - Download PDF report
- `GET /api/analyses` - Get user's analysis history
- `GET /api/stats` - Get user statistics
- `GET /api/insights/{id}` - Get detailed insights

## 🏆 Achievement System

### Available Achievements
- **Resume Master**: Achieve 90%+ match score
- **Strong Match**: Achieve 70%+ match score
- **Skill Champion**: Match 8+ required skills
- **Experienced Professional**: 5+ years experience detected
- **Analysis Expert**: Complete 10+ analyses
- **Career Explorer**: Try 5+ different job roles

### Points System
- **Base Points**: 1 point per 10% match score
- **Bonus Points**: Extra points for high scores
- **Streak Bonus**: Consecutive high scores
- **Achievement Bonus**: Points for unlocking achievements

## 🎨 Customization

### Adding New Job Roles
Edit the `JOB_ROLES` dictionary in `app.py`:
```python
JOB_ROLES = {
    "Your New Role": [
        "skill1", "skill2", "skill3", ...
    ]
}
```

### Modifying Scoring
Adjust the scoring weights in the `score_resume` function:
```python
# Current weights: 70% skills, 20% experience, 10% education
total = 0.7 * skill_score + 0.2 * exp_score + 0.1 * edu_bonus
```

### Adding Skill Synonyms
Update the `SKILL_SYNONYMS` dictionary:
```python
SKILL_SYNONYMS = {
    "your_skill": {"synonym1", "synonym2"},
}
```

## 🚀 Deployment

### Render (Recommended)
1. Push to GitHub
2. Connect to Render
3. Set environment variables:
   - `MONGODB_URI`
   - `SECRET_KEY`
4. Deploy!

### Railway
1. Connect GitHub repo
2. Add environment variables
3. Deploy with `gunicorn app:app --bind 0.0.0.0:$PORT`

### Docker
```dockerfile
FROM python:3.10-slim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000"]
```

## 🔧 Troubleshooting

### Common Issues
- **PDF parsing errors**: Ensure `pdfminer.six` is installed
- **MongoDB connection**: Verify connection string and IP allowlist
- **Theme not saving**: Check browser localStorage permissions
- **File upload issues**: Ensure file is PDF or TXT format

### Performance Tips
- Use text-based PDFs for better parsing
- Keep resume files under 10MB
- Clear browser cache if UI issues persist

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

MIT License - feel free to use and modify!

## 🙏 Acknowledgments

- Flask for the web framework
- MongoDB for data storage
- ReportLab for PDF generation
- Font Awesome for icons
- Unsplash for images

---

**Made with ❤️ for job seekers everywhere**

Transform your resume analysis from a chore into an engaging, gamified experience. Level up your career prospects with Resan AI! 🚀
