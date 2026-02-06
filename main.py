import os
import re
import sys
import sqlite3
from datetime import datetime
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
    # Простая проверка по DATABASE_URL
    db_url = os.environ.get('DATABASE_URL', '')
    return 'railway.app' in db_url and db_url.startswith('postgresql://')

def is_replit():
    """Проверяем, запущены ли на Replit"""
    return 'REPL_ID' in os.environ

# Очистка переменных если на Replit
if is_replit():
    os.environ.pop('DATABASE_URL', None)
    os.environ.pop('RAILWAY_ENVIRONMENT', None)
    print("🧹 Очищены Railway переменные (Replit режим)")

# Получаем токен
TOKEN = os.environ.get('TELEGRAM_TOKEN')
if not TOKEN:
    print("❌ ОШИБКА: TELEGRAM_TOKEN не найден!")
    sys.exit(1)

# ========== БАЗА ДАННЫХ (УНИВЕРСАЛЬНАЯ) ==========
def get_db_connection():
    """Возвращает соединение с БД в зависимости от платформы"""
    if is_railway():
        try:
            import psycopg2
            DATABASE_URL = os.environ.get('DATABASE_URL')
            if DATABASE_URL:
                conn = psycopg2.connect(DATABASE_URL, sslmode='require')
                print("✅ Подключено к PostgreSQL (Railway)")
                return conn
        except Exception as e:
            print(f"⚠️ Ошибка PostgreSQL: {e}")
    
    # На Replit или при ошибке - используем SQLite
    conn = sqlite3.connect('reputation.db')
    print("✅ Подключено к SQLite (Replit/Локально)")
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
        except Exception as e:
            print(f"⚠️ Ошибка создания таблиц PostgreSQL: {e}")
    else:
        # SQLite для Replit
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                registered_at TEXT
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
    
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

# ========== ФУНКЦИИ БАЗЫ ДАННЫХ ==========
def save_user(user_id, username):
    """Сохраняем пользователя в БД"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if is_railway():
            # PostgreSQL синтаксис
            cursor.execute('''
                INSERT INTO users (user_id, username, registered_at) 
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE 
                SET username = EXCLUDED.username
            ''', (user_id, username, datetime.now().isoformat()))
        else:
            # SQLite синтаксис
            cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            if not cursor.fetchone():
                cursor.execute('INSERT INTO users VALUES (?, ?, ?)',
                              (user_id, username, datetime.now().isoformat()))
            else:
                cursor.execute('UPDATE users SET username = ? WHERE user_id = ?', 
                             (username, user_id))
        
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
        print(f"❌ Ошибка сохранения репутации: {e}")
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
        print(f"❌ Ошибка получения репутации: {e}")
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
        if is_railway():
            cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        else:
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        
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
                await update.message.reply_text("⚠️ Не найден")
                return
    else:
        target_user_id = user_id
        target_username = update.effective_user.username or f"id{user_id}"
    
    user_info = get_user_info(target_user_id)
    stats = get_reputation_stats(target_user_id)
    
    display_username = f"@{target_username}" if target_username and not target_username.startswith('id') else target_username
    
    if user_info and user_info.get("registered_at"):
        try:
            reg_date = datetime.fromisoformat(user_info["registered_at"])
            registration_date = reg_date.strftime("%d/%m/%Y")
        except:
            registration_date = datetime.now().strftime("%d/%m/%Y")
    else:
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
    text = f"""👤 <b>{display_username} (ID: {target_user_id})</b>

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote>

<blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

📆 <b>Зарегистрирован:</b> {registration_date}"""
    
    if update.message.chat.type in ['group', 'supergroup']:
        keyboard = [
            [InlineKeyboardButton("📊 Посмотреть репутацию", url=f"https://t.me/{context.bot.username}?start=view_{target_user_id}")]
        ]
    else:
        if target_user_id != user_id:
            context.user_data['found_user_id'] = target_user_id
            keyboard = [
                [InlineKeyboardButton("🏆 Посмотреть репутацию", callback_data='view_found_user_reputation')],
                [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("🏆 Моя репутация", callback_data='my_reputation')],
                [InlineKeyboardButton("📋 Полный профиль", callback_data='profile')]
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
    
    text = f"""<b>🛡 TESS | Репутация</b> — <i>твоя гарантия безопасности</i>.

