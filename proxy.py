import socket
import threading
import base64
import select
import time
import json
import os
import csv
import sys
from collections import defaultdict
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================
# CONFIGURATION
# ============================

LISTEN_HOST = os.getenv("LISTEN_HOST", "192.168.124.9")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8080"))
MONITOR_PORT = int(os.getenv("MONITOR_PORT", "8081"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "180"))
SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "180"))
MAX_CACHED_CONNECTIONS = int(os.getenv("MAX_CACHED_CONNECTIONS", "100"))
CACHE_FILE = os.path.join(os.path.dirname(__file__), "proxy_cache.json")
CACHE_SAVE_INTERVAL = 60
USERS_FILE = os.path.join(os.path.dirname(__file__), "proxy_users.csv")
ENCRYPTION_KEY_FILE = os.path.join(os.path.dirname(__file__), ".proxy_key")
LOGIN_LOG_FILE = os.path.join(os.path.dirname(__file__), "proxy_login.log")
USAGE_LOG_FILE = os.path.join(os.path.dirname(__file__), "proxy_usage.log")
SERVER_LOG_FILE = os.path.join(os.path.dirname(__file__), "proxy_server.log")
BANDWIDTH_LIMIT_MBPS = int(os.getenv("BANDWIDTH_LIMIT_MBPS", "30"))
PROXY_ACCESS_START_HOUR = int(os.getenv("PROXY_ACCESS_START_HOUR", "9"))
PROXY_ACCESS_START_MINUTE = int(os.getenv("PROXY_ACCESS_START_MINUTE", "0"))
PROXY_ACCESS_END_HOUR = int(os.getenv("PROXY_ACCESS_END_HOUR", "15"))
PROXY_ACCESS_END_MINUTE = int(os.getenv("PROXY_ACCESS_END_MINUTE", "15"))

# Dictionary of valid users and passwords (loaded from encrypted CSV file on startup)
PROXY_USERS = {}

# Pre-compute auth tokens for validation (populated after loading users)
proxy_auth_tokens = {}

# Track active user sessions (one device per user)
user_sessions = {}  # {username: (device_ip, timestamp, socket_obj, is_active)}

# Track which sessions have been logged to avoid duplicate logs
logged_sessions = set()  # {(username, device_ip, timestamp)}

# Track data usage per user (username -> total_bytes)
user_data_usage = {}  # {username: total_bytes_used}

# Flag for remote restart
restart_requested = False
restart_lock = threading.Lock()


# ============================
# LOGGING UTILITIES
# ============================

class DualLogger:
    """Log to both console and file."""
    def __init__(self, log_file):
        self.log_file = log_file
        self.lock = threading.Lock()
    
    def log(self, message):
        """Log a message to both console and file."""
        with self.lock:
            print(message)
            try:
                with open(self.log_file, 'a') as f:
                    f.write(message + "\n")
            except:
                pass

server_logger = DualLogger(SERVER_LOG_FILE)


# ============================
# ENCRYPTION UTILITIES
# ============================

def get_or_create_key():
    """Get encryption key from file, or create one if it doesn't exist."""
    if os.path.exists(ENCRYPTION_KEY_FILE):
        with open(ENCRYPTION_KEY_FILE, 'rb') as f:
            key_content = f.read().strip()
            # Handle both binary and text (base64) formats
            if key_content.startswith(b'-----'):
                return key_content  # Binary format
            else:
                return key_content  # Base64 text format
    else:
        key = Fernet.generate_key()
        with open(ENCRYPTION_KEY_FILE, 'wb') as f:
            f.write(key)
        os.chmod(ENCRYPTION_KEY_FILE, 0o600)  # Restrict to user only
        return key

encryption_key = get_or_create_key()
try:
    cipher = Fernet(encryption_key)
except Exception as e:
    print(f"[!] Error initializing cipher: {e}")
    print(f"[!] Encryption key: {encryption_key}")
    sys.exit(1)


def encrypt_text(text):
    """Encrypt text using Fernet."""
    return cipher.encrypt(text.encode()).decode()


def decrypt_text(encrypted_text):
    """Decrypt text using Fernet."""
    try:
        return cipher.decrypt(encrypted_text.encode()).decode()
    except:
        return None


def save_users_to_csv():
    """Save users to encrypted CSV file."""
    try:
        with open(USERS_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['username', 'password_encrypted'])
            for username, password in PROXY_USERS.items():
                encrypted_password = encrypt_text(password)
                writer.writerow([username, encrypted_password])
        print(f"[*] Saved {len(PROXY_USERS)} users to encrypted CSV file")
    except Exception as e:
        print(f"[!] Error saving users to CSV: {e}")


