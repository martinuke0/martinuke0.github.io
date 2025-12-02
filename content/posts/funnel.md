---
title: "The Complete Guide to Python Sales Funnels with FastAPI: From Beginner to Hero"
date: 2025-12-02T23:58:00+02:00
draft: false
tags: ["python", "sales-funnels", "fastapi", "web-development", "business"]
---

# The Complete Guide to Python Sales Funnels with FastAPI: From Beginner to Hero

Learn how to build professional, high-performance sales funnels using FastAPI. This guide takes you from zero to deployed funnel in under an hour.

## What You'll Build

By the end of this tutorial, you'll have a complete, production-ready sales funnel system that includes:

- High-performance landing pages with email capture
- Async request handling for better scalability
- Automatic API documentation
- Email integration ready for customization
- CSV-based lead storage (easily upgradeable to database)
- Mobile-responsive design
- Type-safe code with Pydantic validation

## Prerequisites

- Python 3.8+ installed
- Basic understanding of Python (variables, functions)
- A text editor (VS Code recommended)
- 30-60 minutes of your time

## Part 1: Understanding Sales Funnels

A sales funnel guides potential clients through stages:

1. Awareness - Landing page captures attention
2. Interest - Value proposition hooks them in
3. Action - Email capture or booking form
4. Follow-up - Thank you page and email sequence

## Part 2: Quick Setup (5 minutes)

### Install Dependencies

```bash
# Create project folder
mkdir fastapi-funnel
cd fastapi-funnel

# Create virtual environment
python -m venv venv

# Activate it (Windows)
venv\Scripts\activate
# Activate it (Mac/Linux)
source venv/bin/activate

# Install FastAPI and dependencies
pip install fastapi uvicorn python-multipart jinja2 aiofiles pydantic[email]
```

### Project Structure

```
fastapi-funnel/
├── main.py                # Main application
├── templates/             # HTML templates
│   ├── landing.html
│   ├── thankyou.html
│   ├── leads.html
│   └── base.html
├── static/               # CSS, images
│   └── style.css
├── models.py             # Pydantic models
└── leads.csv             # Store captured leads
```

## Part 3: Build Your First Funnel (20 minutes)

### Step 1: Create Data Models

Create `models.py`:

```python
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class LeadCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=20)

class Lead(LeadCreate):
    timestamp: datetime
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "+1234567890",
                "timestamp": "2025-12-02T10:30:00"
            }
        }
```

### Step 2: Create the FastAPI App

Create `main.py`:

```python
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from datetime import datetime
from typing import List
import csv
import os
import aiofiles
from models import LeadCreate, Lead

app = FastAPI(
    title="Sales Funnel API",
    description="High-performance sales funnel with FastAPI",
    version="1.0.0"
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates")

# Configuration
LEADS_FILE = 'leads.csv'

async def save_lead(lead: LeadCreate) -> None:
    """Save lead to CSV file asynchronously"""
    file_exists = os.path.isfile(LEADS_FILE)
    
    async with aiofiles.open(LEADS_FILE, 'a', newline='', encoding='utf-8') as f:
        if not file_exists:
            await f.write('Timestamp,Name,Email,Phone\n')
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f'{timestamp},{lead.name},{lead.email},{lead.phone or ""}\n'
        await f.write(line)

async def get_leads() -> List[Lead]:
    """Read all leads from CSV file"""
    leads = []
    
    if not os.path.isfile(LEADS_FILE):
        return leads
    
    async with aiofiles.open(LEADS_FILE, 'r', encoding='utf-8') as f:
        content = await f.read()
        lines = content.strip().split('\n')
        
        # Skip header
        for line in lines[1:]:
            if line:
                parts = line.split(',')
                if len(parts) >= 3:
                    leads.append(Lead(
                        timestamp=datetime.strptime(parts[0], '%Y-%m-%d %H:%M:%S'),
                        name=parts[1],
                        email=parts[2],
                        phone=parts[3] if len(parts) > 3 else None
                    ))
    
    return leads

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Landing page - the top of your funnel"""
    return templates.TemplateResponse("landing.html", {"request": request})

@app.post("/submit")
async def submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(None)
):
    """Handle form submission"""
    try:
        # Validate data
        lead = LeadCreate(name=name, email=email, phone=phone)
        
        # Save the lead
        await save_lead(lead)
        
        # Redirect to thank you page
        return RedirectResponse(
            url=f"/thankyou?name={lead.name}",
            status_code=303
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/thankyou", response_class=HTMLResponse)
async def thankyou(request: Request, name: str = "Friend"):
    """Thank you page - confirm submission"""
    return templates.TemplateResponse(
        "thankyou.html",
        {"request": request, "name": name}
    )

@app.get("/leads", response_class=HTMLResponse)
async def view_leads(request: Request):
    """View all captured leads - PROTECT THIS IN PRODUCTION"""
    leads = await get_leads()
    return templates.TemplateResponse(
        "leads.html",
        {"request": request, "leads": leads}
    )

@app.get("/api/leads", response_model=List[Lead])
async def api_leads():
    """API endpoint to get all leads as JSON"""
    return await get_leads()

@app.get("/api/stats")
async def api_stats():
    """API endpoint for funnel statistics"""
    leads = await get_leads()
    return {
        "total_leads": len(leads),
        "today": len([l for l in leads if l.timestamp.date() == datetime.now().date()]),
        "has_phone": len([l for l in leads if l.phone])
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

### Step 3: Create Base Template

Create `templates/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Sales Funnel{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', path='/style.css') }}">
</head>
<body>
    {% block content %}{% endblock %}
</body>
</html>
```

### Step 4: Create Landing Page

Create `templates/landing.html`:

```html
{% extends "base.html" %}

{% block title %}Get Your Free Consultation{% endblock %}

{% block content %}
<div class="container">
    <div class="hero">
        <h1>Transform Your Business in 30 Days</h1>
        <p class="subtitle">Join 1,000+ entrepreneurs who've scaled their revenue with our proven system</p>
    </div>

    <div class="benefits">
        <div class="benefit">
            <span class="icon">&#8593;</span>
            <h3>Fast Results</h3>
            <p>See measurable growth in weeks, not months</p>
        </div>
        <div class="benefit">
            <span class="icon">&#36;</span>
            <h3>Proven ROI</h3>
            <p>Average client sees 3x return in first quarter</p>
        </div>
        <div class="benefit">
            <span class="icon">&#9733;</span>
            <h3>Personalized</h3>
            <p>Custom strategies for your unique business</p>
        </div>
    </div>

    <div class="form-section">
        <h2>Get Your Free Strategy Session</h2>
        <p>Limited spots available - Book yours now</p>
        
        <form method="POST" action="/submit" class="lead-form">
            <input type="text" name="name" placeholder="Your Name" required minlength="2">
            <input type="email" name="email" placeholder="Your Email" required>
            <input type="tel" name="phone" placeholder="Phone (Optional)">
            <button type="submit" class="cta-button">Get My Free Session</button>
        </form>
        
        <p class="privacy">We respect your privacy. No spam, ever.</p>
    </div>

    <div class="social-proof">
        <p class="testimonial">"This system doubled our revenue in 60 days!" - Sarah K., CEO</p>
        <p class="testimonial">"Finally, marketing that actually works." - Mike T., Founder</p>
    </div>
</div>
{% endblock %}
```

### Step 5: Create Thank You Page

Create `templates/thankyou.html`:

```html
{% extends "base.html" %}

{% block title %}Thank You{% endblock %}

{% block content %}
<div class="container thankyou">
    <div class="success-icon">&#10004;</div>
    <h1>You're In, {{ name }}!</h1>
    <p class="subtitle">Check your email - we've sent you the details.</p>
    
    <div class="next-steps">
        <h2>What Happens Next?</h2>
        <ol>
            <li><strong>Check Your Inbox</strong> - Confirmation email arriving now</li>
            <li><strong>Calendar Invite</strong> - We'll send your session details within 24 hours</li>
            <li><strong>Prepare</strong> - Think about your biggest business challenge</li>
        </ol>
    </div>

    <div class="cta-secondary">
        <h3>While You Wait...</h3>
        <p>Follow us for daily business tips:</p>
        <div class="social-links">
            <a href="#" class="social-btn">Twitter</a>
            <a href="#" class="social-btn">LinkedIn</a>
            <a href="#" class="social-btn">Instagram</a>
        </div>
    </div>

    <a href="/" class="back-link">Back to Home</a>
</div>
{% endblock %}
```

### Step 6: Create Leads Dashboard

Create `templates/leads.html`:

```html
{% extends "base.html" %}

{% block title %}Leads Dashboard{% endblock %}

{% block content %}
<div class="container">
    <h1>Captured Leads</h1>
    <p>Total: {{ leads|length }}</p>
    
    <div class="stats">
        <div class="stat-box">
            <h3>{{ leads|length }}</h3>
            <p>Total Leads</p>
        </div>
        <div class="stat-box">
            <h3>{{ leads|selectattr('phone')|list|length }}</h3>
            <p>With Phone</p>
        </div>
    </div>
    
    <table class="leads-table">
        <thead>
            <tr>
                <th>Timestamp</th>
                <th>Name</th>
                <th>Email</th>
                <th>Phone</th>
            </tr>
        </thead>
        <tbody>
            {% for lead in leads %}
            <tr>
                <td>{{ lead.timestamp.strftime('%Y-%m-%d %H:%M') }}</td>
                <td>{{ lead.name }}</td>
                <td>{{ lead.email }}</td>
                <td>{{ lead.phone or '-' }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <div class="api-links">
        <h3>API Endpoints</h3>
        <a href="/api/leads" target="_blank">View Leads JSON</a>
        <a href="/api/stats" target="_blank">View Stats JSON</a>
        <a href="/docs" target="_blank">API Documentation</a>
    </div>
</div>
{% endblock %}
```

### Step 7: Add Styling

Create `static/style.css`:

```css
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    line-height: 1.6;
    color: #333;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    padding: 20px;
}

.container {
    max-width: 800px;
    margin: 0 auto;
    background: white;
    border-radius: 20px;
    padding: 60px 40px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
}

.hero {
    text-align: center;
    margin-bottom: 50px;
}

.hero h1 {
    font-size: 2.5em;
    color: #1a1a1a;
    margin-bottom: 15px;
}

.subtitle {
    font-size: 1.2em;
    color: #666;
    margin-bottom: 30px;
}

.benefits {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 30px;
    margin: 50px 0;
}

.benefit {
    text-align: center;
    padding: 20px;
}

.icon {
    font-size: 3em;
    display: block;
    margin-bottom: 15px;
    color: #667eea;
}

.benefit h3 {
    color: #667eea;
    margin-bottom: 10px;
}

.form-section {
    background: #f8f9fa;
    padding: 40px;
    border-radius: 15px;
    margin: 40px 0;
}

.form-section h2 {
    text-align: center;
    color: #1a1a1a;
    margin-bottom: 10px;
}

.form-section > p {
    text-align: center;
    color: #666;
    margin-bottom: 30px;
}

.lead-form {
    display: flex;
    flex-direction: column;
    gap: 15px;
}

.lead-form input {
    padding: 15px;
    border: 2px solid #e0e0e0;
    border-radius: 8px;
    font-size: 1em;
    transition: border-color 0.3s;
}

.lead-form input:focus {
    outline: none;
    border-color: #667eea;
}

.cta-button {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 18px;
    border: none;
    border-radius: 8px;
    font-size: 1.1em;
    font-weight: bold;
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
}

.cta-button:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 25px rgba(102, 126, 234, 0.4);
}