Ваш ID: <code>[{user_id}]</code>

Здесь можно смотреть и сохранять репутацию, а при сомнениях — провести сделку через гаранта <i>(в разработке)</i>"""
    
    keyboard = [
        [InlineKeyboardButton("✍️Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🗒️Скопировать ID", callback_data='copy_id')],
        [InlineKeyboardButton("🔎Поиск User", callback_data='search_user')],
        [InlineKeyboardButton("👤Профиль", callback_data='profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_profile_deeplink(update: Update, target_user_id: int, context: CallbackContext):
    """Показать профиль при переходе из чата"""
    user_id = update.effective_user.id
    user_info = get_user_info(target_user_id)
    stats = get_reputation_stats(target_user_id)
    
    username = user_info.get("username", "") if user_info else ""
    display_username = f"@{username}" if username else f"id{target_user_id}"
    
    if user_info and user_info.get("registered_at"):
        try:
            reg_date = datetime.fromisoformat(user_info["registered_at"])
            registration_date = reg_date.strftime("%d/%m/%Y")
        except:
            registration_date = datetime.now().strftime("%d/%m/%Y")
    else:
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
    text = f"""👤 <b>{display_username} (ID: {target_user_id})</b>

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote>

<blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

📆 <b>Зарегистрирован:</b> {registration_date}"""
    
    context.user_data['found_user_id'] = target_user_id
    
    keyboard = [
        [InlineKeyboardButton("🏆 Посмотреть репутацию", callback_data='view_found_user_reputation')],
        [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("↩️ Главное меню", callback_data='back_to_main')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def button_handler(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('send_to_'):
        target_user_id = int(query.data.replace('send_to_', ''))
        user_id = query.from_user.id
        
        target_user_info = get_user_info(target_user_id)
        target_username = target_user_info.get("username", f"id{target_user_id}") if target_user_info else f"id{target_user_id}"
        
        await query.message.reply_text(
            f"Для отправки репутации пользователю @{target_username} перейдите в личные сообщения с ботом",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📩 Перейти в бот", url=f"https://t.me/{context.bot.username}")]
            ])
        )
        return
    
    if query.data == 'send_reputation':
        text = """<b>🏆 Отправьте репутацию.</b>

🔎К репутации необходимо приложить хотя бы одну фотографию.

👤Пример «+rep @username все идеально»
👤Пример «-rep user_id сделка не зашла»"""
        
        keyboard = [[InlineKeyboardButton("↩️Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
        context.user_data['waiting_for_rep'] = True
    
    elif query.data == 'copy_id':
        user_id = query.from_user.id
        text = f"""📋 **Ваш ID для копирования:**

`{user_id}`

(Нажмите и удерживайте текст, чтобы скопировать)"""
        
        keyboard = [[InlineKeyboardButton("↩️Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    
    elif query.data == 'search_user':
        text = "🔎 **Поиск пользователя**\n\nВведите username или ID пользователя:"
        
        keyboard = [[InlineKeyboardButton("↩️Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        context.user_data['waiting_for_search'] = True
    
    elif query.data == 'profile':
        await show_profile_pm(query, query.from_user.id, is_own_profile=True)
    
    elif query.data == 'my_reputation':
        await show_my_reputation_menu(query)
    
    elif query.data.startswith('show_'):
        await handle_show_reputation(query)
    
    elif query.data == 'back_to_main':
        await show_main_menu(query)
    
    elif query.data == 'view_found_user_reputation':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_found_user_reputation_menu(query, target_user_id)
    
    elif query.data.startswith('found_show_'):
        await handle_found_user_reputation(query, context)
    
    elif query.data == 'back_to_found_profile':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_profile_pm(query, target_user_id, is_own_profile=False)

async def show_profile_pm(query, user_id, is_own_profile=True):
    user_info = get_user_info(user_id)
    stats = get_reputation_stats(user_id)
    
    username = user_info.get("username", "") if user_info else ""
    display_username = f"@{username}" if username else f"id{user_id}"
    
    if user_info and user_info.get("registered_at"):
        try:
            reg_date = datetime.fromisoformat(user_info["registered_at"])
            registration_date = reg_date.strftime("%d/%m/%Y")
        except:
            registration_date = datetime.now().strftime("%d/%m/%Y")
    else:
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
    text = f"""👤 <b>{display_username} (ID: {user_id})</b>

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote>

<blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

📆 <b>Зарегистрирован:</b> {registration_date}"""
    
    if is_own_profile:
        keyboard = [
            [InlineKeyboardButton("🏆Моя репутация", callback_data='my_reputation')],
            [InlineKeyboardButton("↩️Назад", callback_data='back_to_main')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🏆Посмотреть репутацию", callback_data='view_found_user_reputation')],
            [InlineKeyboardButton("✍️Отправить репутацию", callback_data='send_reputation')],
            [InlineKeyboardButton("↩️Назад к поиску", callback_data='search_user')]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_my_reputation_menu(query):
    text = "🏆 <b>Выберите раздел:</b>"
    
    keyboard = [
        [InlineKeyboardButton("✅ ПОЛОЖИТЕЛЬНАЯ", callback_data='show_positive')],
        [InlineKeyboardButton("❌ ОТРИЦАТЕЛЬНАЯ", callback_data='show_negative')],
        [InlineKeyboardButton("📋 ВСЕ", callback_data='show_all')],
        [InlineKeyboardButton("↩️Назад в профиль", callback_data='profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_found_user_reputation_menu(query, target_user_id):
    text = "🏆 <b>Выберите раздел:</b>"
    
    keyboard = [
        [InlineKeyboardButton("✅ ПОЛОЖИТЕЛЬНАЯ", callback_data='found_show_positive')],
        [InlineKeyboardButton("❌ ОТРИЦАТЕЛЬНАЯ", callback_data='found_show_negative')],
        [InlineKeyboardButton("📋 ВСЕ", callback_data='found_show_all')],
        [InlineKeyboardButton("↩️Назад в профиль", callback_data='back_to_found_profile')]
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
    
    keyboard = [[InlineKeyboardButton("↩️Назад", callback_data=back_button)]]
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
    
    keyboard = [[InlineKeyboardButton("↩️Назад", callback_data=back_button)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def show_main_menu(query):
    user_id = query.from_user.id
    text = f"""<b>🛡 TESS | Репутация</b> — <i>твоя гарантия безопасности</i>.

Ваш ID: <code>[{user_id}]</code>

Здесь можно смотреть и сохранять репутацию, а при сомнениях — провести сделку через гаранта <i>(в разработке)</i>"""
    
    keyboard = [
        [InlineKeyboardButton("✍️Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🗒️Скопировать ID", callback_data='copy_id')],
        [InlineKeyboardButton("🔎Поиск User", callback_data='search_user')],
        [InlineKeyboardButton("👤Профиль", callback_data='profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_all_messages(update: Update, context: CallbackContext) -> None:
    """Обработка ВСЕХ сообщений"""
    user_id = update.effective_user.id
    username = update.effective_user.username or f"id{user_id}"
    save_user(user_id, username)
    
    if update.message.chat.type == 'private':
        if context.user_data.get('waiting_for_rep'):
            await handle_reputation_message_pm(update, context)
        elif context.user_data.get('waiting_for_search'):
            await handle_search_message_pm(update, context)
    
    elif update.message.chat.type in ['group', 'supergroup']:
        await handle_group_reputation(update, context)

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
        await update.message.reply_text("⚠️ Нужно фото")
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
        await update.message.reply_text("⚠️ Неверный формат")
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
            await update.message.reply_text("⚠️ Пользователь не найден\nИспользуйте реплай или ID")
            return
    
    if target_info["id"] == user_id:
        await update.message.reply_text("⚠️ Нельзя себе")
        return
    
    save_reputation(
        from_user=user_id,
        from_username=update.effective_user.username or "",
        to_user=target_info["id"],
        to_username=target_info["username"],
        text=text,
        photo_id=update.message.photo[-1].file_id
    )
    
    await update.message.reply_text("✅ Сохранено")

async def handle_reputation_message_pm(update: Update, context: CallbackContext) -> None:
    """Обработка репутации в личных сообщениях"""
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""
    
    if not update.message.photo:
        await update.message.reply_text("⚠️ Нужно фото")
        return
    
    patterns = [r'[-+](?:rep|реп)\s+(@?\w+)']
    target_identifier = None
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            target_identifier = match.group(1)
            break
    
    if not target_identifier:
        await update.message.reply_text("⚠️ Неверный формат")
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
            await update.message.reply_text("⚠️ Пользователь не найден")
            return
    
    if target_info["id"] == user_id:
        await update.message.reply_text("⚠️ Нельзя себе")
        return
    
    save_reputation(
        from_user=user_id,
        from_username=update.effective_user.username or "",
        to_user=target_info["id"],
        to_username=target_info["username"],
        text=text,
        photo_id=update.message.photo[-1].file_id
    )
    
    await update.message.reply_text("✅ Сохранено")
    await show_main_menu_from_message(update, context, user_id)

async def show_main_menu_from_message(update: Update, context: CallbackContext, user_id: int):
    """Показать главное меню после отправки репутации"""
    text = f"""<b>🛡 TESS | Репутация</b> — <i>твоя гарантия безопасности</i>.