def load_users_from_csv():
    """Load users from encrypted CSV file."""
    if not os.path.exists(USERS_FILE):
        print("[*] No user CSV file found, using default users")
        return False
    
    try:
        with open(USERS_FILE, 'r') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            PROXY_USERS.clear()
            for row in reader:
                if len(row) >= 2:
                    username, encrypted_password = row[0], row[1]
                    decrypted_password = decrypt_text(encrypted_password)
                    if decrypted_password:
                        username_lower = username.lower()
                        password_lower = decrypted_password.lower()
                        PROXY_USERS[username_lower] = password_lower
        
        # Rebuild auth tokens
        rebuild_auth_tokens()
        print(f"[*] Loaded {len(PROXY_USERS)} users from encrypted CSV file")
        return True
    except Exception as e:
        print(f"[!] Error loading users from CSV: {e}")
        return False


def rebuild_auth_tokens():
    """Rebuild auth tokens from PROXY_USERS."""
    proxy_auth_tokens.clear()
    for user, passwd in PROXY_USERS.items():
        user_lower = user.lower()
        passwd_lower = passwd.lower()
        proxy_auth_tokens[base64.b64encode(f"{user_lower}:{passwd_lower}".encode()).decode()] = user_lower


def start_user_reload_thread():
    """Periodically reload users from CSV to pick up new approvals."""
    last_modified_time = 0
    
    def reload_users_periodically():
        nonlocal last_modified_time
        while True:
            try:
                time.sleep(3)  # Check every 3 seconds for changes
                
                # Check if the CSV file has been modified
                if os.path.exists(USERS_FILE):
                    current_modified_time = os.path.getmtime(USERS_FILE)
                    
                    # If the file has been modified, reload users
                    if current_modified_time > last_modified_time:
                        last_modified_time = current_modified_time
                        load_users_from_csv()
                        print(f"[*] Reloaded users due to file modification")
            except Exception as e:
                print(f"[!] Error in user reload thread: {e}")
    
    reload_thread = threading.Thread(target=reload_users_periodically, daemon=True)
    reload_thread.start()
    return reload_thread


# ============================
# BANDWIDTH RATE LIMITER
# ============================

class BandwidthLimiter:
    """Token bucket rate limiter for global bandwidth control."""
    def __init__(self, max_bytes_per_second):
        self.max_bytes_per_second = max_bytes_per_second
        self.tokens = max_bytes_per_second  # Start with full bucket
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def acquire(self, num_bytes):
        """Non-blocking rate limit check. Skip limiting if bandwidth is available."""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            
            # Refill tokens based on elapsed time
            refill_amount = elapsed * self.max_bytes_per_second
            self.tokens = min(self.max_bytes_per_second, self.tokens + refill_amount)
            self.last_refill = now
            
            # If we have enough tokens, consume them
            if self.tokens >= num_bytes:
                self.tokens -= num_bytes
            # If not enough tokens, still allow (don't block) - just deprioritize
            else:
                self.tokens = max(0, self.tokens - num_bytes)


# Initialize rate limiter: 30 Mbps = 3,750,000 bytes/second
rate_limiter = BandwidthLimiter(int(BANDWIDTH_LIMIT_MBPS * 1_000_000 / 8))


def log_login(username, device_ip, status="LOGIN"):
    """Log user login/logout events to file."""
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"{timestamp} | {status} | User: {username} | Device: {device_ip}\n"
        with open(LOGIN_LOG_FILE, 'a') as f:
            f.write(log_entry)
        print(f"[*] Logged: {status} - {username} from {device_ip}")
    except Exception as e:
        print(f"[!] Error writing login log: {e}")


def log_data_usage(username, bytes_used):
    """Log data usage to file and track in memory."""
    global user_data_usage
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        mb_used = bytes_used / (1024 * 1024)
        log_entry = f"{timestamp} | User: {username} | Data: {bytes_used} bytes ({mb_used:.2f} MB)\n"
        with open(USAGE_LOG_FILE, 'a') as f:
            f.write(log_entry)
        
        # Track in memory
        if username not in user_data_usage:
            user_data_usage[username] = 0
        user_data_usage[username] += bytes_used
    except Exception as e:
        print(f"[!] Error writing usage log: {e}")


def is_proxy_access_allowed():
    """Check if current time is within allowed proxy access hours."""
    import datetime
    now = datetime.datetime.now()
    current_time = (now.hour, now.minute)
    start_time = (PROXY_ACCESS_START_HOUR, PROXY_ACCESS_START_MINUTE)
    end_time = (PROXY_ACCESS_END_HOUR, PROXY_ACCESS_END_MINUTE)
    
    if start_time <= current_time < end_time:
        return True
    return False


