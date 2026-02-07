import os
import re
import sys
import psycopg2
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
        # Получаем символ в начале совпадения
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
        print("✅ Подключено к PostgreSQL")
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
                [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("🏆 Моя репутация", callback_data='my_reputation')],
                [InlineKeyboardButton("🏆 Мой профиль", callback_data='profile')]
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
            context.user_data['found_user_id'] = target_user_id
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
        registration_date = datetime.now().strftime("%d/%m/%Y")
    
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

async def button_handler(update: Update, context: CallbackContext) -> None:
    """Обработчик кнопок"""
    query = update.callback_query
    await query.answer()
    
    has_photo = query.message.photo is not None
    
    if query.data.startswith('send_to_'):
        target_user_id = int(query.data.replace('send_to_', ''))
        target_user_info = get_user_info(target_user_id)
        target_username = target_user_info.get("username", f"id{target_user_id}") if target_user_info else f"id{target_user_id}"
        
        await query.message.reply_text(
            f"Для отправки репутации пользователю @{target_username} перейдите в личные сообщения с ботом",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Перейти в бот", url=f"https://t.me/{context.bot.username}")]
            ])
        )
        return
    
    if query.data == 'send_reputation':
        text = """<b><i>🛡️Отправьте репутацию.</i></b>

• К репутации необходимо приложить хотя бы одну фотографию.
<blockquote>Пример «+rep @username все идеально»
Пример «-rep [id] сделка не зашла»</blockquote>

<b>• Отправляйте репутацию строго по шаблону.</b>"""
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if has_photo:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')
        context.user_data['waiting_for_rep'] = True
    
    elif query.data == 'search_user':
        text = "🛡️<b>Введите username/id пользователя:</b>"
        
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if has_photo:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')
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
        else:
            await show_main_menu(query)
    
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
    
    has_photo = query.message.photo is not None
    
    if is_own_profile:
        keyboard = [
            [InlineKeyboardButton("🏆 Моя репутация", callback_data='my_reputation')],
            [InlineKeyboardButton("↩️ Назад", callback_data='back_to_main')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🪄 Посмотреть репутацию", callback_data='view_found_user_reputation')],
            [InlineKeyboardButton("✍️ Отправить репутацию", callback_data='send_reputation')],
            [InlineKeyboardButton("↩️ Назад", callback_data='search_user')]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if has_photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def show_my_reputation_menu(query):
    text = "<b>Выберите раздел:</b>"
    
    has_photo = query.message.photo is not None
    
    keyboard = [
        [InlineKeyboardButton("🪄 Положительные", callback_data='show_positive')],
        [InlineKeyboardButton("🪄 Отрицательные", callback_data='show_negative')],
        [InlineKeyboardButton("🪄 Все", callback_data='show_all')],
        [InlineKeyboardButton("🪄 Последний положительный", callback_data='show_last_positive')],
        [InlineKeyboardButton("🪄 Последний отрицательный", callback_data='show_last_negative')],
        [InlineKeyboardButton("↩️ Назад", callback_data='profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if has_photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def show_found_user_reputation_menu(query, target_user_id):
    text = "<b>Выберите раздел:</b>"
    
    has_photo = query.message.photo is not None
    
    keyboard = [
        [InlineKeyboardButton("🪄 Положительные", callback_data='found_show_positive')],
        [InlineKeyboardButton("🪄 Отрицательные", callback_data='found_show_negative')],
        [InlineKeyboardButton("🪄 Все", callback_data='found_show_all')],
        [InlineKeyboardButton("↩️ Назад", callback_data='back_to_found_profile')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if has_photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_show_reputation(query):
    user_id = query.from_user.id
    stats = get_reputation_stats(user_id)
    
    has_photo = query.message.photo is not None
    
    if query.data == 'show_positive':
        positive_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '+']
        
        if not positive_reps:
            text = "🪄<b>Положительные отзывы</b>\n\nУ вас еще нет положительных отзывов."
        else:
            text = "🪄<b>Положительные отзывы</b>\n\n"
            for i, rep in enumerate(positive_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                text += f"{i}. От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(positive_reps) > 10:
                text += f"\n... и еще {len(positive_reps) - 10} отзывов"
        
        back_button = 'my_reputation'
    
    elif query.data == 'show_negative':
        negative_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '-']
        
        if not negative_reps:
            text = "🪄<b>Отрицательные отзывы</b>\n\nУ вас еще нет отрицательных отзывов."
        else:
            text = "🪄<b>Отрицательные отзывы</b>\n\n"
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
            text = "🪄<b>Все отзывы</b>\n\nУ вас еще нет отзывов."
        else:
            text = "🪄<b>Все отзывы</b>\n\n"
            for i, rep in enumerate(all_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                rep_type = get_reputation_type(rep["text"])
                sign = "✅" if rep_type == '+' else "❌" if rep_type == '-' else "❓"
                text += f"{i}. {sign} От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(all_reps) > 10:
                text += f"\n... и еще {len(all_reps) - 10} отзывов"
        
        back_button = 'my_reputation'
    
    elif query.data == 'show_last_positive':
        last_positive = get_last_positive(user_id)
        
        if not last_positive:
            text = "🪄<b>Последний положительный отзыв</b>\n\nУ вас еще нет положительных отзывов."
        else:
            from_user = last_positive.get("from_username", f"id{last_positive['from_user']}")
            date = datetime.fromisoformat(last_positive["created_at"]).strftime("%d/%m/%Y")
            text = f"""🪄<b>Последный положительный отзыв</b>

От: @{from_user}
Текст: {last_positive['text']}
Дата: {date}"""
        
        back_button = 'my_reputation'
    
    elif query.data == 'show_last_negative':
        last_negative = get_last_negative(user_id)
        
        if not last_negative:
            text = "🪄<b>Последний отрицательный отзыв</b>\n\nУ вас еще нет отрицательных отзывов."
        else:
            from_user = last_negative.get("from_username", f"id{last_negative['from_user']}")
            date = datetime.fromisoformat(last_negative["created_at"]).strftime("%d/%m/%Y")
            text = f"""🪄<b>Последний отрицательный отзыв</b>

От: @{from_user}
Текст: {last_negative['text']}
Дата: {date}"""
        
        back_button = 'my_reputation'
    
    keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data=back_button)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if has_photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_found_user_reputation(query, context):
    target_user_id = context.user_data.get('found_user_id')
    if not target_user_id:
        await query.edit_message_text("Ошибка: пользователь не найден")
        return
    
    stats = get_reputation_stats(target_user_id)
    user_info = get_user_info(target_user_id)
    username = user_info.get("username", "") if user_info else f"id{target_user_id}"
    
    has_photo = query.message.photo is not None
    
    if query.data == 'found_show_positive':
        positive_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '+']
        
        if not positive_reps:
            text = f"🪄<b>Положительные отзывы @{username}</b>\n\nУ пользователя еще нет положительных отзывов."
        else:
            text = f"🪄<b>Положительные отзывы @{username}</b>\n\n"
            for i, rep in enumerate(positive_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                text += f"{i}. От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(positive_reps) > 10:
                text += f"\n... и еще {len(positive_reps) - 10} отзывов"
        
        back_button = 'view_found_user_reputation'
    
    elif query.data == 'found_show_negative':
        negative_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '-']
        
        if not negative_reps:
            text = f"🪄<b>Отрицательные отзывы @{username}</b>\n\nУ пользователя еще нет отрицательных отзывов."
        else:
            text = f"🪄<b>Отрицательные отзывы @{username}</b>\n\n"
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
            text = f"🪄<b>Все отзывы @{username}</b>\n\nУ пользователя еще нет отзывов."
        else:
            text = f"🪄<b>Все отзывы @{username}</b>\n\n"
            for i, rep in enumerate(all_reps[:10], 1):
                from_user = rep.get("from_username", f"id{rep['from_user']}")
                date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
                rep_type = get_reputation_type(rep["text"])
                sign = "✅" if rep_type == '+' else "❌" if rep_type == '-' else "❓"
                text += f"{i}. {sign} От @{from_user}\n   {rep['text'][:50]}...\n   📅 {date}\n\n"
            
            if len(all_reps) > 10:
                text += f"\n... и еще {len(all_reps) - 10} отзывов"
        
        back_button = 'view_found_user_reputation'
    
    keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data=back_button)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if has_photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def show_main_menu(query):
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
    
    has_photo = query.message.photo is not None
    
    if has_photo:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        try:
            await query.message.delete()
            await query.message.chat.send_photo(
                photo=PHOTO_URL,
                caption=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"❌ Ошибка отправки фото: {e}")
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_all_messages(update: Update, context: CallbackContext) -> None:
    """Обработка ВСЕХ сообщений"""
    if not update.message:
        return
    
    user_id = update.effective_user.id
    username = update.effective_user.username or f"id{user_id}"
    
    # Сохраняем отправителя
    save_user(user_id, username)
    
    # Сохраняем пользователя из реплая (если есть и он валидный)
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        reply_user = update.message.reply_to_message.from_user
        save_user(reply_user.id, reply_user.username or f"id{reply_user.id}")
    
    if update.message.chat.type == 'private':
        if context.user_data.get('waiting_for_search'):
            await handle_search_message_pm(update, context)
        elif context.user_data.get('waiting_for_rep'):
            await handle_reputation_message_pm(update, context)
    
    elif update.message.chat.type in ['group', 'supergroup']:
        await handle_group_reputation(update, context)

async def handle_group_reputation(update: Update, context: CallbackContext) -> None:
    """Обработка репутации в групповом чате"""
    user_id = update.effective_user.id
    username = update.effective_user.username or f"id{user_id}"
    text = update.message.text or update.message.caption or ""
    
    # ОТЛАДКА
    print(f"\n{'='*60}")
    print(f"🔍 ПОЛУЧЕНО СООБЩЕНИЕ В ГРУППЕ")
    print(f"👤 От: {username} (ID: {user_id})")
    print(f"💬 Текст: '{text}'")
    print(f"📷 Есть фото: {bool(update.message.photo)}")
    print(f"💬 Тип чата: {update.message.chat.type}")
    print(f"{'='*60}")
    
    # Проверяем, является ли это командой репутации
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
    
    # Улучшенные паттерны поиска пользователя
    patterns = [
        # +rep @username или -rep @username
        r'[+-]\s*(?:rep|реп|рп)[\s:;,.-]*@?([a-zA-Z0-9_]+)',
        # +rep 123456 или -rep 123456
        r'[+-]\s*(?:rep|реп|рп)[\s:;,.-]*(\d+)',
        # @username +rep или 123456 +rep
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
    
    if target_info["id"] == user_id:
        print(f"❌ Попытка отправить репутацию себе")
        await update.message.reply_text("❌ <b>Нельзя отправлять репутацию самому себе</b>", parse_mode='HTML')
        return
    
    print(f"💾 Сохраняем репутацию...")
    
    save_reputation(
        from_user=user_id,
        from_username=update.effective_user.username or "",
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
    
    # Улучшенные паттерны поиска
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
