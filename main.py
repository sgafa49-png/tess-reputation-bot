import os
import re
import sys
import sqlite3
import uuid
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    CallbackContext,
    MessageHandler,
    filters
)

# ========== НАСТРОЙКИ СРЕДЫ ==========
def is_railway():
    """Проверяем что мы на Railway"""
    db_url = os.environ.get('DATABASE_URL', '')
    return 'railway.app' in db_url and db_url.startswith('postgresql://')

def is_replit():
    """Проверяем, запущены ли на Replit"""
    return 'REPL_ID' in os.environ

# Очистка переменных если на Replit
if is_replit():
    os.environ.pop('DATABASE_URL', None)
    os.environ.pop('RAILWAY_ENVIRONMENT', None)
    print("Очищены Railway переменные (Replit режим)")

# Получаем токен
TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    print("ОШИБКА: TELEGRAM_TOKEN не найден!")
    sys.exit(1)

# Гарант (ваш аккаунт)
GUARANTOR_USERNAME = "prade146"

# ========== БАЗА ДАННЫХ (УНИВЕРСАЛЬНАЯ) ==========
def get_db_connection():
    """Возвращает соединение с БД в зависимости от платформы"""
    if is_railway():
        try:
            import psycopg2
            DATABASE_URL = os.environ.get('DATABASE_URL')
            if DATABASE_URL:
                conn = psycopg2.connect(DATABASE_URL, sslmode='require')
                print("Подключено к PostgreSQL (Railway)")
                return conn
        except Exception as e:
            print(f"Ошибка PostgreSQL: {e}")
    
    # На Replit или при ошибке - используем SQLite
    conn = sqlite3.connect('reputation.db')
    print("Подключено к SQLite (Replit/Локально)")
    return conn

def init_db():
    """Инициализация базы данных для обеих платформ"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if is_railway():
        # PostgreSQL для Railway
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    registered_at TEXT,
                    payment_details TEXT,
                    payment_method VARCHAR(50)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reputation (
                    id SERIAL PRIMARY KEY,
                    from_user BIGINT,
                    to_user BIGINT,
                    text TEXT,
                    photo_id TEXT,
                    created_at TEXT
                )
            ''')
            
            # Таблицы для сделок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS deals (
                    id SERIAL PRIMARY KEY,
                    deal_uuid VARCHAR(36) UNIQUE,
                    buyer_id BIGINT,
                    seller_id BIGINT,
                    amount DECIMAL(10,2),
                    currency VARCHAR(10) DEFAULT 'RUB',
                    description TEXT,
                    status VARCHAR(30) DEFAULT 'created',
                    buyer_paid BOOLEAN DEFAULT FALSE,
                    guarantor_confirmed BOOLEAN DEFAULT FALSE,
                    buyer_done BOOLEAN DEFAULT FALSE,
                    seller_done BOOLEAN DEFAULT FALSE,
                    guarantor_paid BOOLEAN DEFAULT FALSE,
                    guarantor_username VARCHAR(100) DEFAULT 'prade146',
                    payment_transaction_id VARCHAR(100),
                    payment_proof TEXT,
                    chat_message_id BIGINT,
                    created_at TIMESTAMP,
                    expires_at TIMESTAMP,
                    completed_at TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS deal_messages (
                    id SERIAL PRIMARY KEY,
                    deal_id INTEGER,
                    user_id BIGINT,
                    username VARCHAR(100),
                    message TEXT,
                    is_system BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS guarantor_notifications (
                    id SERIAL PRIMARY KEY,
                    deal_id INTEGER,
                    notification_type VARCHAR(50),
                    message TEXT,
                    created_at TIMESTAMP,
                    processed BOOLEAN DEFAULT FALSE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payment_requests (
                    id SERIAL PRIMARY KEY,
                    deal_id INTEGER,
                    seller_id BIGINT,
                    amount DECIMAL(10,2),
                    currency VARCHAR(10),
                    payment_details TEXT,
                    status VARCHAR(20) DEFAULT 'pending',
                    transaction_id VARCHAR(100),
                    proof_image_id TEXT,
                    created_at TIMESTAMP,
                    paid_at TIMESTAMP
                )
            ''')
            
        except Exception as e:
            print(f"Ошибка создания таблиц PostgreSQL: {e}")
    else:
        # SQLite для Replit
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                registered_at TEXT,
                payment_details TEXT,
                payment_method TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reputation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_user INTEGER,
                to_user INTEGER,
                text TEXT,
                photo_id TEXT,
                created_at TEXT
            )
        ''')
        
        # Таблицы для сделок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_uuid TEXT UNIQUE,
                buyer_id INTEGER,
                seller_id INTEGER,
                amount REAL,
                currency TEXT DEFAULT 'RUB',
                description TEXT,
                status TEXT DEFAULT 'created',
                buyer_paid INTEGER DEFAULT 0,
                guarantor_confirmed INTEGER DEFAULT 0,
                buyer_done INTEGER DEFAULT 0,
                seller_done INTEGER DEFAULT 0,
                guarantor_paid INTEGER DEFAULT 0,
                guarantor_username TEXT DEFAULT 'prade146',
                payment_transaction_id TEXT,
                payment_proof TEXT,
                chat_message_id INTEGER,
                created_at TEXT,
                expires_at TEXT,
                completed_at TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deal_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id INTEGER,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                is_system INTEGER DEFAULT 0,
                created_at TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guarantor_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id INTEGER,
                notification_type TEXT,
                message TEXT,
                created_at TEXT,
                processed INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id INTEGER,
                seller_id INTEGER,
                amount REAL,
                currency TEXT,
                payment_details TEXT,
                status TEXT DEFAULT 'pending',
                transaction_id TEXT,
                proof_image_id TEXT,
                created_at TEXT,
                paid_at TEXT
            )
        ''')
    
    conn.commit()
    conn.close()
    print("База данных инициализирована (включая систему выплат)")

# ========== ФУНКЦИИ БАЗЫ ДАННЫХ ==========
def save_user(user_id, username, payment_details=None, payment_method=None):
    """Сохраняем пользователя в БД"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('''
                INSERT INTO users (user_id, username, registered_at, payment_details, payment_method) 
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE 
                SET username = EXCLUDED.username,
                    payment_details = COALESCE(EXCLUDED.payment_details, users.payment_details),
                    payment_method = COALESCE(EXCLUDED.payment_method, users.payment_method)
            ''', (user_id, username, datetime.now().isoformat(), payment_details, payment_method))
        else:
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            existing = cursor.fetchone()
            
            if not existing:
                cursor.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?)',
                              (user_id, username, datetime.now().isoformat(), payment_details, payment_method))
            else:
                update_fields = []
                params = []
                
                if username != existing[1]:
                    update_fields.append("username = ?")
                    params.append(username)
                
                if payment_details is not None:
                    update_fields.append("payment_details = ?")
                    params.append(payment_details)
                
                if payment_method is not None:
                    update_fields.append("payment_method = ?")
                    params.append(payment_method)
                
                if update_fields:
                    update_query = f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = ?"
                    params.append(user_id)
                    cursor.execute(update_query, params)
        
        conn.commit()
    except Exception as e:
        print(f"Ошибка сохранения пользователя {user_id}: {e}")
    finally:
        conn.close()

def get_user_payment_details(user_id):
    """Получить платежные реквизиты пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('SELECT payment_details, payment_method FROM users WHERE user_id = %s', (user_id,))
        else:
            cursor.execute('SELECT payment_details, payment_method FROM users WHERE user_id = ?', (user_id,))
        
        row = cursor.fetchone()
        if row and row[0]:
            return {
                'details': row[0],
                'method': row[1] or 'Не указан'
            }
        return None
    except Exception as e:
        print(f"Ошибка получения реквизитов пользователя {user_id}: {e}")
        return None
    finally:
        conn.close()

def save_reputation(from_user, from_username, to_user, to_username, text, photo_id):
    """Сохраняем репутацию в БД"""
    save_user(from_user, from_username)
    save_user(to_user, to_username)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('''
                INSERT INTO reputation (from_user, to_user, text, photo_id, created_at)
                VALUES (%s, %s, %s, %s, %s)
            ''', (from_user, to_user, text, photo_id, datetime.now().isoformat()))
        else:
            cursor.execute('''
                INSERT INTO reputation (from_user, to_user, text, photo_id, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (from_user, to_user, text, photo_id, datetime.now().isoformat()))
        
        conn.commit()
    except Exception as e:
        print(f"Ошибка сохранения репутации: {e}")
    finally:
        conn.close()

def get_user_reputation(user_id):
    """Получаем всю репутацию пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    reps = []
    try:
        if is_railway():
            cursor.execute('''
                SELECT r.*, u.username as from_username 
                FROM reputation r
                LEFT JOIN users u ON r.from_user = u.user_id
                WHERE r.to_user = %s
                ORDER BY r.created_at DESC
            ''', (user_id,))
        else:
            cursor.execute('''
                SELECT r.*, u.username as from_username 
                FROM reputation r
                LEFT JOIN users u ON r.from_user = u.user_id
                WHERE r.to_user = ?
                ORDER BY r.created_at DESC
            ''', (user_id,))
        
        rows = cursor.fetchall()
        
        for row in rows:
            reps.append({
                'id': row[0],
                'from_user': row[1],
                'to_user': row[2],
                'text': row[3],
                'photo_id': row[4],
                'created_at': row[5],
                'from_username': row[6] or f"id{row[1]}"
            })
    except Exception as e:
        print(f"Ошибка получения репутации: {e}")
    finally:
        conn.close()
    
    return reps

def get_user_info(user_id):
    """Получаем информацию о пользователе"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        else:
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        
        row = cursor.fetchone()
        
        if row:
            return {
                'user_id': row[0],
                'username': row[1],
                'registered_at': row[2],
                'payment_details': row[3],
                'payment_method': row[4]
            }
    except Exception as e:
        print(f"Ошибка получения пользователя {user_id}: {e}")
    finally:
        conn.close()
    
    return None