def check_user_session(username, device_ip, current_socket):
    """Enforce one device per user. Every connection requires fresh authentication."""
    global user_sessions, logged_sessions
    
    if username in user_sessions:
        existing_ip, existing_time, existing_socket, is_active = user_sessions[username]
        time_elapsed = time.time() - existing_time
        
        # Same device - ALWAYS require fresh login but don't log again
        if existing_ip == device_ip:
            user_sessions[username] = (device_ip, time.time(), current_socket, True)
            return True, f"Fresh login required for {username} from {device_ip}"
        
        # Different device - check if previous session timed out
        if time_elapsed >= SESSION_TIMEOUT:
            # Previous session expired, allow new device
            try:
                existing_socket.close()
            except:
                pass
            print(f"[*] Previous session for {username} expired after {time_elapsed:.0f}s inactivity")
            log_login(username, existing_ip, "LOGOUT_TIMEOUT")
            logged_sessions.discard((username, existing_ip, existing_time))
            
            # New session on new device
            user_sessions[username] = (device_ip, time.time(), current_socket, True)
            session_key = (username, device_ip, time.time())
            log_login(username, device_ip, "LOGIN_NEW_DEVICE")
            logged_sessions.add(session_key)
            return True, f"New device allowed for {username} (previous session timed out)"
        else:
            # Previous session still active - block this new device
            remaining = SESSION_TIMEOUT - time_elapsed
            response = b"HTTP/1.1 407 Proxy Authentication Required\r\n"
            response += b"Proxy-Authenticate: Basic realm=\"Credentials Already In Use\"\r\n"
            response += b"Connection: close\r\n"
            response += b"\r\nCredentials already in use on another device. Try again in " + f"{remaining:.0f}s".encode() + b".\r\n"
            current_socket.sendall(response)
            current_socket.close()
            print(f"[!] User {username} already active on {existing_ip}. Blocking device {device_ip} for {remaining:.0f}s")
            return False, f"User {username} already connected on another device"
    else:
        # New session
        session_time = time.time()
        user_sessions[username] = (device_ip, session_time, current_socket, True)
        session_key = (username, device_ip, session_time)
        log_login(username, device_ip, "LOGIN")
        logged_sessions.add(session_key)
        return True, f"New session for {username} from {device_ip}"


# ============================
# CACHING SYSTEM
# ============================

