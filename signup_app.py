from flask import Flask, render_template, request, jsonify, session
import csv
from datetime import datetime, timedelta
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import threading

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')

# Server configuration - can be set via environment variables
SERVER_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
SERVER_PORT = int(os.getenv('FLASK_PORT', 5000))
DEBUG_MODE = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

# House options for the dropdown
HOUSES = ['Chanel', 'Chisholm', 'Marcellin', 'Mauley', 'McCormack', 'Remero', 'MacKillop']

# Year levels for the dropdown
YEAR_LEVELS = list(range(7, 13))  # Years 7 to 12

# Email configuration - Update these with your email settings
EMAIL_CONFIG = {
    'sender': os.getenv('EMAIL_SENDER', 'your-email@gmail.com'),
    'password': os.getenv('EMAIL_PASSWORD', 'your-app-password'),
    'smtp_server': os.getenv('EMAIL_SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('EMAIL_SMTP_PORT', 587)),
    'admin_email': os.getenv('EMAIL_ADMIN', 'admin@example.com')
}

# Store verification codes in memory (expires after 10 minutes)
verification_codes = {}

def generate_verification_code(length=6):
    """Generate a random verification code"""
    return ''.join(random.choices(string.digits, k=length))

def send_email_async(sender, password, smtp_server, smtp_port, msg):
    """Send email synchronously"""
    print(f"[EMAIL] Attempting to send email to {msg['To']} from {sender}")
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        print(f"[EMAIL] TLS connection established")
        server.login(sender, password)
        print(f"[EMAIL] Login successful")
        server.send_message(msg)
        print(f"[EMAIL] Email sent successfully to {msg['To']}")

def send_verification_email(email, code):
    """Send verification code to email"""
    try:
        subject = "Helios - Verification Code"
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
                <div style="background-color: white; padding: 30px; border-radius: 10px; max-width: 500px; margin: 0 auto;">
                    <h2 style="color: #333;">Email Verification</h2>
                    <p style="color: #666;">Thank you for signing up with Helios.</p>
                    <p style="color: #666;">Please use the following verification code to complete your registration:</p>
                    <h1 style="color: #667eea; text-align: center; letter-spacing: 5px; font-size: 32px;">{code}</h1>
                    <p style="color: #666;">This code will expire in 10 minutes.</p>
                    <p style="color: #999; font-size: 12px;">If you did not request this code, please ignore this email.</p>
                </div>
            </body>
        </html>
        """
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = EMAIL_CONFIG['sender']
        msg['To'] = email
        
        msg.attach(MIMEText(body, 'html'))
        
        # Send email synchronously - wait for it to complete
        send_email_async(
            EMAIL_CONFIG['sender'],
            EMAIL_CONFIG['password'],
            EMAIL_CONFIG['smtp_server'],
            EMAIL_CONFIG['smtp_port'],
            msg
        )
        
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Error sending email: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def send_signup_notification(username, full_name, last_name, email, year_level, house, password=None):
    """Send signup notification email to admin with applicant details"""
    try:
        subject = f"New Helios Application Submission - {full_name} {last_name}"
        body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
                <div style="background-color: white; padding: 30px; border-radius: 10px; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #E8C547;">New Application Submission</h2>
                    <p style="color: #666; margin-bottom: 20px;">A new applicant has submitted their application to Helios. Details are below:</p>
                    
                    <div style="background-color: #f9f9f9; padding: 20px; border-left: 4px solid #E8C547; margin: 20px 0;">
                        <h3 style="color: #333; margin-top: 0;">Applicant Information</h3>
                        <table style="width: 100%; border-collapse: collapse;">
                            <tr style="border-bottom: 1px solid #e0e0e0;">
                                <td style="padding: 12px; font-weight: 600; color: #333; width: 30%;">Proxy Username:</td>
                                <td style="padding: 12px; color: #555;">{username}</td>
                            </tr>
                            <tr style="border-bottom: 1px solid #e0e0e0;">
                                <td style="padding: 12px; font-weight: 600; color: #333; width: 30%;">Full Name:</td>
                                <td style="padding: 12px; color: #555;">{full_name}</td>
                            </tr>
                            <tr style="border-bottom: 1px solid #e0e0e0;">
                                <td style="padding: 12px; font-weight: 600; color: #333;">Last Name:</td>
                                <td style="padding: 12px; color: #555;">{last_name}</td>
                            </tr>
                            <tr style="border-bottom: 1px solid #e0e0e0;">
                                <td style="padding: 12px; font-weight: 600; color: #333;">Email:</td>
                                <td style="padding: 12px; color: #555;"><a href="mailto:{email}">{email}</a></td>
                            </tr>
                            <tr style="border-bottom: 1px solid #e0e0e0;">
                                <td style="padding: 12px; font-weight: 600; color: #333;">Year Level:</td>
                                <td style="padding: 12px; color: #555;">Year {year_level}</td>
                            </tr>
                            <tr>
                                <td style="padding: 12px; font-weight: 600; color: #333;">House:</td>
                                <td style="padding: 12px; color: #555;">{house}</td>
                            </tr>
                            <tr>
                                <td style="padding: 12px; font-weight: 600; color: #333;">Password:</td>
                                <td style="padding: 12px; color: #555;">{password if password else 'N/A'}</td>
                            </tr>
                        </table>
                    </div>
                    
                    <div style="background-color: #fff8e6; padding: 15px; border-radius: 5px; margin-top: 20px; border-left: 4px solid #E8C547;">
                        <p style="color: #8B4513; margin: 0;">
                            <strong>Submission Time:</strong> {datetime.now().strftime('%d/%m/%Y at %H:%M:%S')}
                        </p>
                    </div>
                    
                    <p style="color: #999; font-size: 12px; margin-top: 20px; border-top: 1px solid #e0e0e0; padding-top: 15px;">
                        This is an automated email from the Helios application system. Please do not reply to this email.
                    </p>
                </div>
            </body>
        </html>
        """
        
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = EMAIL_CONFIG['sender']
        msg['To'] = EMAIL_CONFIG['admin_email']
        
        msg.attach(MIMEText(body, 'html'))
        
        # Send email synchronously - wait for it to complete
        send_email_async(
            EMAIL_CONFIG['sender'],
            EMAIL_CONFIG['password'],
            EMAIL_CONFIG['smtp_server'],
            EMAIL_CONFIG['smtp_port'],
            msg
        )
        
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] Error sending signup notification: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

