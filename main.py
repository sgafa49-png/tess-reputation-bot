import os
import re
import sys
import psycopg2
import glob
import gzip
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    CallbackQueryHandler, 
    CallbackContext,
    MessageHandler,
    filters
)

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    print("❌ ОШИБКА: TELEGRAM_TOKEN не найден!")
    sys.exit(1)

DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("❌ ОШИБКА: DATABASE_URL не найден!")
    sys.exit(1)

PHOTO_URL = "https://raw.githubusercontent.com/sgafa49-png/tess-reputation-bot/main/IMG_0354.jpeg"
ADMINS = [8438564254, 7819922804]  # ID админов

# ========== КЛАВИАТУРЫ ==========
def get_admin_keyboard():
    """Клавиатура для админов"""
    return ReplyKeyboardMarkup([
        ['Админ панель']
    ], resize_keyboard=True, one_time_keyboard=False)

def get_admin_menu_keyboard():
    """Меню админ-панели"""
    return ReplyKeyboardMarkup([
        ['Удалить отзыв'],
        ['Статистика', 'Рассылка'],
        ['Топ по репутации'],
        ['Резервное копирование'],
        ['Главное меню']
    ], resize_keyboard=True, one_time_keyboard=False)

def get_backup_menu_keyboard():
    """Меню резервного копирования"""
    return ReplyKeyboardMarkup([
        ['Создать бэкап'],
        ['Показать бэкапы', 'Восстановить'],
        ['Автоочистка'],
        ['Назад в админ-панель']
    ], resize_keyboard=True, one_time_keyboard=False)

def get_top_menu_keyboard():
    """Меню топов"""
    return ReplyKeyboardMarkup([
        ['Топ за день', 'Топ за неделю'],
        ['Топ за месяц', 'Топ за всё время'],
        ['Топ за N дней', 'Назад в админ-панель']
    ], resize_keyboard=True, one_time_keyboard=False)

# ========== КОНСТАНТЫ ДЛЯ РЕПУТАЦИИ ==========
REP_PATTERN = re.compile(r'[+-][\s:;-]*(?:rep|реп|рп)(?:\s|$|[^a-za-zа-я0-9])', re.IGNORECASE)

def is_reputation_command(text):
    """Определяет, является ли сообщение командой репутации"""
    return bool(REP_PATTERN.search(text)) if text else False

def get_reputation_type(text):
    """Определяет тип репутации: + (positive) или - (negative)"""
    if not text:
        return None
    
    text_lower = text.lower()
    match = REP_PATTERN.search(text_lower)
    if match:
        start_pos = match.start()
        if start_pos < len(text_lower):
            char = text_lower[start_pos]
            if char in '+-':
                return '+' if char == '+' else '-'
    return None

# ========== БАЗА ДАННЫХ POSTGRESQL ==========
def get_db_connection():
    """Возвращает соединение с PostgreSQL"""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения PostgreSQL: {e}")
        sys.exit(1)