class CacheManager:
    """Manages connection pooling and DNS caching with persistent storage."""
    
    def __init__(self, ttl=CACHE_TTL, max_connections=MAX_CACHED_CONNECTIONS, cache_file=CACHE_FILE):
        self.ttl = ttl
        self.max_connections = max_connections
        self.cache_file = cache_file
        self.connection_cache = {}  # {(host, port): (socket, timestamp)}
        self.dns_cache = {}  # {hostname: (ip, timestamp)}
        self.page_cache = {}  # {(host, port, path): [(response_data, timestamp), ...]}  - list of versions
        self.active_clients = {}  # {client_address: (user, timestamp)} - track active connections
        self.lock = threading.Lock()
        self.save_thread = None
        self.should_exit = False
        
        # Load cache from disk on startup
        self.load_cache_from_disk()
    
    def load_cache_from_disk(self):
        """Load cached DNS entries and pages from disk."""
        if not os.path.exists(self.cache_file):
            return
        
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
                with self.lock:
                    # Restore DNS cache
                    current_time = time.time()
                    for hostname, (ip, timestamp) in data.get('dns_cache', {}).items():
                        # Only restore if not expired
                        if current_time - timestamp < self.ttl:
                            self.dns_cache[hostname] = (ip, timestamp)
                    # Restore page cache (pages never expire, store as list of versions)
                    for page_key, versions in data.get('page_cache', {}).items():
                        try:
                            key = tuple(json.loads(page_key))
                            if isinstance(versions, list):
                                self.page_cache[key] = versions
                            else:
                                # Handle old format (single version)
                                self.page_cache[key] = [versions]
                        except:
                            pass
                    print(f"[*] Loaded {len(self.dns_cache)} DNS cache entries and {len(self.page_cache)} page cache entries from disk")
        except Exception as e:
            print(f"[!] Error loading cache from disk: {e}")
    
    def save_cache_to_disk(self):
        """Save cache to disk asynchronously to avoid blocking."""
        # Spawn async thread instead of blocking main thread
        save_thread = threading.Thread(target=self._save_cache_async, daemon=True)
        save_thread.start()
    
    def _save_cache_async(self):
        """Asynchronously save cache to disk."""
        try:
            with self.lock:
                # Save DNS cache and page cache (convert tuple keys to strings for JSON)
                page_cache_serializable = {
                    json.dumps(key): (value, timestamp) 
                    for key, (value, timestamp) in self.page_cache.items()
                }
                data = {
                    'dns_cache': dict(self.dns_cache),
                    'page_cache': page_cache_serializable,
                    'timestamp': time.time()
                }
            
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"[*] Saved cache to disk ({len(self.dns_cache)} DNS entries, {len(self.page_cache)} page entries)")
        except Exception as e:
            print(f"[!] Error saving cache to disk: {e}")
    
    def _auto_save_thread(self):
        """Background thread that periodically saves cache."""
        while not self.should_exit:
            time.sleep(CACHE_SAVE_INTERVAL)
            if not self.should_exit:
                self.save_cache_to_disk()
    
    def start_auto_save(self):
        """Start the background thread for periodic cache saves."""
        self.should_exit = False
        self.save_thread = threading.Thread(target=self._auto_save_thread, daemon=True)
        self.save_thread.start()
    
    def stop_auto_save(self):
        """Stop the background save thread."""
        self.should_exit = True
        if self.save_thread:
            self.save_thread.join(timeout=2)
    
    def get_cached_connection(self, host, port):
        """Retrieve a cached connection if available and valid."""
        with self.lock:
            key = (host, port)
            if key in self.connection_cache:
                sock, timestamp = self.connection_cache[key]
                if time.time() - timestamp < self.ttl:
                    return sock
                else:
                    # Connection expired, close and remove
                    try:
                        sock.close()
                    except:
                        pass
                    del self.connection_cache[key]
        return None
    
    def cache_connection(self, host, port, sock):
        """Cache a connection for future reuse."""
        with self.lock:
            # Clean up expired entries if cache is full
            if len(self.connection_cache) >= self.max_connections:
                self._cleanup_expired_connections()
            
            key = (host, port)
            self.connection_cache[key] = (sock, time.time())
    
    def _cleanup_expired_connections(self):
        """Remove expired connections from cache."""
        current_time = time.time()
        expired_keys = [
            key for key, (sock, timestamp) in self.connection_cache.items()
            if current_time - timestamp >= self.ttl
        ]
        for key in expired_keys:
            try:
                self.connection_cache[key][0].close()
            except:
                pass
            del self.connection_cache[key]
    
    def get_cached_dns(self, hostname):
        """Retrieve a cached DNS lookup if available and valid."""
        with self.lock:
            if hostname in self.dns_cache:
                ip, timestamp = self.dns_cache[hostname]
                if time.time() - timestamp < self.ttl:
                    return ip
                else:
                    del self.dns_cache[hostname]
        return None
    
    def cache_dns(self, hostname, ip):
        """Cache a DNS lookup result."""
        with self.lock:
            self.dns_cache[hostname] = (ip, time.time())
    
    def get_cached_page(self, host, port, path):
        """Retrieve the newest cached page version (never expires)."""
        with self.lock:
            key = (host, port, path)
            if key in self.page_cache:
                versions = self.page_cache[key]
                if versions:
                    # Return the newest version (last in list)
                    response, timestamp = versions[-1]
                    print(f"[*] Found cached page for {host}:{port}{path}")
                    return response
        return None
    
    def cache_page(self, host, port, path, response_data):
        """Cache a page response. Keep only the newest and 2nd newest versions."""
        with self.lock:
            key = (host, port, path)
            
            # Check if page already cached
            if key in self.page_cache:
                versions = self.page_cache[key]
                if versions:
                    newest_response, _ = versions[-1]
                    # Compare with newest cached version
                    if newest_response == response_data:
                        print(f"[*] Page unchanged for {host}:{port}{path} - keeping cached version")
                        return  # Don't update if same as newest
                    else:
                        print(f"[*] Page updated for {host}:{port}{path} - new version added to cache")
                # Add new version
                versions.append((response_data, time.time()))
                # Keep only newest and 2nd newest (delete oldest if more than 2)
                if len(versions) > 2:
                    deleted = versions.pop(0)
                    print(f"[*] Deleted oldest version for {host}:{port}{path}")
            else:
                # First version of this page
                self.page_cache[key] = [(response_data, time.time())]
                print(f"[*] Cached new page: {host}:{port}{path}")
    
    def clear_cache(self):
        """Clear all cached connections and DNS entries."""
        with self.lock:
            for sock, _ in self.connection_cache.values():
                try:
                    sock.close()
                except:
                    pass
            self.connection_cache.clear()
            self.dns_cache.clear()
            self.page_cache.clear()
        # Save empty cache to disk
        self.save_cache_to_disk()


# Initialize global cache manager
cache_manager = CacheManager()


# ============================
# HTTPS PROXY HANDLER
# ============================

