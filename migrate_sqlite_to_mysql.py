import sqlite3
import pymysql
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB = os.path.join(BASE_DIR, 'inventory.db')

MYSQL = {
    'host': '127.0.0.1',
    'user': 'root',
    'password': '',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
}

DB_NAME = 'inventory_db'

print('Connecting to SQLite:', SQLITE_DB)
sqlite_conn = sqlite3.connect(SQLITE_DB)
sqlite_conn.row_factory = sqlite3.Row
sqlite_cur = sqlite_conn.cursor()

print('Connecting to MySQL (XAMPP)')
mysql_conn = pymysql.connect(**MYSQL)
mysql_cur = mysql_conn.cursor()

print('Creating database if not exists:', DB_NAME)
mysql_cur.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} CHARACTER SET utf8mb4")
mysql_conn.commit()

print('Selecting database:', DB_NAME)
mysql_cur.execute(f"USE {DB_NAME}")

print('Creating MySQL tables')
mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    reset_token VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) CHARACTER SET utf8mb4;
""")
mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    icon VARCHAR(10) DEFAULT '📦'
) CHARACTER SET utf8mb4;
""")
mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category_id INT NOT NULL,
    subtype VARCHAR(255),
    quantity INT DEFAULT 0,
    unit VARCHAR(50) DEFAULT 'pcs',
    price DECIMAL(10,2) DEFAULT 0,
    low_stock_threshold INT DEFAULT 10,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id)
) CHARACTER SET utf8mb4;
""")

mysql_conn.commit()

print('Copying categories...')
for row in sqlite_cur.execute('SELECT id, name, icon FROM categories').fetchall():
    mysql_cur.execute(
        'INSERT INTO categories (id, name, icon) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), icon=VALUES(icon)',
        (row['id'], row['name'], row['icon'])
    )

print('Copying users...')
for row in sqlite_cur.execute('SELECT id, username, email, password, reset_token, created_at FROM users').fetchall():
    mysql_cur.execute(
        'INSERT INTO users (id, username, email, password, reset_token, created_at) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE username=VALUES(username), email=VALUES(email), password=VALUES(password), reset_token=VALUES(reset_token), created_at=VALUES(created_at)',
        (row['id'], row['username'], row['email'], row['password'], row['reset_token'], row['created_at'])
    )

print('Copying items...')
for row in sqlite_cur.execute('SELECT id, name, category_id, subtype, quantity, unit, price, low_stock_threshold, created_at, updated_at FROM items').fetchall():
    mysql_cur.execute(
        'INSERT INTO items (id, name, category_id, subtype, quantity, unit, price, low_stock_threshold, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), category_id=VALUES(category_id), subtype=VALUES(subtype), quantity=VALUES(quantity), unit=VALUES(unit), price=VALUES(price), low_stock_threshold=VALUES(low_stock_threshold), created_at=VALUES(created_at), updated_at=VALUES(updated_at)',
        (row['id'], row['name'], row['category_id'], row['subtype'], row['quantity'], row['unit'], row['price'], row['low_stock_threshold'], row['created_at'], row['updated_at'])
    )

mysql_conn.commit()

print('Creating remaining MySQL tables (customers, orders, order_items, riders, notifications, api_keys)')
mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    phone VARCHAR(50),
    address VARCHAR(512),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
)
CHARACTER SET utf8mb4;
""")

mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS orders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    status VARCHAR(50) DEFAULT 'Pending',
    pickup_date DATE NOT NULL,
    pickup_time TIME NOT NULL,
    payment_method VARCHAR(50) DEFAULT 'Cash',
    total_amount DECIMAL(10,2) DEFAULT 0,
    source VARCHAR(50) DEFAULT 'admin',
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    delivery_method VARCHAR(20) DEFAULT 'pickup',
    rider_id INT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
)
CHARACTER SET utf8mb4;
""")

mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    item_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES items(id)
)
CHARACTER SET utf8mb4;
""")

mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS riders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    email VARCHAR(255) DEFAULT NULL,
    username VARCHAR(255) DEFAULT NULL,
    password VARCHAR(255) DEFAULT NULL,
    active TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
CHARACTER SET utf8mb4;
""")

mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS notifications (
    id INT AUTO_INCREMENT PRIMARY KEY,
    rider_id INT,
    message TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
CHARACTER SET utf8mb4;
""")

mysql_cur.execute("""
CREATE TABLE IF NOT EXISTS api_keys (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255),
    token VARCHAR(255) UNIQUE NOT NULL,
    user_id INT,
    active TINYINT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
CHARACTER SET utf8mb4;
""")

mysql_conn.commit()