Ваш ID: <code>[{user_id}]</code>

Здесь можно смотреть и сохранять репутацию, а при сомнениях — провести сделку через гаранта <i>(в разработке)</i>"""
    
    keyboard = [
        [InlineKeyboardButton("✍️Отправить репутацию", callback_data='send_reputation')],
        [InlineKeyboardButton("🗒️Скопировать ID", callback_data='copy_id')],
        [InlineKeyboardButton("🔎Поиск User", callback_data='search_user')],
        [InlineKeyboardButton("👤Профиль", callback_data='profile')]
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
        await update.message.reply_text("⚠️ Не найден")
        return
    
    context.user_data['found_user_id'] = target_user['user_id']
    
    stats = get_reputation_stats(target_user['user_id'])
    username = target_user.get("username", "")
    display_username = f"@{username}" if username else f"id{target_user['user_id']}"
    
    if target_user.get("registered_at"):
        try:
            reg_date = datetime.fromisoformat(target_user["registered_at"])
            registration_date = reg_date.strftime("%d/%m/%Y")
        except:
            registration_date = datetime.now().strftime("%d/%m/%Y")
    else:
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
    text = f"""👤 <b>{display_username} (ID: {target_user['user_id']})</b>

<blockquote>🏆 {stats['total']} шт. · {stats['positive_percent']:.0f}% положительных · {stats['negative_percent']:.0f}% отрицательных</blockquote>

<blockquote>🛡 0 шт. · 0 RUB сумма сделок</blockquote>

📆 <b>Зарегистрирован:</b> {registration_date}"""
    
    keyboard = [
        [InlineKeyboardButton("🏆Посмотреть репутацию", callback_data='view_found_user_reputation')],
        [InlineKeyboardButton("↩️Назад", callback_data='search_user')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')
    
    context.user_data.pop('waiting_for_search', None)

# ========== ЗАПУСК БОТА ==========
def main():
    """Основная функция запуска"""
    print("=" * 60)
    print("🛡 TESS REPUTATION BOT")
    print("=" * 60)
    
    # Определяем платформу
    if is_railway():
        print("🚂 Платформа: Railway (PostgreSQL)")
    elif is_replit():
        print("🔄 Платформа: Replit (SQLite)")
        # Запускаем Flask только на Replit
        try:
            from flask import Flask
            from threading import Thread
            
            app = Flask('')
            @app.route('/')
            def home(): 
                return "✅ Бот работает!"
            
            def run():
                app.run(host='0.0.0.0', port=8080)
            
            t = Thread(target=run, daemon=True)
            t.start()
            print("✅ Keep-alive сервер запущен (Replit)")
        except ImportError:
            print("⚠️ Flask не установлен")
    else:
        print("💻 Платформа: Локальный запуск (SQLite)")
    
    print(f"👤 Токен: {'Установлен' if TOKEN else 'Отсутствует!'}")
    print("=" * 60)
    
    # Инициализация БД
    init_db()
    
    # Создаем приложение бота
    app = Application.builder().token(TOKEN).build()
    
    # Команды для личных сообщений
    app.add_handler(CommandHandler("start", start))
    
    # Команды для чатов (групп)
    app.add_handler(CommandHandler("v", quick_profile))
    app.add_handler(CommandHandler("rep", quick_profile))
    app.add_handler(CommandHandler("profile", quick_profile))
    
    # Обработчики кнопок
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Обработчик ВСЕХ сообщений (включая группы)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_all_messages))
    
    # Запускаем бота
    print("🤖 Бот запускается...")
    print("✅ Готов к работе!")
    print("=" * 60)
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
