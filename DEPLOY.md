# Unraid Deployment - Step by Step Guide

**Last Updated**: February 2026

This guide walks you through deploying Helios on Unraid from scratch.

## Prerequisites

- Unraid 6.9 or higher
- Docker support enabled (Unraid → Settings → Docker)
- SSH access or Console access
- ~2GB free RAM
- ~10GB disk space
- Internet connection

## Step 1: Transfer Files to Unraid

### Option A: Using WinSCP (Easiest for Windows)
1. Download WinSCP: https://winscp.net/
2. Connect to Unraid:
   - Host: `unraid-ip`
   - Username: `root`
   - Password: Your Unraid password
3. Create folder: `/mnt/user/appdata/helios`
4. Drag-and-drop all files from `helios-unraid/` folder

### Option B: Using SCP (Command Line)
```bash
scp -r helios-unraid/* root@<unraid-ip>:/mnt/user/appdata/helios/
```

### Option C: Using Git
```bash
# On Unraid via SSH
cd /mnt/user/appdata
git clone <repo-url> helios
cd helios
```

## Step 2: Configure Environment

### Access Unraid Console
```bash
# SSH to Unraid
ssh root@<unraid-ip>

# Navigate to folder
cd /mnt/user/appdata/helios
```

### Create Configuration File
```bash
# Copy template
cp .env.example .env

# Edit with nano
nano .env
```

### Configure Email (Critical)

1. **Get Gmail App Password**:
   - Go to https://myaccount.google.com
   - Enable 2-Factor Authentication if needed
   - Go to https://myaccount.google.com/apppasswords
   - Generate a 16-character app password

2. **Edit .env file**:
   ```bash
   EMAIL_SENDER=your-email@gmail.com
   EMAIL_PASSWORD=xxxx xxxx xxxx xxxx    # 16-char app password
   EMAIL_ADMIN=admin@gmail.com
   FLASK_SECRET_KEY=<something-secure>
   ```

3. **Save file**:
   - Press `Ctrl+X`
   - Press `Y`
   - Press `Enter`

## Step 3: Build Docker Image

### Build the Image
```bash
cd /mnt/user/appdata/helios
docker build -t helios-signup:latest .
```

**Expected output:**
```
...
Successfully built xxxxxx
Successfully tagged helios-signup:latest
```

### Verify Build (Optional)
```bash
docker images | grep helios
```

## Step 4: Deploy Container

### Start with Docker Compose
```bash
cd /mnt/user/appdata/helios
docker-compose up -d
```

**Expected output:**
```
Creating helios-signup ... done
```

### OR Start Manually
```bash
docker run -d \
  --name helios-signup \
  -p 5000:5000 \
  --env-file /mnt/user/appdata/helios/.env \
  -v /mnt/user/appdata/helios/data:/app/data \
  -v /mnt/user/appdata/helios/logs:/app/logs \
  --restart unless-stopped \
  helios-signup:latest
```

## Step 5: Verify Installation

### Check Container Running
```bash
docker ps | grep helios-signup
```

Should see:
```
CONTAINER ID  IMAGE                  STATUS              NAMES
xxxxxxxx      helios-signup:latest   Up X seconds        helios-signup
```

### Check Logs
```bash
docker logs helios-signup
```

Should see:
```
Running on http://0.0.0.0:5000
WARNING: This is a development server...
```

### Test Web Access
```bash
# From Unraid
curl http://localhost:5000

# From another machine
curl http://<unraid-ip>:5000
```

## Step 6: Access the Application

### In Web Browser
```
http://unraid-ip:5000
```

### Expected Pages
- Landing page with features
- Sign Up button
- Terms & Conditions
- Email verification form
- Sign-up form

## Step 7: Test Email Configuration

### Send Test Code
1. Go to http://unraid-ip:5000
2. Click "Sign Up"
3. Accept Terms
4. Enter test email address
5. Click "Send Code"

### Check Logs
```bash
docker logs helios-signup | grep -i email
```

Should see:
```
[EMAIL] Attempting to send email...
[EMAIL] TLS connection established
[EMAIL] Login successful
[EMAIL] Email sent successfully
```

## Troubleshooting

### Container Won't Start

```bash
# Check error logs
docker logs helios-signup

# Common issues:
# 1. Port 5000 already in use
netstat -tuln | grep 5000

# 2. .env file syntax error
cat .env

# 3. Permission denied
chmod -R 755 /mnt/user/appdata/helios
```

### Email Not Working

```bash
# Check email logs
docker logs helios-signup | grep -i "email\|smtp\|error"

# Verify .env has correct values
grep "^EMAIL_" .env

# Check Gmail app password format (should be 16 chars)
# Correct: xxxx xxxx xxxx xxxx
# Incorrect: your-account-password
```

### Web Page Not Loading

```bash
# Check if port is accessible
curl -v http://localhost:5000

# Check container logs
docker logs -f helios-signup

# Verify port mapping
docker port helios-signup
```

## Post-Deployment

### Enable Auto-Restart
Already configured in `docker-compose.yml`:
```yaml
restart: unless-stopped
```

This means the container will restart if:
- Unraid reboots
- Docker restarts
- Container crashes

### Backup Data
Add to Unraid backup:
```
/mnt/user/appdata/helios/
  - .env (contains secrets!)
  - data/signups.csv
  - logs/
```

### Monitor Resources
```bash
# Check memory usage
docker stats helios-signup

# Check disk usage
du -sh /mnt/user/appdata/helios
```

## Common Operations

### Stop Application
```bash
docker-compose down
# OR
docker stop helios-signup
```

### Start Application
```bash
docker-compose up -d
# OR
docker start helios-signup
```

### Restart Application
```bash
docker restart helios-signup
```

### View Live Logs
```bash
docker logs -f helios-signup
```

### Export Signup Data
```bash
docker cp helios-signup:/app/data/signups.csv ./backup_$(date +%Y%m%d).csv
```

## Security Checklist

- [ ] .env file is NOT committed to git
- [ ] .env has unique, strong secret key
- [ ] Gmail app password is 16 characters
- [ ] Admin email is correct
- [ ] Port 5000 is accessible only as needed
- [ ] /app/data folder has proper permissions
- [ ] Regular backups of .env and data/

## Support

If you encounter issues:

1. **Check Logs**: `docker logs helios-signup`
2. **Verify Config**: `cat .env | grep -v "^#"`
3. **Test Manually**: `curl -v http://localhost:5000`
4. **Check Resources**: `docker stats`

## Next Steps

1. ✅ Deployment complete
2. 📝 Test signup flow
3. 👤 Create user accounts
4. 📧 Verify email notifications work
5. 🔐 Test approval workflow
6. 📊 Monitor usage logs

---

**Deployment Completed!** Your Helios application is now running on Unraid. 🎉