def get_user_by_username(username):
    """Ищем пользователя по username"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    username = username.lstrip('@')
    
    try:
        if is_railway():
            cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        else:
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        
        row = cursor.fetchone()
        
        if row:
            return {
                'user_id': row[0],
                'username': row[1],
                'registered_at': row[2],
                'payment_details': row[3],
                'payment_method': row[4]
            }
    except Exception as e:
        print(f"Ошибка поиска пользователя {username}: {e}")
    finally:
        conn.close()
    
    return None

def get_reputation_stats(user_id):
    """Статистика репутации пользователя"""
    all_reps = get_user_reputation(user_id)
    
    positive = 0
    negative = 0
    
    for rep in all_reps:
        text_lower = rep["text"].lower()
        if text_lower.startswith(('+rep', '+реп')):
            positive += 1
        elif text_lower.startswith(('-rep', '-реп')):
            negative += 1
    
    total = positive + negative
    positive_percent = (positive / total * 100) if total > 0 else 0
    negative_percent = (negative / total * 100) if total > 0 else 0
    
    return {
        'total': total,
        'positive': positive,
        'negative': negative,
        'positive_percent': positive_percent,
        'negative_percent': negative_percent,
        'all_reps': all_reps
    }

def get_last_positive(user_id):
    """Получить последний положительный отзыв"""
    all_reps = get_user_reputation(user_id)
    for rep in all_reps:
        if rep["text"].lower().startswith(('+rep', '+реп')):
            return rep
    return None

def get_last_negative(user_id):
    """Получить последний отрицательный отзыв"""
    all_reps = get_user_reputation(user_id)
    for rep in all_reps:
        if rep["text"].lower().startswith(('-rep', '-реп')):
            return rep
    return None

# ========== ФУНКЦИИ СДЕЛОК И ВЫПЛАТ ==========
def create_deal(buyer_id, seller_id, amount, description, currency='RUB'):
    """Создать новую сделку"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    deal_uuid = str(uuid.uuid4())
    created_at = datetime.now()
    expires_at = created_at + timedelta(hours=48)
    
    try:
        if is_railway():
            cursor.execute('''
                INSERT INTO deals (deal_uuid, buyer_id, seller_id, amount, currency, description, 
                                 status, created_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'created', %s, %s)
                RETURNING id
            ''', (deal_uuid, buyer_id, seller_id, amount, currency, description, created_at, expires_at))
            deal_id = cursor.fetchone()[0]
        else:
            cursor.execute('''
                INSERT INTO deals (deal_uuid, buyer_id, seller_id, amount, currency, description, 
                                 status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, 'created', ?, ?)
            ''', (deal_uuid, buyer_id, seller_id, amount, currency, description, created_at.isoformat(), expires_at.isoformat()))
            deal_id = cursor.lastrowid
        
        conn.commit()
        return deal_id
    except Exception as e:
        print(f"Ошибка создания сделки: {e}")
        return None
    finally:
        conn.close()

def get_deal(deal_id):
    """Получить информацию о сделке"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('SELECT * FROM deals WHERE id = %s', (deal_id,))
        else:
            cursor.execute('SELECT * FROM deals WHERE id = ?', (deal_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        # Определяем структуру в зависимости от БД
        if is_railway():
            deal = {
                'id': row[0],
                'deal_uuid': row[1],
                'buyer_id': row[2],
                'seller_id': row[3],
                'amount': row[4],
                'currency': row[5],
                'description': row[6],
                'status': row[7],
                'buyer_paid': row[8],
                'guarantor_confirmed': row[9],
                'buyer_done': row[10],
                'seller_done': row[11],
                'guarantor_paid': row[12],
                'guarantor_username': row[13],
                'payment_transaction_id': row[14],
                'payment_proof': row[15],
                'chat_message_id': row[16],
                'created_at': row[17],
                'expires_at': row[18],
                'completed_at': row[19]
            }
        else:
            deal = {
                'id': row[0],
                'deal_uuid': row[1],
                'buyer_id': row[2],
                'seller_id': row[3],
                'amount': row[4],
                'currency': row[5],
                'description': row[6],
                'status': row[7],
                'buyer_paid': bool(row[8]),
                'guarantor_confirmed': bool(row[9]),
                'buyer_done': bool(row[10]),
                'seller_done': bool(row[11]),
                'guarantor_paid': bool(row[12]),
                'guarantor_username': row[13],
                'payment_transaction_id': row[14],
                'payment_proof': row[15],
                'chat_message_id': row[16],
                'created_at': datetime.fromisoformat(row[17]) if row[17] else None,
                'expires_at': datetime.fromisoformat(row[18]) if row[18] else None,
                'completed_at': datetime.fromisoformat(row[19]) if row[19] else None
            }
        
        return deal
    except Exception as e:
        print(f"Ошибка получения сделки {deal_id}: {e}")
        return None
    finally:
        conn.close()

def update_deal_status(deal_id, status, **kwargs):
    """Обновить статус сделки"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            query = "UPDATE deals SET status = %s"
            params = [status]
            
            for key, value in kwargs.items():
                query += f", {key} = %s"
                params.append(value)
            
            query += " WHERE id = %s"
            params.append(deal_id)
            
            cursor.execute(query, params)
        else:
            query = "UPDATE deals SET status = ?"
            params = [status]
            
            for key, value in kwargs.items():
                query += f", {key} = ?"
                params.append(value)
            
            query += " WHERE id = ?"
            params.append(deal_id)
            
            cursor.execute(query, params)
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка обновления сделки {deal_id}: {e}")
        return False
    finally:
        conn.close()

def create_payment_request(deal_id, seller_id, amount, currency, payment_details):
    """Создать запрос на выплату"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('''
                INSERT INTO payment_requests (deal_id, seller_id, amount, currency, payment_details, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (deal_id, seller_id, amount, currency, payment_details, datetime.now()))
            request_id = cursor.fetchone()[0]
        else:
            cursor.execute('''
                INSERT INTO payment_requests (deal_id, seller_id, amount, currency, payment_details, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (deal_id, seller_id, amount, currency, payment_details, datetime.now().isoformat()))
            request_id = cursor.lastrowid
        
        conn.commit()
        return request_id
    except Exception as e:
        print(f"Ошибка создания запроса на выплату: {e}")
        return None
    finally:
        conn.close()

def update_payment_request(request_id, transaction_id=None, proof_image_id=None, status='paid'):
    """Обновить запрос на выплату"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('''
                UPDATE payment_requests 
                SET status = %s, 
                    transaction_id = COALESCE(%s, transaction_id),
                    proof_image_id = COALESCE(%s, proof_image_id),
                    paid_at = CASE WHEN %s = 'paid' THEN %s ELSE paid_at END
                WHERE id = %s
            ''', (status, transaction_id, proof_image_id, status, datetime.now(), request_id))
        else:
            cursor.execute('''
                UPDATE payment_requests 
                SET status = ?,
                    transaction_id = COALESCE(?, transaction_id),
                    proof_image_id = COALESCE(?, proof_image_id),
                    paid_at = CASE WHEN ? = 'paid' THEN ? ELSE paid_at END
                WHERE id = ?
            ''', (status, transaction_id, proof_image_id, status, datetime.now().isoformat(), request_id))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка обновления запроса на выплату: {e}")
        return False
    finally:
        conn.close()

def get_payment_request_by_deal(deal_id):
    """Получить запрос на выплату по ID сделки"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('SELECT * FROM payment_requests WHERE deal_id = %s ORDER BY id DESC LIMIT 1', (deal_id,))
        else:
            cursor.execute('SELECT * FROM payment_requests WHERE deal_id = ? ORDER BY id DESC LIMIT 1', (deal_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        if is_railway():
            request = {
                'id': row[0],
                'deal_id': row[1],
                'seller_id': row[2],
                'amount': row[3],
                'currency': row[4],
                'payment_details': row[5],
                'status': row[6],
                'transaction_id': row[7],
                'proof_image_id': row[8],
                'created_at': row[9],
                'paid_at': row[10]
            }
        else:
            request = {
                'id': row[0],
                'deal_id': row[1],
                'seller_id': row[2],
                'amount': row[3],
                'currency': row[4],
                'payment_details': row[5],
                'status': row[6],
                'transaction_id': row[7],
                'proof_image_id': row[8],
                'created_at': datetime.fromisoformat(row[9]) if row[9] else None,
                'paid_at': datetime.fromisoformat(row[10]) if row[10] else None
            }
        
        return request
    except Exception as e:
        print(f"Ошибка получения запроса на выплату: {e}")
        return None
    finally:
        conn.close()

def add_deal_message(deal_id, user_id, username, message, is_system=False):
    """Добавить сообщение в чат сделки"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('''
                INSERT INTO deal_messages (deal_id, user_id, username, message, is_system, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (deal_id, user_id, username, message, is_system, datetime.now()))
        else:
            cursor.execute('''
                INSERT INTO deal_messages (deal_id, user_id, username, message, is_system, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (deal_id, user_id, username, message, 1 if is_system else 0, datetime.now().isoformat()))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка добавления сообщения в сделку {deal_id}: {e}")
        return False
    finally:
        conn.close()

def get_deal_messages(deal_id, limit=50):
    """Получить сообщения из чата сделки"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    messages = []
    try:
        if is_railway():
            cursor.execute('''
                SELECT * FROM deal_messages 
                WHERE deal_id = %s 
                ORDER BY created_at DESC 
                LIMIT %s
            ''', (deal_id, limit))
        else:
            cursor.execute('''
                SELECT * FROM deal_messages 
                WHERE deal_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (deal_id, limit))
        
        rows = cursor.fetchall()
        rows.reverse()  # Чтоб в хронологическом порядке
        
        for row in rows:
            if is_railway():
                messages.append({
                    'id': row[0],
                    'deal_id': row[1],
                    'user_id': row[2],
                    'username': row[3],
                    'message': row[4],
                    'is_system': row[5],
                    'created_at': row[6]
                })
            else:
                messages.append({
                    'id': row[0],
                    'deal_id': row[1],
                    'user_id': row[2],
                    'username': row[3],
                    'message': row[4],
                    'is_system': bool(row[5]),
                    'created_at': datetime.fromisoformat(row[6]) if row[6] else None
                })
        
        return messages
    except Exception as e:
        print(f"Ошибка получения сообщений сделки {deal_id}: {e}")
        return []
    finally:
        conn.close()

