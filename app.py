from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.utils import secure_filename
import sqlite3, hashlib, os, secrets
import calendar
import json
import urllib.request
from datetime import datetime, timedelta

# Optional MySQL support via pymysql (for XAMPP/MariaDB)
try:
    import pymysql
except ImportError:
    pymysql = None

# Use the directory where app.py lives as the base — fixes TemplateNotFound
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static'),
)
flask_secret = os.getenv('FLASK_SECRET')
if not flask_secret:
    print('WARNING: FLASK_SECRET is not set. Sessions will reset on each restart.')
    flask_secret = secrets.token_hex(16)
app.secret_key = flask_secret
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
if os.getenv('FLASK_COOKIE_SECURE', '0').lower() in ('1', 'true', 'yes', 'on'):
    app.config['SESSION_COOKIE_SECURE'] = True
DB = os.path.join(BASE_DIR, 'inventory.db')

ORDER_STATUSES = [
    'Pending',
    'In Transit',
    'Out for Delivery',
    'Ready for Pickup',
    'Picked Up',
    'Delivered',
    'Cancelled'
]

def get_ngrok_public_url():
    try:
        api_url = os.getenv('NGROK_API_URL', 'http://127.0.0.1:4040/api/tunnels')
        with urllib.request.urlopen(api_url, timeout=1.5) as response:
            data = json.loads(response.read().decode('utf-8'))
        for tunnel in data.get('tunnels', []):
            if tunnel.get('proto') in ('https', 'http'):
                public_url = tunnel.get('public_url')
                if public_url:
                    return public_url
    except Exception:
        return None
    return None

@app.context_processor
def global_pickup_reminders():
    today_dt = datetime.now()
    today = today_dt.strftime('%Y-%m-%d')
    start_date = (today_dt - timedelta(days=7)).strftime('%Y-%m-%d')
    end_date = (today_dt + timedelta(days=3)).strftime('%Y-%m-%d')
    portal_new_count = 0
    try:
        with get_db() as db:
            rows = db.execute(
                "SELECT o.id, c.name AS customer_name, o.pickup_date, o.pickup_time, o.status, o.payment_method, o.total_amount, o.source "
                "FROM orders o JOIN customers c ON o.customer_id=c.id "
                "WHERE o.pickup_date BETWEEN ? AND ? "
                "AND o.status NOT IN ('Picked Up','Delivered','Cancelled') "
                "ORDER BY o.pickup_date ASC, o.pickup_time ASC",
                (start_date, end_date)
            ).fetchall()
            pickups = []
            for row in rows:
                pickup = dict(row) if not isinstance(row, dict) else row
                if pickup['pickup_date'] < today:
                    pickup['due_state'] = 'overdue'
                elif pickup['pickup_date'] == today:
                    pickup['due_state'] = 'today'
                else:
                    pickup['due_state'] = 'upcoming'
                pickups.append(pickup)

            cutoff = (today_dt - timedelta(hours=12)).strftime('%Y-%m-%d %H:%M:%S')
            new_portal = db.execute(
                "SELECT COUNT(*) as c FROM orders WHERE source='portal' AND (portal_seen IS NULL OR portal_seen=0) AND created_at >= ?",
                (cutoff,)
            ).fetchone()
            portal_new_count = new_portal['c'] if new_portal else 0
    except Exception:
        pickups = []
        portal_new_count = 0
    today_count = sum(1 for p in pickups if p['due_state'] == 'today')
    overdue_count = sum(1 for p in pickups if p['due_state'] == 'overdue')
    return {
        'global_pickup_reminders': pickups,
        'global_today_date': today,
        'global_today_count': today_count,
        'global_overdue_count': overdue_count,
        'global_portal_order_count': portal_new_count,
        'public_tunnel_url': get_ngrok_public_url(),
    }

DB_TYPE = os.getenv('DB_TYPE', 'sqlite').lower()
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', '127.0.0.1'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQL_DATABASE', 'inventory_db'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor if pymysql else None,
    'autocommit': False,
}

PLACEHOLDER = '%s' if DB_TYPE == 'mysql' else '?'

# ── DB helpers ────────────────────────────────────────────────────────────────
def _normalize_sql(sql: str) -> str:
    if DB_TYPE != 'mysql':
        return sql
    return (sql.replace('INSERT OR IGNORE', 'INSERT IGNORE')
              .replace('AUTOINCREMENT', 'AUTO_INCREMENT')
              .replace('?', PLACEHOLDER))

class DBConnection:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()

    def cursor(self):
        return self._conn.cursor()

    def execute(self, sql, params=None):
        if params is None:
            params = ()
        cur = self.cursor()
        cur.execute(_normalize_sql(sql), params)
        return cur

    def executemany(self, sql, params):
        cur = self.cursor()
        cur.executemany(_normalize_sql(sql), params)
        return cur

    def executescript(self, script):
        if DB_TYPE == 'mysql':
            raise RuntimeError('MySQL does not support executescript; use SQL statements instead.')
        return self._conn.executescript(script)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()