def handle_client(client_sock, addr):
    """Handle incoming HTTPS proxy connections."""
    authenticated_user = None
    # Read the CONNECT request line
    request = b""
    try:
        while b"\r\n\r\n" not in request:
            chunk = client_sock.recv(1024)
            if not chunk:
                return
            request += chunk
        
        # Parse the request
        request_str = request.decode('utf-8', errors='ignore')
        lines = request_str.split("\r\n")
        first_line = lines[0]
        
        # Check if it's a CONNECT request
        if not first_line.startswith("CONNECT"):
            client_sock.close()
            return
        
        # Parse host and port
        parts = first_line.split()
        if len(parts) < 2:
            client_sock.close()
            return
        
        host_port = parts[1]
        try:
            host, port = host_port.split(":")
            port = int(port)
        except:
            client_sock.close()
            return
        
        # Check authentication
        auth_header = None
        for line in lines[1:]:
            if line.lower().startswith("proxy-authorization:"):
                auth_header = line.split(":", 1)[1].strip()
                break
        
        if not auth_header or not auth_header.startswith("Basic "):
            response = b"HTTP/1.1 407 Proxy Authentication Required\r\n"
            response += b"Proxy-Authenticate: Basic realm=\"Home PC Proxy\"\r\n"
            response += b"Connection: close\r\n"
            response += b"\r\n"
            client_sock.sendall(response)
            client_sock.close()
            return
        
        token = auth_header.split(" ", 1)[1].strip() if " " in auth_header else ""
        
        # Validate token and get username
        if token not in proxy_auth_tokens:
            response = b"HTTP/1.1 407 Proxy Authentication Required\r\n"
            response += b"Proxy-Authenticate: Basic realm=\"Home PC Proxy\"\r\n"
            response += b"Connection: close\r\n"
            response += b"\r\n"
            client_sock.sendall(response)
            client_sock.close()
            return
        
        authenticated_user = proxy_auth_tokens[token]
        device_ip = addr[0]
        server_logger.log(f"[*] Authenticated user: {authenticated_user} from device {device_ip}")
        
        # Check if proxy access is allowed at this time
        if not is_proxy_access_allowed():
            current_time = time.strftime("%H:%M")
            response = f"HTTP/1.1 403 Forbidden\r\n"
            response += f"Connection: close\r\n"
            response += f"\r\n"
            response += f"Proxy access is only allowed from {PROXY_ACCESS_START_HOUR}:{PROXY_ACCESS_START_MINUTE:02d} to {PROXY_ACCESS_END_HOUR}:{PROXY_ACCESS_END_MINUTE:02d}. Current time: {current_time}"
            client_sock.sendall(response.encode())
            client_sock.close()
            print(f"[!] Access denied for {authenticated_user} - outside allowed hours ({current_time})")
            return
        
        # Check and manage user sessions (one device per user with 3-minute timeout)
        with cache_manager.lock:
            allowed, msg = check_user_session(authenticated_user, device_ip, client_sock)
            server_logger.log(f"[*] {msg}")
            if not allowed:
                # Session check already sent error response and closed socket
                return
            cache_manager.active_clients[addr] = (authenticated_user, time.time())
        
        try:
            remote_sock = cache_manager.get_cached_connection(host, port)
            
            # If not cached, create new connection
            if remote_sock is None:
                # Check DNS cache first
                resolved_ip = cache_manager.get_cached_dns(host)
                
                try:
                    # Try cached DNS first, with shorter timeout
                    if resolved_ip:
                        server_logger.log(f"[*] Using cached DNS for {host} -> {resolved_ip}")
                        remote_sock = socket.create_connection((resolved_ip, port), timeout=5)
                    else:
                        # Use shorter timeout for initial connection attempt
                        remote_sock = socket.create_connection((host, port), timeout=5)
                        # Cache the DNS resolution asynchronously (don't wait)
                        try:
                            resolved_ip = socket.gethostbyname(host)
                            cache_manager.cache_dns(host, resolved_ip)
                            print(f"[*] Cached DNS: {host} -> {resolved_ip}")
                        except Exception as dns_err:
                            # DNS cache failed, but connection already succeeded - that's ok
                            pass
                except socket.timeout:
                    response = f"HTTP/1.1 504 Gateway Timeout\r\nConnection: close\r\n\r\n".encode()
                    client_sock.sendall(response)
                    client_sock.close()
                    return
                except Exception as e:
                    response = f"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n".encode()
                    client_sock.sendall(response)
                    client_sock.close()
                    return
            else:
                print(f"[*] Using cached connection to {host}:{port}")
            
            # Send 200 response
            response = b"HTTP/1.1 200 Connection Established\r\n\r\n"
            client_sock.sendall(response)
            
            # Tunnel data bidirectionally (pass authenticated_user to check if deleted)
            tunnel(client_sock, remote_sock, host, port, authenticated_user)
        
        except Exception as e:
            print(f"[Error] {e}")
        finally:
            # Mark session as inactive on disconnect and log only once
            if authenticated_user:
                device_ip = addr[0]
                with cache_manager.lock:
                    if addr in cache_manager.active_clients:
                        del cache_manager.active_clients[addr]
                    # Mark session as inactive but keep it for 3-minute timeout
                    if authenticated_user in user_sessions:
                        stored_ip, stored_time, stored_socket, is_active = user_sessions[authenticated_user]
                        if stored_ip == device_ip and is_active:  # Only log if was active
                            user_sessions[authenticated_user] = (stored_ip, stored_time, stored_socket, False)
                            session_key = (authenticated_user, device_ip, stored_time)
                            if session_key in logged_sessions:
                                log_login(authenticated_user, device_ip, "DISCONNECT")
                                logged_sessions.discard(session_key)
            try:
                client_sock.close()
            except:
                pass
    
    except Exception as e:
        print(f"[Error in handle_client] {e}")
        try:
            client_sock.close()
        except:
            pass


