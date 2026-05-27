#!/usr/bin/env python3
"""Manage helper: initialize DB and create admin user."""
from app import init_db, hash_pw, get_db
import sqlite3
import os

def create_admin(username='admin', email='admin@rellosas.com', password='admin123'):
    init_db()
    pw = hash_pw(password)
    with get_db() as db:
        try:
            db.execute("INSERT INTO users (username,email,password) VALUES (?,?,?)", (username, email, pw))
            print('Admin user created or already exists.')
        except Exception as e:
            print('Could not create admin:', e)

if __name__ == '__main__':
    print('Initializing DB...')
    init_db()
    create_admin()
    print('Done.')