@app.route('/')
def index():
    """Display the landing page"""
    return render_template('landing.html')

@app.route('/terms')
def terms():
    """Display the terms and service page"""
    return render_template('terms.html')

@app.route('/verify-email')
def verify_email_page():
    """Display the email verification page"""
    if 'terms_accepted' not in session:
        return {'error': 'Please accept terms and conditions first'}, 403
    return render_template('verify_email.html')

@app.route('/accept-terms', methods=['POST'])
def accept_terms():
    """Handle terms acceptance"""
    try:
        data = request.get_json()
        accepted = data.get('accepted', False)
        
        if not accepted:
            return jsonify({'success': False, 'message': 'Returning to home page', 'redirect': '/'}), 200
        
        session['terms_accepted'] = True
        return jsonify({'success': True, 'message': 'Terms accepted', 'redirect': '/verify-email'}), 200
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/send-code', methods=['POST'])
def send_code():
    """Send verification code to email"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        # Validate email format
        if not email or '@' not in email or '.' not in email:
            return jsonify({'success': False, 'message': 'Please enter a valid email address'}), 400
        
        # Generate verification code
        code = generate_verification_code()
        
        # Store code with expiration time (10 minutes)
        verification_codes[email] = {
            'code': code,
            'expires': datetime.now() + timedelta(minutes=10),
            'attempts': 0
        }
        
        # Send email with code
        if send_verification_email(email, code):
            return jsonify({'success': True, 'message': 'Verification code sent to your email'}), 200
        else:
            return jsonify({'success': False, 'message': 'Failed to send verification code. Please check email settings.'}), 500
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/verify-code', methods=['POST'])
def verify_code():
    """Verify the code entered by user"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        code = data.get('code', '').strip()
        
        if not email or not code:
            return jsonify({'success': False, 'message': 'Email and code are required'}), 400
        
        # Check if email has a verification code
        if email not in verification_codes:
            return jsonify({'success': False, 'message': 'No verification code sent to this email'}), 400
        
        code_data = verification_codes[email]
        
        # Check if code has expired
        if datetime.now() > code_data['expires']:
            del verification_codes[email]
            return jsonify({'success': False, 'message': 'Verification code has expired. Please request a new one.'}), 400
        
        # Check if too many attempts
        if code_data['attempts'] >= 3:
            del verification_codes[email]
            return jsonify({'success': False, 'message': 'Too many failed attempts. Please request a new code.'}), 400
        
        # Verify code
        if code == code_data['code']:
            # Store email in session for sign-up page
            session['verified_email'] = email
            del verification_codes[email]
            return jsonify({'success': True, 'message': 'Email verified successfully!'}), 200
        else:
            code_data['attempts'] += 1
            remaining = 3 - code_data['attempts']
            return jsonify({'success': False, 'message': f'Invalid code. {remaining} attempts remaining.'}), 400
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/signup')
def signup_page():
    """Display the sign-up form (only after email verification)"""
    if 'verified_email' not in session:
        return {'error': 'Please verify your email first'}, 403
    
    return render_template('signup.html', houses=HOUSES, years=YEAR_LEVELS, email=session['verified_email'])

