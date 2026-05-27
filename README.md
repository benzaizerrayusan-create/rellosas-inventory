# 🛒 Rellosas Shop — Inventory Management System

A blue-themed, full-featured inventory management web app built with Flask + SQLite.

## Project Structure
```
rellosas_shop/
├── app.py                  # Flask backend + routes
├── inventory.db            # SQLite database (auto-created)
├── requirements.txt
├── templates/
│   ├── base.html           # Shared layout with sidebar
│   ├── auth_base.html      # Auth page layout
│   ├── login.html
│   ├── signup.html
│   ├── forgot_password.html
│   ├── reset_password.html
│   ├── dashboard.html
│   ├── inventory.html
│   ├── add_item.html
│   └── edit_item.html
└── static/
    ├── css/style.css
    └── js/main.js
```

## Setup & Run

### For Local Network (same Wi-Fi)
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run with SQLite (Windows)
START_APP_SQLITE.bat

# 2. Run with SQLite (Mac/Linux)
python app.py

# 3. Open in browser
http://localhost:5000
```

On another device on the same Wi-Fi, use your PC's IP:
```
http://192.168.1.10:5000  (replace with your actual IP)
```

### For Remote Access (different network, mobile, customers)
**Option 1: ngrok (Recommended - easiest)**

1. Run the setup helper:
   ```
   START_APP_SETUP.bat
   ```
   This will guide you through the process.

2. If ngrok is not installed yet:
   - Download from https://ngrok.com/download
   - Extract and add to PATH, or place `ngrok.exe` in this folder
   - Run `START_APP_SETUP.bat` again

3. Once ngrok is running, you'll see a public URL like:
   ```
   https://xxxxxx.ngrok.io
   ```

4. Share this URL with customers (e.g., `https://xxxxxx.ngrok.io/customer-order`)

**Option 2: Manual ngrok**
```bash
# Make sure ngrok is installed
ngrok http 5000

# Then in another terminal, run:
python app.py
```

**Option 3: Cloud hosting (permanent)**
Deploy to Heroku, Render, PythonAnywhere, or similar for a permanent public URL.

### XAMPP / MySQL

1. Start XAMPP and enable Apache + MySQL.
2. Create a database named `inventory_db` in phpMyAdmin, or use the database name configured in `START_APP_MYSQL.bat`.
3. Run `START_APP_MYSQL.bat` to start the app in MySQL mode.

## Default Login
- **Username:** admin
- **Password:** admin123

## Remote Access (different network)
If the phone or customer is not on the same Wi-Fi, you need a public tunnel or hosted deployment.

### Recommended: ngrok
1. Install ngrok from https://ngrok.com/download
2. Run `START_APP_NGROK.bat`
3. ngrok will open a public URL like `https://xxxxxx.ngrok.io`
4. Share the ngrok URL with anyone, from any network

> If ngrok is running and the app detects it, the public order link will also show automatically on the login page.

## Features
- 🔐 Auth: Sign in, Sign up, Sign out, Forgot/Reset password
- 📦 Inventory: Add, Edit, Delete items
- ⚡ Quick stock adjust (+1 / -1 / +10 / -10) via AJAX
- 🏷️ Categories: Plastic Ware, Sugar, Cups, Flour, Rice, Condiments, Juices
- 🍚 Rice & Flour subtypes (Sinandomeng, Jasmine, Dinorado, etc.)
- 🔍 Search + category filter + sort
- 👥 Customer management: create, view, edit, delete records
- ⚠️ Low stock alerts with configurable threshold
- 💰 All prices in Philippine Pesos (₱)
- 🌙 Light/Dark mode toggle (remembers preference)
- 📱 Fully responsive (mobile + desktop)
- 💡 Contextual quick guides on every page
