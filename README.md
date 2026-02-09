# Helios Unraid Deployment Package

Complete, self-contained Docker setup for running Helios on Unraid. This folder contains everything needed to deploy the signup webapp AND proxy system together.

## 📁 Folder Structure

```
helios-unraid/
├── signup_app.py          # Flask web application
├── proxy.py               # HTTPS proxy server
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker container configuration
├── docker-compose.yml    # Multi-container orchestration
├── .env.example          # Configuration template
├── startup.sh            # Container startup script
├── data/                 # Data storage (persisted)
│   ├── signups.csv      # User applications
│   └── proxy_users.csv  # Proxy user credentials
├── logs/                 # Application logs (persisted)
├── static/              # Static assets
│   └── logo.jpg        # Logo image
└── templates/           # HTML templates
    ├── landing.html
    ├── signup.html
    ├── terms.html
    ├── verify_email.html
    └── review_pending.html
```

## 🚀 Quick Start

### 1. **Prepare Configuration**

```bash
# Copy template to .env and edit
cp .env.example .env
nano .env
```

**Required settings in `.env`:**
- `EMAIL_SENDER`: Your Gmail address
- `EMAIL_PASSWORD`: 16-character Gmail app password
- `EMAIL_ADMIN`: Admin email to receive notifications
- `FLASK_SECRET_KEY`: Change to something secure

### 2. **Deploy on Unraid**

**Option A: Using Docker Compose (Recommended)**
```bash
# On Unraid server
cd /mnt/user/appdata/helios
docker-compose up -d
```

**Option B: Manual Docker**
```bash
docker build -t helios-signup:latest .
docker run -d --name helios-signup \
  -p 5000:5000 \
  --env-file .env \
  -v /mnt/user/appdata/helios/data:/app/data \
  -v /mnt/user/appdata/helios/logs:/app/logs \
  --restart unless-stopped \
  helios-signup:latest
```

### 3. **Verify Installation**

```bash
# Check container is running
docker ps | grep helios

# Check logs
docker logs -f helios-signup

# Test web app
curl http://unraid-ip:5000
```

## 🎯 What's Included

### Signup Web Application (Port 5000)
- Email verification with OTP codes
- Multi-step user registration
- Terms & conditions acceptance
- Application status checking
- Admin notifications
- Professional web UI

### HTTPS Proxy Server (Ports 8080, 8081)
- Connection pooling and caching
- Bandwidth rate limiting
- Session management
- User authentication
- Monitor server (port 8081)
- Access time restrictions
- Data usage logging

## 📋 Configuration Guide

### Email Setup (Gmail)

1. Enable 2-Factor Authentication: https://myaccount.google.com
2. Generate app password: https://myaccount.google.com/apppasswords
3. Copy 16-character password to `.env`:
   ```
   EMAIL_PASSWORD=xxxx xxxx xxxx xxxx
   ```

### File Structure After Deployment

On Unraid, files will be located at:
```
/mnt/user/appdata/helios/
├── data/
│   ├── signups.csv          # User signup records
│   └── proxy_users.csv      # Encrypted proxy users
└── logs/
    ├── startup.log
    └── flask.log
```

## 🔧 Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `EMAIL_SENDER` | Yes | - | Gmail sender address |
| `EMAIL_PASSWORD` | Yes | - | Gmail app password (16 chars) |
| `EMAIL_ADMIN` | Yes | - | Admin email for notifications |
| `FLASK_SECRET_KEY` | No | random | Session encryption key |
| `FLASK_DEBUG` | No | False | Enable debug mode (prod: False) |
| `APPDATA_PATH` | No | ./data | Data volume path |
| `LOGS_PATH` | No | ./logs | Logs volume path |

## 📱 Access Points

| Service | URL | Port | Purpose |
|---------|-----|------|---------|
| Signup Web | http://unraid-ip:5000 | 5000 | User registration & status |
| Proxy Server | unraid-ip:8080 | 8080 | HTTPS proxy (client connections) |
| Proxy Monitor | telnet unraid-ip:8081 | 8081 | Admin monitoring interface |

### Health Check
```bash
curl http://unraid-ip:5000/
```

## 🛠️ Managing the Application

### View Logs
```bash
docker logs -f helios-signup
docker logs --tail 100 helios-signup
```