@app.route('/submit-signup', methods=['POST'])
def submit_signup():
    """Handle sign-up form submission"""
    try:
        if 'verified_email' not in session:
            return jsonify({'success': False, 'message': 'Email not verified'}), 403
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['username', 'full_name', 'last_name', 'year_level', 'house', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'message': f'{field} is required'}), 400
        
        # Validate username format (alphanumeric and underscore only)
        username = data.get('username', '').strip()
        if not username or not all(c.isalnum() or c == '_' for c in username):
            return jsonify({'success': False, 'message': 'Username must contain only letters, numbers, and underscores'}), 400
        
        if len(username) < 3 or len(username) > 20:
            return jsonify({'success': False, 'message': 'Username must be between 3 and 20 characters'}), 400
        
        # Validate password length
        password = data.get('password', '')
        if len(password) < 6:
            return jsonify({'success': False, 'message': 'Password must be at least 6 characters long'}), 400
        
        # Validate year level
        year_level = int(data.get('year_level', 0))
        if year_level < 7 or year_level > 12:
            return jsonify({'success': False, 'message': 'Year level must be between 7 and 12'}), 400
        
        # Validate house
        if data.get('house') not in HOUSES:
            return jsonify({'success': False, 'message': 'Invalid house selected'}), 400
        
        # Get verified email from session
        email = session.get('verified_email', '')
        
        # Save to CSV file
        signup_data = [
            username,
            data.get('full_name'),
            data.get('last_name'),
            email,
            year_level,
            data.get('house'),
            password,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'pending'  # Auto-set status to pending
        ]
        
        try:
            with open('/app/data/signups.csv', 'a', newline='') as f:
                writer = csv.writer(f)
                # Write header if file is empty
                if f.tell() == 0:
                    writer.writerow(['Username', 'Full Name', 'Last Name', 'Email', 'Year Level', 'House', 'Password', 'Signup Time', 'Status'])
                writer.writerow(signup_data)
        except Exception as e:
            return jsonify({'success': False, 'message': f'Error saving data: {str(e)}'}), 500
        
        # Send notification email to admin with signup details
        send_signup_notification(
            username,
            data.get('full_name'),
            data.get('last_name'),
            email,
            year_level,
            data.get('house'),
            password
        )
        
        # Clear session and store email, name, and password for review page
        email_for_review = session.pop('verified_email', '')
        session['review_email'] = email_for_review
        session['review_full_name'] = data.get('full_name')
        session['review_password'] = password
        return jsonify({'success': True, 'message': 'Sign-up successful!', 'redirect': '/review-pending'}), 200
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/review-pending')
def review_pending():
    """Display review pending page after successful signup"""
    if 'review_email' not in session:
        return {'error': 'No signup in progress'}, 403
    
    email = session.get('review_email', '')
    full_name = session.get('review_full_name', '')
    password = session.get('review_password', '')
    return render_template('review_pending.html', email=email, full_name=full_name, password=password)