def tunnel(client, remote, host, port, authenticated_user):
    """Tunnel data bidirectionally and check if user still exists. Cache connection if reusable."""
    connection_reusable = True
    check_interval = 0
    
    try:
        while True:
            # Only check if user still exists every 10 iterations (not every select)
            check_interval += 1
            if check_interval % 10 == 0:
                if authenticated_user not in PROXY_USERS:
                    print(f"[!] User {authenticated_user} was deleted. Disconnecting.")
                    log_login(authenticated_user, "0.0.0.0", "DISCONNECT_USER_DELETED_MID_SESSION")
                    return
            
            readable, _, exceptional = select.select([client, remote], [], [client, remote], 1)
            
            if exceptional:
                break
            
            for sock in readable:
                try:
                    data = sock.recv(4096)
                    if not data:
                        return
                    
                    # Apply bandwidth rate limiting (non-blocking)
                    rate_limiter.acquire(len(data))
                    
                    # Log data usage
                    log_data_usage(authenticated_user, len(data))
                    
                    if sock is client:
                        remote.sendall(data)
                    else:
                        client.sendall(data)
                except:
                    connection_reusable = False
                    return
    except:
        connection_reusable = False
    finally:
        try:
            client.close()
        except:
            pass
        
        # Cache the remote connection for reuse if it's still valid
        if connection_reusable:
            try:
                # Don't test the connection - just cache it if we got through tunnel without errors
                # Testing with empty send() can break some proxy servers
                cache_manager.cache_connection(host, port, remote)
                print(f"[*] Cached connection for {host}:{port}")
            except:
                try:
                    remote.close()
                except:
                    pass
        else:
            try:
                remote.close()
            except:
                pass


def start_monitor_server():
    """Start a monitoring server for remote cache/activity viewing."""
    monitor_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    monitor_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        monitor_sock.bind((LISTEN_HOST, MONITOR_PORT))
        monitor_sock.listen(1)
        monitor_sock.settimeout(1.0)  # 1 second timeout to check restart flag
        server_logger.log(f"[*] Monitor server started on {LISTEN_HOST}:{MONITOR_PORT}")
    except Exception as e:
        print(f"[!] Failed to start monitor server: {e}")
        return
    
    while True:
        try:
            # Check if restart was requested
            with restart_lock:
                if restart_requested:
                    print(f"[*] Monitor server detected restart signal, shutting down...")
                    break
            
            client_sock, addr = monitor_sock.accept()
            server_logger.log(f"[*] Monitor connection from {addr[0]}:{addr[1]}")
            threading.Thread(target=handle_monitor_request, args=(client_sock,), daemon=True).start()
        except socket.timeout:
            continue  # Timeout expired, loop will check restart flag
        except Exception as e:
            print(f"[!] Monitor error: {e}")