def notify_guarantor(deal_id, notification_type, message):
    """Отправить уведомление гаранту"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            cursor.execute('''
                INSERT INTO guarantor_notifications (deal_id, notification_type, message, created_at)
                VALUES (%s, %s, %s, %s)
            ''', (deal_id, notification_type, message, datetime.now()))
        else:
            cursor.execute('''
                INSERT INTO guarantor_notifications (deal_id, notification_type, message, created_at)
                VALUES (?, ?, ?, ?)
            ''', (deal_id, notification_type, message, datetime.now().isoformat()))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка уведомления гаранта: {e}")
        return False
    finally:
        conn.close()

def get_user_deals(user_id, limit=10):
    """Получить сделки пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    deals = []
    try:
        if is_railway():
            cursor.execute('''
                SELECT * FROM deals 
                WHERE (buyer_id = %s OR seller_id = %s)
                ORDER BY created_at DESC 
                LIMIT %s
            ''', (user_id, user_id, limit))
        else:
            cursor.execute('''
                SELECT * FROM deals 
                WHERE (buyer_id = ? OR seller_id = ?)
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (user_id, user_id, limit))
        
        rows = cursor.fetchall()
        
        for row in rows:
            if is_railway():
                deal = {
                    'id': row[0],
                    'deal_uuid': row[1],
                    'buyer_id': row[2],
                    'seller_id': row[3],
                    'amount': row[4],
                    'currency': row[5],
                    'description': row[6],
                    'status': row[7],
                    'buyer_paid': row[8],
                    'guarantor_confirmed': row[9],
                    'buyer_done': row[10],
                    'seller_done': row[11],
                    'guarantor_paid': row[12],
                    'guarantor_username': row[13],
                    'payment_transaction_id': row[14],
                    'payment_proof': row[15],
                    'chat_message_id': row[16],
                    'created_at': row[17],
                    'expires_at': row[18],
                    'completed_at': row[19]
                }
            else:
                deal = {
                    'id': row[0],
                    'deal_uuid': row[1],
                    'buyer_id': row[2],
                    'seller_id': row[3],
                    'amount': row[4],
                    'currency': row[5],
                    'description': row[6],
                    'status': row[7],
                    'buyer_paid': bool(row[8]),
                    'guarantor_confirmed': bool(row[9]),
                    'buyer_done': bool(row[10]),
                    'seller_done': bool(row[11]),
                    'guarantor_paid': bool(row[12]),
                    'guarantor_username': row[13],
                    'payment_transaction_id': row[14],
                    'payment_proof': row[15],
                    'chat_message_id': row[16],
                    'created_at': datetime.fromisoformat(row[17]) if row[17] else None,
                    'expires_at': datetime.fromisoformat(row[18]) if row[18] else None,
                    'completed_at': datetime.fromisoformat(row[19]) if row[19] else None
                }
            deals.append(deal)
        
        return deals
    except Exception as e:
        print(f"Ошибка получения сделок пользователя {user_id}: {e}")
        return []
    finally:
        conn.close()

# ========== КНОПКИ ДЛЯ СДЕЛОК ==========
def get_deal_keyboard(deal_id, user_id, deal):
    """Получить клавиатуру для сделки в зависимости от роли и статуса"""
    keyboard = []
    user_role = 'buyer' if user_id == deal['buyer_id'] else 'seller' if user_id == deal['seller_id'] else 'guarantor' if str(user_id) == GUARANTOR_USERNAME else 'viewer'
    
    status = deal['status']
    buyer_paid = deal['buyer_paid']
    guarantor_confirmed = deal['guarantor_confirmed']
    buyer_done = deal['buyer_done']
    seller_done = deal['seller_done']
    guarantor_paid = deal['guarantor_paid']
    
    # Кнопки для покупателя
    if user_role == 'buyer':
        if status == 'created':
            keyboard.append([
                InlineKeyboardButton("❌ Отменить сделку", callback_data=f'deal_cancel_{deal_id}')
            ])
        
        elif status == 'accepted':
            keyboard.append([
                InlineKeyboardButton("💰 Перевести гаранту", url=f"https://t.me/{GUARANTOR_USERNAME}"),
                InlineKeyboardButton("✅ Я перевел", callback_data=f'deal_paid_{deal_id}')
            ])
            keyboard.append([
                InlineKeyboardButton("❌ Отменить сделку", callback_data=f'deal_cancel_{deal_id}')
            ])
        
        elif status == 'payment_confirmed':
            keyboard.append([
                InlineKeyboardButton("✅ Я получил товар", callback_data=f'deal_buyer_done_{deal_id}'),
                InlineKeyboardButton("💬 Чат сделки", callback_data=f'deal_chat_{deal_id}')
            ])
            
            if buyer_done:
                keyboard.append([
                    InlineKeyboardButton("⏳ Ожидание продавца", callback_data=f'deal_waiting_{deal_id}')
                ])
    
    # Кнопки для продавца
    elif user_role == 'seller':
        if status == 'created':
            keyboard.append([
                InlineKeyboardButton("✅ Принять сделку", callback_data=f'deal_accept_{deal_id}'),
                InlineKeyboardButton("❌ Отклонить", callback_data=f'deal_reject_{deal_id}')
            ])
        
        elif status in ['accepted', 'payment_confirmed']:
            keyboard.append([
                InlineKeyboardButton("✅ Я отправил товар", callback_data=f'deal_seller_done_{deal_id}'),
                InlineKeyboardButton("💬 Чат сделки", callback_data=f'deal_chat_{deal_id}')
            ])
            
            if seller_done:
                keyboard.append([
                    InlineKeyboardButton("⏳ Ожидание покупателя", callback_data=f'deal_waiting_{deal_id}')
                ])
    
    # Кнопки для гаранта
    elif user_role == 'guarantor':
        if status == 'accepted' and buyer_paid and not guarantor_confirmed:
            keyboard.append([
                InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f'deal_guarantor_confirm_{deal_id}'),
                InlineKeyboardButton("❌ Оплаты нет", callback_data=f'deal_guarantor_reject_{deal_id}')
            ])
        
        elif status == 'payment_confirmed' and buyer_done and seller_done and not guarantor_paid:
            keyboard.append([
                InlineKeyboardButton("💸 Выплатить продавцу", callback_data=f'deal_payment_request_{deal_id}'),
                InlineKeyboardButton("⚖️ Открыть спор", callback_data=f'deal_dispute_{deal_id}')
            ])
        
        elif guarantor_paid:
            keyboard.append([
                InlineKeyboardButton("✅ Выплата завершена", callback_data=f'deal_payment_done_{deal_id}')
            ])
        
        keyboard.append([
            InlineKeyboardButton("📊 Детали сделки", callback_data=f'deal_details_{deal_id}'),
            InlineKeyboardButton("💬 Чат сделки", callback_data=f'deal_chat_{deal_id}')
        ])
    
    # Кнопки для просмотра (другие пользователи)
    else:
        keyboard.append([
            InlineKeyboardButton("👀 Только просмотр", callback_data=f'deal_view_{deal_id}')
        ])
    
    # Кнопка возврата
    if user_role in ['buyer', 'seller']:
        keyboard.append([
            InlineKeyboardButton("🔙 Мои сделки", callback_data='my_deals')
        ])
    
    return InlineKeyboardMarkup(keyboard)

def get_payment_request_keyboard(deal_id):
    """Клавиатура для запроса на выплату"""
    keyboard = [
        [
            InlineKeyboardButton("✅ Я перевел деньги", callback_data=f'payment_done_{deal_id}'),
            InlineKeyboardButton("📸 Прикрепить скрин", callback_data=f'payment_proof_{deal_id}')
        ],
        [
            InlineKeyboardButton("🔙 Назад к сделке", callback_data=f'deal_view_{deal_id}')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_deal_text(deal):
    """Получить форматированный текст для сделки"""
    buyer_info = get_user_info(deal['buyer_id'])
    seller_info = get_user_info(deal['seller_id'])
    
    buyer_name = f"@{buyer_info['username']}" if buyer_info and buyer_info.get('username') else f"ID: {deal['buyer_id']}"
    seller_name = f"@{seller_info['username']}" if seller_info and seller_info.get('username') else f"ID: {deal['seller_id']}"
    
    # Статусы с иконками
    status_icons = {
        'created': '📝',
        'accepted': '✅',
        'payment_confirmed': '💰',
        'completed': '🏁',
        'disputed': '⚖️',
        'cancelled': '❌'
    }
    
    status_icon = status_icons.get(deal['status'], '🔄')
    
    text = f"""
{status_icon} <b>СДЕЛКА #{deal['id']}</b>
━━━━━━━━━━━━━━━━━━
<b>💰 Сумма:</b> {deal['amount']:,} {deal['currency']}
<b>👤 Покупатель:</b> {buyer_name}
<b>👨‍💼 Продавец:</b> {seller_name}
<b>📦 Товар:</b> {deal['description']}
<b>⏳ Статус:</b> {deal['status'].upper()}
━━━━━━━━━━━━━━━━━━
"""
    
    # Дополнительная информация по статусу
    if deal['buyer_paid']:
        text += f"✅ <b>Покупатель оплатил</b>\n"
    
    if deal['guarantor_confirmed']:
        text += f"🛡️ <b>Гарант подтвердил</b>\n"
    
    if deal['buyer_done']:
        text += f"📦 <b>Покупатель получил товар</b>\n"
    
    if deal['seller_done']:
        text += f"🚚 <b>Продавец отправил товар</b>\n"
    
    if deal['guarantor_paid']:
        text += f"💸 <b>Гарант выплатил продавцу</b>\n"
        if deal['payment_transaction_id']:
            text += f"🔢 <b>ID транзакции:</b> {deal['payment_transaction_id']}\n"
    
    # Время создания
    if deal['created_at']:
        created = deal['created_at'] if isinstance(deal['created_at'], str) else deal['created_at'].strftime("%d.%m.%Y %H:%M")
        text += f"\n<b>📅 Создана:</b> {created}"
    
    return text

# ========== TELEGRAM HANDLERS ==========
async def quick_profile(update: Update, context: CallbackContext) -> None:
    """Быстрый просмотр профиля в чате"""
    user_id = update.effective_user.id
    
    if update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or f"id{target_user_id}"
        save_user(target_user_id, target_username)
        
    elif context.args and len(context.args) > 0:
        arg = context.args[0].strip()
        
        if arg.isdigit():
            target_user_id = int(arg)
            target_username = f"id{target_user_id}"
        else:
            username = arg.lstrip('@')
            user_info = get_user_by_username(username)
            if user_info:
                target_user_id = user_info['user_id']
                target_username = user_info['username'] or f"id{target_user_id}"
            else:
                await update.message.reply_text("❌ <b>Пользователь не найден</b>", parse_mode='HTML')
                return
    else:
        target_user_id = user_id
        target_username = update.effective_user.username or f"id{user_id}"
    
    user_info = get_user_info(target_user_id)
    stats = get_reputation_stats(target_user_id)
    
    display_username = f"👤@{target_username}" if target_username and not target_username.startswith('id') else f"👤{target_username}"
    
    if user_info and user_info.get("registered_at"):
        try:
            reg_date = datetime.fromisoformat(user_info["registered_at"])
            registration_date = reg_date.strftime("%d/%m/%Y")
        except:
            registration_date = datetime.now().strftime("%d/%m/%Y")
    else:
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
    text = f"""{display_username} (ID: {target_user_id})

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote><blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

<b>ВНИМАТЕЛЬНО СМОТРИТЕ ПОЛЕ «О СЕБЕ»</b>

💳 Депозит: отсутствует

🗓️ Зарегистрирован: {registration_date}"""
    
    if update.message.chat.type in ['group', 'supergroup']:
        keyboard = [
            [InlineKeyboardButton("Посмотреть репутацию", url=f"https://t.me/{context.bot.username}?start=view_{target_user_id}")],
            [InlineKeyboardButton("🏆 Купить префикс", url="https://t.me/prade146")]
        ]
    else:
        if target_user_id != user_id:
            context.user_data['found_user_id'] = target_user_id
            keyboard = [
                [InlineKeyboardButton("Посмотреть репутацию", callback_data='view_found_user_reputation')],
                [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
                [InlineKeyboardButton("🤝 Создать сделку", callback_data=f'create_deal_with_{target_user_id}')]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("🏆 Моя репутация", callback_data='my_reputation')],
                [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')],
                [InlineKeyboardButton("🤝 Мои сделки", callback_data='my_deals')]
            ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def start(update: Update, context: CallbackContext) -> None:
    """Команда /start в личных сообщениях"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    
    save_user(user_id, username)
    
    if context.args and context.args[0].startswith('view_'):
        try:
            target_user_id = int(context.args[0].replace('view_', ''))
            await show_profile_deeplink(update, target_user_id, context)
            return
        except:
            pass
    
    if context.args and context.args[0].startswith('deal_'):
        try:
            deal_id = int(context.args[0].replace('deal_', ''))
            deal = get_deal(deal_id)
            if deal:
                await show_deal_to_user(update, deal_id, user_id, context)
                return
        except:
            pass
    
    text = f"""<b>🛡️ TESS | Репутация — твоя гарантия безопасности!</b>
ID - [{user_id}]

• Здесь можно отправить или просмотреть репутацию пользователя, а также провести сделку! Выберите раздел:"""
    
    keyboard = [
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🔎 Найти пользователя", callback_data='search_user')],
        [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')],
        [InlineKeyboardButton("🤝 Мои сделки", callback_data='my_deals')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_profile_deeplink(update: Update, target_user_id: int, context: CallbackContext):
    """Показать профиль при переходе из чата"""
    user_id = update.effective_user.id
    user_info = get_user_info(target_user_id)
    stats = get_reputation_stats(target_user_id)
    
    username = user_info.get("username", "") if user_info else ""
    display_username = f"👤@{username}" if username else f"👤id{target_user_id}"
    
    if user_info and user_info.get("registered_at"):
        try:
            reg_date = datetime.fromisoformat(user_info["registered_at"])
            registration_date = reg_date.strftime("%d/%m/%Y")
        except:
            registration_date = datetime.now().strftime("%d/%m/%Y")
    else:
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
    text = f"""{display_username} (ID: {target_user_id})

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote><blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

<b>ВНИМАТЕЛЬНО СМОТРИТЕ ПОЛЕ «О СЕБЕ»</b>

💳 Депозит: отсутствует

🗓️ Зарегистрирован: {registration_date}"""
    
    context.user_data['found_user_id'] = target_user_id
    
    keyboard = [
        [InlineKeyboardButton("Посмотреть репутацию", callback_data='view_found_user_reputation')],
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🤝 Создать сделку", callback_data=f'create_deal_with_{target_user_id}')],
        [InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

# ========== ОБРАБОТЧИКИ КНОПОК СДЕЛОК ==========
async def deal_button_handler(update: Update, context: CallbackContext, query, data):
    """Обработчик кнопок сделок"""
    user_id = query.from_user.id
    
    if data == 'my_deals':
        await show_my_deals_menu(query)
    
    elif data.startswith('create_deal_with_'):
        target_user_id = int(data.replace('create_deal_with_', ''))
        context.user_data['deal_target'] = target_user_id
        await ask_deal_amount(query, context)
    
    elif data.startswith('deal_'):
        parts = data.split('_')
        if len(parts) >= 2:
            deal_id = int(parts[-1])
            action = '_'.join(parts[1:-1])
            
            deal = get_deal(deal_id)
            if not deal:
                await query.answer("Сделка не найдена", show_alert=True)
                return
            
            # Определяем роль пользователя
            if user_id == deal['buyer_id']:
                role = 'buyer'
            elif user_id == deal['seller_id']:
                role = 'seller'
            elif str(user_id) == GUARANTOR_USERNAME or (query.from_user.username and query.from_user.username.lower() == GUARANTOR_USERNAME.lower()):
                role = 'guarantor'
            else:
                await query.answer("У вас нет доступа к этой сделке", show_alert=True)
                return
            
            # Обрабатываем действия
            if action == 'accept':
                await accept_deal(query, deal_id, role)
            elif action == 'reject':
                await reject_deal(query, deal_id, role)
            elif action == 'cancel':
                await cancel_deal(query, deal_id, role)
            elif action == 'paid':
                await buyer_paid(query, deal_id, role)
            elif action == 'buyer_done':
                await buyer_done(query, deal_id, role)
            elif action == 'seller_done':
                await seller_done(query, deal_id, role)
            elif action == 'guarantor_confirm':
                await guarantor_confirm(query, deal_id, role)
            elif action == 'guarantor_reject':
                await guarantor_reject(query, deal_id, role)
            elif action == 'payment_request':
                await create_payment_request_handler(query, deal_id, role)
            elif action == 'payment_done':
                await payment_done_handler(query, deal_id, role, context)
            elif action == 'payment_proof':
                await ask_payment_proof(query, deal_id, role, context)
            elif action == 'dispute':
                await open_dispute(query, deal_id, role)
            elif action == 'chat':
                await show_deal_chat(query, deal_id, role)
            elif action == 'details':
                await show_deal_details(query, deal_id, role)
            elif action == 'view':
                await show_deal_view(query, deal_id)

async def show_my_deals_menu(query):
    """Показать меню сделок пользователя"""
    user_id = query.from_user.id
    deals = get_user_deals(user_id, limit=10)
    
    if not deals:
        text = "🤝 <b>Мои сделки</b>\n\nУ вас пока нет сделок."
        keyboard = [[InlineKeyboardButton("🔙 Главное меню", callback_data='back_to_main')]]
    else:
        text = "🤝 <b>Мои сделки</b>\n\nВыберите сделку:"
        keyboard = []
        
        for deal in deals[:5]:  # Показываем первые 5 сделок
            buyer_info = get_user_info(deal['buyer_id'])
            seller_info = get_user_info(deal['seller_id'])
            
            is_buyer = user_id == deal['buyer_id']
            other_user = seller_info if is_buyer else buyer_info
            other_name = f"@{other_user['username']}" if other_user and other_user.get('username') else f"ID: {deal['seller_id' if is_buyer else 'buyer_id']}"
            
            role_icon = "🛒" if is_buyer else "🏪"
            status_icons = {
                'created': '📝',
                'accepted': '✅',
                'payment_confirmed': '💰',
                'completed': '🏁',
                'disputed': '⚖️',
                'cancelled': '❌'
            }
            status_icon = status_icons.get(deal['status'], '🔄')
            
            keyboard.append([
                InlineKeyboardButton(
                    f"{status_icon} #{deal['id']} {role_icon} с {other_name} - {deal['amount']:,} {deal['currency']}",
                    callback_data=f'deal_view_{deal["id"]}'
                )
            ])
        
        if len(deals) > 5:
            keyboard.append([
                InlineKeyboardButton("📋 Показать все сделки", callback_data='show_all_deals')
            ])
        
        keyboard.append([
            InlineKeyboardButton("🔙 Главное меню", callback_data='back_to_main'),
            InlineKeyboardButton("➕ Новая сделка", callback_data='create_deal')
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def ask_deal_amount(query, context):
    """Спросить сумму сделки"""
    text = "💰 <b>Введите сумму сделки (в RUB):</b>"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='my_deals')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    context.user_data['awaiting_deal_amount'] = True

async def create_deal_from_input(update: Update, context: CallbackContext):
    """Создать сделку из введенных данных"""
    user_id = update.effective_user.id
    
    if 'awaiting_deal_amount' in context.user_data:
        try:
            amount = float(update.message.text.replace(',', '.'))
            if amount <= 0:
                await update.message.reply_text("❌ Сумма должна быть больше 0")
                return
            
            context.user_data['deal_amount'] = amount
            context.user_data.pop('awaiting_deal_amount', None)
            
            # Спрашиваем описание
            text = "📝 <b>Введите описание товара/услуги:</b>"
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data='my_deals')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
            context.user_data['awaiting_deal_description'] = True
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат суммы. Введите число (например: 5000)")
    
    elif 'awaiting_deal_description' in context.user_data:
        description = update.message.text.strip()
        if len(description) < 5:
            await update.message.reply_text("❌ Описание слишком короткое")
            return
        
        target_user_id = context.user_data.get('deal_target')
        amount = context.user_data.get('deal_amount')
        
        if not target_user_id or not amount:
            await update.message.reply_text("❌ Ошибка создания сделки")
            return
        
        # Создаем сделку
        deal_id = create_deal(
            buyer_id=user_id,
            seller_id=target_user_id,
            amount=amount,
            description=description
        )
        
        if deal_id:
            deal = get_deal(deal_id)
            
            # Отправляем уведомление продавцу
            seller_info = get_user_info(target_user_id)
            if seller_info:
                try:
                    text = f"🤝 <b>Новая сделка #{deal_id}</b>\n\nПокупатель хочет совершить сделку с вами!"
                    keyboard = [[InlineKeyboardButton("📋 Посмотреть сделку", url=f"https://t.me/{context.bot.username}?start=deal_{deal_id}")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await context.bot.send_message(
                        chat_id=target_user_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode='HTML'
                    )
                except:
                    pass
            
            # Показываем сделку покупателю
            await show_deal_to_user(update, deal_id, user_id, context)
            
            # Очищаем данные
            context.user_data.pop('deal_target', None)
            context.user_data.pop('deal_amount', None)
            context.user_data.pop('awaiting_deal_description', None)
        else:
            await update.message.reply_text("❌ Ошибка создания сделки")

async def show_deal_to_user(update, deal_id, user_id, context):
    """Показать сделку пользователю"""
    deal = get_deal(deal_id)
    if not deal:
        return
    
    text = get_deal_text(deal)
    keyboard = get_deal_keyboard(deal_id, user_id, deal)
    
    if hasattr(update, 'message'):
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')
    elif hasattr(update, 'callback_query'):
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')

async def accept_deal(query, deal_id, role):
    """Продавец принимает сделку"""
    if role != 'seller':
        await query.answer("Только продавец может принять сделку", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'accepted')
    if success:
        deal = get_deal(deal_id)
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", "✅ Продавец принял сделку", True)
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        # Уведомляем покупателя
        buyer_info = get_user_info(deal['buyer_id'])
        if buyer_info:
            try:
                notification = f"✅ Продавец принял вашу сделку #{deal_id}\n\nТеперь переведите деньги гаранту @{GUARANTOR_USERNAME}"
                await query.bot.send_message(chat_id=deal['buyer_id'], text=notification)
            except:
                pass
        
        await query.answer("✅ Сделка принята")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def reject_deal(query, deal_id, role):
    """Продавец отклоняет сделку"""
    if role != 'seller':
        await query.answer("Только продавец может отклонить сделку", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'cancelled', completed_at=datetime.now())
    if success:
        deal = get_deal(deal_id)
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", "❌ Продавец отклонил сделку", True)
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        # Уведомляем покупателя
        buyer_info = get_user_info(deal['buyer_id'])
        if buyer_info:
            try:
                notification = f"❌ Продавец отклонил вашу сделку #{deal_id}"
                await query.bot.send_message(chat_id=deal['buyer_id'], text=notification)
            except:
                pass
        
        await query.answer("❌ Сделка отклонена")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def cancel_deal(query, deal_id, role):
    """Покупатель отменяет сделку"""
    if role not in ['buyer', 'seller']:
        await query.answer("Только участники сделки могут отменить", show_alert=True)
        return
    
    deal = get_deal(deal_id)
    if deal['status'] in ['completed', 'cancelled', 'disputed']:
        await query.answer("Сделка уже завершена", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'cancelled', completed_at=datetime.now())
    if success:
        # Добавляем системное сообщение
        user_name = f"@{query.from_user.username}" if query.from_user.username else f"ID:{query.from_user.id}"
        add_deal_message(deal_id, 0, "Система", f"❌ {user_name} отменил сделку", True)
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        # Уведомляем второго участника
        other_user_id = deal['seller_id'] if role == 'buyer' else deal['buyer_id']
        try:
            notification = f"❌ Другой участник отменил сделку #{deal_id}"
            await query.bot.send_message(chat_id=other_user_id, text=notification)
        except:
            pass
        
        await query.answer("✅ Сделка отменена")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def buyer_paid(query, deal_id, role):
    """Покупатель подтверждает оплату"""
    if role != 'buyer':
        await query.answer("Только покупатель может подтвердить оплату", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'accepted', buyer_paid=True)
    if success:
        deal = get_deal(deal_id)
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", "💰 Покупатель перевел деньги гаранту", True)
        
        # Уведомляем гаранта
        notify_guarantor(deal_id, 'payment_waiting', f"Покупатель утверждает что перевел деньги по сделке #{deal_id}")
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        await query.answer("✅ Ожидайте подтверждения гаранта")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def buyer_done(query, deal_id, role):
    """Покупатель подтверждает получение товара"""
    if role != 'buyer':
        await query.answer("Только покупатель может подтвердить получение", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'payment_confirmed', buyer_done=True)
    if success:
        deal = get_deal(deal_id)
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", "📦 Покупатель подтвердил получение товара", True)
        
        # Проверяем, завершена ли сделка
        if deal['seller_done']:
            success = update_deal_status(deal_id, 'completed', completed_at=datetime.now())
            if success:
                add_deal_message(deal_id, 0, "Система", "🏁 Сделка завершена! Ожидайте выплаты продавцу", True)
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        await query.answer("✅ Подтверждено")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def seller_done(query, deal_id, role):
    """Продавец подтверждает отправку товара"""
    if role != 'seller':
        await query.answer("Только продавец может подтвердить отправку", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'payment_confirmed', seller_done=True)
    if success:
        deal = get_deal(deal_id)
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", "🚚 Продавец подтвердил отправку товара", True)
        
        # Проверяем, завершена ли сделка
        if deal['buyer_done']:
            success = update_deal_status(deal_id, 'completed', completed_at=datetime.now())
            if success:
                add_deal_message(deal_id, 0, "Система", "🏁 Сделка завершена! Ожидайте выплаты продавцу", True)
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        await query.answer("✅ Подтверждено")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def guarantor_confirm(query, deal_id, role):
    """Гарант подтверждает получение оплаты"""
    if role != 'guarantor':
        await query.answer("Только гарант может подтвердить оплату", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'payment_confirmed', guarantor_confirmed=True)
    if success:
        deal = get_deal(deal_id)
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", "🛡️ Гарант подтвердил получение оплаты", True)
        
        # Уведомляем участников
        for user_id in [deal['buyer_id'], deal['seller_id']]:
            try:
                notification = f"🛡️ Гарант подтвердил оплату по сделке #{deal_id}\n\nТеперь продавец может отправить товар."
                await query.bot.send_message(chat_id=user_id, text=notification)
            except:
                pass
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        await query.answer("✅ Оплата подтверждена")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def guarantor_reject(query, deal_id, role):
    """Гарант отклоняет оплату"""
    if role != 'guarantor':
        await query.answer("Только гарант может отклонить оплату", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'accepted', buyer_paid=False)
    if success:
        deal = get_deal(deal_id)
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", "❌ Гарант не получил оплату", True)
        
        # Уведомляем покупателя
        try:
            notification = f"❌ Гарант не получил оплату по сделке #{deal_id}\n\nПожалуйста, проверьте перевод."
            await query.bot.send_message(chat_id=deal['buyer_id'], text=notification)
        except:
            pass
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        await query.answer("✅ Оплата отклонена")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def create_payment_request_handler(query, deal_id, role):
    """Создать запрос на выплату продавцу"""
    if role != 'guarantor':
        await query.answer("Только гарант может создать запрос на выплату", show_alert=True)
        return
    
    deal = get_deal(deal_id)
    if not deal:
        await query.answer("Сделка не найдена", show_alert=True)
        return
    
    # Получаем реквизиты продавца
    seller_info = get_user_info(deal['seller_id'])
    payment_details = get_user_payment_details(deal['seller_id'])
    
    if not payment_details:
        # Уведомляем продавца что нужно указать реквизиты
        try:
            await query.bot.send_message(
                chat_id=deal['seller_id'],
                text=f"🛡️ <b>Укажите платежные реквизиты</b>\n\nДля получения выплаты по сделке #{deal_id} вам нужно указать платежные реквизиты.\n\nОтправьте их в формате:\n<code>Карта: 1234 5678 9012 3456\nБанк: Сбербанк\nИмя: Иван Иванов</code>"
            )
        except:
            pass
        
        await query.answer("❌ У продавца не указаны реквизиты", show_alert=True)
        return
    
    # Создаем запрос на выплату
    request_id = create_payment_request(
        deal_id=deal_id,
        seller_id=deal['seller_id'],
        amount=deal['amount'],
        currency=deal['currency'],
        payment_details=payment_details['details']
    )
    
    if request_id:
        # Показываем детали выплаты гаранту
        seller_name = f"@{seller_info['username']}" if seller_info and seller_info.get('username') else f"ID: {deal['seller_id']}"
        
        text = f"""
💸 <b>ЗАПРОС НА ВЫПЛАТУ #{request_id}</b>
━━━━━━━━━━━━━━━━━━
<b>Сделка:</b> #{deal_id}
<b>Продавец:</b> {seller_name}
<b>Сумма к выплате:</b> {deal['amount']:,} {deal['currency']}
<b>Способ оплаты:</b> {payment_details['method']}
<b>Реквизиты:</b>
<code>{payment_details['details']}</code>
━━━━━━━━━━━━━━━━━━
<b>Инструкция:</b>
1. Переведите деньги по указанным реквизитам
2. Нажмите "✅ Я перевел деньги"
3. Прикрепите скриншот перевода (опционально)
"""
        
        keyboard = get_payment_request_keyboard(deal_id)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", f"💸 Создан запрос на выплату продавцу #{request_id}", True)
        
        await query.answer("✅ Запрос на выплату создан")
    else:
        await query.answer("❌ Ошибка создания запроса", show_alert=True)

async def payment_done_handler(query, deal_id, role, context):
    """Гарант подтверждает что перевел деньги"""
    if role != 'guarantor':
        await query.answer("Только гарант может подтвердить выплату", show_alert=True)
        return
    
    # Запрашиваем ID транзакции
    context.user_data['awaiting_transaction_id'] = deal_id
    text = "🔢 <b>Введите ID транзакции / номер перевода:</b>\n\nПример: <code>T123456789</code> или <code>7965423185</code>"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f'deal_view_{deal_id}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def ask_payment_proof(query, deal_id, role, context):
    """Запрос на прикрепление скриншота перевода"""
    if role != 'guarantor':
        await query.answer("Только гарант может прикрепить скриншот", show_alert=True)
        return
    
    context.user_data['awaiting_payment_proof'] = deal_id
    text = "📸 <b>Прикрепите скриншот перевода:</b>\n\nСфотографируйте или сделайте скриншот подтверждения перевода и отправьте его."
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f'deal_view_{deal_id}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_payment_confirmation(update: Update, context: CallbackContext):
    """Обработка подтверждения выплаты"""
    user_id = update.effective_user.id
    
    # Проверяем что это гарант
    if str(user_id) != GUARANTOR_USERNAME and (not update.effective_user.username or update.effective_user.username.lower() != GUARANTOR_USERNAME.lower()):
        return
    
    if 'awaiting_transaction_id' in context.user_data:
        deal_id = context.user_data['awaiting_transaction_id']
        transaction_id = update.message.text.strip()
        
        if not transaction_id:
            await update.message.reply_text("❌ ID транзакции не может быть пустым")
            return
        
        # Обновляем сделку
        success = update_deal_status(
            deal_id, 
            'completed',
            guarantor_paid=True,
            payment_transaction_id=transaction_id,
            completed_at=datetime.now()
        )
        
        if success:
            deal = get_deal(deal_id)
            
            # Обновляем запрос на выплату
            payment_request = get_payment_request_by_deal(deal_id)
            if payment_request:
                update_payment_request(payment_request['id'], transaction_id=transaction_id, status='paid')
            
            # Добавляем системное сообщение
            add_deal_message(deal_id, 0, "Система", f"💸 Гарант выплатил деньги продавцу (ID транзакции: {transaction_id})", True)
            
            # Автоматически добавляем репутацию
            try:
                buyer_info = get_user_info(deal['buyer_id'])
                seller_info = get_user_info(deal['seller_id'])
                
                # +rep покупателю от продавца
                if seller_info:
                    save_reputation(
                        from_user=deal['seller_id'],
                        from_username=seller_info.get('username', ''),
                        to_user=deal['buyer_id'],
                        to_username=buyer_info.get('username', '') if buyer_info else '',
                        text=f"+rep За успешную сделку #{deal_id} на {deal['amount']} {deal['currency']}",
                        photo_id=''
                    )
                
                # +rep продавцу от покупателя
                if buyer_info:
                    save_reputation(
                        from_user=deal['buyer_id'],
                        from_username=buyer_info.get('username', ''),
                        to_user=deal['seller_id'],
                        to_username=seller_info.get('username', '') if seller_info else '',
                        text=f"+rep За успешную сделку #{deal_id} на {deal['amount']} {deal['currency']}",
                        photo_id=''
                    )
            except:
                pass
            
            # Уведомляем продавца
            try:
                payment_request = get_payment_request_by_deal(deal_id)
                if payment_request:
                    notification = f"""
💸 <b>Выплата получена!</b>

✅ Гарант перевел вам {deal['amount']:,} {deal['currency']}
📦 По сделке: #{deal_id}
🔢 ID транзакции: {transaction_id}
📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}

💰 Проверьте ваш счет!
"""
                    await update.message.bot.send_message(
                        chat_id=deal['seller_id'],
                        text=notification,
                        parse_mode='HTML'
                    )
            except:
                pass
            
            # Показываем завершенную сделку
            text = get_deal_text(get_deal(deal_id))
            keyboard = get_deal_keyboard(deal_id, user_id, get_deal(deal_id))
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')
            
            context.user_data.pop('awaiting_transaction_id', None)
        else:
            await update.message.reply_text("❌ Ошибка обновления сделки")
    
    elif 'awaiting_payment_proof' in context.user_data and update.message.photo:
        deal_id = context.user_data['awaiting_payment_proof']
        photo_id = update.message.photo[-1].file_id
        
        # Обновляем сделку с ID скриншота
        success = update_deal_status(deal_id, payment_proof=photo_id)
        
        if success:
            # Обновляем запрос на выплату
            payment_request = get_payment_request_by_deal(deal_id)
            if payment_request:
                update_payment_request(payment_request['id'], proof_image_id=photo_id)
            
            await update.message.reply_text("✅ Скриншот сохранен")
            
            # Показываем сделку
            text = get_deal_text(get_deal(deal_id))
            keyboard = get_deal_keyboard(deal_id, user_id, get_deal(deal_id))
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode='HTML')
            
            context.user_data.pop('awaiting_payment_proof', None)
        else:
            await update.message.reply_text("❌ Ошибка сохранения скриншота")

async def open_dispute(query, deal_id, role):
    """Открыть спор по сделке"""
    if role != 'guarantor':
        await query.answer("Только гарант может открыть спор", show_alert=True)
        return
    
    success = update_deal_status(deal_id, 'disputed')
    if success:
        deal = get_deal(deal_id)
        
        # Добавляем системное сообщение
        add_deal_message(deal_id, 0, "Система", "⚖️ Гарант открыл спор по сделке", True)
        
        # Уведомляем участников
        for user_id in [deal['buyer_id'], deal['seller_id']]:
            try:
                notification = f"⚖️ Открыт спор по сделке #{deal_id}\n\nГарант @{GUARANTOR_USERNAME} рассмотрит ситуацию."
                await query.bot.send_message(chat_id=user_id, text=notification)
            except:
                pass
        
        # Обновляем сообщение
        text = get_deal_text(deal)
        keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')
        
        await query.answer("✅ Спор открыт")
    else:
        await query.answer("❌ Ошибка", show_alert=True)

async def show_deal_chat(query, deal_id, role):
    """Показать чат сделки"""
    deal = get_deal(deal_id)
    if not deal:
        await query.answer("Сделка не найдена", show_alert=True)
        return
    
    messages = get_deal_messages(deal_id, limit=20)
    
    text = f"💬 <b>Чат сделки #{deal_id}</b>\n\n"
    
    if not messages:
        text += "Сообщений пока нет.\n\n"
    else:
        for msg in messages:
            if msg['is_system']:
                text += f"<i>🔔 {msg['message']}</i>\n"
            else:
                username = msg['username'] or f"ID:{msg['user_id']}"
                time_str = msg['created_at'].strftime("%H:%M") if isinstance(msg['created_at'], datetime) else msg['created_at'][11:16]
                text += f"<b>{username}:</b> {msg['message']}\n"
    
    text += f"\n━━━━━━━━━━━━━━━━━━\n"
    text += f"<i>Отправьте сообщение в чат, чтобы добавить его в обсуждение</i>"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад к сделке", callback_data=f'deal_view_{deal_id}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    # Сохраняем ID сделки для обработки сообщений
    context = query.message._bot_data.get('context')
    if context:
        context.user_data['active_deal_chat'] = deal_id

async def show_deal_details(query, deal_id, role):
    """Показать детали сделки (для гаранта)"""
    deal = get_deal(deal_id)
    if not deal:
        await query.answer("Сделка не найдена", show_alert=True)
        return
    
    buyer_info = get_user_info(deal['buyer_id'])
    seller_info = get_user_info(deal['seller_id'])
    
    buyer_name = f"@{buyer_info['username']}" if buyer_info and buyer_info.get('username') else f"ID: {deal['buyer_id']}"
    seller_name = f"@{seller_info['username']}" if seller_info and seller_info.get('username') else f"ID: {deal['seller_id']}"
    
    text = f"""
📊 <b>Детали сделки #{deal_id}</b>
━━━━━━━━━━━━━━━━━━
<b>ID сделки:</b> {deal['deal_uuid']}
<b>Сумма:</b> {deal['amount']:,} {deal['currency']}
<b>Покупатель:</b> {buyer_name} (ID: {deal['buyer_id']})
<b>Продавец:</b> {seller_name} (ID: {deal['seller_id']})
<b>Описание:</b> {deal['description']}
<b>Статус:</b> {deal['status']}
━━━━━━━━━━━━━━━━━━
<b>Дата создания:</b> {deal['created_at'].strftime('%d.%m.%Y %H:%M') if isinstance(deal['created_at'], datetime) else deal['created_at']}
<b>Истекает:</b> {deal['expires_at'].strftime('%d.%m.%Y %H:%M') if isinstance(deal['expires_at'], datetime) else deal['expires_at']}
"""
    
    if deal['completed_at']:
        text += f"<b>Дата завершения:</b> {deal['completed_at'].strftime('%d.%m.%Y %H:%M') if isinstance(deal['completed_at'], datetime) else deal['completed_at']}\n"
    
    if deal['payment_transaction_id']:
        text += f"<b>ID транзакции выплаты:</b> {deal['payment_transaction_id']}\n"
    
    # Показываем реквизиты продавца если есть
    payment_details = get_user_payment_details(deal['seller_id'])
    if payment_details and role == 'guarantor':
        text += f"\n<b>Реквизиты продавца:</b>\n"
        text += f"<code>{payment_details['details']}</code>\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f'deal_view_{deal_id}')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_deal_view(query, deal_id):
    """Показать сделку для просмотра"""
    deal = get_deal(deal_id)
    if not deal:
        await query.answer("Сделка не найдена", show_alert=True)
        return
    
    text = get_deal_text(deal)
    keyboard = get_deal_keyboard(deal_id, query.from_user.id, deal)
    
    await query.edit_message_text(text, reply_markup=keyboard, parse_mode='HTML')

# ========== ГЛАВНЫЙ ОБРАБОТЧИК КНОПОК ==========
async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Обработка сделок
    if data.startswith(('deal_', 'create_deal', 'my_deals', 'payment_')):
        await deal_button_handler(update, context, query, data)
        return
    
    if data.startswith('send_to_'):
        target_user_id = int(data.replace('send_to_', ''))
        user_id = query.from_user.id
        
        target_user_info = get_user_info(target_user_id)
        target_username = target_user_info.get("username", f"id{target_user_id}") if target_user_info else f"id{target_user_id}"
        
        await query.message.reply_text(
            f"Для отправки репутации пользователю @{target_username} перейдите в личные сообщения с ботом",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Перейти в бот", url=f"https://t.me/{context.bot.username}")]
            ])
        )
        return
    
    if data == 'send_reputation':
        text = """<b>Отправьте репутацию.</b>

К репутации необходимо приложить хотя бы одну фотографию.

Пример «+rep @username все идеально»
Пример «-rep user_id сделка не зашла»"""
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        context.user_data['waiting_for_rep'] = True
    
    elif data == 'search_user':
        text = "🛡️<b>Введите username/id пользователя:</b>"
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        context.user_data['waiting_for_search'] = True
    
    elif data == 'profile':
        await show_profile_pm(query, query.from_user.id, is_own_profile=True)
    
    elif data == 'my_reputation':
        await show_my_reputation_menu(query)
    
    elif data.startswith('show_'):
        await handle_show_reputation(query)
    
    elif data == 'back_to_main':
        await show_main_menu(query)
    
    elif data == 'view_found_user_reputation':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_found_user_reputation_menu(query, target_user_id)
    
    elif data.startswith('found_show_'):
        await handle_found_user_reputation(query, context)
    
    elif data == 'back_to_found_profile':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_profile_pm(query, target_user_id, is_own_profile=False)

async def show_profile_pm(query, user_id, is_own_profile=True):
    user_info = get_user_info(user_id)
    stats = get_reputation_stats(user_id)
    
    username = user_info.get("username", "") if user_info else ""
    display_username = f"👤@{username}" if username else f"👤id{user_id}"
    
    if user_info and user_info.get("registered_at"):
        try:
            reg_date = datetime.fromisoformat(user_info["registered_at"])
            registration_date = reg_date.strftime("%d/%m/%Y")
        except:
            registration_date = datetime.now().strftime("%d/%m/%Y")
    else:
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
    text = f"""{display_username} (ID: {user_id})

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote><blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

<b>ВНИМАТЕЛЬНО СМОТРИТЕ ПОЛЕ «О СЕБЕ»</b>

💳 Депозит: отсутствует

🗓️ Зарегистрирован: {registration_date}"""
    
    if is_own_profile:
        keyboard = [
            [InlineKeyboardButton("🏆 Моя репутация", callback_data='my_reputation')],
            [InlineKeyboardButton("🤝 Мои сделки", callback_data='my_deals')],
            [InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("Посмотреть репутацию", callback_data='view_found_user_reputation')],
            [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
            [InlineKeyboardButton("🤝 Создать сделку", callback_data=f'create_deal_with_{user_id}')],
            [InlineKeyboardButton("↩️ Назад", callback_data='search_user')]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_my_reputation_menu(query):
    text = "<b>Выберите раздел:</b>"
    
    keyboard = [
        [InlineKeyboardButton("Положительные", callback_data='show_positive')],
        [InlineKeyboardButton("Отрицательные", callback_data='show_negative')],
        [InlineKeyboardButton("Все", callback_data='show_all')],
        [InlineKeyboardButton("Последний положительный", callback_data='show_last_positive')],
        [InlineKeyboardButton("Последний отрицательный", callback_data='show_last_negative')],
        [InlineKeyboardButton("↩️ Назад", callback_data='profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_found_user_reputation_menu(query, target_user_id):
    text = "<b>Выберите раздел:</b>"
    
    keyboard = [
        [InlineKeyboardButton("Положительные", callback_data='found_show_positive')],
        [InlineKeyboardButton("Отрицательные", callback_data='found_show_negative')],
        [InlineKeyboardButton("Все", callback_data='found_show_all')],
        [InlineKeyboardButton("↩️ Назад", callback_data='back_to_found_profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_show_reputation(query):
    user_id = query.from_user.id
    stats = get_reputation_stats(user_id)
    
    if query.data == 'show_positive':
        positive_reps = [r for r in stats['all_reps'] 
                        if r["text"].lower().startswith(('+rep', '+реп'))]
        
        if not positive_reps:
            text = "✅ <b>Положительные отзывы</b>\n\nУ вас еще нет положительных отзывов."
        else:
            text = "✅ <b>Положительные отзывы</b>\n\n"
            for i, rep in enumerate(positive_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                text += f"{i}. От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(positive_reps) > 10:
                text += f"\n... и еще {len(positive_reps) - 10} отзывов"
        
        back_button = 'my_reputation'
    
    elif query.data == 'show_negative':
        negative_reps = [r for r in stats['all_reps'] 
                        if r["text"].lower().startswith(('-rep', '-реп'))]
        
        if not negative_reps:
            text = "❌ <b>Отрицательные отзывы</b>\n\nУ вас еще нет отрицательных отзывов."
        else:
            text = "❌ <b>Отрицательные отзывы</b>\n\n"
            for i, rep in enumerate(negative_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                text += f"{i}. От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(negative_reps) > 10:
                text += f"\n... и еще {len(negative_reps) - 10} отзывов"
        
        back_button = 'my_reputation'
    
    elif query.data == 'show_all':
        all_reps = stats['all_reps']
        
        if not all_reps:
            text = "📋 <b>Все отзывы</b>\n\nУ вас еще нет отзывов."
        else:
            text = "📋 <b>Все отзывы</b>\n\n"
            for i, rep in enumerate(all_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                sign = "✅" if rep["text"].lower().startswith(('+rep', '+реп')) else "❌"
                text += f"{i}. {sign} От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(all_reps) > 10:
                text += f"\n... и еще {len(all_reps) - 10} отзывов"
        
        back_button = 'my_reputation'
    
    elif query.data == 'show_last_positive':
        last_positive = get_last_positive(user_id)
        
        if not last_positive:
            text = "✅ <b>Последний положительный отзыв</b>\n\nУ вас еще нет положительных отзывов."
        else:
            from_user = last_positive.get("from_username", f"id{last_positive['from_user']}")
            date = datetime.fromisoformat(last_positive["created_at"]).strftime("%d/%m/%Y")
            text = f"""✅ <b>Последний положительный отзыв</b>

От: @{from_user}
Текст: {last_positive['text']}
Дата: {date}"""
        
        back_button = 'my_reputation'
    
    elif query.data == 'show_last_negative':
        last_negative = get_last_negative(user_id)
        
        if not last_negative:
            text = "❌ <b>Последний отрицательный отзыв</b>\n\nУ вас еще нет отрицательных отзывов."
        else:
            from_user = last_negative.get("from_username", f"id{last_negative['from_user']}")
            date = datetime.fromisoformat(last_negative["created_at"]).strftime("%d/%m/%Y")
            text = f"""❌ <b>Последний отрицательный отзыв</b>

От: @{from_user}
Текст: {last_negative['text']}
Дата: {date}"""
        
        back_button = 'my_reputation'
    
    keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data=back_button)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_found_user_reputation(query, context):
    target_user_id = context.user_data.get('found_user_id')
    if not target_user_id:
        await query.edit_message_text("Ошибка: пользователь не найден")
        return
    
    stats = get_reputation_stats(target_user_id)
    user_info = get_user_info(target_user_id)
    username = user_info.get("username", "") if user_info else f"id{target_user_id}"
    
    if query.data == 'found_show_positive':
        positive_reps = [r for r in stats['all_reps'] 
                        if r["text"].lower().startswith(('+rep', '+реп'))]
        
        if not positive_reps:
            text = f"✅ <b>Положительные отзывы @{username}</b>\n\nУ пользователя еще нет положительных отзывов."
        else:
            text = f"✅ <b>Положительные отзывы @{username}</b>\n\n"
            for i, rep in enumerate(positive_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                text += f"{i}. От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(positive_reps) > 10:
                text += f"\n... и еще {len(positive_reps) - 10} отзывов"
        
        back_button = 'view_found_user_reputation'
    
    elif query.data == 'found_show_negative':
        negative_reps = [r for r in stats['all_reps'] 
                        if r["text"].lower().startswith(('-rep', '-реп'))]
        
        if not negative_reps:
            text = f"❌ <b>Отрицательные отзывы @{username}</b>\n\nУ пользователя еще нет отрицательных отзывов."
        else:
            text = f"❌ <b>Отрицательные отзывы @{username}</b>\n\n"
            for i, rep in enumerate(negative_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                text += f"{i}. От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(negative_reps) > 10:
                text += f"\n... и еще {len(negative_reps) - 10} отзывов"
        
        back_button = 'view_found_user_reputation'
    
    elif query.data == 'found_show_all':
        all_reps = stats['all_reps']
        
        if not all_reps:
            text = f"📋 <b>Все отзывы @{username}</b>\n\nУ пользователя еще нет отзывов."
        else:
            text = f"📋 <b>Все отзывы @{username}</b>\n\n"
            for i, rep in enumerate(all_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                sign = "✅" if rep["text"].lower().startswith(('+rep', '+реп')) else "❌"
                text += f"{i}. {sign} От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(all_reps) > 10:
                text += f"\n... и еще {len(all_reps) - 10} отзывов"
        
        back_button = 'view_found_user_reputation'
    
    keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data=back_button)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_main_menu(query):
    user_id = query.from_user.id
    text = f"""<b>🛡️ TESS | Репутация — твоя гарантия безопасности!</b>
ID - [{user_id}]

• Здесь можно отправить или просмотреть репутацию пользователя, а также провести сделку! Выберите раздел:"""
    
    keyboard = [
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🔎 Найти пользователя", callback_data='search_user')],
        [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')],
        [InlineKeyboardButton("🤝 Мои сделки", callback_data='my_deals')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_all_messages(update: Update, context: CallbackContext) -> None:
    """Обработка ВСЕХ сообщений"""
    user_id = update.effective_user.id
    username = update.effective_user.username or f"id{user_id}"
    
    # Проверяем что это гарант (для обработки подтверждений выплат)
    is_guarantor = (str(user_id) == GUARANTOR_USERNAME) or (username and username.lower() == GUARANTOR_USERNAME.lower())
    
    save_user(user_id, username)
    
    if update.message.chat.type == 'private':
        # Обработка подтверждений выплат от гаранта
        if is_guarantor and ('awaiting_transaction_id' in context.user_data or 'awaiting_payment_proof' in context.user_data):
            await handle_payment_confirmation(update, context)
            return
        
        # Обработка реквизитов продавца
        if 'awaiting_payment_details' in context.user_data and user_id == context.user_data['awaiting_payment_details']:
            payment_details = update.message.text.strip()
            if len(payment_details) > 10:
                save_user(user_id, username, payment_details, 'bank_card')
                await update.message.reply_text("✅ Платежные реквизиты сохранены!")
                context.user_data.pop('awaiting_payment_details', None)
            else:
                await update.message.reply_text("❌ Реквизиты слишком короткие")
            return
        
        # Проверяем состояния в правильном порядке
        if context.user_data.get('waiting_for_search'):
            await handle_search_message_pm(update, context)
        elif context.user_data.get('waiting_for_rep'):
            await handle_reputation_message_pm(update, context)
        elif context.user_data.get('awaiting_deal_amount') or context.user_data.get('awaiting_deal_description'):
            await create_deal_from_input(update, context)
        elif context.user_data.get('active_deal_chat'):
            await handle_deal_chat_message(update, context)
    
    elif update.message.chat.type in ['group', 'supergroup']:
        await handle_group_reputation(update, context)

async def handle_deal_chat_message(update: Update, context: CallbackContext):
    """Обработка сообщений в чате сделки"""
    user_id = update.effective_user.id
    deal_id = context.user_data.get('active_deal_chat')
    
    if not deal_id:
        return
    
    deal = get_deal(deal_id)
    if not deal:
        return
    
    # Проверяем, является ли пользователь участником сделки
    if user_id not in [deal['buyer_id'], deal['seller_id']]:
        await update.message.reply_text("Вы не участник этой сделки")
        return
    
    # Добавляем сообщение в чат
    username = update.effective_user.username or f"id{user_id}"
    add_deal_message(deal_id, user_id, username, update.message.text)
    
    # Отправляем уведомление другому участнику
    other_user_id = deal['seller_id'] if user_id == deal['buyer_id'] else deal['buyer_id']
    try:
        await context.bot.send_message(
            chat_id=other_user_id,
            text=f"💬 Новое сообщение в сделке #{deal_id}:\n\n{update.message.text}"
        )
    except:
        pass
    
    await update.message.reply_text("✅ Сообщение добавлено в чат сделки")

async def handle_group_reputation(update: Update, context: CallbackContext) -> None:
    """Обработка репутации в групповом чате"""
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""
    
    patterns = [
        r'[-+](?:rep|реп)\s+(@?\w+)',
        r'[-+](?:rep|реп)\s+(\d+)',
    ]
    
    has_rep_pattern = False
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            has_rep_pattern = True
            break
    
    if has_rep_pattern and not update.message.photo:
        await update.message.reply_text("❗️ <b>Необходимо прикрепить фото/скриншот</b>", parse_mode='HTML')
        return
    
    if not update.message.photo:
        return
    
    target_identifier = None
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            target_identifier = match.group(1)
            break
    
    if not target_identifier:
        await update.message.reply_text("Неверный формат")
        return
    
    target_info = {"id": None, "username": None}
    
    if target_identifier.isdigit():
        target_info["id"] = int(target_identifier)
        target_info["username"] = f"id{target_identifier}"
    
    elif update.message.reply_to_message:
        target_info["id"] = update.message.reply_to_message.from_user.id
        target_username = update.message.reply_to_message.from_user.username
        target_info["username"] = target_username or f"id{target_info['id']}"
        
    else:
        username = target_identifier.lstrip('@')
        user_info = get_user_by_username(username)
        
        if user_info:
            target_info["id"] = user_info['user_id']
            target_info["username"] = user_info['username']
        else:
            await update.message.reply_text("❌ <b>Пользователь не найден</b>\nИспользуйте реплай или ID", parse_mode='HTML')
            return
    
    if target_info["id"] == user_id:
        await update.message.reply_text("Нельзя себе")
        return
    
    save_reputation(
        from_user=user_id,
        from_username=update.effective_user.username or "",
        to_user=target_info["id"],
        to_username=target_info["username"],
        text=text,
        photo_id=update.message.photo[-1].file_id
    )
    
    await update.message.reply_text("Сохранено")

async def handle_reputation_message_pm(update: Update, context: CallbackContext) -> None:
    """Обработка репутации в личных сообщениях"""
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""
    
    if not update.message.photo:
        await update.message.reply_text("❗️ <b>Необходимо прикрепить фото/скриншот</b>", parse_mode='HTML')
        return
    
    patterns = [r'[-+](?:rep|реп)\s+(@?\w+)']
    target_identifier = None
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            target_identifier = match.group(1)
            break
    
    if not target_identifier:
        await update.message.reply_text("Неверный формат")
        return
    
    target_info = {"id": None, "username": None}
    
    if target_identifier.isdigit():
        target_info["id"] = int(target_identifier)
        target_info["username"] = f"id{target_identifier}"
    else:
        username = target_identifier.lstrip('@')
        user_info = get_user_by_username(username)
        if user_info:
            target_info["id"] = user_info['user_id']
            target_info["username"] = user_info['username']
        else:
            await update.message.reply_text("❌ <b>Пользователь не найден</b>", parse_mode='HTML')
            return
    
    if target_info["id"] == user_id:
        await update.message.reply_text("Нельзя себе")
        return
    
    save_reputation(
        from_user=user_id,
        from_username=update.effective_user.username or "",
        to_user=target_info["id"],
        to_username=target_info["username"],
        text=text,
        photo_id=update.message.photo[-1].file_id
    )
    
    await update.message.reply_text("Сохранено")
    await show_main_menu_from_message(update, context, user_id)

async def show_main_menu_from_message(update: Update, context: CallbackContext, user_id: int):
    """Показать главное меню после отправки репутации"""
    text = f"""<b>🛡️ TESS | Репутация — твоя гарантия безопасности!</b>
ID - [{user_id}]

• Здесь можно отправить или просмотреть репутацию пользователя, а также провести сделку! Выберите раздел:"""
    
    keyboard = [
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🔎 Найти пользователя", callback_data='search_user')],
        [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')],
        [InlineKeyboardButton("🤝 Мои сделки", callback_data='my_deals')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    if 'waiting_for_rep' in context.user_data:
        context.user_data.pop('waiting_for_rep')

async def handle_search_message_pm(update: Update, context: CallbackContext) -> None:
    """Поиск пользователя в личных сообщениях"""
    search_text = update.message.text.strip()
    user_id = update.effective_user.id
    
    target_user = None
    
    if search_text.isdigit():
        target_user = get_user_info(int(search_text))
    else:
        username = search_text.lstrip('@')
        target_user = get_user_by_username(username)
    
    if not target_user:
        await update.message.reply_text("❌ <b>Пользователь не найден</b>", parse_mode='HTML')
        return
    
    context.user_data['found_user_id'] = target_user['user_id']
    
    stats = get_reputation_stats(target_user['user_id'])
    username = target_user.get("username", "")
    display_username = f"👤@{username}" if username else f"👤id{target_user['user_id']}"
    
    if target_user.get("registered_at"):
        try:
            reg_date = datetime.fromisoformat(target_user["registered_at"])
            registration_date = reg_date.strftime("%d/%m/%Y")
        except:
            registration_date = datetime.now().strftime("%d/%m/%Y")
    else:
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
    text = f"""{display_username} (ID: {target_user['user_id']})

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote><blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

<b>ВНИМАТЕЛЬНО СМОТРИТЕ ПОЛЕ «О СЕБЕ»</b>

💳 Депозит: отсутствует

🗓️ Зарегистрирован: {registration_date}"""
    
    keyboard = [
        [InlineKeyboardButton("Посмотреть репутацию", callback_data='view_found_user_reputation')],
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🤝 Создать сделку", callback_data=f'create_deal_with_{target_user["user_id"]}')],
        [InlineKeyboardButton("↩️ Назад", callback_data='search_user')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    context.user_data.pop('waiting_for_search', None)

# ========== ЗАПУСК БОТА ==========
def main():
    """Основная функция запуска"""
    print("=" * 60)
    print("TESS REPUTATION BOT with COMPLETE PAYMENT SYSTEM")
    print("=" * 60)
    
    # Определяем платформу
    if is_railway():
        print("Платформа: Railway (PostgreSQL)")
    elif is_replit():
        print("Платформа: Replit (SQLite)")
        # Запускаем Flask только на Replit
        try:
            from flask import Flask
            from threading import Thread
            
            app = Flask('')
            @app.route('/')
            def home(): 
                return "Бот работает!"
            
            def run():
                app.run(host='0.0.0.0', port=8080)
            
            t = Thread(target=run, daemon=True)
            t.start()
            print("Keep-alive сервер запущен (Replit)")
        except ImportError:
            print("Flask не установлен")
    else:
        print("Платформа: Локальный запуск (SQLite)")
    
    print(f"Токен: {'Установлен' if TOKEN else 'Отсутствует!'}")
    print(f"Гарант: @{GUARANTOR_USERNAME}")
    print("=" * 60)
    
    # Инициализация БД
    init_db()
    
    # Создаем приложение бота
    app = Application.builder().token(TOKEN).build()
    
    # Сохраняем ссылку на приложение для доступа из хендлеров
    app.user_data['bot_app'] = app
    
    # Команды для личных сообщений
    app.add_handler(CommandHandler("start", start))
    
    # Команды для чатов (групп)
    app.add_handler(CommandHandler("v", quick_profile))
    app.add_handler(CommandHandler("rep", quick_profile))
    app.add_handler(CommandHandler("profile", quick_profile))
    app.add_handler(CommandHandler("deal", quick_profile))
    
    # Обработчики кнопок
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик ВСЕХ сообщений (включая группы)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_all_messages))
    
    # Запускаем бота
    print("Бот запускается...")
    print("Система сделок с полной системой выплат активирована!")
    print("Готов к работе!")
    print("=" * 60)
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