.privacy {
    text-align: center;
    color: #999;
    font-size: 0.9em;
    margin-top: 15px;
}

.social-proof {
    margin-top: 50px;
    padding-top: 30px;
    border-top: 2px solid #e0e0e0;
}

.testimonial {
    font-style: italic;
    color: #666;
    text-align: center;
    margin: 15px 0;
    font-size: 1.1em;
}

/* Thank You Page */
.thankyou {
    text-align: center;
}

.success-icon {
    font-size: 5em;
    margin-bottom: 20px;
    color: #28a745;
}

.next-steps {
    background: #f8f9fa;
    padding: 30px;
    border-radius: 15px;
    margin: 40px 0;
    text-align: left;
}

.next-steps ol {
    margin-left: 20px;
    margin-top: 20px;
}

.next-steps li {
    margin: 15px 0;
    font-size: 1.1em;
}

.cta-secondary {
    margin-top: 40px;
}

.social-links {
    display: flex;
    gap: 15px;
    justify-content: center;
    margin-top: 20px;
}

.social-btn {
    padding: 10px 25px;
    background: #667eea;
    color: white;
    text-decoration: none;
    border-radius: 5px;
    transition: background 0.3s;
}

.social-btn:hover {
    background: #764ba2;
}

.back-link {
    display: inline-block;
    margin-top: 30px;
    color: #667eea;
    text-decoration: none;
    font-weight: 500;
}