@app.route('/api/check-approval', methods=['POST'])
def check_approval():
    """Check if a user's application has been approved"""
    try:
        data = request.get_json()
        # Accept either email or username for checking
        email = data.get('email', '').strip().lower() if data.get('email') else ''
        username = data.get('username', '').strip().lower() if data.get('username') else ''
        password = data.get('password', '').strip()
        
        if not password or (not email and not username):
            return jsonify({'success': False, 'message': 'Email/Username and password required'}), 400
        
        # Read signups.csv to check approval status
        try:
            found = False
            with open('/app/data/signups.csv', 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row and row.get('Password') == password:
                        # Check by email or username
                        email_match = email and row.get('Email', '').lower() == email
                        username_match = username and row.get('Username', '').lower() == username
                        
                        if email_match or username_match:
                            found = True
                            # Check if approved
                            status = row.get('Status', 'pending').lower()
                            if status == 'approved':
                                return jsonify({
                                    'success': True,
                                    'approved': True,
                                    'message': 'Application approved!',
                                    'user': {
                                        'name': row.get('Full Name', ''),
                                        'email': row.get('Email', ''),
                                        'username': row.get('Username', '')
                                    }
                                }), 200
                            else:
                                return jsonify({
                                    'success': True,
                                    'approved': False,
                                    'message': f'Application still under review. Status: {status}',
                                    'status': status
                                }), 200
            
            if not found:
                return jsonify({'success': False, 'message': 'Invalid email/username or password'}), 401
                
        except FileNotFoundError:
            return jsonify({'success': False, 'message': 'Unable to check approval status at this time'}), 500
    
    except Exception as e:
        print(f"[ERROR] check_approval: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/api/request-password-change', methods=['POST'])
def request_password_change():
    """Request a password change"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip()
        
        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400
        
        # Send password change request email
        try:
            subject = "Helios - Password Change Request"
            body = f"""
            <html>
                <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
                    <div style="background-color: white; padding: 30px; border-radius: 10px; max-width: 500px; margin: 0 auto;">
                        <h2 style="color: #333;">Password Change Request</h2>
                        <p style="color: #666;">You have requested a password change for your Helios account.</p>
                        <p style="color: #666;">Please contact the Helios admissions office to process your password change request.</p>
                        <p style="color: #666;"><strong>Email:</strong> {EMAIL_CONFIG['admin_email']}</p>
                        <p style="color: #999; font-size: 12px;">If you did not request this change, please ignore this email.</p>
                    </div>
                </body>
            </html>
            """
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = EMAIL_CONFIG['sender']
            msg['To'] = email
            
            msg.attach(MIMEText(body, 'html'))
            
            # Send email
            send_email_async(
                EMAIL_CONFIG['sender'],
                EMAIL_CONFIG['password'],
                EMAIL_CONFIG['smtp_server'],
                EMAIL_CONFIG['smtp_port'],
                msg
            )
            
            return jsonify({'success': True, 'message': 'Password change request sent to your email'}), 200
        except Exception as e:
            print(f"[EMAIL ERROR] Error sending password change request: {str(e)}")
            return jsonify({'success': False, 'message': 'Error sending email. Please try again later.'}), 500
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/api/approve-user', methods=['POST'])
def approve_user():
    """Approve a user application by email (admin function)"""
    try:
        data = request.get_json()
        email = data.get('email', '').strip().lower()
        admin_key = data.get('admin_key', '')
        
        if not email or not admin_key:
            return jsonify({'success': False, 'message': 'Email and admin key required'}), 400
        
        # Check admin key (can be configured in environment)
        admin_password = os.getenv('ADMIN_KEY', 'admin123')
        if admin_key != admin_password:
            return jsonify({'success': False, 'message': 'Invalid admin key'}), 403
        
        # Read CSV, find user, and update status
        try:
            rows = []
            found = False
            
            with open('/app/data/signups.csv', 'r') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                for row in reader:
                    if row.get('Email', '').lower() == email:
                        row['Status'] = 'approved'
                        found = True
                        user_name = row.get('Full Name', '')
                    rows.append(row)
            
            if not found:
                return jsonify({'success': False, 'message': 'User not found'}), 404
            
            # Write updated CSV
            with open('/app/data/signups.csv', 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            
            # Send approval email to user
            try:
                subject = "Helios - Application Approved!"
                body = f"""
                <html>
                    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
                        <div style="background-color: white; padding: 30px; border-radius: 10px; max-width: 500px; margin: 0 auto;">
                            <h2 style="color: #4CAF50;">✓ Application Approved!</h2>
                            <p style="color: #666;">Congratulations! Your Helios application has been approved.</p>
                            <p style="color: #666;">You can now log in using your credentials:</p>
                            <p style="color: #333;"><strong>Email:</strong> {email}</p>
                            <p style="color: #999; font-size: 13px;">Welcome to the Helios community!</p>
                        </div>
                    </body>
                </html>
                """
                
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = EMAIL_CONFIG['sender']
                msg['To'] = email
                
                msg.attach(MIMEText(body, 'html'))
                
                send_email_async(
                    EMAIL_CONFIG['sender'],
                    EMAIL_CONFIG['password'],
                    EMAIL_CONFIG['smtp_server'],
                    EMAIL_CONFIG['smtp_port'],
                    msg
                )
            except Exception as e:
                print(f"[EMAIL ERROR] Error sending approval email: {str(e)}")
            
            return jsonify({'success': True, 'message': f'User {email} has been approved'}), 200
        
        except Exception as e:
            print(f"[ERROR] approve_user file operation: {str(e)}")
            return jsonify({'success': False, 'message': 'Error updating user status'}), 500
    
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=DEBUG_MODE, host=SERVER_HOST, port=SERVER_PORT)