print('Copying customers...')
for row in sqlite_cur.execute('SELECT id, name, email, phone, address, created_at, updated_at FROM customers').fetchall():
    mysql_cur.execute(
        'INSERT INTO customers (id, name, email, phone, address, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), email=VALUES(email), phone=VALUES(phone), address=VALUES(address), created_at=VALUES(created_at), updated_at=VALUES(updated_at)'
        ,(row['id'], row['name'], row['email'], row['phone'], row['address'], row['created_at'], row['updated_at'])
    )

print('Copying orders...')
for row in sqlite_cur.execute('SELECT id, customer_id, status, pickup_date, pickup_time, payment_method, total_amount, source, notes, created_at, updated_at, delivery_method, rider_id FROM orders').fetchall():
    mysql_cur.execute(
        'INSERT INTO orders (id, customer_id, status, pickup_date, pickup_time, payment_method, total_amount, source, notes, created_at, updated_at, delivery_method, rider_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE customer_id=VALUES(customer_id), status=VALUES(status), pickup_date=VALUES(pickup_date), pickup_time=VALUES(pickup_time), payment_method=VALUES(payment_method), total_amount=VALUES(total_amount), source=VALUES(source), notes=VALUES(notes), created_at=VALUES(created_at), updated_at=VALUES(updated_at), delivery_method=VALUES(delivery_method), rider_id=VALUES(rider_id)'
        ,(row['id'], row['customer_id'], row['status'], row['pickup_date'], row['pickup_time'], row['payment_method'], row['total_amount'], row['source'], row['notes'], row['created_at'], row['updated_at'], row.get('delivery_method') if isinstance(row, dict) else row[10], row.get('rider_id') if isinstance(row, dict) else None)
    )

print('Copying order_items...')
for row in sqlite_cur.execute('SELECT id, order_id, item_id, quantity, unit_price, subtotal FROM order_items').fetchall():
    mysql_cur.execute(
        'INSERT INTO order_items (id, order_id, item_id, quantity, unit_price, subtotal) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE order_id=VALUES(order_id), item_id=VALUES(item_id), quantity=VALUES(quantity), unit_price=VALUES(unit_price), subtotal=VALUES(subtotal)'
        ,(row['id'], row['order_id'], row['item_id'], row['quantity'], row['unit_price'], row['subtotal'])
    )

print('Copying riders...')
# Ensure MySQL `riders` table has expected columns (in case an older schema exists)
mysql_cur.execute("SHOW COLUMNS FROM riders LIKE 'email'")
if not mysql_cur.fetchall():
    try:
        mysql_cur.execute("ALTER TABLE riders ADD COLUMN email VARCHAR(255) NULL")
    except Exception:
        pass
mysql_cur.execute("SHOW COLUMNS FROM riders LIKE 'username'")
if not mysql_cur.fetchall():
    try:
        mysql_cur.execute("ALTER TABLE riders ADD COLUMN username VARCHAR(255) NULL")
    except Exception:
        pass
mysql_cur.execute("SHOW COLUMNS FROM riders LIKE 'password'")
if not mysql_cur.fetchall():
    try:
        mysql_cur.execute("ALTER TABLE riders ADD COLUMN password VARCHAR(255) NULL")
    except Exception:
        pass

for row in sqlite_cur.execute('SELECT id, name, phone, email, username, password, active, created_at FROM riders').fetchall():
    mysql_cur.execute(
        'INSERT INTO riders (id, name, phone, email, username, password, active, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), phone=VALUES(phone), email=VALUES(email), username=VALUES(username), password=VALUES(password), active=VALUES(active), created_at=VALUES(created_at)'
        ,(row['id'], row['name'], row.get('phone') if isinstance(row, dict) else row[2], row.get('email') if isinstance(row, dict) else None, row.get('username') if isinstance(row, dict) else None, row.get('password') if isinstance(row, dict) else None, row.get('active') if isinstance(row, dict) else 1, row.get('created_at') if isinstance(row, dict) else None)
    )

print('Copying notifications...')
for row in sqlite_cur.execute('SELECT id, rider_id, message, created_at FROM notifications').fetchall():
    mysql_cur.execute(
        'INSERT INTO notifications (id, rider_id, message, created_at) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE rider_id=VALUES(rider_id), message=VALUES(message), created_at=VALUES(created_at)'
        ,(row['id'], row['rider_id'], row['message'], row['created_at'])
    )

print('Copying api_keys...')
for row in sqlite_cur.execute('SELECT id, name, token, user_id, active, created_at FROM api_keys').fetchall():
    mysql_cur.execute(
        'INSERT INTO api_keys (id, name, token, user_id, active, created_at) VALUES (%s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), token=VALUES(token), user_id=VALUES(user_id), active=VALUES(active), created_at=VALUES(created_at)'
        ,(row['id'], row['name'], row['token'], row['user_id'], row['active'], row['created_at'])
    )

mysql_conn.commit()

print('Done. Data migrated.')

sqlite_conn.close()
mysql_conn.close()