.back-link:hover {
    text-decoration: underline;
}

/* Leads Dashboard */
.stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 20px;
    margin: 30px 0;
}

.stat-box {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 25px;
    border-radius: 10px;
    text-align: center;
}

.stat-box h3 {
    font-size: 2.5em;
    margin-bottom: 5px;
}

.stat-box p {
    font-size: 0.9em;
    opacity: 0.9;
}

.leads-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 30px;
}

.leads-table th,
.leads-table td {
    padding: 12px;
    text-align: left;
    border-bottom: 1px solid #e0e0e0;
}

.leads-table th {
    background: #667eea;
    color: white;
}

.leads-table tr:hover {
    background: #f8f9fa;
}

.api-links {
    margin-top: 40px;
    padding: 25px;
    background: #f8f9fa;
    border-radius: 10px;
}

.api-links h3 {
    margin-bottom: 15px;
    color: #1a1a1a;
}

.api-links a {
    display: inline-block;
    margin: 5px 10px 5px 0;
    padding: 8px 15px;
    background: #667eea;
    color: white;
    text-decoration: none;
    border-radius: 5px;
    font-size: 0.9em;
}

.api-links a:hover {
    background: #764ba2;
}

/* Mobile Responsive */
@media (max-width: 768px) {
    .container {
        padding: 40px 20px;
    }
    
    .hero h1 {
        font-size: 1.8em;
    }
    
    .benefits {
        grid-template-columns: 1fr;
    }
    
    .form-section {
        padding: 30px 20px;
    }
    
    .stats {
        grid-template-columns: 1fr;
    }
}
```

## Part 4: Launch Your Funnel (2 minutes)

```bash
# Run the application
python main.py
```

Visit `http://localhost:8000` - Your funnel is live!

Visit `http://localhost:8000/docs` - Interactive API documentation (auto-generated by FastAPI)

## Part 5: FastAPI Advantages

### Automatic API Documentation

FastAPI automatically generates interactive API docs:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Built-in Data Validation

Pydantic models validate all incoming data:

```python
# Invalid email automatically rejected
# Missing required fields caught before processing
# Type mismatches handled gracefully
```

### High Performance

FastAPI is one of the fastest Python frameworks:

- Async/await support for concurrent requests
- Built on Starlette and Pydantic
- Production-ready performance

## Part 6: Customization Guide

### Change the Copy

Edit `templates/landing.html`:

```html
<!-- Change headline -->
<h1>Your Unique Value Proposition Here</h1>

<!-- Update benefits -->
<div class="benefit">
    <span class="icon">&#9733;</span>
    <h3>Your Benefit</h3>
    <p>Your benefit description</p>
</div>
```

### Add New Form Fields

1. Update `models.py`:

```python
class LeadCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=20)
    company: Optional[str] = Field(None, max_length=100)  # New field
    message: Optional[str] = Field(None, max_length=500)  # New field
```

2. Update form in `templates/landing.html`:

```html
<input type="text" name="company" placeholder="Company Name (Optional)">
<textarea name="message" placeholder="Tell us about your needs" rows="4"></textarea>
```

3. Update `main.py` submit function:

```python
@app.post("/submit")
async def submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(None),
    company: str = Form(None),
    message: str = Form(None)
):
    lead = LeadCreate(
        name=name,
        email=email,
        phone=phone,
        company=company,
        message=message
    )
    await save_lead(lead)
    return RedirectResponse(url=f"/thankyou?name={lead.name}", status_code=303)
```

### Change Colors

Edit `static/style.css`:

```css
/* Primary gradient - change these hex values */
background: linear-gradient(135deg, #YOUR_COLOR_1 0%, #YOUR_COLOR_2 100%);

/* Update all instances of #667eea and #764ba2 */
```

### Add Email Notifications

Install email library:

```bash
pip install fastapi-mail
```

Create `email_config.py`:

```python
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from pydantic import EmailStr
from typing import List

conf = ConnectionConfig(
    MAIL_USERNAME="your-email@gmail.com",
    MAIL_PASSWORD="your-app-password",
    MAIL_FROM="your-email@gmail.com",
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True
)

fm = FastMail(conf)

async def send_welcome_email(name: str, email: EmailStr):
    message = MessageSchema(
        subject="Welcome! Your Free Session Details",
        recipients=[email],
        body=f"""Hi {name},

Thank you for signing up! We're excited to work with you.

Your free strategy session will be scheduled within 24 hours.

Best regards,
Your Team
""",
        subtype="plain"
    )
    
    await fm.send_message(message)
```

Update `main.py`:

```python
from email_config import send_welcome_email

@app.post("/submit")
async def submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(None)
):
    lead = LeadCreate(name=name, email=email, phone=phone)
    await save_lead(lead)
    
    # Send welcome email asynchronously
    await send_welcome_email(lead.name, lead.email)
    
    return RedirectResponse(url=f"/thankyou?name={lead.name}", status_code=303)
```

### Add Database Support

Install SQLAlchemy:

```bash
pip install sqlalchemy aiosqlite
```

Create `database.py`:

```python
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

SQLALCHEMY_DATABASE_URL = "sqlite:///./leads.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class LeadDB(Base):
    __tablename__ = "leads"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.now)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    phone = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)
```

Update `main.py` to use database:

```python
from database import SessionLocal, LeadDB

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/submit")
async def submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(None),
    db: Session = Depends(get_db)
):
    lead = LeadCreate(name=name, email=email, phone=phone)
    
    # Save to database
    db_lead = LeadDB(**lead.dict(), timestamp=datetime.now())
    db.add(db_lead)
    db.commit()
    
    return RedirectResponse(url=f"/thankyou?name={lead.name}", status_code=303)
```

### Add Analytics Tracking

Add to `templates/base.html` before `</head>`:

```html
<!-- Google Analytics -->
<script async src="https://www.googletagmanager.com/gtag/js?id=GA_MEASUREMENT_ID"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'GA_MEASUREMENT_ID');
</script>
```

### Protect the Leads Dashboard

Add authentication:

```bash
pip install python-jose[cryptography] passlib[bcrypt] python-multipart
```

Create `auth.py`:

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, "admin")
    correct_password = secrets.compare_digest(credentials.password, "your-secure-password")
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
```

Update leads route in `main.py`:

```python
from auth import verify_credentials