def init_db():
    """Инициализация базы данных"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                registered_at TEXT
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
        
        conn.commit()
        print("✅ Таблицы созданы/проверены")
    except Exception as e:
        print(f"❌ Ошибка создания таблиц: {e}")
    finally:
        conn.close()

def check_database_connection():
    """Проверка подключения к БД"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM users')
        users_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reputation')
        reps_count = cursor.fetchone()[0]
        
        conn.close()
        
        print(f"✅ Подключение к БД: Успешно")
        print(f"👥 Пользователей в БД: {users_count}")
        print(f"📝 Отзывов в БД: {reps_count}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
        return False

# ========== ФУНКЦИИ БАЗЫ ДАННЫХ ==========
def save_user(user_id, username):
    """Сохраняем пользователя в БД"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO users (user_id, username, registered_at) 
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE 
            SET username = EXCLUDED.username
        ''', (user_id, username, datetime.now().isoformat()))
        
        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка сохранения пользователя {user_id}: {e}")
    finally:
        conn.close()

def save_reputation(from_user, from_username, to_user, to_username, text, photo_id):
    """Сохраняем репутацию в БД"""
    save_user(from_user, from_username)
    save_user(to_user, to_username)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO reputation (from_user, to_user, text, photo_id, created_at)
            VALUES (%s, %s, %s, %s, %s)
        ''', (from_user, to_user, text, photo_id, datetime.now().isoformat()))
        
        conn.commit()
        print(f"✅ Репутация сохранена: {from_user} → {to_user}")
    except Exception as e:
        print(f"❌ Ошибка сохранения репутации: {e}")
    finally:
        conn.close()

def get_all_users():
    """Получить всех пользователей из БД"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    users = []
    try:
        cursor.execute('SELECT user_id FROM users')
        rows = cursor.fetchall()
        users = [{'user_id': row[0]} for row in rows]
    except Exception as e:
        print(f"❌ Ошибка получения пользователей: {e}")
    finally:
        conn.close()
    
    return users

def get_user_reputation(user_id):
    """Получаем всю репутацию пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    reps = []
    try:
        cursor.execute('''
            SELECT r.*, u.username as from_username 
            FROM reputation r
            LEFT JOIN users u ON r.from_user = u.user_id
            WHERE r.to_user = %s
            ORDER BY r.created_at DESC
        ''', (user_id,))
        
        rows = cursor.fetchall()
        
        for row in rows:
            from_username = row[6]
            if not from_username and row[1] is None:
                from_username = "Скрытый профиль"
            elif not from_username:
                from_username = f"id{row[1]}"
            
            reps.append({
                'id': row[0],
                'from_user': row[1],
                'to_user': row[2],
                'text': row[3],
                'photo_id': row[4],
                'created_at': row[5],
                'from_username': from_username
            })
    except Exception as e:
        print(f"❌ Ошибка получения репутации: {e}")
    finally:
        conn.close()
    
    return reps

def get_reputation_by_id(rep_id):
    """Получить отзыв по ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT r.*, u.username as from_username 
            FROM reputation r
            LEFT JOIN users u ON r.from_user = u.user_id
            WHERE r.id = %s
        ''', (rep_id,))
        
        row = cursor.fetchone()
        if row:
            from_username = row[6]
            if not from_username and row[1] is None:
                from_username = "Скрытый профиль"
            elif not from_username:
                from_username = f"id{row[1]}"
            
            return {
                'id': row[0],
                'from_user': row[1],
                'to_user': row[2],
                'text': row[3],
                'photo_id': row[4],
                'created_at': row[5],
                'from_username': from_username
            }
    except Exception as e:
        print(f"❌ Ошибка получения отзыва {rep_id}: {e}")
    finally:
        conn.close()
    
    return None

def delete_reputation_by_id(rep_id):
    """Удалить отзыв по ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM reputation WHERE id = %s', (rep_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        return deleted
    except Exception as e:
        print(f"❌ Ошибка удаления отзыва {rep_id}: {e}")
        return False
    finally:
        conn.close()

def get_reputations_by_user_id(user_id):
    """Получить все отзывы пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    reps = []
    try:
        cursor.execute('''
            SELECT r.*, u1.username as from_username, u2.username as to_username
            FROM reputation r
            LEFT JOIN users u1 ON r.from_user = u1.user_id
            LEFT JOIN users u2 ON r.to_user = u2.user_id
            WHERE r.from_user = %s OR r.to_user = %s
            ORDER BY r.created_at DESC
            LIMIT 100
        ''', (user_id, user_id))
        
        rows = cursor.fetchall()
        
        for row in rows:
            from_username = row[6]
            if not from_username and row[1] is None:
                from_username = "Скрытый профиль"
            elif not from_username:
                from_username = f"id{row[1]}"
            
            to_username = row[7]
            if not to_username:
                to_username = f"id{row[2]}"
            
            reps.append({
                'id': row[0],
                'from_user': row[1],
                'to_user': row[2],
                'text': row[3],
                'photo_id': row[4],
                'created_at': row[5],
                'from_username': from_username,
                'to_username': to_username
            })
    except Exception as e:
        print(f"❌ Ошибка получения отзывов пользователя {user_id}: {e}")
    finally:
        conn.close()
    
    return reps

def get_db_stats():
    """Статистика базы данных"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    stats = {}
    try:
        cursor.execute('SELECT COUNT(*) FROM users')
        stats['total_users'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reputation')
        stats['total_reputations'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM reputation WHERE text LIKE '%%+%%' OR text LIKE '%%+rep%%' OR text LIKE '%%+реп%%'")
        stats['positive_reps'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM reputation WHERE text LIKE '%%-%%' OR text LIKE '%%-rep%%' OR text LIKE '%%-реп%%'")
        stats['negative_reps'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT from_user) FROM reputation')
        stats['unique_senders'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT to_user) FROM reputation')
        stats['unique_receivers'] = cursor.fetchone()[0]
        
    except Exception as e:
        print(f"❌ Ошибка получения статистики: {e}")
    finally:
        conn.close()
    
    return stats

def get_user_info(user_id):
    """Получаем информацию о пользователе"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
        
        if row:
            return {
                'user_id': row[0],
                'username': row[1],
                'registered_at': row[2]
            }
    except Exception as e:
        print(f"❌ Ошибка получения пользователя {user_id}: {e}")
    finally:
        conn.close()
    
    return None

def get_user_by_username(username):
    """Ищем пользователя по username"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    username = username.lstrip('@')
    
    try:
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        row = cursor.fetchone()
        
        if row:
            return {
                'user_id': row[0],
                'username': row[1],
                'registered_at': row[2]
            }
    except Exception as e:
        print(f"❌ Ошибка поиска пользователя {username}: {e}")
    finally:
        conn.close()
    
    return None

def get_reputation_stats(user_id):
    """Статистика репутации пользователя"""
    all_reps = get_user_reputation(user_id)
    
    positive = 0
    negative = 0
    
    for rep in all_reps:
        rep_type = get_reputation_type(rep["text"])
        if rep_type == '+':
            positive += 1
        elif rep_type == '-':
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
        if get_reputation_type(rep["text"]) == '+':
            return rep
    return None

def get_last_negative(user_id):
    """Получить последний отрицательный отзыв"""
    all_reps = get_user_reputation(user_id)
    for rep in all_reps:
        if get_reputation_type(rep["text"]) == '-':
            return rep
    return None

# ========== ФУНКЦИИ ДЛЯ ТОПОВ ==========
def get_top_users_by_period(days=None, limit=10):
    """Получить топ пользователей по количеству отзывов за период"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if days:
            # За указанное количество дней
            date_filter = f"WHERE r.created_at >= NOW() - INTERVAL '{days} days'"
        else:
            # За всё время
            date_filter = ""
        
        query = f"""
            SELECT u.user_id, u.username, 
                   COUNT(r.id) as rep_count,
                   SUM(CASE WHEN r.text LIKE '%%+%%' OR r.text LIKE '%%+rep%%' OR r.text LIKE '%%+реп%%' THEN 1 ELSE 0 END) as positive_count,
                   SUM(CASE WHEN r.text LIKE '%%-%%' OR r.text LIKE '%%-rep%%' OR r.text LIKE '%%-реп%%' THEN 1 ELSE 0 END) as negative_count
            FROM users u
            LEFT JOIN reputation r ON u.user_id = r.to_user
            {date_filter}
            GROUP BY u.user_id, u.username
            HAVING COUNT(r.id) > 0
            ORDER BY rep_count DESC
            LIMIT {limit}
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        result = []
        for i, row in enumerate(rows, 1):
            result.append({
                'rank': i,
                'user_id': row[0],
                'username': row[1] or f"id{row[0]}",
                'total_reps': row[2],
                'positive': row[3],
                'negative': row[4],
                'percentage': (row[3] / row[2] * 100) if row[2] > 0 else 0
            })
        
        return result
        
    except Exception as e:
        print(f"❌ Ошибка получения топа: {e}")
        return []
    finally:
        conn.close()

def get_daily_top(limit=10):
    """Топ за день"""
    return get_top_users_by_period(days=1, limit=limit)

def get_weekly_top(limit=10):
    """Топ за неделю"""
    return get_top_users_by_period(days=7, limit=limit)

def get_monthly_top(limit=10):
    """Топ за месяц"""
    return get_top_users_by_period(days=30, limit=limit)

def get_all_time_top(limit=10):
    """Топ за всё время"""
    return get_top_users_by_period(days=None, limit=limit)

def format_top_message(top_data, period_name):
    """Форматировать сообщение с топом"""
    if not top_data:
        return f"📊 <b>Топ за {period_name}</b>\n\n📭 Данных пока нет"
    
    message = f"🏆 <b>ТОП ПО РЕПУТАЦИИ</b>\n📅 <i>{period_name}</i>\n\n"
    
    for user in top_data:
        medal = ""
        if user['rank'] == 1:
            medal = "🥇"
        elif user['rank'] == 2:
            medal = "🥈"
        elif user['rank'] == 3:
            medal = "🥉"
        else:
            medal = f"{user['rank']}."
        
        username_display = f"@{user['username']}" if user['username'] and not user['username'].startswith('id') else user['username']
        
        message += f"{medal} {username_display}\n"
        message += f"   📊 Всего: {user['total_reps']} отзывов\n"
        message += f"   ✅ Положительных: {user['positive']} ({user['percentage']:.0f}%)\n"
        message += f"   ❌ Отрицательных: {user['negative']}\n"
        message += f"   🆔 ID: {user['user_id']}\n\n"
    
    return message

# ========== РЕЗЕРВНОЕ КОПИРОВАНИЕ ==========
class SimpleBackup:
    def __init__(self):
        self.backup_dir = "database_backups"
        os.makedirs(self.backup_dir, exist_ok=True)
    
    async def create_backup(self, update: Update, context: CallbackContext):
        """Создать бэкап базы данных (Python версия)"""
        user_id = update.effective_user.id
        
        if user_id not in ADMINS:
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        msg = await update.message.reply_text("Создание бэкапа...")
        
        try:
            print("1. Начинаю создание бэкапа...")
            
            timestamp = datetime.now().strftime("%d%m%y_%H%M")
            filename = f"backup_{timestamp}.sql"
            filepath = os.path.join(self.backup_dir, filename)
            
            print(f"2. Файл: {filepath}")
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            print("3. Подключился к базе")
            
            # Создаём SQL файл вручную
            with open(filepath, 'w', encoding='utf-8') as f:
                # 1. Заголовок
                f.write(f"-- Backup TESS Reputation Bot\n")
                f.write(f"-- Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                print("4. Начинаю выгрузку users...")
                # 2. Таблица users
                cursor.execute("SELECT * FROM users")
                users = cursor.fetchall()
                print(f"5. Нашёл {len(users)} пользователей")
                
                f.write("-- Table: users\n")
                f.write("TRUNCATE TABLE users CASCADE;\n")
                for user in users:
                    user_id_db = user[0]
                    username = str(user[1]).replace("'", "''") if user[1] else "NULL"
                    registered_at = str(user[2]).replace("'", "''") if user[2] else "NULL"
                    f.write(f"INSERT INTO users (user_id, username, registered_at) VALUES ({user_id_db}, '{username}', '{registered_at}');\n")
                
                print("6. Начинаю выгрузку reputation...")
                # 3. Таблица reputation
                cursor.execute("SELECT * FROM reputation ORDER BY id")
                reps = cursor.fetchall()
                print(f"7. Нашёл {len(reps)} отзывов")
                
                f.write("\n-- Table: reputation\n")
                f.write("TRUNCATE TABLE reputation CASCADE;\n")
                for rep in reps:
                    rep_id = rep[0]
                    from_user = rep[1] if rep[1] is not None else "NULL"
                    to_user = rep[2]
                    text = str(rep[3]).replace("'", "''") if rep[3] else "NULL"
                    photo_id = str(rep[4]).replace("'", "''") if rep[4] else "NULL"
                    created_at = str(rep[5]).replace("'", "''") if rep[5] else "NULL"
                    f.write(f"INSERT INTO reputation (id, from_user, to_user, text, photo_id, created_at) VALUES ({rep_id}, {from_user}, {to_user}, '{text}', '{photo_id}', '{created_at}');\n")
            
            conn.close()
            print("8. База закрыта")
            
            # Архивируем
            with open(filepath, 'rb') as f_in:
                with gzip.open(filepath + '.gz', 'wb') as f_out:
                    f_out.write(f_in.read())
            
            # Удаляем несжатый файл
            os.remove(filepath)
            filepath = filepath + '.gz'
            filename = filename + '.gz'
            
            size_bytes = os.path.getsize(filepath)
            size_mb = size_bytes / (1024 * 1024)
            
            print(f"9. Бэкап создан: {filename}, размер: {size_mb} MB")
            
            # Просто показываем сообщение без кнопок, так как это edit_text
            await msg.edit_text(
                f"✅ Бэкап создан\n"
                f"📁 Файл: {filename}\n"
                f"📊 Размер: {size_mb:.2f} MB\n"
                f"📅 Дата: {datetime.now().strftime('%d.%m %H:%M')}\n"
                f"📊 Записей: {len(users)} пользователей, {len(reps)} отзывов"
            )
            
            # Отправляем отдельное сообщение с меню
            await update.message.reply_text(
                "Что дальше?",
                reply_markup=get_backup_menu_keyboard()
            )
            
        except Exception as e:
            print(f"❌ ОШИБКА в create_backup: {e}")
            import traceback
            traceback.print_exc()
            await msg.edit_text(f"Ошибка: {str(e)[:200]}")
    
    async def show_backups(self, update: Update, context: CallbackContext):
        """Показать список доступных бэкапов с кнопками"""
        user_id = update.effective_user.id
        
        if user_id not in ADMINS:
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        backups = glob.glob(os.path.join(self.backup_dir, "*.sql.gz"))
        backups.sort(key=os.path.getmtime, reverse=True)
        
        if not backups:
            await update.message.reply_text("Бэкапов нет", reply_markup=get_backup_menu_keyboard())
            return
        
        text = "Доступные бэкапы:\n\n"
        keyboard = []
        
        for i, backup in enumerate(backups[:5], 1):
            name = os.path.basename(backup)[7:-7]
            size = os.path.getsize(backup) / (1024 * 1024)
            date = datetime.fromtimestamp(os.path.getmtime(backup)).strftime('%d.%m %H:%M')
            text += f"{i}. {name} ({size:.1f} MB) - {date}\n"
            
            # Добавляем инлайн-кнопку для каждого бэкапа
            keyboard.append([InlineKeyboardButton(
                f"Восстановить {i}", 
                callback_data=f"restore_{i}"
            )])
        
        # Добавляем кнопку "Отмена"
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="backup_cancel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup)
        
        context.user_data['backups_list'] = backups
    
    async def restore_backup(self, update: Update, context: CallbackContext, backup_index=None):
        """Восстановить базу из бэкапа"""
        user_id = update.effective_user.id
        
        if user_id not in ADMINS:
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        if backup_index is not None:
            # Вызвано из инлайн-кнопки
            backups = context.user_data.get('backups_list', [])
            idx = backup_index - 1
            
            if idx < 0 or idx >= len(backups):
                await update.message.reply_text("❌ Неверный номер", reply_markup=get_backup_menu_keyboard())
                return
            
            backup_file = backups[idx]
            context.user_data['restore_file'] = backup_file
            
            filename = os.path.basename(backup_file)
            size = os.path.getsize(backup_file) / (1024 * 1024)
            date = datetime.fromtimestamp(os.path.getmtime(backup_file)).strftime('%d.%m %H:%M')
            
            # Используем инлайн-кнопки для подтверждения
            keyboard = [
                [InlineKeyboardButton("✅ Да, восстановить", callback_data="confirm_restore")],
                [InlineKeyboardButton("❌ Нет, отменить", callback_data="cancel_restore")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Для инлайн-режима нужно редактировать сообщение
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    f"Восстановить из:\n{filename}\n"
                    f"Размер: {size:.1f} MB\n"
                    f"Дата: {date}\n\n"
                    f"Все текущие данные будут перезаписаны!",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    f"Восстановить из:\n{filename}\n"
                    f"Размер: {size:.1f} MB\n"
                    f"Дата: {date}\n\n"
                    f"Все текущие данные будут перезаписаны!",
                    reply_markup=reply_markup
                )
            return
        
        # Если вызвано из текстового меню
        if not context.user_data.get('backups_list'):
            await update.message.reply_text(
                "Сначала просмотрите список бэкапов",
                reply_markup=get_backup_menu_keyboard()
            )
            return
    async def perform_restore(self, update: Update, context: CallbackContext):
        backup_file = context.user_data.get('restore_file')
        
        # Определяем message
        if update.callback_query:
            message = update.callback_query.message
        else:
            message = update.message
        
        if not backup_file or not os.path.exists(backup_file):
            await message.reply_text("Файл не найден", reply_markup=get_backup_menu_keyboard())
            context.user_data.pop('restore_file', None)
            return
        
        msg = await message.reply_text("Восстановление...")
        
        try:
            with gzip.open(backup_file, 'rt', encoding='utf-8') as f:
                sql_content = f.read()
            
            conn = get_db_connection()
            cursor = conn.cursor()
            sql_commands = sql_content.split(';')
            
            for cmd in sql_commands:
                cmd = cmd.strip()
                if cmd and not cmd.startswith('--'):
                    try:
                        cursor.execute(cmd)
                    except Exception as e:
                        print(f"Ошибка SQL: {cmd[:50]}... - {e}")
            
            conn.commit()
            conn.close()
            
            await msg.edit_text("✅ База восстановлена")
            await message.reply_text("Меню:", reply_markup=get_backup_menu_keyboard())
            
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")
        
        context.user_data.pop('restore_file', None)
        context.user_data.pop('backups_list', None)
    
    async def auto_cleanup(self, update: Update, context: CallbackContext):
        """Автоочистка старых бэкапов"""
        user_id = update.effective_user.id
        
        if user_id not in ADMINS:
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        try:
            backups = glob.glob(os.path.join(self.backup_dir, "*.sql.gz"))
            backups.sort(key=os.path.getmtime, reverse=True)
            
            if len(backups) <= 1:
                await update.message.reply_text(
                    "Нет старых бэкапов для очистки",
                    reply_markup=get_backup_menu_keyboard()
                )
                return
            
            deleted_count = 0
            freed_space = 0
            
            for old_backup in backups[1:]:
                try:
                    size = os.path.getsize(old_backup)
                    os.remove(old_backup)
                    deleted_count += 1
                    freed_space += size
                except:
                    pass
            
            if deleted_count > 0:
                freed_mb = freed_space / (1024 * 1024)
                
                # Получаем информацию об оставшемся бэкапе
                remaining_backup = backups[0] if backups else None
                if remaining_backup and os.path.exists(remaining_backup):
                    remaining_size = os.path.getsize(remaining_backup) / (1024 * 1024)
                    remaining_name = os.path.basename(remaining_backup)
                    
                    await update.message.reply_text(
                        f"Автоочистка выполнена\n\n"
                        f"Удалено: {deleted_count} файлов\n"
                        f"Освобождено: {freed_mb:.1f} MB\n\n"
                        f"Оставлен бэкап:\n"
                        f"{remaining_name} ({remaining_size:.1f} MB)",
                        reply_markup=get_backup_menu_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        f"Автоочистка выполнена\n\n"
                        f"Удалено: {deleted_count} файлов\n"
                        f"Освобождено: {freed_mb:.1f} MB",
                        reply_markup=get_backup_menu_keyboard()
                    )
            else:
                await update.message.reply_text(
                    "Не удалось удалить старые бэкапы",
                    reply_markup=get_backup_menu_keyboard()
                )
                
        except Exception as e:
            await update.message.reply_text(
                f"Ошибка автоочистки: {str(e)[:100]}",
                reply_markup=get_backup_menu_keyboard()
            )

# Создаем глобальный объект для бэкапов
backup_manager = SimpleBackup()

# ========== ТЕЛЕГРАМ HANDLERS ==========
async def quick_profile(update: Update, context: CallbackContext) -> None:
    """Быстрый просмотр профиля в чате - команда /и"""
    if update.message.chat.type == 'private':
        # В личных сообщениях не работает
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username or f"id{user_id}"
    
    # Сохраняем текущего пользователя
    save_user(user_id, username)
    
    # Определяем целевого пользователя
    target_user_id = None
    target_username = None
    
    # Проверяем аргументы команды
    if context.args and len(context.args) > 0:
        arg = context.args[0].strip()
        
        # Вариант 1: ID пользователя
        if arg.isdigit():
            target_user_id = int(arg)
            target_username = f"id{target_user_id}"
        
        # Вариант 2: @username
        elif arg.startswith('@'):
            username_search = arg[1:]  # Убираем @
            user_info = get_user_by_username(username_search)
            if user_info:
                target_user_id = user_info['user_id']
                target_username = user_info['username'] or f"id{target_user_id}"
            else:
                await update.message.reply_text(
                    "❌ Пользователь не найден в базе\n\n"
                    "Отправьте репутацию этому пользователю, чтобы добавить его в базу.",
                    parse_mode='HTML'
                )
                return
        
        # Вариант 3: username без @
        else:
            user_info = get_user_by_username(arg)
            if user_info:
                target_user_id = user_info['user_id']
                target_username = user_info['username'] or f"id{target_user_id}"
            else:
                # Проверяем, может быть это ID без @
                if arg.startswith('id') and arg[2:].isdigit():
                    target_user_id = int(arg[2:])
                    target_username = arg
                else:
                    await update.message.reply_text(
                        "❌ Пользователь не найден в базе\n\n"
                        "Отправьте репутацию этому пользователю, чтобы добавить его в базу.",
                        parse_mode='HTML'
                    )
                    return
    
    # Если нет аргументов, проверяем реплай
    elif update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        target_user_id = target_user.id
        target_username = target_user.username or f"id{target_user_id}"
    
    # Если нет ни аргументов, ни реплая - показываем профиль автора
    else:
        target_user_id = user_id
        target_username = username
    
    # Сохраняем целевого пользователя
    save_user(target_user_id, target_username)
    
    # Получаем информацию о пользователе
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
                [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("🏆 Моя репутация", callback_data='my_reputation')],
                [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')]
            ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_fake_i_command(update: Update, context: CallbackContext):
    """Эмуляция команды /и (работает только в группах)"""
    if update.message.chat.type == 'private':
        return  # Не работаем в личке
    await quick_profile(update, context)  # Используем ту же логику
    
async def start(update: Update, context: CallbackContext) -> None:
    """Команда /start в личных сообщениях"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    
    save_user(user_id, username)
    
    # Показываем клавиатуру админам
    if user_id in ADMINS:
        await update.message.reply_text(
            "Клавиатура админа активирована.",
            reply_markup=get_admin_keyboard()
        )
    
    if context.args and context.args[0].startswith('view_'):
        try:
            target_user_id = int(context.args[0].replace('view_', ''))
            context.user_data['found_user_id'] = target_user_id
            context.user_data['from_group'] = True
            
            await show_profile_with_working_buttons(update, target_user_id, context)
            return
        except:
            pass
    
    text = f"""<b>🛡️TESS | Репутация — вселенная безграничных возможностей!</b>
ID - [{user_id}]

• Здесь можно отправить или просмотреть репутацию пользователя, а также провести сделку! Выберите раздел:"""
    
    keyboard = [
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🔎 Найти пользователя", callback_data='search_user')],
        [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_photo(
            photo=PHOTO_URL,
            caption=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"❌ Ошибка отправки фото: {e}")
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

# ========== АДМИН ПАНЕЛЬ ==========
async def handle_admin_panel(update: Update, context: CallbackContext) -> None:
    """Обработка кнопки админ-панели"""
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    text = "Админ панель\n\nВыберите действие:"
    
    await update.message.reply_text(
        text,
        reply_markup=get_admin_menu_keyboard()
    )

async def handle_admin_menu(update: Update, context: CallbackContext) -> None:
    """Обработка меню админ-панели"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    if text == "❌ Отмена":
        context.user_data.pop('admin_action', None)
        context.user_data.pop('user_to_delete_reps', None)
        context.user_data.pop('rep_to_delete', None)
        context.user_data.pop('broadcast_text', None)
        
        # Определяем, откуда была отмена
        if 'waiting_days_input' in context.user_data:
            context.user_data.pop('admin_action', None)
            await update.message.reply_text(
                "Отменено",
                reply_markup=get_top_menu_keyboard()
            )
        else:
            await update.message.reply_text(
                "Отменено",
                reply_markup=get_admin_menu_keyboard()
            )
        return
    
    if text == "Главное меню":
        await update.message.reply_text(
            "Возврат в главное меню",
            reply_markup=get_admin_keyboard()
        )
        return
    
    if text == "Резервное копирование":
        await update.message.reply_text(
            "Резервное копирование\n\nВыберите действие:",
            reply_markup=get_backup_menu_keyboard()
        )
        return
    
    if text == "Назад в админ-панель":
        await update.message.reply_text(
            "Возврат в админ-панель",
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    if text == "Создать бэкап":
        await backup_manager.create_backup(update, context)
        return
    
    if text == "Показать бэкапы":
        await backup_manager.show_backups(update, context)
        return
    
    if text == "Восстановить":
        await backup_manager.show_backups(update, context)
        return
    
    if text == "Автоочистка":
        await backup_manager.auto_cleanup(update, context)
        return
    
    if text == "✅ Да, восстановить":
        if 'restore_file' in context.user_data:
            await backup_manager.perform_restore(update, context)
        return
    
    if text == "❌ Нет, отменить":
        await update.message.reply_text(
            "Восстановление отменено",
            reply_markup=get_backup_menu_keyboard()
        )
        context.user_data.pop('restore_file', None)
        context.user_data.pop('backups_list', None)
        return
    
    if text == "Удалить отзыв":
        context.user_data['admin_action'] = 'select_user_for_deletion'
        await update.message.reply_text(
            "Введите ID пользователя, чьи отзывы хотите удалить:\n\n(или отправьте ❌ Отмена)",
            reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
        )
        return
    
    if text == "Статистика":
        stats = get_db_stats()
        message = f"""Статистика базы данных

Пользователей: {stats.get('total_users', 0)}
Всего отзывов: {stats.get('total_reputations', 0)}
Положительных: {stats.get('positive_reps', 0)}
Отрицательных: {stats.get('negative_reps', 0)}
Отправителей: {stats.get('unique_senders', 0)}
Получателей: {stats.get('unique_receivers', 0)}"""
        
        await update.message.reply_text(
            message,
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    if text == "Рассылка":
        context.user_data['admin_action'] = 'broadcast'
        await update.message.reply_text(
            "Введите текст для рассылки всем пользователям:\n\n(или отправьте ❌ Отмена)",
            reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
        )
        return
    
    if text == "Топ по репутации":
        await update.message.reply_text(
            "📊 <b>Топы по репутации</b>\n\nВыберите период:",
            reply_markup=get_top_menu_keyboard(),
            parse_mode='HTML'
        )
        return
    
    if text == "Топ за день":
        top_data = get_daily_top(limit=15)
        message = format_top_message(top_data, "за день")
        await update.message.reply_text(
            message,
            reply_markup=get_top_menu_keyboard(),
            parse_mode='HTML'
        )
        return
    
    if text == "Топ за неделю":
        top_data = get_weekly_top(limit=15)
        message = format_top_message(top_data, "за неделю")
        await update.message.reply_text(
            message,
            reply_markup=get_top_menu_keyboard(),
            parse_mode='HTML'
        )
        return
    
    if text == "Топ за месяц":
        top_data = get_monthly_top(limit=15)
        message = format_top_message(top_data, "за месяц")
        await update.message.reply_text(
            message,
            reply_markup=get_top_menu_keyboard(),
            parse_mode='HTML'
        )
        return
    
    if text == "Топ за всё время":
        top_data = get_all_time_top(limit=15)
        message = format_top_message(top_data, "за всё время")
        await update.message.reply_text(
            message,
            reply_markup=get_top_menu_keyboard(),
            parse_mode='HTML'
        )
        return
    
    if text == "Топ за N дней":
        context.user_data['admin_action'] = 'waiting_days_input'
        await update.message.reply_text(
            "🔢 <b>Введите количество дней:</b>\n\nНапример: 5, 10, 100\n(или отправьте ❌ Отмена)",
            reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True),
            parse_mode='HTML'
        )
        return
    
    if text == "✅ Да, удалить":
        rep_id = context.user_data.get('rep_to_delete')
        if not rep_id:
            await update.message.reply_text("❌ Ошибка: ID отзыва не найден", reply_markup=get_admin_menu_keyboard())
            return
        
        if delete_reputation_by_id(rep_id):
            message = f"✅ Отзыв #{rep_id} успешно удален"
        else:
            message = f"❌ Ошибка при удалении отзыва #{rep_id}"
        
        await update.message.reply_text(
            message,
            reply_markup=get_admin_menu_keyboard()
        )
        
        context.user_data.pop('admin_action', None)
        context.user_data.pop('user_to_delete_reps', None)
        context.user_data.pop('rep_to_delete', None)
    
    elif text == "❌ Нет":
        await update.message.reply_text(
            "Удаление отменено",
            reply_markup=get_admin_menu_keyboard()
        )
        context.user_data.pop('admin_action', None)
        context.user_data.pop('rep_to_delete', None)
    
    elif text == "✅ Да, отправить":
        broadcast_text = context.user_data.get('broadcast_text')
        if not broadcast_text:
            await update.message.reply_text("❌ Текст рассылки не найден", reply_markup=get_admin_menu_keyboard())
            return
        
        users = get_all_users()
        total = len(users)
        
        if total == 0:
            await update.message.reply_text("❌ Нет пользователей для рассылки", reply_markup=get_admin_menu_keyboard())
            return
        
        progress_msg = await update.message.reply_text(f"Начинаю рассылку... 0/{total}")
        
        success = 0
        failed = 0
        
        for i, user in enumerate(users):
            try:
                await context.bot.send_message(
                    chat_id=user['user_id'],
                    text=broadcast_text
                )
                success += 1
            except Exception as e:
                failed += 1
            
            if i % 10 == 0 or i == total - 1:
                try:
                    await progress_msg.edit_text(
                        f"Рассылка... {i+1}/{total}\n"
                        f"Успешно: {success}\n"
                        f"Ошибок: {failed}"
                    )
                except:
                    pass
        
        await update.message.reply_text(
            f"✅ Рассылка завершена!\n\n"
            f"Всего пользователей: {total}\n"
            f"Отправлено: {success}\n"
            f"Не отправлено: {failed}\n\n"
            f"Текст рассылки:\n{broadcast_text[:200]}{'...' if len(broadcast_text) > 200 else ''}",
            reply_markup=get_admin_menu_keyboard()
        )
        
        context.user_data.pop('admin_action', None)
        context.user_data.pop('broadcast_text', None)

async def handle_admin_input(update: Update, context: CallbackContext) -> None:
    """Обработка ввода от админа"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    action = context.user_data.get('admin_action')
    
    if not action:
        await update.message.reply_text(
            "Выберите действие в меню:",
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    if action == 'select_user_for_deletion':
        if not text.isdigit():
            await update.message.reply_text("❌ Введите числовой ID пользователя")
            return
        
        target_id = int(text)
        context.user_data['user_to_delete_reps'] = target_id
        
        await show_user_reputations_for_deletion(update, target_id)
        context.user_data['admin_action'] = 'waiting_for_rep_selection'
    
    elif action == 'broadcast':
        if not text or text.strip() == "":
            await update.message.reply_text("❌ Введите текст для рассылки")
            return
        
        context.user_data['broadcast_text'] = text.strip()
        
        users = get_all_users()
        total = len(users)
        
        preview = text.strip()
        if len(preview) > 100:
            preview = preview[:97] + "..."
        
        await update.message.reply_text(
            f"Предпросмотр рассылки\n\n"
            f"{text.strip()}\n\n"
            f"Отправить {total} пользователям?\n\n"
            f"Текст ({len(text.strip())} символов):\n{preview}",
            reply_markup=ReplyKeyboardMarkup([
                ['✅ Да, отправить', '❌ Нет, отменить']
            ], resize_keyboard=True)
        )
    
    elif action == 'waiting_days_input':
        if not text.isdigit():
            await update.message.reply_text("❌ Введите число (например: 5, 30, 100)")
            return
        
        days = int(text)
        
        if days <= 0:
            await update.message.reply_text("❌ Число должно быть больше 0")
            return
        
        if days > 3650:  # 10 лет максимум
            await update.message.reply_text("❌ Максимум 3650 дней (10 лет)")
            return
        
        top_data = get_top_users_by_period(days=days, limit=15)
        
        if not top_data:
            await update.message.reply_text(
                f"📊 <b>Топ за {days} дней</b>\n\n📭 За этот период нет отзывов",
                reply_markup=get_top_menu_keyboard(),
                parse_mode='HTML'
            )
        else:
            message = f"<b>📊 ТОП ПО РЕПУТАЦИИ</b>\n"
            message += f"<i>За последние {days} дней</i>\n\n"
            
            for i, user in enumerate(top_data[:10], 1):
                medal = ""
                if i == 1:
                    medal = "🥇"
                elif i == 2:
                    medal = "🥈"
                elif i == 3:
                    medal = "🥉"
                else:
                    medal = f"{i}."
                
                username_display = f"@{user['username']}" if user['username'] and not user['username'].startswith('id') else user['username']
                
                message += f"{medal} {username_display}\n"
                message += f"   📊 Всего: {user['total_reps']} отз.\n"
                message += f"   ✅ Положительных: {user['positive']} ({user['percentage']:.0f}%)\n"
                message += f"   🆔 ID: {user['user_id']}\n\n"
            
            if len(top_data) > 10:
                message += f"... и еще {len(top_data) - 10} пользователей"
        
        await update.message.reply_text(
            message,
            reply_markup=get_top_menu_keyboard(),
            parse_mode='HTML'
        )
        
        # Очищаем состояние
        context.user_data.pop('admin_action', None)
        return

async def show_user_reputations_for_deletion(update: Update, user_id: int):
    """Показать отзывы пользователя с кнопками удаления"""
    reps = get_reputations_by_user_id(user_id)
    
    if not reps:
        await update.message.reply_text(
            f"У пользователя ID{user_id} нет отзывов",
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    for i, rep in enumerate(reps[:10]):
        rep_type = get_reputation_type(rep["text"])
        type_emoji = "🪄"
        
        short_text = rep['text']
        if len(short_text) > 50:
            short_text = short_text[:47] + "..."
        
        date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
        
        if rep['to_user'] == user_id:
            direction = f"Получил от {rep['from_username']}"
        else:
            direction = f"Отправил {rep['to_username']}"
        
        message = f"""Отзыв #{rep['id']}
{direction}
{short_text}
{date}"""
        
        keyboard = [
            [
                InlineKeyboardButton("🗑 Удалить", callback_data=f"admin_delete_rep_{rep['id']}"),
                InlineKeyboardButton("👁 Просмотр", callback_data=f"admin_view_rep_{rep['id']}")
            ]
        ]
        
        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    if len(reps) > 10:
        await update.message.reply_text(f"... и еще {len(reps) - 10} отзывов")
    
    await update.message.reply_text(
        "Выберите отзыв для удаления или нажмите ❌ Отмена",
        reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
    )

async def handle_admin_callback(update: Update, context: CallbackContext) -> None:
    """Обработка inline-кнопок админ-панели"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMINS:
        await query.answer("Доступ запрещен", show_alert=True)
        return
    
    data = query.data
    
    if data.startswith('admin_delete_rep_'):
        rep_id = int(data.replace('admin_delete_rep_', ''))
        
        context.user_data['rep_to_delete'] = rep_id
        
        rep_data = get_reputation_by_id(rep_id)
        if rep_data:
            rep_type = get_reputation_type(rep_data["text"])
            type_text = "Положительный" if rep_type == '+' else "Отрицательный"
            date = datetime.fromisoformat(rep_data["created_at"]).strftime("%d/%m/%Y %H:%M")
            
            message = f"""Отзыв #{rep_id} ({type_text})

От: {rep_data['from_username']}
Кому: id{rep_data['to_user']}
Дата: {date}
Текст: {rep_data['text'][:100]}...

Удалить этот отзыв?"""
            
            try:
                await query.message.delete()
            except:
                pass
            
            await query.message.chat.send_message(
                message,
                reply_markup=ReplyKeyboardMarkup([
                    ['✅ Да, удалить', '❌ Нет']
                ], resize_keyboard=True)
            )
    
    elif data.startswith('admin_view_rep_'):
        rep_id = int(data.replace('admin_view_rep_', ''))
        
        rep_data = get_reputation_by_id(rep_id)
        if rep_data and rep_data['photo_id']:
            rep_type = get_reputation_type(rep_data["text"])
            type_text = "Положительный отзыв" if rep_type == '+' else "Отрицательный отзыв"
            
            date = datetime.fromisoformat(rep_data["created_at"]).strftime("%d/%m/%Y %H:%M")
            
            caption = f"""<b>{type_text}</b>

От: {rep_data['from_username']}
ID: {rep_data['from_user'] if rep_data['from_user'] else "Неизвестно"}
Дата: {date}

Текст:
{rep_data['text']}"""
            
            try:
                await query.message.chat.send_photo(
                    photo=rep_data['photo_id'],
                    caption=caption,
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"❌ Ошибка отправки фото: {e}")
                await query.message.chat.send_message(
                    f"{caption}\n\n⚠️ Фото недоступно",
                    parse_mode='HTML'
                )
        else:
            await query.answer("Отзыв не найден", show_alert=True)
    
    # Обработка кнопок бэкапов
    elif data.startswith('restore_'):
        try:
            backup_index = int(data.replace('restore_', ''))
            await backup_manager.restore_backup(update, context, backup_index)
        except Exception as e:
            print(f"❌ Ошибка обработки restore: {e}")
            await query.answer("Ошибка обработки", show_alert=True)
    
    elif data == "backup_cancel":
        await query.edit_message_text(
            "Отменено"
        )
        await query.message.chat.send_message(
            "Возврат в меню бэкапов",
            reply_markup=get_backup_menu_keyboard()
        )
    
    elif data == "confirm_restore":
        if 'restore_file' in context.user_data:
            await backup_manager.perform_restore(update, context)
        else:
            await query.answer("Файл бэкапа не найден", show_alert=True)
    
    elif data == "cancel_restore":
        await query.edit_message_text(
            "Восстановление отменено"
        )
        await query.message.chat.send_message(
            "Возврат в меню бэкапов",
            reply_markup=get_backup_menu_keyboard()
        )
        context.user_data.pop('restore_file', None)
        context.user_data.pop('backups_list', None)

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ ==========
async def show_profile_with_working_buttons(update: Update, target_user_id: int, context: CallbackContext):
    """Показать профиль пользователя с кнопками при переходе из чата"""
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
        registration_date = datetime.now().strftime("%d/%m/Y")
    
    text = f"""{display_username} (ID: {target_user_id})

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote><blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

<b>ВНИМАТЕЛЬНО СМОТРИТЕ ПОЛЕ «О СЕБЕ»</b>

💳 Депозит: отсутствует

🗓️ Зарегистрирован: {registration_date}"""
    
    context.user_data['found_user_id'] = target_user_id
    
    keyboard = [
        [InlineKeyboardButton("🪄 Посмотреть репутацию", callback_data='view_found_user_reputation')],
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_photo(
            photo=PHOTO_URL,
            caption=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"❌ Ошибка отправки фото: {e}")
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_reputation_photo(update: Update, rep_id: int, back_context: str, context: CallbackContext) -> None:
    """Показать фото отзыва с информацией"""
    query = update.callback_query
    await query.answer()
    
    rep_data = get_reputation_by_id(rep_id)
    if not rep_data:
        await query.answer("Отзыв не найден", show_alert=True)
        return
    
    target_user_id = rep_data['to_user']
    current_user_id = query.from_user.id
    
    if context.user_data.get('from_group') and target_user_id != current_user_id:
        back_context = 'back_from_group_view'
    
    rep_type = get_reputation_type(rep_data["text"])
    type_text = "Положительный отзыв" if rep_type == '+' else "Отрицательный отзыв"
    
    from_username = rep_data["from_username"]
    user_id_display = rep_data["from_user"] if rep_data["from_user"] else "Неизвестно"
    
    date = datetime.fromisoformat(rep_data["created_at"]).strftime("%d/%m/%Y %H:%M")
    
    caption = f"""<b>{type_text}</b>

От: {from_username}
ID: {user_id_display}
Дата: {date}

Текст:
{rep_data['text']}"""
    
    keyboard = [
        [InlineKeyboardButton("↩️ Назад к списку", callback_data=back_context)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=rep_data['photo_id'],
                caption=caption,
                parse_mode='HTML'
            ),
            reply_markup=reply_markup
        )
    except Exception as e:
        print(f"❌ Ошибка редактирования фото: {e}")
        try:
            await query.edit_message_caption(
                caption=f"{caption}\n\n⚠️ Фото недоступно",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        except Exception as e2:
            print(f"❌ Ошибка редактирования подписи: {e2}")
            try:
                await query.edit_message_text(
                    text=f"{caption}\n\n⚠️ Фото недоступно",
                    reply_markup=reply_markup,
                    parse_mode='HTML'
                )
            except Exception as e3:
                print(f"❌ Ошибка редактирования текста: {e3}")

async def show_my_reputation_menu(query, rep_type='all'):
    """Показать меню репутации с кнопками для просмотра фото"""
    user_id = query.from_user.id
    stats = get_reputation_stats(user_id)
    
    if rep_type == 'positive':
        filtered_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '+']
        title = "Положительные отзывы"
    elif rep_type == 'negative':
        filtered_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '-']
        title = "Отрицательные отзывы"
    else:
        filtered_reps = stats['all_reps']
        title = "Все отзывы"
    
    if not filtered_reps:
        text = f"{title}\n\n📭 Отзывов пока нет"
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='my_reputation')]]
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=PHOTO_URL,
                    caption=text,
                    parse_mode='HTML'
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"❌ Ошибка редактирования фото: {e}")
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        return
    
    text = f"<b>{title}</b>\n\n"
    keyboard = []
    
    for i, rep in enumerate(filtered_reps[:10], 1):
        rep_type_char = get_reputation_type(rep["text"])
        emoji = "🪄"
        from_user = rep.get("from_username", f"id{rep['from_user']}")
        date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
        
        short_text = rep['text']
        if len(short_text) > 40:
            short_text = short_text[:37] + "..."
        
        text += f"{i}. От {from_user}\n"
        text += f"   {short_text}\n"
        text += f"   {date}\n\n"
        
        keyboard.append([InlineKeyboardButton(
            f"{i}. {from_user} - {date}",
            callback_data=f"view_photo_{rep['id']}_{rep_type}"
        )])
    
    if len(filtered_reps) > 10:
        text += f"\n... и еще {len(filtered_reps) - 10} отзывов"
    
    keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data='my_reputation')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=PHOTO_URL,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=reply_markup
        )
    except Exception as e:
        print(f"❌ Ошибка редактирования фото: {e}")
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def show_found_user_reputation_menu(query, target_user_id, rep_type='all'):
    """Показать меню репутации найденного пользователя"""
    user_info = get_user_info(target_user_id)
    username = user_info.get("username", "") if user_info else f"id{target_user_id}"
    
    stats = get_reputation_stats(target_user_id)
    
    if rep_type == 'positive':
        filtered_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '+']
        title = f"Положительные отзывы @{username}"
    elif rep_type == 'negative':
        filtered_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '-']
        title = f"Отрицательные отзывы @{username}"
    else:
        filtered_reps = stats['all_reps']
        title = f"Все отзывы @{username}"
    
    if not filtered_reps:
        text = f"{title}\n\n📭 Отзывов пока нет"
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='view_found_user_reputation')]]
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=PHOTO_URL,
                    caption=text,
                    parse_mode='HTML'
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"❌ Ошибка редактирования фото: {e}")
            await query.edit_message_text(
                text=text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='HTML'
            )
        return
    
    text = f"<b>{title}</b>\n\n"
    keyboard = []
    
    for i, rep in enumerate(filtered_reps[:10], 1):
        rep_type_char = get_reputation_type(rep["text"])
        emoji = "🪄"
        from_user = rep.get("from_username", f"id{rep['from_user']}")
        date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
        
        short_text = rep['text']
        if len(short_text) > 40:
            short_text = short_text[:37] + "..."
        
        text += f"{i}. От {from_user}\n"
        text += f"   {short_text}\n"
        text += f"   {date}\n\n"
        
        keyboard.append([InlineKeyboardButton(
            f"{i}. {from_user} - {date}",
            callback_data=f"found_view_photo_{rep['id']}_{rep_type}"
        )])
    
    if len(filtered_reps) > 10:
        text += f"\n... и еще {len(filtered_reps) - 10} отзывов"
    
    keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data='view_found_user_reputation')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=PHOTO_URL,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=reply_markup
        )
    except Exception as e:
        print(f"❌ Ошибка редактирования фото: {e}")
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

async def button_handler(update: Update, context: CallbackContext) -> None:
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('admin_'):
        await handle_admin_callback(update, context)
        return
    
    # Обработка кнопок бэкапов
    if (query.data.startswith('restore_') or 
        query.data == 'backup_cancel' or 
        query.data == 'confirm_restore' or 
        query.data == 'cancel_restore'):
        await handle_admin_callback(update, context)
        return
    
    if query.data.startswith('view_photo_'):
        parts = query.data.split('_')
        if len(parts) >= 4:
            rep_id = int(parts[2])
            rep_type = parts[3]
            back_context = f"back_to_list_{rep_type}"
            await show_reputation_photo(update, rep_id, back_context, context)
        return
    
    if query.data.startswith('back_to_list_'):
        rep_type = query.data.replace('back_to_list_', '')
        await show_my_reputation_menu(query, rep_type)
        return
    
    if query.data == 'back_from_group_view':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_reputation_selection_menu(query, is_own=False, target_user_id=target_user_id)
        else:
            await show_main_menu(query)
        return
    
    if query.data.startswith('found_view_photo_'):
        parts = query.data.split('_')
        if len(parts) >= 5:
            rep_id = int(parts[3])
            rep_type = parts[4]
            if context.user_data.get('from_group'):
                back_context = 'back_from_group_view'
            else:
                back_context = f"found_back_to_list_{rep_type}_{context.user_data.get('found_user_id', 0)}"
            
            await show_reputation_photo(update, rep_id, back_context, context)
        return
    
    if query.data.startswith('found_back_to_list_'):
        parts = query.data.split('_')
        if len(parts) >= 5:
            rep_type = parts[3]
            target_user_id = int(parts[4])
            if target_user_id > 0:
                await show_found_user_reputation_menu(query, target_user_id, rep_type)
            else:
                await query.edit_message_text("Ошибка: пользователь не найден")
        return
    
    if query.data == 'send_reputation':
        text = """<b><i>🛡️Отправьте репутацию.</i></b>

• К репутации необходимо приложить хотя бы одну фотографию.
<blockquote>Пример «+rep @username все идеально»
Пример «-rep [id] сделка не зашла»</blockquote>

<b>• Отправляйте репутацию строго по шаблону.</b>"""
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=PHOTO_URL,
                    caption=text,
                    parse_mode='HTML'
                ),
                reply_markup=reply_markup
            )
        except Exception as e:
            print(f"❌ Ошибка редактирования фото: {e}")
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')
        
        context.user_data['waiting_for_rep'] = True
    
    elif query.data == 'search_user':
        text = "🛡️<b>Введите username/id пользователя:</b>"
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=PHOTO_URL,
                    caption=text,
                    parse_mode='HTML'
                ),
                reply_markup=reply_markup
            )
        except Exception as e:
            print(f"❌ Ошибка редактирования фото: {e}")
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')
        
        context.user_data['waiting_for_search'] = True
    
    elif query.data == 'profile':
        await show_profile_pm(query, query.from_user.id, is_own_profile=True)
    
    elif query.data == 'my_reputation':
        await show_reputation_selection_menu(query, is_own=True)
    
    elif query.data == 'show_positive':
        await show_my_reputation_menu(query, rep_type='positive')
    
    elif query.data == 'show_negative':
        await show_my_reputation_menu(query, rep_type='negative')
    
    elif query.data == 'show_all':
        await show_my_reputation_menu(query, rep_type='all')
    
    elif query.data == 'show_last_positive':
        await handle_last_reputation(query, is_positive=True, is_own=True)
    
    elif query.data == 'show_last_negative':
        await handle_last_reputation(query, is_positive=False, is_own=True)
    
    elif query.data == 'back_to_main':
        await show_main_menu(query)
    
    elif query.data == 'view_found_user_reputation':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_reputation_selection_menu(query, is_own=False, target_user_id=target_user_id)
        else:
            await show_main_menu(query)
    
    elif query.data == 'found_show_positive':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_found_user_reputation_menu(query, target_user_id, rep_type='positive')
    
    elif query.data == 'found_show_negative':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_found_user_reputation_menu(query, target_user_id, rep_type='negative')
    
    elif query.data == 'found_show_all':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_found_user_reputation_menu(query, target_user_id, rep_type='all')
    
    elif query.data == 'back_to_found_profile':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_profile_pm(query, target_user_id, is_own_profile=False)
    
    else:
        await handle_old_button_logic(query, context)

async def show_reputation_selection_menu(query, is_own=True, target_user_id=None):
    """Меню выбора типа репутации"""
    text = "<b>Выберите раздел:</b>"
    
    if is_own:
        keyboard = [
            [InlineKeyboardButton("Положительные", callback_data='show_positive')],
            [InlineKeyboardButton("Отрицательные", callback_data='show_negative')],
            [InlineKeyboardButton("Все", callback_data='show_all')],
            [InlineKeyboardButton("Последний положительный", callback_data='show_last_positive')],
            [InlineKeyboardButton("Последный отрицательный", callback_data='show_last_negative')],
            [InlineKeyboardButton("↩️ Назад", callback_data='profile')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("Положительные", callback_data='found_show_positive')],
            [InlineKeyboardButton("Отрицательные", callback_data='found_show_negative')],
            [InlineKeyboardButton("Все", callback_data='found_show_all')],
            [InlineKeyboardButton("↩️ Назад", callback_data='back_to_found_profile')]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=PHOTO_URL,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=reply_markup
        )
    except Exception as e:
        print(f"❌ Ошибка редактирования фото: {e}")
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_last_reputation(query, is_positive=True, is_own=True):
    """Обработка последнего отзыва"""
    user_id = query.from_user.id if is_own else query.message.chat.id
    
    if is_positive:
        rep_data = get_last_positive(user_id)
        title = "Последний положительный отзыв"
    else:
        rep_data = get_last_negative(user_id)
        title = "Последний отрицательный отзыв"
    
    if not rep_data:
        text = f"{title}\n\n📭 Отзывов пока нет"
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='my_reputation')]]
        
        try:
            await query.edit_message_media(
                media=InputMediaPhoto(
                    media=PHOTO_URL,
                    caption=text,
                    parse_mode='HTML'
                ),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception as e:
            print(f"❌ Ошибка редактирования фото: {e}")
            await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        return
    
    from_username = rep_data.get("from_username", f"id{rep_data['from_user']}")
    date = datetime.fromisoformat(rep_data["created_at"]).strftime("%d/%m/%Y %H:%M")
    rep_type = get_reputation_type(rep_data["text"])
    
    text = f"""<b>{title}</b>

От: {from_username}
Дата: {date}

Текст:
{rep_data['text']}"""
    
    callback_type = 'view_photo_' if is_own else 'found_view_photo_'
    rep_type_str = 'positive' if is_positive else 'negative'
    keyboard = [
        [InlineKeyboardButton("Посмотреть скрин", callback_data=f"{callback_type}{rep_data['id']}_{rep_type_str}")],
        [InlineKeyboardButton("↩️ Назад", callback_data='my_reputation' if is_own else 'view_found_user_reputation')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=PHOTO_URL,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=reply_markup
        )
    except Exception as e:
        print(f"❌ Ошибка редактирования фото: {e}")
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_old_button_logic(query, context):
    """Старая логика для кнопок"""
    pass

async def show_profile_pm(query, user_id, is_own_profile=True):
    """Показать профиль в личных сообщениях"""
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
            [InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("Посмотреть репутацию", callback_data='view_found_user_reputation')],
            [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
            [InlineKeyboardButton("↩️ Назад", callback_data='search_user')]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=PHOTO_URL,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=reply_markup
        )
    except Exception as e:
        print(f"❌ Ошибка редактирования фото: {e}")
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def show_main_menu(query):
    """Главное меню"""
    user_id = query.from_user.id
    text = f"""<b>🛡️TESS | Репутация — твоя гарантия безопасности!</b>
ID - [{user_id}]

• Здесь можно отправить или просмотреть репутацию пользователя, а также провести сделку! Выберите раздел:"""
    
    keyboard = [
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🔎 Найти пользователя", callback_data='search_user')],
        [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=PHOTO_URL,
                caption=text,
                parse_mode='HTML'
            ),
            reply_markup=reply_markup
        )
    except Exception as e:
        print(f"❌ Ошибка редактирования фото: {e}")
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')
        except:
            await query.message.delete()
            await query.message.chat.send_photo(
                photo=PHOTO_URL,
                caption=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

async def handle_all_messages(update: Update, context: CallbackContext) -> None:
    """Обработка ВСЕХ сообщений"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    
    if update.message.chat.type == 'private' and user_id in ADMINS:
        text = update.message.text or ""
        
        if text == "Админ панель":
            await handle_admin_panel(update, context)
            return
        
        admin_menu_commands = [
            "Удалить отзыв", "Статистика", "Рассылка", "Главное меню",
            "Резервное копирование", "Назад в админ-панель",
            "Создать бэкап", "Показать бэкапы", "Восстановить", "Автоочистка",
            "✅ Да, удалить", "❌ Нет", "❌ Отмена",
            "✅ Да, отправить", "❌ Нет, отменить",
            "✅ Да, восстановить", "❌ Нет, отменить",
            "Топ по репутации", "Топ за день", "Топ за неделю", "Топ за месяц",
            "Топ за всё время", "Топ за N дней"
        ]
        
        if text in admin_menu_commands:
            await handle_admin_menu(update, context)
            return
        
        if 'admin_action' in context.user_data:
            await handle_admin_input(update, context)
            return
    
    if update.message.from_user:
        save_user(update.message.from_user.id, update.message.from_user.username or "")
    
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        reply_user = update.message.reply_to_message.from_user
        save_user(reply_user.id, reply_user.username or "")
    
    if update.message.forward_from:
        save_user(update.message.forward_from.id, update.message.forward_from.username or "")
    
    if update.message.chat.type == 'private':
        if context.user_data.get('waiting_for_search'):
            await handle_search_message_pm(update, context)
        elif context.user_data.get('waiting_for_rep'):
            await handle_reputation_message_pm(update, context)
    
    elif update.message.chat.type in ['group', 'supergroup']:
        await handle_group_reputation(update, context)

async def handle_group_reputation(update: Update, context: CallbackContext) -> None:
    """Обработка репутации в групповом чате"""
    
    if update.message.forward_from:
        original_user = update.message.forward_from
        is_forwarded = True
        from_username = original_user.username or f"id{original_user.id}"
        from_user_id = original_user.id
        print(f"🔍 Сообщение ПЕРЕСЛАНО от: {from_username}")
    elif update.message.forward_sender_name:
        original_user = None
        is_forwarded = True
        from_username = f"{update.message.forward_sender_name} (скрытый)"
        from_user_id = None
        print(f"🔍 Сообщение переслано от скрытого пользователя: {from_username}")
    else:
        original_user = update.message.from_user
        is_forwarded = False
        from_username = original_user.username or f"id{original_user.id}"
        from_user_id = original_user.id
    
    text = update.message.text or update.message.caption or ""
    
    print(f"\n{'='*60}")
    print(f"🔍 ПОЛУЧЕНО СООБЩЕНИЕ В ГРУППЕ")
    print(f"👤 Отправитель: {from_username} (ID: {from_user_id})")
    print(f"🔁 Переслано: {'Да' if is_forwarded else 'Нет'}")
    print(f"💬 Текст: '{text}'")
    print(f"📷 Есть фото: {bool(update.message.photo)}")
    print(f"{'='*60}")
    
    is_rep_command = is_reputation_command(text)
    
    print(f"🔍 Поиск +rep/-rep: {'НАЙДЕНО' if is_rep_command else 'НЕ НАЙДЕНО'}")
    
    if not is_rep_command:
        print(f"❌ Не команда репутации - игнорируем")
        return
    
    if not update.message.photo:
        print(f"❌ Нет фото - отправляем ошибку")
        await update.message.reply_text("❗️ <b>Необходимо прикрепить фото/скриншот</b>", parse_mode='HTML')
        return
    
    print(f"✅ Фото есть, продолжаем обработку")
    
    target_identifier = None
    
    patterns = [
        r'[+-]\s*(?:rep|реп|рп)[\s:;,.-]*@?([a-zA-Z0-9_]+)',
        r'[+-]\s*(?:rep|реп|рп)[\s:;,.-]*(\d+)',
        r'@?([a-zA-Z0-9_]+)[\s:;,.-]*[+-]\s*(?:rep|реп|рп)',
        r'(\d+)[\s:;,.-]*[+-]\s*(?:rep|реп|рп)',
    ]
    
    for i, pattern in enumerate(patterns):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            target_identifier = match.group(1)
            print(f"🔍 Паттерн {i+1} совпал: {target_identifier}")
            break
    
    if not target_identifier:
        if update.message.reply_to_message:
            print(f"🔍 Используем реплай для определения пользователя")
            target_user = update.message.reply_to_message.from_user
            target_info = {"id": target_user.id, "username": target_user.username or f"id{target_user.id}"}
        else:
            print(f"❌ Не найден username/id в сообщении")
            await update.message.reply_text("❌ <b>Не найден username/id в сообщении</b>\nИспользуйте: @username +rep или реплай", parse_mode='HTML')
            return
    else:
        target_info = {"id": None, "username": None}
        
        if target_identifier.isdigit():
            target_info["id"] = int(target_identifier)
            target_info["username"] = f"id{target_identifier}"
            print(f"🔍 Найден ID: {target_info['id']}")
        else:
            username_search = target_identifier.lstrip('@')
            user_info = get_user_by_username(username_search)
            
            if user_info:
                target_info["id"] = user_info['user_id']
                target_info["username"] = user_info['username']
                print(f"🔍 Найден username: @{target_info['username']} (ID: {target_info['id']})")
            else:
                print(f"❌ Пользователь @{username_search} не найден в базе")
                await update.message.reply_text("❌ <b>Пользователь не найден в базе</b>\nИспользуйте реплай или ID", parse_mode='HTML')
                return
    
    print(f"🎯 Целевой пользователь: {target_info['username']} (ID: {target_info['id']})")
    
    if from_user_id and target_info["id"] == from_user_id:
        print(f"❌ Попытка отправить репутацию себе")
        await update.message.reply_text("❌ <b>Нельзя отправлять репутацию самому себе</b>", parse_mode='HTML')
        return
    
    print(f"💾 Сохраняем репутацию...")
    
    save_reputation(
        from_user=from_user_id,
        from_username=from_username,
        to_user=target_info["id"],
        to_username=target_info["username"],
        text=text,
        photo_id=update.message.photo[-1].file_id
    )
    
    print(f"✅ Репутация успешно сохранена!")
    
    await update.message.reply_text("✅ <b>Репутация сохранена</b>", parse_mode='HTML')

async def handle_reputation_message_pm(update: Update, context: CallbackContext) -> None:
    """Обработка репутации в личных сообщениях"""
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""
    
    if not update.message.photo:
        await update.message.reply_text("❗️ <b>Необходимо прикрепить фото/скриншот</b>", parse_mode='HTML')
        return
    
    if not text.strip():
        await update.message.reply_text("❌ <b>Добавьте текст к фото!</b>\n\nПример: +rep @username сделка прошла успешно", parse_mode='HTML')
        return
    
    patterns = [
        r'[+-]\s*(?:rep|реп|рп)[\s:;,.-]*@?([a-zA-Z0-9_]+)',
        r'[+-]\s*(?:rep|реп|рп)[\s:;,.-]*(\d+)',
        r'@?([a-zA-Z0-9_]+)[\s:;,.-]*[+-]\s*(?:rep|реп|рп)',
        r'(\d+)[\s:;,.-]*[+-]\s*(?:rep|реп|рп)',
    ]
    
    target_identifier = None
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            target_identifier = match.group(1)
            break
    
    if not target_identifier:
        await update.message.reply_text("❌ <b>Неверный формат</b>\n\nИспользуйте: +rep @username или -rep @username", parse_mode='HTML')
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
        await update.message.reply_text("❌ <b>Нельзя отправлять репутацию самому себе</b>", parse_mode='HTML')
        return
    
    save_reputation(
        from_user=user_id,
        from_username=update.effective_user.username or "",
        to_user=target_info["id"],
        to_username=target_info["username"],
        text=text,
        photo_id=update.message.photo[-1].file_id
    )
    
    await update.message.reply_text("✅ <b>Репутация сохранена!</b>", parse_mode='HTML')
    await show_main_menu_from_message(update, context, user_id)

async def show_main_menu_from_message(update: Update, context: CallbackContext, user_id: int):
    """Показать главное меню после отправки репутации"""
    text = f"""<b>🛡️TESS | Репутация — твоя гарантия безопасности!</b>
ID - [{user_id}]

• Здесь можно отправить или просмотреть репутацию пользователя, а также провести сделку! Выберите раздел:"""
    
    keyboard = [
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🔎 Найти пользователя", callback_data='search_user')],
        [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')]
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
        [InlineKeyboardButton("↩️ Назад", callback_data='search_user')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    context.user_data.pop('waiting_for_search', None)

# ========== ЗАПУСК БОТА ==========
def main():
    """Основная функция запуска"""
    print("=" * 60)
    print("🛡️ TESS REPUTATION BOT - PostgreSQL Version")
    print("=" * 60)
    
    print(f"✅ Токен: {'Установлен' if TOKEN else 'Отсутствует!'}")
    print(f"✅ DATABASE_URL: {'Установлен' if DATABASE_URL else 'Отсутствует!'}")
    print(f"✅ URL фото: {PHOTO_URL}")
    print(f"✅ Админы: {len(ADMINS)} пользователей")
    
    print("\n🔍 Проверка базы данных...")
    check_database_connection()
    
    print(f"\n✅ Резервное копирование: Добавлено")
    print(f"   - Создание бэкапов (Python версия)")
    print(f"   - Восстановление из бэкапов (Python версия)")
    print(f"   - Автоочистка")
    print(f"   - Инлайн-кнопки для выбора")
    
    # Инициализация БД
    init_db()
    
    # Создаем приложение бота
    app = Application.builder().token(TOKEN).build()
    
    # Команды для личных сообщений
    app.add_handler(CommandHandler("start", start))
    
    # Команды для чатов (групп)
    app.add_handler(CommandHandler("i", quick_profile))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^/и\b'), handle_fake_i_command))
    # Обработчики кнопок
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик ВСЕХ сообщений
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_all_messages))
    
    print("=" * 60)
    print("🚀 Бот запускается...")
    print("=" * 60)
    
    # Запускаем бота с сбросом старых обновлений
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