def handle_monitor_request(client_sock):
    """Handle a monitoring request."""
    global restart_requested
    try:
        # Read full request
        request = client_sock.recv(1024).decode('utf-8', errors='ignore').strip()
        parts = request.split()
        
        if not parts:
            response = "No command received.\n"
            client_sock.sendall(response.encode())
            return
        
        command = parts[0].upper()
        
        if command == "STATUS":
            # Build status response
            with cache_manager.lock:
                dns_count = len(cache_manager.dns_cache)
                page_count = len(cache_manager.page_cache)
                conn_count = len(cache_manager.connection_cache)
                active_count = len(cache_manager.active_clients)
            
            # Check if current time is within allowed access hours
            accepting_status = "YES" if is_proxy_access_allowed() else "NO"
            
            response = f"""PROXY STATUS
============
Accepting Clients: {accepting_status}
DNS Cache Entries: {dns_count}
Cached Pages: {page_count}
Active Connections: {conn_count}
Active Clients: {active_count}
Cache File: {CACHE_FILE}
"""
            client_sock.sendall(response.encode())
        
        elif command == "CLIENTS":
            # List active clients
            with cache_manager.lock:
                clients_info = list(cache_manager.active_clients.items())
            
            if not clients_info:
                response = "No active clients.\n"
            else:
                response = "ACTIVE CLIENTS\n==============\n"
                for addr, (user, timestamp) in clients_info:
                    age = int(time.time() - timestamp)
                    response += f"{addr[0]}:{addr[1]} - User: {user} (connected {age}s ago)\n"
            
            client_sock.sendall(response.encode())
        
        elif command == "ADDUSER":
            if len(parts) < 3:
                response = "Usage: ADDUSER username password\n"
                client_sock.sendall(response.encode())
                return
            
            username = parts[1].lower()
            password = parts[2].lower()
            
            if username in PROXY_USERS:
                response = f"User '{username}' already exists.\n"
            else:
                PROXY_USERS[username] = password
                # Rebuild auth tokens
                proxy_auth_tokens.clear()
                for user, passwd in PROXY_USERS.items():
                    proxy_auth_tokens[base64.b64encode(f"{user}:{passwd}".encode()).decode()] = user
                save_users_to_csv()  # Save to encrypted CSV
                response = f"User '{username}' added successfully with password '{password}'.\n"
                print(f"[*] Added user: {username}:{password}")
            
            client_sock.sendall(response.encode())
        
        elif command == "DELUSER":
            if len(parts) < 2:
                response = "Usage: DELUSER username\n"
                client_sock.sendall(response.encode())
                return
            
            username = parts[1].lower()
            
            if username not in PROXY_USERS:
                response = f"User '{username}' does not exist.\n"
            else:
                del PROXY_USERS[username]
                # Rebuild auth tokens
                proxy_auth_tokens.clear()
                for user, passwd in PROXY_USERS.items():
                    proxy_auth_tokens[base64.b64encode(f"{user}:{passwd}".encode()).decode()] = user
                save_users_to_csv()  # Save to encrypted CSV
                
                # Disconnect any active sessions for this user
                global user_sessions
                if username in user_sessions:
                    stored_ip, _, stored_socket, _ = user_sessions[username]
                    try:
                        stored_socket.close()
                        print(f"[*] Forcefully disconnected active session for deleted user: {username} from {stored_ip}")
                        log_login(username, stored_ip, "DISCONNECT_USER_DELETED")
                    except:
                        pass
                    del user_sessions[username]
                
                response = f"User '{username}' deleted successfully and disconnected if active.\n"
                print(f"[*] Deleted user: {username}")
            
            client_sock.sendall(response.encode())
        
        elif command == "LISTUSERS":
            response = "VALID PROXY USERS\n=================\n"
            with cache_manager.lock:
                for user, passwd in PROXY_USERS.items():
                    response += f"{user}:{passwd}\n"
            
            client_sock.sendall(response.encode())
        
        elif command == "CACHE":
            # Send full cache data as JSON
            with cache_manager.lock:
                data = {
                    'dns_cache': dict(cache_manager.dns_cache),
                    'page_cache_count': len(cache_manager.page_cache),
                    'connection_count': len(cache_manager.connection_cache),
                    'timestamp': time.time()
                }
            client_sock.sendall(json.dumps(data, indent=2).encode())
        
        elif command == "LOGINLOG":
            # Display login log
            if os.path.exists(LOGIN_LOG_FILE):
                try:
                    with open(LOGIN_LOG_FILE, 'r') as f:
                        log_content = f.read()
                    response = "LOGIN/LOGOUT LOG\n================\n" + log_content
                except Exception as e:
                    response = f"Error reading login log: {e}\n"
            else:
                response = "No login log file found.\n"
            client_sock.sendall(response.encode())
        
        elif command == "USAGE":
            # Show data usage for all users or specific user
            if len(parts) > 1:
                # Specific user
                username = parts[1].lower()
                if username in user_data_usage:
                    bytes_used = user_data_usage[username]
                    gb_used = bytes_used / (1024 * 1024 * 1024)
                    response = f"Data Usage for {username}\n========================\n"
                    response += f"Total: {bytes_used:,} bytes ({gb_used:.3f} GB)\n"
                else:
                    response = f"No data usage recorded for user '{username}'.\n"
            else:
                # All users
                response = "DATA USAGE (Current Session)\n============================\n"
                if user_data_usage:
                    for user, bytes_used in sorted(user_data_usage.items(), key=lambda x: x[1], reverse=True):
                        gb_used = bytes_used / (1024 * 1024 * 1024)
                        mb_used = (bytes_used % (1024 * 1024 * 1024)) / (1024 * 1024)
                        response += f"{user}: {bytes_used:,} bytes ({gb_used:.2f} GB)\n"
                else:
                    response = "No data usage recorded.\n"
            client_sock.sendall(response.encode())
        
        elif command == "USAGELOG":
            # Display usage log from file (last 30 days)
            if os.path.exists(USAGE_LOG_FILE):
                try:
                    import datetime
                    thirty_days_ago = datetime.datetime.now() - datetime.timedelta(days=30)
                    
                    with open(USAGE_LOG_FILE, 'r') as f:
                        lines = f.readlines()
                    
                    # Filter for last 30 days
                    recent_lines = []
                    for line in lines:
                        try:
                            date_str = line.split(" |")[0]
                            entry_date = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                            if entry_date >= thirty_days_ago:
                                recent_lines.append(line)
                        except:
                            recent_lines.append(line)
                    
                    if recent_lines:
                        response = "DATA USAGE LOG (Last 30 Days)\n============================\n"
                        response += "".join(recent_lines[-100:])  # Show last 100 entries
                    else:
                        response = "No usage data in the last 30 days.\n"
                except Exception as e:
                    response = f"Error reading usage log: {e}\n"
            else:
                response = "No usage log file found.\n"
            client_sock.sendall(response.encode())
        
        elif command == "LOGS":
            # Display server logs
            if os.path.exists(SERVER_LOG_FILE):
                try:
                    with open(SERVER_LOG_FILE, 'r') as f:
                        log_content = f.read()
                    response = "SERVER LOGS\n===========\n" + log_content
                except Exception as e:
                    response = f"Error reading server log: {e}\n"
            else:
                response = "No server log file found.\n"
            client_sock.sendall(response.encode())
        
        elif command == "HELP":
            response = """PROXY MONITOR COMMANDS
======================
STATUS        - Show proxy status
CLIENTS       - List active connected clients
ADDUSER u p   - Add new user (username password)
DELUSER u     - Delete user (username)
LISTUSERS     - List all valid users
CACHE         - Show cache data (JSON)
LOGS          - Show login/logout history
LOGINLOG      - Show login/logout history
USAGE         - Show current session data usage for all users
USAGE u       - Show current session data usage for specific user
USAGELOG      - Show data usage log (last 30 days)
RESTART       - Remotely restart the proxy server
HELP          - Show this help message
"""
            client_sock.sendall(response.encode())
        
        elif command == "RESTART":
            response = "Proxy server restarting...\n"
            client_sock.sendall(response.encode())
            with restart_lock:
                restart_requested = True
            print(f"[*] Remote restart requested")
            time.sleep(0.5)  # Give client time to receive response
        
        else:
            response = f"Unknown command: {command}\nType 'HELP' for available commands.\n"
            client_sock.sendall(response.encode())
    
    except Exception as e:
        print(f"[!] Monitor request error: {e}")
    finally:
        try:
            client_sock.close()
        except:
            pass