@app.get("/leads", response_class=HTMLResponse)
async def view_leads(
    request: Request,
    username: str = Depends(verify_credentials)
):
    leads = await get_leads()
    return templates.TemplateResponse("leads.html", {"request": request, "leads": leads})
```

## Part 7: Deployment Options

### Deploy to Render (Free Tier)

1. Create `requirements.txt`:

```bash
pip freeze > requirements.txt
```

2. Create `render.yaml`:

```yaml
services:
  - type: web
    name: sales-funnel
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
```

3. Push to GitHub and connect to Render

### Deploy to Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

### Deploy with Docker

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t sales-funnel .
docker run -p 8000:8000 sales-funnel
```

### Deploy to AWS Lambda

```bash
pip install mangum

# Update main.py
from mangum import Mangum
handler = Mangum(app)
```

## Part 8: Advanced Features

### A/B Testing

Create multiple landing page variants:

```python
import random

@app.get("/")
async def landing(request: Request):
    variant = random.choice(['A', 'B'])
    template = f"landing_{variant}.html"
    return templates.TemplateResponse(template, {"request": request, "variant": variant})
```

### Rate Limiting

```bash
pip install slowapi
```

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.post("/submit")
@limiter
.limit("5/minute")
async def submit(request: Request, ...):
    # Your code here
    pass
```

### Webhook Integration

Add webhook notifications to Slack/Discord:

```python
import httpx

async def send_webhook(lead: LeadCreate):
    webhook_url = "your-webhook-url"
    message = {
        "text": f"New lead: {lead.name} ({lead.email})"
    }
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json=message)

@app.post("/submit")
async def submit(...):
    lead = LeadCreate(name=name, email=email, phone=phone)
    await save_lead(lead)
    await send_webhook(lead)  # Send notification
    return RedirectResponse(...)
```

### Export Leads to CSV

```python
from fastapi.responses import StreamingResponse
import io

@app.get("/export/leads")
async def export_leads(username: str = Depends(verify_credentials)):
    leads = await get_leads()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Timestamp', 'Name', 'Email', 'Phone'])
    
    for lead in leads:
        writer.writerow([
            lead.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            lead.name,
            lead.email,
            lead.phone or ''
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"}
    )
```

## Part 9: Best Practices

### Environment Variables

Create `.env` file:

```
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///./leads.db
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
ADMIN_USERNAME=admin
ADMIN_PASSWORD=secure-password
```

Use with:

```bash
pip install python-dotenv
```

```python
from dotenv import load_dotenv
import os

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
```

### Logging

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.post("/submit")
async def submit(...):
    logger.info(f"New lead submission: {email}")
    # Your code
```

### Error Handling

```python
from fastapi import Request
from fastapi.responses import HTMLResponse

@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(
        "404.html",
        {"request": request},
        status_code=404
    )

@app.exception_handler(500)
async def server_error(request: Request, exc):
    logger.error(f"Server error: {exc}")
    return templates.TemplateResponse(
        "500.html",
        {"request": request},
        status_code=500
    )
```

### Testing

Create `test_main.py`:

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_landing_page():
    response = client.get("/")
    assert response.status_code == 200
    assert b"Transform Your Business" in response.content

def test_submit_lead():
    response = client.post("/submit", data={
        "name": "Test User",
        "email": "test@example.com",
        "phone": "1234567890"
    }, follow_redirects=False)
    assert response.status_code == 303
    assert "/thankyou" in response.headers["location"]
```

Run tests:

```bash
pip install pytest
pytest test_main.py
```

## Conclusion

You now have a complete, production-ready sales funnel built with FastAPI. Key takeaways:

- FastAPI provides automatic API documentation
- Async support enables high performance
- Pydantic ensures data validation
- Easy to customize and extend
- Production-ready with proper error handling

Next steps:

1. Customize the copy and design
2. Add your email integration
3. Set up analytics
4. Deploy to production
5. Test with real traffic

Visit `http://localhost:8000/docs` to explore the auto-generated API documentation and see all available endpoints.

Happy funnel building!