def _ensure_mysql_database_exists():
    if not pymysql:
        raise RuntimeError('pymysql is required for DB_TYPE=mysql. Install with pip install pymysql')
    # First connect without specifying the database, then create it if needed.
    conn = pymysql.connect(
        host=MYSQL_CONFIG['host'],
        user=MYSQL_CONFIG['user'],
        password=MYSQL_CONFIG['password'],
        charset=MYSQL_CONFIG['charset'],
        cursorclass=MYSQL_CONFIG['cursorclass'],
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_CONFIG['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    finally:
        conn.close()


def get_db():
    if DB_TYPE == 'mysql':
        if not pymysql:
            raise RuntimeError('pymysql is required for DB_TYPE=mysql. Install with pip install pymysql')
        try:
            conn = pymysql.connect(
                host=MYSQL_CONFIG['host'],
                user=MYSQL_CONFIG['user'],
                password=MYSQL_CONFIG['password'],
                database=MYSQL_CONFIG['database'],
                charset=MYSQL_CONFIG['charset'],
                cursorclass=MYSQL_CONFIG['cursorclass'],
                autocommit=False,
            )
        except pymysql.err.OperationalError as err:
            # If the database does not exist, create it and reconnect.
            if err.args and err.args[0] in (1049,):
                _ensure_mysql_database_exists()
                conn = pymysql.connect(
                    host=MYSQL_CONFIG['host'],
                    user=MYSQL_CONFIG['user'],
                    password=MYSQL_CONFIG['password'],
                    database=MYSQL_CONFIG['database'],
                    charset=MYSQL_CONFIG['charset'],
                    cursorclass=MYSQL_CONFIG['cursorclass'],
                    autocommit=False,
                )
            else:
                raise
        return DBConnection(conn)

    conn = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return DBConnection(conn)

def row_to_dict(row):
    if row is None:
        return None
    return dict(row) if not isinstance(row, dict) else row


def get_api_key_record(token: str):
    if not token:
        return None
    try:
        with get_db() as db:
            rec = db.execute("SELECT * FROM api_keys WHERE token=? AND active=1", (token,)).fetchone()
            return rec
    except Exception:
        return None


def get_rider_by_token(token: str):
    if not token:
        return None
    try:
        with get_db() as db:
            r = db.execute("SELECT * FROM riders WHERE portal_token=? AND active=1", (token,)).fetchone()
            return r
    except Exception:
        return None


def api_auth_from_request():
    # supports header or query param
    token = request.headers.get('X-API-Key') or request.args.get('api_key')
    return get_api_key_record(token)


def get_rider_name(rider_id):
    try:
        with get_db() as db:
            r = db.execute("SELECT name FROM riders WHERE id=?", (rider_id,)).fetchone()
            return r['name'] if r else None
    except Exception:
        return None


def is_image_filename(filename):
    if not filename or not isinstance(filename, str):
        return False
    # allow remote URLs
    if filename.startswith('http://') or filename.startswith('https://'):
        return True
    ext = os.path.splitext(filename)[1].lower()
    if ext not in {'.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp'}:
        return False
    # check common static image locations
    possible = [
        os.path.join(BASE_DIR, 'static', 'images', 'items', filename),
        os.path.join(BASE_DIR, 'static', 'images', 'categories', filename),
        os.path.join(BASE_DIR, 'static', 'images', filename),
    ]
    for p in possible:
        if os.path.exists(p):
            return True
    return False

app.jinja_env.globals.update(get_rider_name=get_rider_name, is_image_filename=is_image_filename)


def send_rider_notification(rider_id, message):
    try:
        with get_db() as db:
            db.execute("INSERT INTO notifications (rider_id,message,created_at) VALUES (?,?,?)",
                       (rider_id, message, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        print(f"[notify] Rider {rider_id}: {message}")
        return True
    except Exception as e:
        print(f"[notify-fail] {e}")
        return False


def send_portal_link(email, order_id, token):
    try:
        portal_url = url_for('portal_view_order', order_id=order_id, token=token, _external=True)
    except Exception:
        portal_url = f"/portal/order/{order_id}?token={token}"
    smtp_host = os.getenv('SMTP_HOST')
    if smtp_host:
        try:
            import smtplib
            from email.message import EmailMessage
            smtp_port = int(os.getenv('SMTP_PORT', '25'))
            smtp_user = os.getenv('SMTP_USER')
            smtp_pass = os.getenv('SMTP_PASS')
            msg = EmailMessage()
            msg['Subject'] = f"Your Order #{order_id} - Manage Link"
            msg['From'] = os.getenv('SMTP_FROM', smtp_user or 'no-reply@example.com')
            msg['To'] = email
            msg.set_content(f"View or manage your order: {portal_url}")
            s = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            if os.getenv('SMTP_STARTTLS','0') == '1':
                s.starttls()
            if smtp_user and smtp_pass:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)
            s.quit()
            print(f"[email] Sent portal link to {email}")
            return True
        except Exception as e:
            print(f"[email-fail] {e}; portal link: {portal_url}")
            return False
    else:
        print(f"[portal-link] {email}: {portal_url}")
        return False


def require_api_or_session():
    if logged_in():
        return True
    if api_auth_from_request():
        return True
    return False


def validate_item_payload(data: dict):
    if not data.get('name'):
        return False, 'name is required'
    if not data.get('category_id'):
        return False, 'category_id is required'
    return True, None


def validate_order_payload(data: dict):
    items = data.get('items')
    if not items or not isinstance(items, list):
        return False, 'items must be a non-empty list'
    if not data.get('pickup_date') or not data.get('pickup_time'):
        return False, 'pickup_date and pickup_time are required'
    return True, None
def init_db():
    with get_db() as db:
        if DB_TYPE == 'mysql':
            db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT PRIMARY KEY AUTO_INCREMENT,
                username VARCHAR(150) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password VARCHAR(128) NOT NULL,
                reset_token VARCHAR(255),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(150) UNIQUE NOT NULL,
                icon VARCHAR(8) DEFAULT '📦'
            )""")
            db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(255) NOT NULL,
                category_id INT NOT NULL,
                subtype VARCHAR(100),
                quantity INT DEFAULT 0,
                unit VARCHAR(50) DEFAULT 'pcs',
                price DECIMAL(10,2) DEFAULT 0,
                low_stock_threshold INT DEFAULT 10,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )""")
            db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(255) NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                phone VARCHAR(50),
                address VARCHAR(512),
                password VARCHAR(255),
                reset_token VARCHAR(255),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )""")
            # Ensure customers table has required customer account columns
            cols = db.execute("SHOW COLUMNS FROM customers LIKE 'phone'").fetchall()
            if not cols:
                db.execute("ALTER TABLE customers ADD COLUMN phone VARCHAR(50) NULL")
            cols = db.execute("SHOW COLUMNS FROM customers LIKE 'address'").fetchall()
            if not cols:
                db.execute("ALTER TABLE customers ADD COLUMN address VARCHAR(512) NULL")
            cols = db.execute("SHOW COLUMNS FROM customers LIKE 'password'").fetchall()
            if not cols:
                db.execute("ALTER TABLE customers ADD COLUMN password VARCHAR(255) NULL")
            cols = db.execute("SHOW COLUMNS FROM customers LIKE 'reset_token'").fetchall()
            if not cols:
                db.execute("ALTER TABLE customers ADD COLUMN reset_token VARCHAR(255) NULL")
            db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INT PRIMARY KEY AUTO_INCREMENT,
                customer_id INT NOT NULL,
                image TEXT,
                status VARCHAR(50) DEFAULT 'Pending',
                pickup_date DATE NOT NULL,
                pickup_time TIME NOT NULL,
                payment_method VARCHAR(50) DEFAULT 'Cash',
                total_amount DECIMAL(10,2) DEFAULT 0,
                source VARCHAR(50) DEFAULT 'admin',
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            )""")
            db.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id INT PRIMARY KEY AUTO_INCREMENT,
                order_id INT NOT NULL,
                item_id INT NOT NULL,
                quantity INT NOT NULL,
                unit_price DECIMAL(10,2) NOT NULL,
                subtotal DECIMAL(10,2) NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
                FOREIGN KEY (item_id) REFERENCES items(id)
            )""")
        else:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                reset_token TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                icon TEXT DEFAULT '📦'
            );
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category_id INTEGER NOT NULL,
                subtype TEXT,
                quantity INTEGER DEFAULT 0,
                unit TEXT DEFAULT 'pcs',
                price REAL DEFAULT 0,
                low_stock_threshold INTEGER DEFAULT 10,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (category_id) REFERENCES categories(id)
            );
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT,
                address TEXT,
                password TEXT,
                reset_token TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                status TEXT DEFAULT 'Pending',
                pickup_date TEXT NOT NULL,
                pickup_time TEXT NOT NULL,
                payment_method TEXT DEFAULT 'Cash',
                total_amount REAL DEFAULT 0,
                source TEXT DEFAULT 'admin',
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                item_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                subtotal REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (item_id) REFERENCES items(id)
            );
            """)
            columns = db.execute("PRAGMA table_info(customers)").fetchall()
            if not any(col['name'] == 'phone' for col in columns):
                db.execute("ALTER TABLE customers ADD COLUMN phone TEXT")
            if not any(col['name'] == 'address' for col in columns):
                db.execute("ALTER TABLE customers ADD COLUMN address TEXT")
            if not any(col['name'] == 'password' for col in columns):
                db.execute("ALTER TABLE customers ADD COLUMN password TEXT")
            if not any(col['name'] == 'reset_token' for col in columns):
                db.execute("ALTER TABLE customers ADD COLUMN reset_token TEXT")
        # Ensure the orders table has a source column for portal orders
        if DB_TYPE == 'mysql':
            columns = db.execute("SHOW COLUMNS FROM orders LIKE 'source'").fetchall()
            if not columns:
                db.execute("ALTER TABLE orders ADD COLUMN source VARCHAR(50) DEFAULT 'admin'")
        else:
            columns = db.execute("PRAGMA table_info(orders)").fetchall()
            if not any(col['name'] == 'source' for col in columns):
                db.execute("ALTER TABLE orders ADD COLUMN source TEXT DEFAULT 'admin'")

        # Add delivery_method and rider_id columns if missing
        if DB_TYPE == 'mysql':
            cols = db.execute("SHOW COLUMNS FROM orders LIKE 'delivery_method'").fetchall()
            if not cols:
                db.execute("ALTER TABLE orders ADD COLUMN delivery_method VARCHAR(20) DEFAULT 'pickup'")
            cols = db.execute("SHOW COLUMNS FROM orders LIKE 'rider_id'").fetchall()
            if not cols:
                db.execute("ALTER TABLE orders ADD COLUMN rider_id INT NULL")
        else:
            cols = db.execute("PRAGMA table_info(orders)").fetchall()
            if not any(col['name'] == 'delivery_method' for col in cols):
                db.execute("ALTER TABLE orders ADD COLUMN delivery_method TEXT DEFAULT 'pickup'")
            if not any(col['name'] == 'rider_id' for col in cols):
                db.execute("ALTER TABLE orders ADD COLUMN rider_id INTEGER")

        # Ensure portal_token and stock_released columns exist
        if DB_TYPE == 'mysql':
            cols = db.execute("SHOW COLUMNS FROM orders LIKE 'portal_token'").fetchall()
            if not cols:
                db.execute("ALTER TABLE orders ADD COLUMN portal_token VARCHAR(255) NULL")
            cols = db.execute("SHOW COLUMNS FROM orders LIKE 'stock_released'").fetchall()
            if not cols:
                db.execute("ALTER TABLE orders ADD COLUMN stock_released TINYINT DEFAULT 0")
            cols = db.execute("SHOW COLUMNS FROM orders LIKE 'portal_seen'").fetchall()
            if not cols:
                db.execute("ALTER TABLE orders ADD COLUMN portal_seen TINYINT DEFAULT 0")
            cols = db.execute("SHOW COLUMNS FROM orders LIKE 'portal_seen_at'").fetchall()
            if not cols:
                db.execute("ALTER TABLE orders ADD COLUMN portal_seen_at DATETIME NULL")
        else:
            cols = db.execute("PRAGMA table_info(orders)").fetchall()
            if not any(col['name'] == 'portal_token' for col in cols):
                db.execute("ALTER TABLE orders ADD COLUMN portal_token TEXT")
            if not any(col['name'] == 'stock_released' for col in cols):
                db.execute("ALTER TABLE orders ADD COLUMN stock_released INTEGER DEFAULT 0")
            if not any(col['name'] == 'portal_seen' for col in cols):
                db.execute("ALTER TABLE orders ADD COLUMN portal_seen INTEGER DEFAULT 0")
            if not any(col['name'] == 'portal_seen_at' for col in cols):
                db.execute("ALTER TABLE orders ADD COLUMN portal_seen_at TEXT NULL")

        # Add image column to items if missing
        if DB_TYPE == 'mysql':
            cols = db.execute("SHOW COLUMNS FROM items LIKE 'image'").fetchall()
            if not cols:
                db.execute("ALTER TABLE items ADD COLUMN image VARCHAR(255) NULL")
        else:
            cols = db.execute("PRAGMA table_info(items)").fetchall()
            if not any(col['name'] == 'image' for col in cols):
                db.execute("ALTER TABLE items ADD COLUMN image TEXT")

        # Create riders table for delivery personnel
        if DB_TYPE == 'mysql':
            db.execute("""
            CREATE TABLE IF NOT EXISTS riders (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(255) NOT NULL,
                phone VARCHAR(50),
                email VARCHAR(255) UNIQUE,
                username VARCHAR(255) UNIQUE,
                password VARCHAR(255),
                active TINYINT DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            cols = db.execute("SHOW COLUMNS FROM riders LIKE 'email'").fetchall()
            if not cols:
                db.execute("ALTER TABLE riders ADD COLUMN email VARCHAR(255) NULL")
            cols = db.execute("SHOW COLUMNS FROM riders LIKE 'username'").fetchall()
            if not cols:
                db.execute("ALTER TABLE riders ADD COLUMN username VARCHAR(255) UNIQUE NULL")
            cols = db.execute("SHOW COLUMNS FROM riders LIKE 'password'").fetchall()
            if not cols:
                db.execute("ALTER TABLE riders ADD COLUMN password VARCHAR(255) NULL")
            cols = db.execute("SHOW COLUMNS FROM riders LIKE 'portal_token'").fetchall()
            if not cols:
                db.execute("ALTER TABLE riders ADD COLUMN portal_token VARCHAR(255) NULL")
        else:
            db.execute("""
            CREATE TABLE IF NOT EXISTS riders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT UNIQUE,
                username TEXT UNIQUE,
                password TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );""")
            cols = db.execute("PRAGMA table_info(riders)").fetchall()
            if not any(col['name'] == 'email' for col in cols):
                db.execute("ALTER TABLE riders ADD COLUMN email TEXT")
            if not any(col['name'] == 'username' for col in cols):
                db.execute("ALTER TABLE riders ADD COLUMN username TEXT")
            if not any(col['name'] == 'password' for col in cols):
                db.execute("ALTER TABLE riders ADD COLUMN password TEXT")
            if not any(col['name'] == 'portal_token' for col in cols):
                db.execute("ALTER TABLE riders ADD COLUMN portal_token TEXT")

        # Seed a couple of riders only if riders table is empty
        cur = db.execute("SELECT COUNT(*) AS c FROM riders")
        cnt = cur.fetchone()
        cnt = (cnt['c'] if isinstance(cnt, dict) else cnt[0]) if cnt is not None else 0
        if not cnt:
            riders = [('Rider Jose','09171234567'),('Rider Maria','09179876543')]
            for r in riders:
                db.execute("INSERT OR IGNORE INTO riders (name,phone) VALUES (?,?)", r)
        # Ensure every rider has a portal token for public access links
        try:
            cur = db.execute("SELECT id, portal_token FROM riders")
            rows = cur.fetchall()
            for row in rows:
                token = row['portal_token'] if isinstance(row, dict) else row[1]
                if not token:
                    newt = secrets.token_urlsafe(12)
                    db.execute("UPDATE riders SET portal_token=? WHERE id=?", (newt, row['id'] if isinstance(row, dict) else row[0]))
        except Exception:
            pass
        # Create notifications table
        if DB_TYPE == 'mysql':
            db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INT PRIMARY KEY AUTO_INCREMENT,
                rider_id INT,
                message TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
        else:
            db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rider_id INTEGER,
                message TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );""")
        db.commit()

        # Seed categories
        cats = [
            ('Plastic Ware', '🥤'), ('Sugar', '🍬'), ('Cups', '🧃'),
            ('Flour', '🌾'), ('Rice', '🍚'), ('Condiments', '🧂'), ('Juices', '🥤')
        ]
        for c in cats:
            db.execute("INSERT OR IGNORE INTO categories (name, icon) VALUES (?,?)", c)
        # Seed demo admin
        pw = hashlib.sha256("admin123".encode()).hexdigest()
        db.execute("INSERT OR IGNORE INTO users (username, email, password) VALUES (?,?,?)",
                   ("admin", "admin@rellosas.com", pw))
        # Seed sample items only if items table is empty
        cur = db.execute("SELECT COUNT(*) AS c FROM items")
        cnt_items = cur.fetchone()
        cnt_items = (cnt_items['c'] if isinstance(cnt_items, dict) else cnt_items[0]) if cnt_items is not None else 0
        if not cnt_items:
            sample = [
            ("Plastic Bag Small", 1, None, 200, "pcs", 1.50, 50),
            ("Plastic Bag Large", 1, None, 150, "pcs", 2.50, 30),
            ("White Sugar", 2, None, 50, "kg", 65.00, 20),
            ("Brown Sugar", 2, None, 30, "kg", 70.00, 10),
            ("Disposable Cup 8oz", 3, None, 300, "pcs", 3.00, 100),
            ("Disposable Cup 12oz", 3, None, 250, "pcs", 4.00, 80),
            ("All-Purpose Flour", 4, "All-Purpose", 40, "kg", 50.00, 15),
            ("Bread Flour", 4, "Bread", 20, "kg", 60.00, 10),
            ("Rice (Sinandomeng)", 5, "Sinandomeng", 100, "kg", 52.00, 30),
            ("Rice (Jasmine)", 5, "Jasmine", 50, "kg", 58.00, 20),
            ("Soy Sauce", 6, None, 60, "bottle", 22.00, 20),
            ("Vinegar", 6, None, 45, "bottle", 18.00, 15),
            ("Orange Juice", 7, None, 30, "bottle", 45.00, 10),
            ("Apple Juice", 7, None, 25, "bottle", 48.00, 10),
        ]
            for s in sample:
                db.execute("""INSERT OR IGNORE INTO items
                    (name,category_id,subtype,quantity,unit,price,low_stock_threshold)
                    VALUES (?,?,?,?,?,?,?)""", s)
        db.commit()
        # API keys table for token-based auth
        if DB_TYPE == 'mysql':
            db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(255),
                token VARCHAR(255) UNIQUE NOT NULL,
                user_id INT,
                active TINYINT DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
        else:
            db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                token TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );""")
        db.commit()

_db_initialized = False

@app.before_request
def ensure_db_initialized():
    global _db_initialized
    if not _db_initialized:
        init_db()
        _db_initialized = True

# ── Auth helpers ──────────────────────────────────────────────────────────────
def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()
def logged_in(): return 'user_id' in session
def customer_logged_in(): return 'customer_id' in session
def rider_logged_in(): return 'rider_id' in session

# ── Routes: Auth ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    if logged_in():
        return redirect(url_for('dashboard'))
    if rider_logged_in():
        return redirect(url_for('rider_dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if logged_in(): return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = hash_pw(request.form['password'])
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE (username=? OR email=?) AND password=?",
                              (username, username, password)).fetchone()
            if user:
                session['user_id'] = user['id']
                session['username'] = user['username']
                return redirect(url_for('dashboard'))
        error = "Invalid username or password."
    return render_template('login.html', error=error)

@app.route('/signup', methods=['GET','POST'])
def signup():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            try:
                with get_db() as db:
                    db.execute("INSERT INTO users (username,email,password) VALUES (?,?,?)",
                               (username, email, hash_pw(password)))
                    db.commit()
                flash("Account created! Please log in.", "success")
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                error = "Username or email already exists."
    return render_template('signup.html', error=error)


@app.route('/customer/signup', methods=['GET','POST'])
def customer_signup():
    error = None
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        email = request.form.get('email','').strip()
        password = request.form.get('password','')
        confirm = request.form.get('confirm_password','')
        phone = request.form.get('phone','').strip() or None
        address = request.form.get('address','').strip() or None
        if password != confirm:
            error = 'Passwords do not match.'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters.'
        elif not name or not email:
            error = 'Name and email are required.'
        else:
            try:
                with get_db() as db:
                    db.execute("INSERT INTO customers (name,email,phone,address,password,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                               (name, email, phone, address, hash_pw(password), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                flash('Account created. Please log in.', 'success')
                return redirect(url_for('customer_login'))
            except Exception as e:
                # show friendly message for duplicate email
                if isinstance(e, sqlite3.IntegrityError) or 'UNIQUE constraint' in str(e) or 'Duplicate' in str(e):
                    error = 'An account with that email already exists.'
                else:
                    error = str(e)
    return render_template('customer_signup.html', error=error)


@app.route('/customer/login', methods=['GET','POST'])
def customer_login():
    error = None
    next_url = request.args.get('next') or request.form.get('next') or url_for('customer_order')
    if session.get('customer_id'):
        return redirect(next_url)
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        password = request.form.get('password','')
        with get_db() as db:
            cust = db.execute("SELECT * FROM customers WHERE email=? AND password=?", (email, hash_pw(password))).fetchone()
            if cust:
                session['customer_id'] = cust['id'] if isinstance(cust, dict) else cust[0]
                session['customer_name'] = cust['name'] if isinstance(cust, dict) else cust[1]
                # Mark recent portal orders for this customer as seen so admin notif clears
                try:
                    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    db.execute("UPDATE orders SET portal_seen=1, portal_seen_at=? WHERE customer_id=? AND source='portal' AND (portal_seen IS NULL OR portal_seen=0)",
                               (now_ts, session['customer_id']))
                except Exception:
                    pass
                return redirect(next_url)
        error = 'Invalid email or password.'
    return render_template('customer_login.html', error=error, next_url=next_url)


@app.route('/customer/logout')
def customer_logout():
    session.pop('customer_id', None)
    session.pop('customer_name', None)
    return redirect(url_for('customer_login'))

@app.route('/customer/forgot-password', methods=['GET','POST'])
def customer_forgot_password():
    message = None
    error = None
    if request.method == 'POST':
        email = request.form['email'].strip()
        with get_db() as db:
            customer = db.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
            if customer:
                token = secrets.token_urlsafe(16)
                db.execute("UPDATE customers SET reset_token=? WHERE email=?", (token, email))
                db.commit()
                message = f"Password reset token: {token} (use this on the reset page)"
            else:
                error = "Email not found."
    return render_template('customer_forgot_password.html', message=message, error=error)

@app.route('/customer/reset-password', methods=['GET','POST'])
def customer_reset_password():
    error = None
    message = None
    if request.method == 'POST':
        token = request.form['token'].strip()
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            error = "Passwords do not match."
        else:
            with get_db() as db:
                customer = db.execute("SELECT * FROM customers WHERE reset_token=?", (token,)).fetchone()
                if customer:
                    db.execute("UPDATE customers SET password=?, reset_token=NULL WHERE id=?",
                               (hash_pw(password), customer['id'] if isinstance(customer, dict) else customer[0]))
                    db.commit()
                    message = "Password reset! You can now log in."
                else:
                    error = "Invalid or expired token."
    return render_template('customer_reset_password.html', error=error, message=message)

@app.route('/customer/change-password', methods=['GET','POST'])
def customer_change_password():
    if not customer_logged_in():
        return redirect(url_for('customer_login'))
    error = None
    success = None
    if request.method == 'POST':
        current_password = request.form.get('current_password','')
        new_password = request.form.get('new_password','')
        confirm_password = request.form.get('confirm_password','')
        if not current_password or not new_password or not confirm_password:
            error = 'All password fields are required.'
        elif new_password != confirm_password:
            error = 'New password and confirmation do not match.'
        elif len(new_password) < 6:
            error = 'New password must be at least 6 characters.'
        else:
            with get_db() as db:
                customer = db.execute("SELECT * FROM customers WHERE id=? AND password=?",
                                      (session['customer_id'], hash_pw(current_password))).fetchone()
                if not customer:
                    error = 'Current password is incorrect.'
                else:
                    db.execute("UPDATE customers SET password=? WHERE id=?",
                               (hash_pw(new_password), session['customer_id']))
                    success = 'Password updated successfully.'
    return render_template('customer_change_password.html', error=error, success=success)

@app.route('/forgot-password', methods=['GET','POST'])
def forgot_password():
    message = None
    error = None
    if request.method == 'POST':
        email = request.form['email'].strip()
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if user:
                token = secrets.token_urlsafe(16)
                db.execute("UPDATE users SET reset_token=? WHERE email=?", (token, email))
                db.commit()
                message = f"Password reset token: {token} (use this on the reset page)"
            else:
                error = "Email not found."
    return render_template('forgot_password.html', message=message, error=error)

@app.route('/reset-password', methods=['GET','POST'])
def reset_password():
    error = None
    message = None
    if request.method == 'POST':
        token = request.form['token'].strip()
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            error = "Passwords do not match."
        else:
            with get_db() as db:
                user = db.execute("SELECT * FROM users WHERE reset_token=?", (token,)).fetchone()
                if user:
                    db.execute("UPDATE users SET password=?, reset_token=NULL WHERE id=?",
                               (hash_pw(password), user['id']))
                    db.commit()
                    message = "Password reset! You can now log in."
                else:
                    error = "Invalid or expired token."
    return render_template('reset_password.html', error=error, message=message)

@app.route('/change-password', methods=['GET','POST'])
def change_password():
    # Admin change password (logged-in users)
    if not logged_in():
        return redirect(url_for('login'))
    error = None
    success = None
    if request.method == 'POST':
        current_password = request.form.get('current_password','')
        new_password = request.form.get('new_password','')
        confirm_password = request.form.get('confirm_password','')
        if not current_password or not new_password or not confirm_password:
            error = 'All password fields are required.'
        elif new_password != confirm_password:
            error = 'New password and confirmation do not match.'
        elif len(new_password) < 6:
            error = 'New password must be at least 6 characters.'
        else:
            with get_db() as db:
                user = db.execute("SELECT * FROM users WHERE id=? AND password=?",
                                  (session['user_id'], hash_pw(current_password))).fetchone()
                if not user:
                    error = 'Current password is incorrect.'
                else:
                    db.execute("UPDATE users SET password=? WHERE id=?",
                               (hash_pw(new_password), session['user_id']))
                    success = 'Password updated successfully.'
    return render_template('change_password.html', error=error, success=success)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/rider-login', methods=['GET','POST'])
def rider_login():
    if rider_logged_in():
        return redirect(url_for('rider_dashboard'))
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = hash_pw(request.form['password'])
        with get_db() as db:
            rider = db.execute(
                "SELECT * FROM riders WHERE username=? AND password=? AND active=1",
                (username, password)
            ).fetchone()
            if rider:
                session.clear()
                session['rider_id'] = rider['id']
                session['rider_name'] = rider['name']
                return redirect(url_for('rider_dashboard'))
        error = 'Invalid rider username or password.'
    return render_template('rider_login.html', error=error)

@app.route('/rider-logout')
def rider_logout():
    session.pop('rider_id', None)
    session.pop('rider_name', None)
    return redirect(url_for('rider_login'))

@app.route('/rider/change-password', methods=['GET','POST'])
def rider_change_password():
    if not rider_logged_in():
        return redirect(url_for('rider_login'))
    error = None
    success = None
    if request.method == 'POST':
        current_password = request.form.get('current_password','')
        new_password = request.form.get('new_password','')
        confirm_password = request.form.get('confirm_password','')
        if not current_password or not new_password or not confirm_password:
            error = 'All password fields are required.'
        elif new_password != confirm_password:
            error = 'New password and confirmation do not match.'
        elif len(new_password) < 6:
            error = 'New password must be at least 6 characters.'
        else:
            with get_db() as db:
                rider = db.execute(
                    "SELECT * FROM riders WHERE id=? AND password=? AND active=1",
                    (session['rider_id'], hash_pw(current_password))
                ).fetchone()
                if not rider:
                    error = 'Current password is incorrect.'
                else:
                    db.execute(
                        "UPDATE riders SET password=? WHERE id=?",
                        (hash_pw(new_password), session['rider_id'])
                    )
                    success = 'Password updated successfully.'
    return render_template('rider_change_password.html', error=error, success=success)

@app.route('/rider-dashboard')
def rider_dashboard():
    if not rider_logged_in():
        return redirect(url_for('rider_login'))
    with get_db() as db:
        orders = db.execute(
            "SELECT o.*, c.name AS customer_name, c.phone AS customer_phone, c.address AS customer_address "
            "FROM orders o JOIN customers c ON o.customer_id=c.id "
            "WHERE o.delivery_method='delivery' "
            "ORDER BY o.pickup_date ASC, o.pickup_time ASC"
        ).fetchall()
    return render_template('rider_dashboard.html', orders=orders)

@app.route('/rider/order/<int:order_id>')
def rider_view_order(order_id):
    if not rider_logged_in():
        return redirect(url_for('rider_login'))
    with get_db() as db:
        order = db.execute(
            "SELECT o.*, c.name AS customer_name, c.email AS customer_email, c.phone AS customer_phone, c.address AS customer_address "
            "FROM orders o JOIN customers c ON o.customer_id=c.id "
            "WHERE o.id=? AND o.delivery_method='delivery'",
            (order_id,)
        ).fetchone()
        if not order:
            return redirect(url_for('rider_dashboard'))
        items = db.execute(
            "SELECT oi.*, i.name AS item_name FROM order_items oi JOIN items i ON oi.item_id=i.id WHERE oi.order_id=?",
            (order_id,)
        ).fetchall()
    return render_template('rider_view_order.html', order=order, items=items)

@app.route('/rider/order/<int:order_id>/action', methods=['POST'])
def rider_order_action(order_id):
    if not rider_logged_in():
        return redirect(url_for('rider_login'))
    action = request.form.get('action')
    with get_db() as db:
        order = db.execute(
            "SELECT * FROM orders WHERE id=? AND delivery_method='delivery'",
            (order_id,)
        ).fetchone()
        if not order:
            return redirect(url_for('rider_dashboard'))
        new_status = None
        if action == 'accept' and order['status'] == 'Pending':
            new_status = 'Out for Delivery'
            db.execute(
                "UPDATE orders SET status=?, rider_id=?, updated_at=? WHERE id=?",
                (new_status, session['rider_id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), order_id)
            )
        elif action == 'deliver' and order['status'] in ('Pending', 'Out for Delivery'):
            # Allow delivery mark even if the order was unassigned, but assign it to the current rider if needed.
            new_status = 'Delivered'
            db.execute(
                "UPDATE orders SET status=?, rider_id=COALESCE(rider_id, ?), updated_at=? WHERE id=?",
                (new_status, session['rider_id'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), order_id)
            )
        if new_status is None:
            return redirect(url_for('rider_dashboard'))
    return redirect(url_for('rider_view_order', order_id=order_id))


@app.route('/rider/portal/<token>')
def portal_rider_dashboard(token):
    rider = get_rider_by_token(token)
    if not rider:
        return "Invalid or expired rider link.", 404
    rider_id = rider['id'] if isinstance(rider, dict) else rider[0]
    with get_db() as db:
        orders = db.execute(
            "SELECT o.*, c.name AS customer_name, c.phone AS customer_phone, c.address AS customer_address "
            "FROM orders o JOIN customers c ON o.customer_id=c.id "
            "WHERE o.delivery_method='delivery' AND o.rider_id=? ORDER BY o.pickup_date ASC, o.pickup_time ASC",
            (rider_id,)
        ).fetchall()
    return render_template('portal_rider_dashboard.html', orders=orders, token=token)


@app.route('/rider/portal/order/<int:order_id>')
def portal_rider_view_order(order_id):
    token = request.args.get('token') or request.form.get('token')
    rider = get_rider_by_token(token)
    if not rider:
        return "Invalid or expired rider link.", 404
    rider_id = rider['id'] if isinstance(rider, dict) else rider[0]
    with get_db() as db:
        order = db.execute(
            "SELECT o.*, c.name AS customer_name, c.email AS customer_email, c.phone AS customer_phone, c.address AS customer_address "
            "FROM orders o JOIN customers c ON o.customer_id=c.id "
            "WHERE o.id=? AND o.delivery_method='delivery' AND o.rider_id=?",
            (order_id, rider_id)
        ).fetchone()
        if not order:
            return redirect(url_for('portal_rider_dashboard', token=token))
        items = db.execute(
            "SELECT oi.*, i.name AS item_name FROM order_items oi JOIN items i ON oi.item_id=i.id WHERE oi.order_id=?",
            (order_id,)
        ).fetchall()
    return render_template('portal_rider_view_order.html', order=order, items=items, token=token)


@app.route('/rider/portal/order/<int:order_id>/action', methods=['POST'])
def portal_rider_order_action(order_id):
    token = request.form.get('token')
    action = request.form.get('action')
    rider = get_rider_by_token(token)
    if not rider:
        return "Invalid or expired rider link.", 403
    rider_id = rider['id'] if isinstance(rider, dict) else rider[0]
    with get_db() as db:
        order = db.execute("SELECT * FROM orders WHERE id=? AND delivery_method='delivery' AND rider_id=?", (order_id, rider_id)).fetchone()
        if not order:
            return redirect(url_for('portal_rider_dashboard', token=token))
        if action == 'accept' and order['status'] == 'Pending':
            db.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", ('Out for Delivery', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), order_id))
        elif action == 'deliver' and order['status'] in ('Pending', 'Out for Delivery'):
            db.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", ('Delivered', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), order_id))
    return redirect(url_for('portal_rider_view_order', order_id=order_id) + f"?token={token}")

@app.route('/order/status/<int:order_id>', methods=['POST'])
def update_order_status(order_id):
    if not logged_in():
        return redirect(url_for('login'))
    action = request.form.get('action')
    with get_db() as db:
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            flash('Order not found.', 'error')
            return redirect(url_for('orders'))
        order = row_to_dict(order)
        status = order.get('status')
        delivery_method = order.get('delivery_method')
        new_status = None
        if action == 'picked_up' and delivery_method == 'pickup' and status not in ('Cancelled', 'Picked Up', 'Delivered'):
            new_status = 'Picked Up'
        elif action == 'delivered' and delivery_method == 'delivery' and status not in ('Cancelled', 'Delivered'):
            new_status = 'Delivered'
        if new_status:
            db.execute(
                "UPDATE orders SET status=?, updated_at=? WHERE id=?",
                (new_status, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), order_id)
            )
            flash(f'Order marked as {new_status}.', 'success')
        else:
            flash('Unable to update order status.', 'error')
    return redirect(url_for('view_order', order_id=order_id))

# ── Routes: Dashboard ─────────────────────────────────────────────────────────
@app.route('/dashboard')
def dashboard():
    if not logged_in(): return redirect(url_for('login'))
    today = datetime.now().date().isoformat()
    with get_db() as db:
        row = db.execute("SELECT COUNT(*) AS total_items FROM items").fetchone()
        total_items = row['total_items'] if isinstance(row, dict) else row[0]
        row = db.execute("SELECT SUM(quantity*price) AS total_value FROM items").fetchone()
        total_value = (row['total_value'] if isinstance(row, dict) else row[0]) or 0
        row = db.execute("SELECT COUNT(*) AS total_customers FROM customers").fetchone()
        total_customers = row['total_customers'] if isinstance(row, dict) else row[0]
        row = db.execute("SELECT COUNT(*) AS total_orders FROM orders").fetchone()
        total_orders = row['total_orders'] if isinstance(row, dict) else row[0]
        row = db.execute("SELECT SUM(total_amount) AS total_sales FROM orders").fetchone()
        total_sales = (row['total_sales'] if isinstance(row, dict) else row[0]) or 0
        start_date = (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
        sales_rows = db.execute(
            "SELECT DATE(created_at) AS order_date, SUM(total_amount) AS sales, COUNT(*) AS order_count "
            "FROM orders WHERE DATE(created_at) >= ? GROUP BY DATE(created_at) ORDER BY DATE(created_at) ASC",
            (start_date,)
        ).fetchall()
        sales_amount_map = {}
        sales_count_map = {}
        for row in sales_rows:
            order_date = row['order_date'] if isinstance(row, dict) else row[0]
            sales_amount_map[order_date] = float((row['sales'] if isinstance(row, dict) else row[1]) or 0)
            sales_count_map[order_date] = int((row['order_count'] if isinstance(row, dict) else row[2]) or 0)
        sales_chart_labels = []
        sales_chart_values = []
        weekly_sales_total = 0
        weekly_order_count = 0
        for i in range(7):
            current_date = datetime.now().date() - timedelta(days=6 - i)
            label = current_date.strftime('%b %d')
            day_key = current_date.isoformat()
            sales_chart_labels.append(label)
            sales_value = sales_amount_map.get(day_key, 0.0)
            sales_chart_values.append(sales_value)
            weekly_sales_total += sales_value
            weekly_order_count += sales_count_map.get(day_key, 0)
        product_rows = db.execute(
            "SELECT i.name AS item_name, SUM(oi.quantity) AS quantity_sold, SUM(oi.quantity * oi.unit_price) AS revenue "
            "FROM order_items oi JOIN items i ON oi.item_id=i.id JOIN orders o ON oi.order_id=o.id "
            "WHERE o.status != 'Cancelled' GROUP BY i.id, i.name ORDER BY revenue DESC LIMIT 6"
        ).fetchall()
        product_sales_labels = []
        product_sales_values = []
        product_sales_qty = []
        top_product_revenue_total = 0
        top_product_quantity_total = 0
        for row in product_rows:
            item_name = row['item_name'] if isinstance(row, dict) else row[0]
            revenue = float((row['revenue'] if isinstance(row, dict) else row[2]) or 0)
            qty = int((row['quantity_sold'] if isinstance(row, dict) else row[1]) or 0)
            product_sales_labels.append(item_name)
            product_sales_values.append(revenue)
            product_sales_qty.append(qty)
            top_product_revenue_total += revenue
            top_product_quantity_total += qty
        low_stock = db.execute(
            "SELECT i.*, c.name as cat_name, c.icon, i.image as image FROM items i JOIN categories c ON i.category_id=c.id WHERE i.quantity <= i.low_stock_threshold").fetchall()
        upcoming_pickups = db.execute(
            "SELECT o.*, c.name as customer_name FROM orders o JOIN customers c ON o.customer_id=c.id WHERE o.pickup_date >= ? ORDER BY o.pickup_date ASC, o.pickup_time ASC LIMIT 5",
            (today,)).fetchall()
        categories = db.execute("SELECT c.*, COUNT(i.id) as item_count FROM categories c LEFT JOIN items i ON c.id=i.category_id GROUP BY c.id").fetchall()
        recent = db.execute("SELECT i.*, c.name as cat_name, c.icon, i.image as image FROM items i JOIN categories c ON i.category_id=c.id ORDER BY i.updated_at DESC LIMIT 5").fetchall()
    return render_template('dashboard.html', total_items=total_items, total_value=total_value,
                           total_customers=total_customers, total_orders=total_orders,
                           total_sales=total_sales, weekly_sales_total=weekly_sales_total,
                           weekly_order_count=weekly_order_count,
                           sales_chart_labels=sales_chart_labels, sales_chart_values=sales_chart_values,
                           product_sales_labels=product_sales_labels, product_sales_values=product_sales_values,
                           top_product_revenue_total=top_product_revenue_total, top_product_quantity_total=top_product_quantity_total,
                           low_stock=low_stock, upcoming_pickups=upcoming_pickups,
                           categories=categories, recent=recent)

# ── Routes: Inventory ─────────────────────────────────────────────────────────
@app.route('/inventory')
def inventory():
    if not logged_in(): return redirect(url_for('login'))
    cat_id = request.args.get('category', '')
    sort = request.args.get('sort', 'name')
    search = request.args.get('search', '')
    valid_sorts = {'name','price','quantity','updated_at'}
    if sort not in valid_sorts: sort = 'name'
    query = "SELECT i.*, c.name as cat_name, c.icon, i.image as image FROM items i JOIN categories c ON i.category_id=c.id WHERE 1=1"
    params = []
    if cat_id:
        query += " AND i.category_id=?"; params.append(cat_id)
    if search:
        query += " AND (i.name LIKE ? OR i.subtype LIKE ?)"; params += [f'%{search}%', f'%{search}%']
    query += f" ORDER BY i.{sort}"
    with get_db() as db:
        items = db.execute(query, params).fetchall()
        categories = db.execute("SELECT * FROM categories").fetchall()
    return render_template('inventory.html', items=items, categories=categories,
                           selected_cat=cat_id, sort=sort, search=search)

@app.route('/item/add', methods=['GET','POST'])
def add_item():
    if not logged_in(): return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        try:
            image_filename = None
            file = request.files.get('image')
            if file and file.filename:
                filename = secure_filename(file.filename)
                filename = f"{secrets.token_hex(8)}_{filename}"
                img_dir = os.path.join(BASE_DIR, 'static', 'images', 'items')
                os.makedirs(img_dir, exist_ok=True)
                save_path = os.path.join(img_dir, filename)
                file.save(save_path)
                image_filename = filename
            with get_db() as db:
                db.execute("""INSERT INTO items (name,category_id,subtype,quantity,unit,price,low_stock_threshold,image)
                    VALUES (?,?,?,?,?,?,?,?)""", (
                    request.form['name'], int(request.form['category_id']),
                    request.form.get('subtype','').strip() or None,
                    int(request.form['quantity']), request.form['unit'],
                    float(request.form['price']), int(request.form.get('low_stock_threshold',10)),
                    image_filename
                ))
                db.commit()
            flash("Item added successfully!", "success")
            return redirect(url_for('inventory'))
        except Exception as e:
            error = str(e)
    with get_db() as db:
        categories = db.execute("SELECT * FROM categories").fetchall()
    return render_template('add_item.html', categories=categories, error=error)

@app.route('/item/edit/<int:item_id>', methods=['GET','POST'])
def edit_item(item_id):
    if not logged_in(): return redirect(url_for('login'))
    with get_db() as db:
        item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not item: return redirect(url_for('inventory'))
    error = None
    if request.method == 'POST':
        try:
            image_filename = None
            file = request.files.get('image')
            if file and file.filename:
                filename = secure_filename(file.filename)
                filename = f"{secrets.token_hex(8)}_{filename}"
                img_dir = os.path.join(BASE_DIR, 'static', 'images', 'items')
                os.makedirs(img_dir, exist_ok=True)
                save_path = os.path.join(img_dir, filename)
                file.save(save_path)
                image_filename = filename
            with get_db() as db:
                if image_filename:
                    db.execute("""UPDATE items SET name=?,category_id=?,subtype=?,quantity=?,unit=?,
                        price=?,low_stock_threshold=?,image=?,updated_at=? WHERE id=?""", (
                        request.form['name'], int(request.form['category_id']),
                        request.form.get('subtype','').strip() or None,
                        int(request.form['quantity']), request.form['unit'],
                        float(request.form['price']), int(request.form.get('low_stock_threshold',10)),
                        image_filename, datetime.now().isoformat(), item_id
                    ))
                else:
                    db.execute("""UPDATE items SET name=?,category_id=?,subtype=?,quantity=?,unit=?,
                        price=?,low_stock_threshold=?,updated_at=? WHERE id=?""", (
                        request.form['name'], int(request.form['category_id']),
                        request.form.get('subtype','').strip() or None,
                        int(request.form['quantity']), request.form['unit'],
                        float(request.form['price']), int(request.form.get('low_stock_threshold',10)),
                        datetime.now().isoformat(), item_id
                    ))
                db.commit()
            flash("Item updated!", "success")
            return redirect(url_for('inventory'))
        except Exception as e:
            error = str(e)
    with get_db() as db:
        categories = db.execute("SELECT * FROM categories").fetchall()
    return render_template('edit_item.html', item=item, categories=categories, error=error)

@app.route('/item/delete/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    if not logged_in(): return redirect(url_for('login'))
    with get_db() as db:
        db.execute("DELETE FROM items WHERE id=?", (item_id,))
        db.commit()
    flash("Item deleted.", "info")
    return redirect(url_for('inventory'))

@app.route('/item/adjust/<int:item_id>', methods=['POST'])
def adjust_stock(item_id):
    if not logged_in(): return jsonify(error="Not logged in"), 401
    delta = int(request.json.get('delta', 0))
    with get_db() as db:
        item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not item: return jsonify(error="Not found"), 404
        new_qty = max(0, item['quantity'] + delta)
        db.execute("UPDATE items SET quantity=?, updated_at=? WHERE id=?",
                   (new_qty, datetime.now().isoformat(), item_id))
    return jsonify(quantity=new_qty)

# ── Routes: Customers ────────────────────────────────────────────────────────
@app.route('/customers')
def customers():
    if not logged_in(): return redirect(url_for('login'))
    search = request.args.get('search', '')
    query = "SELECT * FROM customers"
    params = []
    if search:
        query += " WHERE name LIKE ? OR email LIKE ? OR phone LIKE ? OR address LIKE ?"
        params = [f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%']
    query += " ORDER BY name"
    with get_db() as db:
        customers = db.execute(query, params).fetchall()
    return render_template('customers.html', customers=customers, search=search)

@app.route('/customer/<int:customer_id>')
def view_customer(customer_id):
    if not logged_in(): return redirect(url_for('login'))
    with get_db() as db:
        customer = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        return redirect(url_for('customers'))
    return render_template('view_customer.html', customer=customer)

@app.route('/customer/add', methods=['GET','POST'])
def add_customer():
    if not logged_in(): return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip()
        phone = request.form.get('phone','').strip() or None
        address = request.form.get('address','').strip() or None
        if not name or not email:
            error = "Name and email are required."
        else:
            try:
                with get_db() as db:
                    db.execute("INSERT INTO customers (name,email,phone,address) VALUES (?,?,?,?)",
                               (name, email, phone, address))
                flash("Customer added successfully!", "success")
                return redirect(url_for('customers'))
            except Exception as e:
                error = str(e)
    return render_template('add_customer.html', error=error)

@app.route('/customer/edit/<int:customer_id>', methods=['GET','POST'])
def edit_customer(customer_id):
    if not logged_in(): return redirect(url_for('login'))
    error = None
    with get_db() as db:
        customer = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        return redirect(url_for('customers'))
    if request.method == 'POST':
        name = request.form['name'].strip()
        email = request.form['email'].strip()
        phone = request.form.get('phone','').strip() or None
        address = request.form.get('address','').strip() or None
        if not name or not email:
            error = "Name and email are required."
        else:
            try:
                with get_db() as db:
                    db.execute("UPDATE customers SET name=?, email=?, phone=?, address=?, updated_at=? WHERE id=?",
                               (name, email, phone, address, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), customer_id))
                flash("Customer updated successfully!", "success")
                return redirect(url_for('customers'))
            except Exception as e:
                error = str(e)
    return render_template('edit_customer.html', customer=customer, error=error)

@app.route('/customer/delete/<int:customer_id>', methods=['POST'])
def delete_customer(customer_id):
    if not logged_in(): return redirect(url_for('login'))
    try:
        with get_db() as db:
            orders = db.execute("SELECT id, stock_released FROM orders WHERE customer_id=?", (customer_id,)).fetchall()
            for ordrec in orders:
                ordrec = row_to_dict(ordrec)
                if int(ordrec.get('stock_released') or 0):
                    items = db.execute("SELECT item_id, quantity FROM order_items WHERE order_id=?", (ordrec['id'],)).fetchall()
                    for it in items:
                        it = row_to_dict(it)
                        db.execute("UPDATE items SET quantity = quantity + ? WHERE id=?", (it['quantity'], it['item_id']))
                db.execute("DELETE FROM order_items WHERE order_id=?", (ordrec['id'],))
            db.execute("DELETE FROM orders WHERE customer_id=?", (customer_id,))
            db.execute("DELETE FROM customers WHERE id=?", (customer_id,))
        flash("Customer and related orders deleted.", "info")
    except Exception as e:
        flash(f"Failed to delete customer: {e}", "error")
    return redirect(url_for('customers'))

# ── Routes: Orders ───────────────────────────────────────────────────────────
@app.route('/orders')
def orders():
    if not logged_in(): return redirect(url_for('login'))
    search = request.args.get('search', '')
    pickup_date = request.args.get('pickup_date', '')
    query = "SELECT o.*, c.name as customer_name FROM orders o JOIN customers c ON o.customer_id=c.id"
    params = []
    filters = []
    if search:
        filters.append("(c.name LIKE ? OR o.payment_method LIKE ? OR o.status LIKE ?)")
        params += [f'%{search}%', f'%{search}%', f'%{search}%']
    if pickup_date:
        filters.append("o.pickup_date = ?")
        params.append(pickup_date)
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY o.pickup_date DESC, o.pickup_time DESC"
    with get_db() as db:
        orders = db.execute(query, params).fetchall()
    return render_template('orders.html', orders=orders, search=search, pickup_date=pickup_date)


@app.route('/order/cancel/<int:order_id>', methods=['POST'])
def cancel_order(order_id):
    # Allow cancellation by logged-in staff or via portal orders (customer-facing)
    with get_db() as db:
        ordrec = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not ordrec:
            flash('Order not found.', 'error')
            return redirect(url_for('orders'))
        ordrec = row_to_dict(ordrec)
        status = ordrec.get('status')
        source = ordrec.get('source')
        # require login for non-portal orders
        if not logged_in() and source != 'portal':
            return redirect(url_for('login'))
        if status == 'Cancelled':
            flash('Order is already cancelled.', 'info')
            return redirect(url_for('view_order', order_id=order_id))
        try:
            reason = request.form.get('cancel_reason') or ('Cancelled by customer' if source == 'portal' and not logged_in() else 'Cancelled')
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db.execute("UPDATE orders SET status=?, notes=COALESCE(notes, '') || ? , updated_at=? WHERE id=?",
                       ('Cancelled', '\n' + reason, now, order_id))
            # If stock was reserved for this order, restore quantities
            stock_released = ordrec.get('stock_released') if isinstance(ordrec, dict) else ordrec[ 'stock_released' ] if 'stock_released' in ordrec else None
            try:
                sr = int(stock_released) if stock_released is not None else 0
            except Exception:
                sr = 0
            if sr:
                items = db.execute("SELECT item_id, quantity FROM order_items WHERE order_id=?", (order_id,)).fetchall()
                for it in items:
                    item_id = it['item_id'] if isinstance(it, dict) else it[0]
                    qty = it['quantity'] if isinstance(it, dict) else it[1]
                    db.execute("UPDATE items SET quantity = quantity + ? WHERE id=?", (qty, item_id))
                db.execute("UPDATE orders SET stock_released=0 WHERE id=?", (order_id,))
            flash('Order cancelled successfully.', 'success')
        except Exception as e:
            flash('Failed to cancel order: ' + str(e), 'error')
    # If this was a portal cancellation (no login), redirect back to the portal view
    if source == 'portal' and not logged_in():
        token = ordrec.get('portal_token') if isinstance(ordrec, dict) else None
        return redirect(url_for('portal_view_order', order_id=order_id, token=token or ''))
    return redirect(url_for('view_order', order_id=order_id))

@app.route('/portal/order/<int:order_id>')
def portal_view_order(order_id):
    # Public-facing order view for portal orders. Requires matching token query param.
    token = request.args.get('token', '').strip()
    with get_db() as db:
        order = db.execute("SELECT o.*, c.name as customer_name, c.email as customer_email, c.phone as customer_phone, c.address as customer_address FROM orders o JOIN customers c ON o.customer_id=c.id WHERE o.id=?", (order_id,)).fetchone()
        if not order:
            flash('Order not found.', 'error')
            return redirect(url_for('customer_order'))
        # Only allow portal-sourced orders through this public view
        source = order['source'] if isinstance(order, dict) and 'source' in order else None
        if source != 'portal':
            flash('Public view not available for this order.', 'error')
            return redirect(url_for('customer_order'))
        # If a portal token exists for this order, require it
        portal_token = order.get('portal_token') if isinstance(order, dict) else None
        if portal_token:
            if not token or token != portal_token:
                flash('Invalid or missing order token.', 'error')
                return redirect(url_for('customer_login', next=url_for('customer_order')))
        else:
            # fallback to email match for legacy orders
            email = request.args.get('email', '').strip()
            if email and (order['customer_email'] if isinstance(order, dict) else order[3]) != email:
                flash('Email does not match this order.', 'error')
                return redirect(url_for('customer_login', next=url_for('customer_order')))
        items = db.execute("SELECT oi.*, i.name as item_name FROM order_items oi JOIN items i ON oi.item_id=i.id WHERE oi.order_id=?", (order_id,)).fetchall()
    return render_template('portal_view_order.html', order=order, items=items)

@app.route('/schedule')
def schedule():
    if not logged_in(): return redirect(url_for('login'))
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    now = datetime.now()
    if not year or not month:
        year = now.year
        month = now.month
    if month < 1:
        month = 1
    if month > 12:
        month = 12
    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, calendar.monthrange(year, month)[1])
    prev_month = (first_day - timedelta(days=1))
    next_month = (last_day + timedelta(days=1))
    with get_db() as db:
        orders = db.execute(
            "SELECT o.*, c.name AS customer_name FROM orders o JOIN customers c ON o.customer_id=c.id "
            "WHERE o.pickup_date BETWEEN ? AND ? AND o.status != 'Cancelled' "
            "ORDER BY o.pickup_date ASC, o.pickup_time ASC",
            (first_day.strftime('%Y-%m-%d'), last_day.strftime('%Y-%m-%d'))
        ).fetchall()
    events = {}
    for order in orders:
        date_key = order['pickup_date']
        events.setdefault(date_key, []).append(order)
    month_year = first_day.strftime('%B %Y')
    calendar_weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    return render_template(
        'schedule.html',
        month_year=month_year,
        calendar_weeks=calendar_weeks,
        events=events,
        current_year=year,
        current_month=month,
        prev_month=prev_month,
        next_month=next_month,
        today=now.strftime('%Y-%m-%d')
    )

@app.route('/order/<int:order_id>')
def view_order(order_id):
    if not logged_in(): return redirect(url_for('login'))
    with get_db() as db:
        order = db.execute("SELECT o.*, c.name as customer_name, c.email as customer_email, c.phone as customer_phone, c.address as customer_address FROM orders o JOIN customers c ON o.customer_id=c.id WHERE o.id=?", (order_id,)).fetchone()
        if not order:
            return redirect(url_for('orders'))
        items = db.execute("SELECT oi.*, i.name as item_name FROM order_items oi JOIN items i ON oi.item_id=i.id WHERE oi.order_id=?", (order_id,)).fetchall()
    return render_template('view_order.html', order=order, items=items)

@app.route('/order/add', methods=['GET','POST'])
def add_order():
    if not logged_in(): return redirect(url_for('login'))
    error = None
    with get_db() as db:
        customers = db.execute("SELECT * FROM customers ORDER BY name").fetchall()
        items = db.execute("SELECT * FROM items ORDER BY name").fetchall()
        riders = db.execute("SELECT * FROM riders WHERE active=1 ORDER BY name").fetchall()
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        pickup_date = request.form.get('pickup_date')
        pickup_time = request.form.get('pickup_time')
        payment_method = request.form.get('payment_method')
        status = request.form.get('status', 'Pending')
        notes = request.form.get('notes', '').strip() or None
        delivery_method = request.form.get('delivery_method','pickup')
        rider_id = request.form.get('rider_id') or None
        order_items = []
        total_amount = 0
        item_lookup = {str(item['id']): item for item in items}
        for idx, item_id in enumerate(request.form.getlist('item_id')):
            if not item_id:
                continue
            quantity = int(request.form.getlist('quantity')[idx] or 0)
            if quantity <= 0:
                continue
            item = item_lookup.get(item_id)
            if not item:
                continue
            unit_price = float(item['price'])
            subtotal = unit_price * quantity
            total_amount += subtotal
            order_items.append((item_id, quantity, unit_price, subtotal))
        # Validate
        validation_error = None
        if not customer_id:
            validation_error = "Please select a customer."
        elif not payment_method:
            validation_error = "Please select a payment method."
        elif not order_items:
            validation_error = "Please select at least one item."
        elif delivery_method == 'pickup' and (not pickup_date or not pickup_time):
            validation_error = "Pickup date and time are required."
        elif delivery_method == 'delivery' and not rider_id:
            validation_error = "Please assign a rider for delivery."
        
        if validation_error:
            error = validation_error
        else:
            try:
                with get_db() as db:
                    # Admin-created order (no portal token by default)
                    cursor = db.execute("INSERT INTO orders (customer_id,status,pickup_date,pickup_time,payment_method,total_amount,notes,delivery_method,rider_id,portal_token) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                        (customer_id, status, pickup_date, pickup_time, payment_method, total_amount, notes, delivery_method, rider_id, None))
                    order_id = cursor.lastrowid
                    for item_id, quantity, unit_price, subtotal in order_items:
                        db.execute("INSERT INTO order_items (order_id,item_id,quantity,unit_price,subtotal) VALUES (?,?,?,?,?)",
                                   (order_id, item_id, quantity, unit_price, subtotal))
                    # Reserve stock for the order
                    try:
                        for item_id, quantity, _, _ in order_items:
                            db.execute("UPDATE items SET quantity = quantity - ? WHERE id=?", (quantity, item_id))
                        db.execute("UPDATE orders SET stock_released=1 WHERE id=?", (order_id,))
                    except Exception:
                        pass
                flash("Order created successfully!", "success")
                # notify rider if delivery and rider assigned
                try:
                    if delivery_method == 'delivery' and rider_id:
                        send_rider_notification(rider_id, f"New delivery assigned: Order #{order_id} pickup {pickup_date} {pickup_time}")
                except Exception:
                    pass
                return redirect(url_for('orders'))
            except Exception as e:
                error = str(e)
    return render_template('add_order.html', customers=customers, items=items, order_statuses=ORDER_STATUSES, error=error)

@app.route('/customer-order', methods=['GET','POST'])
def customer_order():
    error = None
    customer = None
    with get_db() as db:
        items = db.execute("SELECT * FROM items ORDER BY name").fetchall()
        riders = db.execute("SELECT * FROM riders WHERE active=1 ORDER BY name").fetchall()
        if session.get('customer_id'):
            customer = db.execute("SELECT * FROM customers WHERE id=?", (session['customer_id'],)).fetchone()
            # normalize dict/row
            customer = row_to_dict(customer)
    # If not logged in as customer, redirect to customer login
    if not session.get('customer_id') and request.method != 'POST':
        return redirect(url_for('customer_login', next=url_for('customer_order')))
    if request.method == 'POST':
        # If customer logged in, use their saved info; otherwise use submitted fields
        if session.get('customer_id') and customer:
            name = customer.get('name','')
            email = customer.get('email','')
            phone = customer.get('phone')
            address = customer.get('address')
        else:
            name = request.form.get('name','').strip()
            email = request.form.get('email','').strip()
            phone = request.form.get('phone','').strip() or None
            address = request.form.get('address','').strip() or None
        phone = request.form.get('phone','').strip() or None
        address = request.form.get('address','').strip() or None
        pickup_date = request.form.get('pickup_date')
        pickup_time = request.form.get('pickup_time')
        payment_method = request.form.get('payment_method')
        delivery_method = request.form.get('delivery_method','pickup')
        rider_id = request.form.get('rider_id') or None
        order_items = []
        total_amount = 0
        item_lookup = {str(item['id']): item for item in items}
        for idx, item_id in enumerate(request.form.getlist('item_id')):
            if not item_id:
                continue
            quantity = int(request.form.getlist('quantity')[idx] or 0)
            if quantity <= 0:
                continue
            item = item_lookup.get(item_id)
            if not item:
                continue
            unit_price = float(item['price'])
            subtotal = unit_price * quantity
            total_amount += subtotal
            order_items.append((item_id, quantity, unit_price, subtotal))
        # Validate based on delivery method
        validation_error = None
        if not name or not email:
            validation_error = "Name and email are required."
        elif not payment_method:
            validation_error = "Please select a payment method."
        elif not order_items:
            validation_error = "Please select at least one item."
        elif delivery_method == 'pickup' and (not pickup_date or not pickup_time):
            validation_error = "Pickup date and time are required for pickup."
        elif delivery_method == 'delivery' and not address:
            validation_error = "Delivery address is required for delivery."
        
        if validation_error:
            error = validation_error
        else:
            try:
                with get_db() as db:
                    customer = db.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
                    if customer:
                        customer_id = customer['id']
                        db.execute("UPDATE customers SET name=?, phone=?, address=?, updated_at=? WHERE id=?",
                                   (name, phone, address, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), customer_id))
                    else:
                        cursor = db.execute("INSERT INTO customers (name,email,phone,address,updated_at) VALUES (?,?,?,?,?)",
                                            (name, email, phone, address, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                        customer_id = cursor.lastrowid
                    # Generate portal token for customer orders
                    token = secrets.token_urlsafe(12)
                    cursor = db.execute("INSERT INTO orders (customer_id,status,pickup_date,pickup_time,payment_method,total_amount,source,notes,delivery_method,rider_id,portal_token) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                        (customer_id, 'Pending', pickup_date, pickup_time, payment_method, total_amount, 'portal', 'Customer portal order', delivery_method, rider_id, token))
                    order_id = cursor.lastrowid
                    for item_id, quantity, unit_price, subtotal in order_items:
                        db.execute("INSERT INTO order_items (order_id,item_id,quantity,unit_price,subtotal) VALUES (?,?,?,?,?)",
                                   (order_id, item_id, quantity, unit_price, subtotal))
                    # Reserve stock for the order
                    try:
                        for item_id, quantity, _, _ in order_items:
                            db.execute("UPDATE items SET quantity = quantity - ? WHERE id=?", (quantity, item_id))
                        db.execute("UPDATE orders SET stock_released=1 WHERE id=?", (order_id,))
                    except Exception:
                        pass
                # notify rider if delivery and rider assigned
                try:
                    if delivery_method == 'delivery' and rider_id:
                        send_rider_notification(rider_id, f"New delivery assigned: Order #{order_id} pickup {pickup_date} {pickup_time}")
                except Exception:
                    pass
                # send portal link to customer (prints to console if SMTP not configured)
                try:
                    send_portal_link(email, order_id, token)
                except Exception:
                    pass
                return render_template('customer_order_thanks.html', customer_name=name, pickup_date=pickup_date, pickup_time=pickup_time, order_id=order_id, email=email, order_token=token)
            except Exception as e:
                error = str(e)
    return render_template('customer_order.html', items=items, riders=riders, error=error, customer=customer)

@app.route('/order-now')
def order_now():
    return redirect(url_for('customer_login', next=url_for('customer_order')))

@app.route('/order', methods=['GET'])
def public_order_redirect():
    return redirect(url_for('customer_login', next=url_for('customer_order')))

@app.route('/order/edit/<int:order_id>', methods=['GET','POST'])
def edit_order(order_id):
    if not logged_in(): return redirect(url_for('login'))
    error = None
    with get_db() as db:
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            return redirect(url_for('orders'))
        customers = db.execute("SELECT * FROM customers ORDER BY name").fetchall()
        items = db.execute("SELECT * FROM items ORDER BY name").fetchall()
        order_items = db.execute("SELECT oi.*, i.name as item_name FROM order_items oi JOIN items i ON oi.item_id=i.id WHERE oi.order_id=?", (order_id,)).fetchall()
        riders = db.execute("SELECT * FROM riders WHERE active=1 ORDER BY name").fetchall()
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        pickup_date = request.form.get('pickup_date')
        pickup_time = request.form.get('pickup_time')
        payment_method = request.form.get('payment_method')
        status = request.form.get('status', 'Pending')
        notes = request.form.get('notes', '').strip() or None
        items_data = []
        total_amount = 0
        item_lookup = {str(item['id']): item for item in items}
        for idx, item_id in enumerate(request.form.getlist('item_id')):
            if not item_id:
                continue
            quantity = int(request.form.getlist('quantity')[idx] or 0)
            if quantity <= 0:
                continue
            item = item_lookup.get(item_id)
            if not item:
                continue
            unit_price = float(item['price'])
            subtotal = unit_price * quantity
            total_amount += subtotal
            items_data.append((item_id, quantity, unit_price, subtotal))
        # Validate
        validation_error = None
        if not customer_id:
            validation_error = "Please select a customer."
        elif not payment_method:
            validation_error = "Please select a payment method."
        elif not items_data:
            validation_error = "Please select at least one item."
        elif request.form.get('delivery_method','pickup') == 'pickup' and (not pickup_date or not pickup_time):
            validation_error = "Pickup date and time are required."
        
        if validation_error:
            error = validation_error
        else:
            try:
                with get_db() as db:
                    db.execute("UPDATE orders SET customer_id=?, status=?, pickup_date=?, pickup_time=?, payment_method=?, total_amount=?, notes=?, delivery_method=?, rider_id=?, updated_at=? WHERE id=?",
                               (customer_id, status, pickup_date, pickup_time, payment_method, total_amount, notes, request.form.get('delivery_method','pickup'), request.form.get('rider_id') or None, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), order_id))
                    db.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
                    for item_id, quantity, unit_price, subtotal in items_data:
                        db.execute("INSERT INTO order_items (order_id,item_id,quantity,unit_price,subtotal) VALUES (?,?,?,?,?)",
                                   (order_id, item_id, quantity, unit_price, subtotal))
                flash("Order updated successfully!", "success")
                try:
                    # notify rider if delivery and rider assigned
                    dm = request.form.get('delivery_method','pickup')
                    rid = request.form.get('rider_id') or None
                    if dm == 'delivery' and rid:
                        send_rider_notification(rid, f"Assigned delivery updated: Order #{order_id} pickup {pickup_date} {pickup_time}")
                except Exception:
                    pass
                return redirect(url_for('orders'))
            except Exception as e:
                error = str(e)
    return render_template('edit_order.html', order=order, customers=customers, items=items, order_items=order_items, order_statuses=ORDER_STATUSES, error=error)

@app.route('/order/delete/<int:order_id>', methods=['POST'])
def delete_order(order_id):
    if not logged_in(): return redirect(url_for('login'))
    with get_db() as db:
        db.execute("DELETE FROM order_items WHERE order_id=?", (order_id,))
        db.execute("DELETE FROM orders WHERE id=?", (order_id,))
    flash("Order deleted.", "info")
    return redirect(url_for('orders'))

# ------------------ JSON API endpoints ------------------
@app.route('/api/items', methods=['GET','POST'])
def api_items():
    if request.method == 'GET':
        with get_db() as db:
            items = db.execute("SELECT i.*, c.name as category_name, c.icon, i.image as image FROM items i JOIN categories c ON i.category_id=c.id ORDER BY i.name").fetchall()
        return jsonify([row_to_dict(i) for i in items])

    # POST - create item (admin or API key)
    if not require_api_or_session():
        return jsonify(error="Unauthorized"), 401
    data = request.get_json() or {}
    ok, msg = validate_item_payload(data)
    if not ok:
        return jsonify(error=msg), 400
    try:
        with get_db() as db:
            cursor = db.execute(
                "INSERT INTO items (name,category_id,subtype,quantity,unit,price,low_stock_threshold,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    data.get('name'), data.get('category_id'), data.get('subtype'), data.get('quantity', 0),
                    data.get('unit', 'pcs'), data.get('price', 0), data.get('low_stock_threshold', 10),
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                )
            )
            item_id = cursor.lastrowid
            item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return jsonify(row_to_dict(item)), 201
    except Exception as e:
        return jsonify(error=str(e)), 400

@app.route('/api/items/<int:item_id>', methods=['GET','PUT','DELETE'])
def api_item_detail(item_id):
    if request.method == 'GET':
        with get_db() as db:
            item = db.execute("SELECT i.*, c.name as category_name, c.icon, i.image as image FROM items i JOIN categories c ON i.category_id=c.id WHERE i.id=?", (item_id,)).fetchone()
        if not item:
            return jsonify(error="Not found"), 404
        return jsonify(row_to_dict(item))

    if not require_api_or_session():
        return jsonify(error="Unauthorized"), 401

    if request.method == 'PUT':
        data = request.get_json() or {}
        try:
            with get_db() as db:
                db.execute("UPDATE items SET name=?,category_id=?,subtype=?,quantity=?,unit=?,price=?,low_stock_threshold=?,updated_at=? WHERE id=?",
                           (data.get('name'), data.get('category_id'), data.get('subtype'), data.get('quantity', 0), data.get('unit', 'pcs'), data.get('price', 0), data.get('low_stock_threshold', 10), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), item_id))
                item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            return jsonify(row_to_dict(item))
        except Exception as e:
            return jsonify(error=str(e)), 400

    if request.method == 'DELETE':
        try:
            with get_db() as db:
                db.execute("DELETE FROM items WHERE id=?", (item_id,))
            return jsonify(success=True)
        except Exception as e:
            return jsonify(error=str(e)), 400

@app.route('/api/customers', methods=['GET','POST'])
def api_customers():
    if request.method == 'GET':
        with get_db() as db:
            customers = db.execute("SELECT * FROM customers ORDER BY name").fetchall()
        return jsonify([row_to_dict(c) for c in customers])

    # POST - create customer (admin or API key)
    if not require_api_or_session():
        return jsonify(error="Unauthorized"), 401
    data = request.get_json() or {}
    try:
        with get_db() as db:
            cursor = db.execute("INSERT INTO customers (name,email,phone,address,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                                (data.get('name'), data.get('email'), data.get('phone'), data.get('address'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            cust_id = cursor.lastrowid
            cust = db.execute("SELECT * FROM customers WHERE id=?", (cust_id,)).fetchone()
        return jsonify(row_to_dict(cust)), 201
    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route('/api/api-keys', methods=['GET','POST'])
def api_api_keys():
    # list/create API keys (requires admin session or valid API key)
    if not require_api_or_session():
        return jsonify(error="Unauthorized"), 401
    if request.method == 'GET':
        with get_db() as db:
            keys = db.execute("SELECT id,name,token,user_id,active,created_at FROM api_keys ORDER BY created_at DESC").fetchall()
        out = []
        for k in keys:
            d = row_to_dict(k)
            # never return raw token in list view
            if 'token' in d:
                d.pop('token')
            out.append(d)
        return jsonify(out)

    data = request.get_json() or {}
    name = data.get('name') or 'key'
    user_id = session.get('user_id') if logged_in() else None
    token = secrets.token_urlsafe(24)
    try:
        with get_db() as db:
            cur = db.execute("INSERT INTO api_keys (name,token,user_id,active,created_at) VALUES (?,?,?,?,?)",
                             (name, token, user_id, 1, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            kid = cur.lastrowid
            key = db.execute("SELECT id,name,token,user_id,active,created_at FROM api_keys WHERE id=?", (kid,)).fetchone()
        # return token once
        return jsonify(row_to_dict(key)), 201
    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route('/api/api-keys/<int:key_id>', methods=['DELETE'])
def api_api_key_delete(key_id):
    if not require_api_or_session():
        return jsonify(error="Unauthorized"), 401
    try:
        with get_db() as db:
            db.execute("UPDATE api_keys SET active=0 WHERE id=?", (key_id,))
        return jsonify(success=True)
    except Exception as e:
        return jsonify(error=str(e)), 400


@app.route('/api/openapi.json')
def openapi_json():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Inventory API","version":"1.0"},
        "paths": {
            "/api/items": {
                "get": {"summary":"List items"},
                "post": {"summary":"Create item (auth required)"}
            },
            "/api/orders": {
                "get": {"summary":"List orders"},
                "post": {"summary":"Create order"}
            },
            "/api/orders/{order_id}": {
                "get": {"summary":"Order detail"}
            }
        }
    }
    return jsonify(spec)


@app.route('/api/docs')
def api_docs():
    openapi_url = url_for('openapi_json', _external=True)
    html = '''<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@4/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@4/swagger-ui-bundle.js"></script>
    <script>
      window.onload = function() {
        SwaggerUIBundle({ url: '%s', dom_id: '#swagger-ui' });
      };
    </script>
  </body>
</html>''' % openapi_url
    return html

@app.route('/api/customers/<int:customer_id>', methods=['GET'])
def api_customer_detail(customer_id):
    with get_db() as db:
        cust = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not cust:
        return jsonify(error="Not found"), 404
    return jsonify(row_to_dict(cust))

@app.route('/api/orders', methods=['GET','POST'])
def api_orders():
    if request.method == 'GET':
        with get_db() as db:
            orders = db.execute("SELECT o.*, c.name as customer_name FROM orders o JOIN customers c ON o.customer_id=c.id ORDER BY o.created_at DESC").fetchall()
        return jsonify([row_to_dict(o) for o in orders])

    # POST - create order (public or admin)
    data = request.get_json() or {}
    try:
        items = data.get('items', [])
        if not items:
            return jsonify(error="No items"), 400
        pickup_date = data.get('pickup_date')
        pickup_time = data.get('pickup_time')
        if not pickup_date or not pickup_time:
            return jsonify(error="pickup_date and pickup_time required"), 400

        with get_db() as db:
            # handle customer
            customer_id = data.get('customer_id')
            if not customer_id:
                cust = data.get('customer') or {}
                email = cust.get('email')
                if email:
                    existing = db.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
                    if existing:
                        customer_id = existing['id']
                        db.execute("UPDATE customers SET name=?, phone=?, address=?, updated_at=? WHERE id=?",
                                   (cust.get('name'), cust.get('phone'), cust.get('address'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), customer_id))
                    else:
                        cur = db.execute("INSERT INTO customers (name,email,phone,address,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                                         (cust.get('name'), email, cust.get('phone'), cust.get('address'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                        customer_id = cur.lastrowid

            total_amount = 0
            for it in items:
                iid = it.get('item_id')
                qty = int(it.get('quantity', 0))
                if not iid or qty <= 0:
                    continue
                row = db.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
                if not row:
                    continue
                total_amount += float(row['price']) * qty

            cursor = db.execute("INSERT INTO orders (customer_id,status,pickup_date,pickup_time,payment_method,total_amount,source,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (customer_id or 0, data.get('status','Pending'), pickup_date, pickup_time, data.get('payment_method','Cash'), total_amount, data.get('source','api'), data.get('notes'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            order_id = cursor.lastrowid
            for it in items:
                iid = it.get('item_id')
                qty = int(it.get('quantity', 0))
                if not iid or qty <= 0:
                    continue
                row = db.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
                if not row:
                    continue
                unit_price = float(row['price'])
                subtotal = unit_price * qty
                db.execute("INSERT INTO order_items (order_id,item_id,quantity,unit_price,subtotal) VALUES (?,?,?,?,?)",
                           (order_id, iid, qty, unit_price, subtotal))
        return jsonify(order_id=order_id, total_amount=total_amount), 201
    except Exception as e:
        return jsonify(error=str(e)), 400

@app.route('/api/orders/<int:order_id>', methods=['GET'])
def api_order_detail(order_id):
    with get_db() as db:
        order = db.execute("SELECT o.*, c.name as customer_name, c.email as customer_email FROM orders o JOIN customers c ON o.customer_id=c.id WHERE o.id=?", (order_id,)).fetchone()
        if not order:
            return jsonify(error="Not found"), 404
        items = db.execute("SELECT oi.*, i.name as item_name FROM order_items oi JOIN items i ON oi.item_id=i.id WHERE oi.order_id=?", (order_id,)).fetchall()
    out = row_to_dict(order)
    out['items'] = [row_to_dict(i) for i in items]
    return jsonify(out)


@app.route('/riders', methods=['GET','POST'])
def riders():
    if not logged_in(): return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip() or None
        email = request.form.get('email','').strip() or None
        username = request.form.get('username','').strip() or None
        password = request.form.get('password','')
        if not name:
            error = 'Name required.'
        elif not username:
            error = 'Rider username required.'
        elif not password or len(password) < 6:
            error = 'Password must be at least 6 characters.'
        else:
            try:
                with get_db() as db:
                    db.execute(
                        "INSERT INTO riders (name,phone,email,username,password,active,created_at) VALUES (?,?,?,?,?,1,?)",
                        (name, phone, email, username, hash_pw(password), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    db.commit()
                flash('Rider added.', 'success')
                return redirect(url_for('riders'))
            except Exception as e:
                error = 'Rider username or email already exists.'
    with get_db() as db:
        riders = db.execute("SELECT * FROM riders ORDER BY name").fetchall()
    return render_template('riders.html', riders=riders, error=error)


@app.route('/rider/add', methods=['GET','POST'])
def add_rider():
    if not logged_in(): return redirect(url_for('login'))
    error = None
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip() or None
        email = request.form.get('email','').strip() or None
        username = request.form.get('username','').strip() or None
        password = request.form.get('password','')
        if not name:
            error = 'Name required.'
        elif not username:
            error = 'Rider username required.'
        elif not password or len(password) < 6:
            error = 'Password must be at least 6 characters.'
        else:
            try:
                with get_db() as db:
                    db.execute(
                        "INSERT INTO riders (name,phone,email,username,password,active,created_at) VALUES (?,?,?,?,?,1,?)",
                        (name, phone, email, username, hash_pw(password), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                    db.commit()
                flash('Rider added.', 'success')
                return redirect(url_for('riders'))
            except Exception:
                error = 'Rider username or email already exists.'
    return render_template('add_rider.html', error=error)


@app.route('/rider/delete/<int:rider_id>', methods=['POST'])
def delete_rider(rider_id):
    if not logged_in(): return redirect(url_for('login'))
    with get_db() as db:
        db.execute("UPDATE riders SET active=0 WHERE id=?", (rider_id,))
        db.commit()
    flash('Rider deactivated.', 'info')
    return redirect(url_for('riders'))


@app.route('/rider/remove/<int:rider_id>', methods=['POST'])
def remove_rider(rider_id):
    if not logged_in(): return redirect(url_for('login'))
    with get_db() as db:
        db.execute("DELETE FROM riders WHERE id=?", (rider_id,))
        db.commit()
    flash('Rider deleted permanently.', 'warning')
    return redirect(url_for('riders'))


@app.route('/rider/reactivate/<int:rider_id>', methods=['POST'])
def reactivate_rider(rider_id):
    if not logged_in(): return redirect(url_for('login'))
    with get_db() as db:
        db.execute("UPDATE riders SET active=1 WHERE id=?", (rider_id,))
        db.commit()
    flash('Rider reactivated.', 'success')
    return redirect(url_for('riders'))


@app.route('/category/edit/<int:cat_id>', methods=['GET','POST'])
def edit_category(cat_id):
    if not logged_in(): return redirect(url_for('login'))
    error = None
    with get_db() as db:
        cat = db.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
        if not cat:
            return redirect(url_for('dashboard'))
    if request.method == 'POST':
        try:
            file = request.files.get('image')
            if file and file.filename:
                filename = secure_filename(file.filename)
                filename = f"{secrets.token_hex(8)}_{filename}"
                img_dir = os.path.join(BASE_DIR, 'static', 'images', 'categories')
                os.makedirs(img_dir, exist_ok=True)
                save_path = os.path.join(img_dir, filename)
                file.save(save_path)
                with get_db() as db:
                    db.execute("UPDATE categories SET icon=? WHERE id=?", (filename, cat_id))
                    db.commit()
            return redirect(url_for('dashboard'))
        except Exception as e:
            error = str(e)
    return render_template('edit_category.html', cat=cat, error=error)
if __name__ == '__main__':
    init_db()
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '5000'))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() in ('1', 'true', 'yes', 'on')
    app.run(host=host, port=port, debug=debug)