def start_proxy():
    """Start the HTTPS proxy server."""
    # Load users from encrypted CSV file on startup
    if not load_users_from_csv():
        # If no CSV exists, save default users
        save_users_to_csv()
    
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((LISTEN_HOST, LISTEN_PORT))
    server_sock.listen(5)
    server_sock.settimeout(1.0)  # 1 second timeout to check restart flag
    
    server_logger.log(f"[*] HTTPS Proxy Server with Persistent Caching")
    server_logger.log(f"[*] Listening on {LISTEN_HOST}:{LISTEN_PORT}")
    server_logger.log(f"[*] Monitor listening on {LISTEN_HOST}:{MONITOR_PORT}")
    server_logger.log(f"[*] Cache TTL: {CACHE_TTL} seconds")
    server_logger.log(f"[*] Cache file: {CACHE_FILE}")
    server_logger.log(f"[*] Users file: {USERS_FILE} (encrypted)")
    server_logger.log(f"[*] Auto-save interval: {CACHE_SAVE_INTERVAL} seconds")
    server_logger.log(f"[*] Max cached connections: {MAX_CACHED_CONNECTIONS}")
    server_logger.log(f"[*] Valid users:")
    for user, passwd in PROXY_USERS.items():
        server_logger.log(f"     - {user}:{passwd}")
    server_logger.log(f"[*] Ready to accept connections...")
    
    # Start auto-save thread
    cache_manager.start_auto_save()
    
    # Start user reload thread (checks every 30 seconds for new approved users)
    start_user_reload_thread()
    
    # Start monitor server
    monitor_thread = threading.Thread(target=start_monitor_server, daemon=True)
    monitor_thread.start()
    
    try:
        while True:
            # Check if restart was requested
            with restart_lock:
                if restart_requested:
                    print(f"[*] Proxy server detected restart signal, shutting down...")
                    break
            
            try:
                client_sock, addr = server_sock.accept()
                server_logger.log(f"[*] Connection from {addr[0]}:{addr[1]}")
                threading.Thread(target=handle_client, args=(client_sock, addr), daemon=True).start()
            except socket.timeout:
                continue  # Timeout expired, loop will check restart flag
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
        cache_manager.stop_auto_save()
        cache_manager.save_cache_to_disk()
    finally:
        server_sock.close()


def main_loop():
    """Main loop that handles restarts."""
    global restart_requested
    while True:
        try:
            # Reset the restart flag before starting
            with restart_lock:
                restart_requested = False
            start_proxy()
        except Exception as e:
            print(f"[!] Proxy crashed: {e}")
            print(f"[*] Restarting in 2 seconds...")
            time.sleep(2)


if __name__ == "__main__":
    main_loop()