### Stop/Start
```bash
docker-compose down
docker-compose up -d
```

### Restart
```bash
docker restart helios-signup
```

### Check Status
```bash
docker ps
docker stats helios-signup
```

### Connect to Proxy Monitor (Port 8081)
```bash
telnet unraid-ip 8081
```

## ⚙️ Proxy Configuration

The proxy server runs alongside signup app. Configure in `.env`:

```
# Proxy Server Settings
LISTEN_HOST=0.0.0.0
LISTEN_PORT=8080
MONITOR_PORT=8081
CACHE_TTL=3600              # Cache expiry in seconds
SESSION_TIMEOUT=1800        # Session duration
MAX_CACHED_CONNECTIONS=100  # Connection pool size
BANDWIDTH_LIMIT_MBPS=100    # Rate limit per connection
PROXY_ACCESS_HOURS=08-18    # Allowed access window (24-hour format)
ADMIN_KEY=your-secret-key   # Admin monitor access key
```

## 📊 Data Management

### Backup User Data
```bash
docker exec helios-signup cat /app/data/signups.csv > backup_$(date +%Y%m%d).csv
```

### Clear Data (Caution!)
```bash
# Remove container
docker rm helios-signup

# Remove volume
docker volume rm helios-unraid_data

# Rebuild
docker-compose up -d
```

## 🔒 Security

### Change Flask Secret Key
Edit `.env`:
```
FLASK_SECRET_KEY=<generate-random-key>
```

Generate secure key:
```bash
openssl rand -base64 32
```

### Update Email Credentials
Always use **app passwords**, never account passwords:
1. Never commit `.env` to version control
2. Use strong admin key
3. Rotate credentials periodically

### Firewall Rules
- Allow port 5000 only from trusted networks
- Consider reverse proxy with authentication
- Use HTTPS in production

## 🐛 Troubleshooting

### "Email not sending"
```bash
# Check logs for SMTP errors
docker logs helios-signup | grep EMAIL

# Verify credentials in .env
cat .env | grep EMAIL_

# Test with curl
curl -X POST http://localhost:5000/send-code
```

### "Container won't start"
```bash
# Check error logs
docker logs helios-signup

# Verify .env syntax
docker run -it --rm -v $(pwd)/.env:/test.env python cat /test.env
```

### "Permission denied" on files
```bash
# Fix volume permissions
docker exec -u root helios-signup chmod -R 755 /app/data /app/logs
```

### "Connection refused" 
```bash
# Check if port is in use
netstat -tuln | grep 5000

# Kill conflicting process
lsof -i :5000
```

## 📈 Performance Tips

1. **Resource Limits** (Add to docker-compose.yml):
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '1'
         memory: 512M
   ```

2. **Enable Compression**: Already configured in code

3. **Database Indexing**: Consider SQLite for scale

4. **Log Rotation**: Set in docker-compose.yml:
   ```yaml
   logging:
     driver: "json-file"
     options:
       max-size: "10m"
       max-file: "3"
   ```

## 🔄 Updating

### Update Application Code
```bash
# Pull latest changes (if using git)
git pull

# Rebuild image
docker build -t helios-signup:latest .

# Restart
docker-compose down
docker-compose up -d
```

### Update Dependencies
```bash
# Edit requirements.txt
nano requirements.txt

# Rebuild
docker build --no-cache -t helios-signup:latest .
docker-compose up -d
```

## 📞 Support

**Common Issues:**
- Check logs first: `docker logs helios-signup`
- Verify `.env` configuration
- Ensure all ports are accessible
- Check Unraid system resources

**Files to Review:**
- `.env` - All configuration
- `docker-compose.yml` - Container setup
- `Dockerfile` - Image build config
- `signup_app.py` - Application logic

## 📝 Notes

- **First Run**: Create `.env` from `.env.example`
- **Persistence**: Data in `data/` and `logs/` survives container restarts
- **Updates**: Images are tagged with `:latest` - rebuild after changes
- **Backup**: Include `.env` and `data/` folder in Unraid backups

## 📄 License

Helios - Marymede Catholic College 2026

---

**Created**: February 2026  
**Last Updated**: February 2026  
**Ready to Deploy**: Yes ✓
