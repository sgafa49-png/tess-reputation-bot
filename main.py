import os
import re
import sys
import psycopg2
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardMarkup, ReplyKeyboardRemove
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
ADMINS = [8438564254, 7819922804]  # 🆕 ID админов

# ========== КЛАВИАТУРЫ ========== 🆕
def get_admin_keyboard():
    """Клавиатура для админов (только кнопка админ-панели)"""
    return ReplyKeyboardMarkup([
        ['🪄 АДМИН ПАНЕЛЬ']
    ], resize_keyboard=True, one_time_keyboard=False)

def get_admin_menu_keyboard():
    """Меню админ-панели"""
    return ReplyKeyboardMarkup([
        ['Удалить отзыв', 'Все отзывы'],
        ['Поиск по ID', 'Статистика'],
        ['Экспорт', 'Просмотр'],
        ['Главное меню']
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
    """Удалить отзыв по ID""" # 🆕
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

def get_all_reputations(limit=50):
    """Получить все отзывы (для админов)""" # 🆕
    conn = get_db_connection()
    cursor = conn.cursor()
    
    reps = []
    try:
        cursor.execute('''
            SELECT r.*, u1.username as from_username, u2.username as to_username
            FROM reputation r
            LEFT JOIN users u1 ON r.from_user = u1.user_id
            LEFT JOIN users u2 ON r.to_user = u2.user_id
            ORDER BY r.created_at DESC
            LIMIT %s
        ''', (limit,))
        
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
        print(f"❌ Ошибка получения всех отзывов: {e}")
    finally:
        conn.close()
    
    return reps

def get_reputations_by_user_id(user_id):
    """Получить все отзывы пользователя (по from_user или to_user)""" # 🆕
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
    """Статистика базы данных""" # 🆕
    conn = get_db_connection()
    cursor = conn.cursor()
    
    stats = {}
    try:
        cursor.execute('SELECT COUNT(*) FROM users')
        stats['total_users'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reputation')
        stats['total_reputations'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reputation WHERE text LIKE "+%" OR text LIKE "%+rep%" OR text LIKE "%+реп%"')
        stats['positive_reps'] = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM reputation WHERE text LIKE "-%" OR text LIKE "%-rep%" OR text LIKE "%-реп%"')
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

# ========== ТЕЛЕГРАМ HANDLERS ==========
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

# ========== АДМИН ПАНЕЛЬ ========== 🆕
async def start(update: Update, context: CallbackContext) -> None:
    """Команда /start в личных сообщениях"""
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    
    save_user(user_id, username)
    
    # Показываем клавиатуру админам
    if user_id in ADMINS:
        await update.message.reply_text(
            "🪄 Клавиатура админа активирована.",
            reply_markup=get_admin_keyboard()
        )
    
    if context.args and context.args[0].startswith('view_'):
        try:
            target_user_id = int(context.args[0].replace('view_', ''))
            # Сохраняем найденного пользователя для работы кнопки "Назад"
            context.user_data['found_user_id'] = target_user_id
            context.user_data['from_group'] = True  # Флаг что пришли из группы
            
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

async def handle_admin_panel(update: Update, context: CallbackContext) -> None:
    """Обработка кнопки админ-панели"""
    user_id = update.effective_user.id
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    text = "🪄 АДМИН ПАНЕЛЬ\n\nВыберите действие:"
    
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
    
    if text == "Главное меню":
        # Возвращаемся к главной клавиатуре админа
        await update.message.reply_text(
            "🪄 Возврат в главное меню",
            reply_markup=get_admin_keyboard()
        )
        return
    
    if text == "Удалить отзыв":
        context.user_data['admin_action'] = 'delete_rep'
        await update.message.reply_text(
            "🪄 Введите ID отзыва для удаления:\n\n(или отправьте ❌ Отмена)",
            reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
        )
        return
    
    if text == "Все отзывы":
        reps = get_all_reputations(limit=20)
        if not reps:
            await update.message.reply_text("🪄 Отзывов пока нет", reply_markup=get_admin_menu_keyboard())
            return
        
        message = "🪄 Последние 20 отзывов:\n\n"
        for rep in reps:
            rep_type = get_reputation_type(rep["text"])
            emoji = "✅" if rep_type == '+' else "❌" if rep_type == '-' else "📝"
            short_text = rep['text'][:50] + "..." if len(rep['text']) > 50 else rep['text']
            date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
            
            message += f"{emoji} ID{rep['id']}: {rep['from_username']} → {rep['to_username']}\n"
            message += f"   📝 {short_text}\n"
            message += f"   📅 {date}\n\n"
        
        message += "\n🪄 Для удаления введите команду: Удалить отзыв"
        
        await update.message.reply_text(
            message,
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    if text == "Поиск по ID":
        context.user_data['admin_action'] = 'search_user_id'
        await update.message.reply_text(
            "🪄 Введите ID пользователя для поиска всех его отзывов:\n\n(или отправьте ❌ Отмена)",
            reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
        )
        return
    
    if text == "Статистика":
        stats = get_db_stats()
        message = f"""🪄 СТАТИСТИКА БАЗЫ ДАННЫХ

👥 Пользователей: {stats.get('total_users', 0)}
📝 Всего отзывов: {stats.get('total_reputations', 0)}
✅ Положительных: {stats.get('positive_reps', 0)}
❌ Отрицательных: {stats.get('negative_reps', 0)}
📤 Отправителей: {stats.get('unique_senders', 0)}
📥 Получателей: {stats.get('unique_receivers', 0)}"""
        
        await update.message.reply_text(
            message,
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    if text == "Экспорт":
        await update.message.reply_text(
            "🪄 Экспорт в разработке...",
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    if text == "Просмотр":
        context.user_data['admin_action'] = 'view_rep'
        await update.message.reply_text(
            "🪄 Введите ID отзыва для просмотра:\n\n(или отправьте ❌ Отмена)",
            reply_markup=ReplyKeyboardMarkup([['❌ Отмена']], resize_keyboard=True)
        )
        return

async def handle_admin_input(update: Update, context: CallbackContext) -> None:
    """Обработка ввода от админа"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    if text == "❌ Отмена":
        await update.message.reply_text(
            "🪄 Отменено",
            reply_markup=get_admin_menu_keyboard()
        )
        context.user_data.pop('admin_action', None)
        context.user_data.pop('rep_to_delete', None)
        return
    
    action = context.user_data.get('admin_action')
    
    if not action:
        # Если нет активного действия, возвращаем в меню
        await update.message.reply_text(
            "🪄 Выберите действие в меню:",
            reply_markup=get_admin_menu_keyboard()
        )
        return
    
    if action == 'delete_rep':
        if 'rep_to_delete' not in context.user_data:
            # Первый шаг: получение ID
            if not text.isdigit():
                await update.message.reply_text("❌ Введите числовой ID отзыва")
                return
            
            rep_id = int(text)
            rep_data = get_reputation_by_id(rep_id)
            
            if not rep_data:
                await update.message.reply_text("❌ Отзыв не найден")
                return
            
            # Сохраняем данные отзыва и показываем подтверждение
            context.user_data['rep_to_delete'] = rep_data
            
            rep_type = get_reputation_type(rep_data["text"])
            type_text = "✅ ПОЛОЖИТЕЛЬНЫЙ" if rep_type == '+' else "❌ ОТРИЦАТЕЛЬНЫЙ"
            date = datetime.fromisoformat(rep_data["created_at"]).strftime("%d/%m/%Y %H:%M")
            
            message = f"""🪄 Отзыв #{rep_id} ({type_text})

👤 От: {rep_data['from_username']}
🎯 Кому: id{rep_data['to_user']}
📅 Дата: {date}
📝 Текст: {rep_data['text'][:100]}...

Удалить этот отзыв?"""
            
            await update.message.reply_text(
                message,
                reply_markup=ReplyKeyboardMarkup([
                    ['✅ Да, удалить', '❌ Нет']
                ], resize_keyboard=True)
            )
        
        else:
            # Второй шаг: подтверждение удаления
            if text == "✅ Да, удалить":
                rep_data = context.user_data['rep_to_delete']
                rep_id = rep_data['id']
                
                if delete_reputation_by_id(rep_id):
                    message = f"✅ Отзыв #{rep_id} успешно удален"
                else:
                    message = f"❌ Ошибка при удалении отзыва #{rep_id}"
                
                await update.message.reply_text(
                    message,
                    reply_markup=get_admin_menu_keyboard()
                )
                
                # Очищаем данные
                context.user_data.pop('rep_to_delete', None)
                context.user_data.pop('admin_action', None)
            
            elif text == "❌ Нет":
                await update.message.reply_text(
                    "🪄 Удаление отменено",
                    reply_markup=get_admin_menu_keyboard()
                )
                context.user_data.pop('rep_to_delete', None)
                context.user_data.pop('admin_action', None)
    
    elif action == 'search_user_id':
        if not text.isdigit():
            await update.message.reply_text("❌ Введите числовой ID пользователя")
            return
        
        target_id = int(text)
        reps = get_reputations_by_user_id(target_id)
        
        if not reps:
            await update.message.reply_text(f"🪄 У пользователя ID{target_id} нет отзывов", reply_markup=get_admin_menu_keyboard())
            return
        
        message = f"🪄 Отзывы пользователя ID{target_id}:\n\n"
        
        for rep in reps[:15]:  # Ограничим 15 отзывами
            rep_type = get_reputation_type(rep["text"])
            emoji = "✅" if rep_type == '+' else "❌" if rep_type == '-' else "📝"
            short_text = rep['text'][:40] + "..." if len(rep['text']) > 40 else rep['text']
            date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
            
            direction = f"{rep['from_username']} → {rep['to_username']}"
            if rep['from_user'] == target_id:
                direction = f"👤 Отправил → {rep['to_username']}"
            else:
                direction = f"👤 Получил от {rep['from_username']}"
            
            message += f"{emoji} ID{rep['id']}: {direction}\n"
            message += f"   📝 {short_text}\n"
            message += f"   📅 {date}\n\n"
        
        if len(reps) > 15:
            message += f"\n... и еще {len(reps) - 15} отзывов"
        
        message += "\n🪄 Для удаления используйте 'Удалить отзыв'"
        
        await update.message.reply_text(
            message,
            reply_markup=get_admin_menu_keyboard()
        )
        context.user_data.pop('admin_action', None)
    
    elif action == 'view_rep':
        if not text.isdigit():
            await update.message.reply_text("❌ Введите числовой ID отзыва")
            return
        
        rep_id = int(text)
        rep_data = get_reputation_by_id(rep_id)
        
        if not rep_data:
            await update.message.reply_text("❌ Отзыв не найден", reply_markup=get_admin_menu_keyboard())
            return
        
        rep_type = get_reputation_type(rep_data["text"])
        type_text = "✅ ПОЛОЖИТЕЛЬНЫЙ" if rep_type == '+' else "❌ ОТРИЦАТЕЛЬНЫЙ"
        date = datetime.fromisoformat(rep_data["created_at"]).strftime("%d/%m/%Y %H:%M")
        
        message = f"""🪄 Отзыв #{rep_id} ({type_text})

👤 От: {rep_data['from_username']}
🎯 Кому: id{rep_data['to_user']}
📅 Дата: {date}
📝 Текст: {rep_data['text']}

🪄 Действия:"""
        
        keyboard = [
            ['🗑 Удалить этот отзыв', '🔙 Назад в меню'],
            ['❌ Отмена']
        ]
        
        # Сохраняем ID для возможного удаления
        context.user_data['viewing_rep_id'] = rep_id
        
        await update.message.reply_text(
            message,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )

async def handle_admin_actions(update: Update, context: CallbackContext) -> None:
    """Обработка действий в режиме просмотра"""
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    if text == "🔙 Назад в меню":
        await update.message.reply_text(
            "🪄 Возврат в меню",
            reply_markup=get_admin_menu_keyboard()
        )
        context.user_data.pop('viewing_rep_id', None)
        return
    
    if text == "🗑 Удалить этот отзыв":
        rep_id = context.user_data.get('viewing_rep_id')
        if not rep_id:
            await update.message.reply_text("❌ ID отзыва не найден")
            return
        
        if delete_reputation_by_id(rep_id):
            message = f"✅ Отзыв #{rep_id} успешно удален"
        else:
            message = f"❌ Ошибка при удалении отзыва #{rep_id}"
        
        await update.message.reply_text(
            message,
            reply_markup=get_admin_menu_keyboard()
        )
        context.user_data.pop('viewing_rep_id', None)
        return
    
    if text == "❌ Отмена":
        await update.message.reply_text(
            "🪄 Отменено",
            reply_markup=get_admin_menu_keyboard()
        )
        context.user_data.pop('viewing_rep_id', None)

# ========== ОСТАЛЬНОЙ КОД (без изменений) ==========
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

async def show_reputation_photo(update: Update, rep_id: int, back_context: str, context: CallbackContext) -> None:
    """Показать фото отзыва с информацией (редактируем текущее сообщение)"""
    query = update.callback_query
    await query.answer()
    
    rep_data = get_reputation_by_id(rep_id)
    if not rep_data:
        await query.answer("Отзыв не найден", show_alert=True)
        return
    
    # Определяем правильный back_context для кнопки "Назад"
    target_user_id = rep_data['to_user']
    current_user_id = query.from_user.id
    
    # Если пришли из группы и смотрим не свои отзывы
    if context.user_data.get('from_group') and target_user_id != current_user_id:
        back_context = 'back_from_group_view'
    
    # Форматируем подпись
    rep_type = get_reputation_type(rep_data["text"])
    type_text = "✅ ПОЛОЖИТЕЛЬНЫЙ ОТЗЫВ" if rep_type == '+' else "❌ ОТРИЦАТЕЛЬНЫЙ ОТЗЫВ"
    
    from_username = rep_data["from_username"]
    user_id_display = rep_data["from_user"] if rep_data["from_user"] else "Неизвестно"
    
    date = datetime.fromisoformat(rep_data["created_at"]).strftime("%d/%m/%Y %H:%M")
    
    caption = f"""<b>{type_text}</b>

🪄 От: {from_username}
🪄 ID: {user_id_display}
🪄 Дата: {date}

🪄 Текст:
{rep_data['text']}"""
    
    keyboard = [
        [InlineKeyboardButton("↩️ Назад к списку", callback_data=back_context)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Редактируем текущее сообщение, заменяя фото
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
        # Если не удалось отредактировать фото, пробуем отредактировать текст
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
    """Показать меню репутации с кнопками для просмотра фото (с фото)"""
    user_id = query.from_user.id
    stats = get_reputation_stats(user_id)
    
    # Фильтруем отзывы
    if rep_type == 'positive':
        filtered_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '+']
        title = "🪄 Положительные отзывы"
    elif rep_type == 'negative':
        filtered_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '-']
        title = "🪄 Отрицательные отзывы"
    else:
        filtered_reps = stats['all_reps']
        title = "🪄 Все отзывы"
    
    if not filtered_reps:
        text = f"{title}\n\n📭 Отзывов пока нет"
        keyboard = [[InlineKeyboardButton("↩️ Назад", callback_data='my_reputation')]]
        
        try:
            # Всегда показываем фото
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
    
    # Формируем текст и кнопки
    text = f"<b>{title}</b>\n\n"
    keyboard = []
    
    for i, rep in enumerate(filtered_reps[:10], 1):
        rep_type_char = get_reputation_type(rep["text"])
        emoji = "✅" if rep_type_char == '+' else "❌" if rep_type_char == '-' else "📝"
        from_user = rep.get("from_username", f"id{rep['from_user']}")
        date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
        
        # Обрезаем текст для отображения
        short_text = rep['text']
        if len(short_text) > 40:
            short_text = short_text[:37] + "..."
        
        text += f"{i}. {emoji} От {from_user}\n"
        text += f"   {short_text}\n"
        text += f"   📅 {date}\n\n"
        
        # Добавляем кнопку для просмотра скрина
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {i}. {from_user} - 📅 {date}", 
            callback_data=f"view_photo_{rep['id']}_{rep_type}"
        )])
    
    if len(filtered_reps) > 10:
        text += f"\n... и еще {len(filtered_reps) - 10} отзывов"
    
    # Кнопка возврата
    keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data='my_reputation')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        # Всегда показываем фото
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
    """Показать меню репутации найденного пользователя (с фото)"""
    user_info = get_user_info(target_user_id)
    username = user_info.get("username", "") if user_info else f"id{target_user_id}"
    
    stats = get_reputation_stats(target_user_id)
    
    # Фильтруем отзывы
    if rep_type == 'positive':
        filtered_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '+']
        title = f"🪄 Положительные отзывы @{username}"
    elif rep_type == 'negative':
        filtered_reps = [r for r in stats['all_reps'] if get_reputation_type(r["text"]) == '-']
        title = f"🪄 Отрицательные отзывы @{username}"
    else:
        filtered_reps = stats['all_reps']
        title = f"🪄 Все отзывы @{username}"
    
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
    
    # Формируем текст и кнопки
    text = f"<b>{title}</b>\n\n"
    keyboard = []
    
    for i, rep in enumerate(filtered_reps[:10], 1):
        rep_type_char = get_reputation_type(rep["text"])
        emoji = "✅" if rep_type_char == '+' else "❌" if rep_type_char == '-' else "📝"
        from_user = rep.get("from_username", f"id{rep['from_user']}")
        date = datetime.fromisoformat(rep["created_at"]).strftime("%d/%m/%Y")
        
        # Обрезаем текст для отображения
        short_text = rep['text']
        if len(short_text) > 40:
            short_text = short_text[:37] + "..."
        
        text += f"{i}. {emoji} От {from_user}\n"
        text += f"   {short_text}\n"
        text += f"   📅 {date}\n\n"
        
        # Добавляем кнопку для просмотра скрина
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {i}. {from_user} - 📅 {date}", 
            callback_data=f"found_view_photo_{rep['id']}_{rep_type}"
        )])
    
    if len(filtered_reps) > 10:
        text += f"\n... и еще {len(filtered_reps) - 10} отзывов"
    
    # Кнопка возврата
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
    
    # Обработка просмотра фото для своих отзывов
    if query.data.startswith('view_photo_'):
        parts = query.data.split('_')
        if len(parts) >= 4:
            rep_id = int(parts[2])
            rep_type = parts[3]
            # Для своих отзывов возвращаемся к соответствующему списку
            back_context = f"back_to_list_{rep_type}"
            await show_reputation_photo(update, rep_id, back_context, context)
        return
    
    # Обработка возврата к списку (свои отзывы)
    if query.data.startswith('back_to_list_'):
        rep_type = query.data.replace('back_to_list_', '')
        await show_my_reputation_menu(query, rep_type)
        return
    
    # Обработка возврата из просмотра фото (пришли из группы)
    if query.data == 'back_from_group_view':
        target_user_id = context.user_data.get('found_user_id')
        if target_user_id:
            await show_reputation_selection_menu(query, is_own=False, target_user_id=target_user_id)
        else:
            await show_main_menu(query)
        return
    
    # Обработка просмотра фото для найденных пользователей
    if query.data.startswith('found_view_photo_'):
        parts = query.data.split('_')
        if len(parts) >= 5:
            rep_id = int(parts[3])
            rep_type = parts[4]
            # Определяем back_context в зависимости от контекста
            if context.user_data.get('from_group'):
                back_context = 'back_from_group_view'
            else:
                back_context = f"found_back_to_list_{rep_type}_{context.user_data.get('found_user_id', 0)}"
            
            await show_reputation_photo(update, rep_id, back_context, context)
        return
    
    # Обработка возврата к списку для найденных пользователей
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
        # Старая логика для остальных кнопок
        await handle_old_button_logic(query, context)

async def show_reputation_selection_menu(query, is_own=True, target_user_id=None):
    """Меню выбора типа репутации (с фото)"""
    text = "<b>Выберите раздел:</b>"
    
    if is_own:
        keyboard = [
            [InlineKeyboardButton("🪄 Положительные", callback_data='show_positive')],
            [InlineKeyboardButton("🪄 Отрицательные", callback_data='show_negative')],
            [InlineKeyboardButton("🪄 Все", callback_data='show_all')],
            [InlineKeyboardButton("🪄 Последний положительный", callback_data='show_last_positive')],
            [InlineKeyboardButton("🪄 Последний отрицательный", callback_data='show_last_negative')],
            [InlineKeyboardButton("↩️ Назад", callback_data='profile')]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🪄 Положительные", callback_data='found_show_positive')],
            [InlineKeyboardButton("🪄 Отрицательные", callback_data='found_show_negative')],
            [InlineKeyboardButton("🪄 Все", callback_data='found_show_all')],
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
    """Обработка последнего отзыва (с фото)"""
    user_id = query.from_user.id if is_own else query.message.chat.id
    
    if is_positive:
        rep_data = get_last_positive(user_id)
        title = "🪄 Последний положительный отзыв"
    else:
        rep_data = get_last_negative(user_id)
        title = "🪄 Последний отрицательный отзыв"
    
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
    
    # Показываем информацию о последнем отзыве
    from_username = rep_data.get("from_username", f"id{rep_data['from_user']}")
    date = datetime.fromisoformat(rep_data["created_at"]).strftime("%d/%m/%Y %H:%M")
    rep_type = get_reputation_type(rep_data["text"])
    emoji = "✅" if rep_type == '+' else "❌" if rep_type == '-' else "📝"
    
    text = f"""<b>{title}</b>

{emoji} От: {from_username}
📅 Дата: {date}

📝 Текст:
{rep_data['text']}"""
    
    # Добавляем кнопку для просмотра скрина
    callback_type = 'view_photo_' if is_own else 'found_view_photo_'
    rep_type_str = 'positive' if is_positive else 'negative'
    keyboard = [
        [InlineKeyboardButton("🪄 Посмотреть скрин", callback_data=f"{callback_type}{rep_data['id']}_{rep_type_str}")],
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
    """Старая логика для кнопок (оставлена для совместимости)"""
    pass

async def show_profile_pm(query, user_id, is_own_profile=True):
    """Показать профиль в личных сообщениях (с фото)"""
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
            [InlineKeyboardButton("🪄 Посмотреть репутацию", callback_data='view_found_user_reputation')],
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
    
    # 🆕 ПРОВЕРКА АДМИНСКИХ КОМАНД
    if update.message.chat.type == 'private' and user_id in ADMINS:
        text = update.message.text or ""
        
        # Обработка кнопки админ-панели
        if text == "🪄 АДМИН ПАНЕЛЬ":
            await handle_admin_panel(update, context)
            return
        
        # Обработка меню админ-панели
        admin_menu_commands = [
            "Удалить отзыв", "Все отзывы", "Поиск по ID",
            "Статистика", "Экспорт", "Просмотр", "Главное меню",
            "✅ Да, удалить", "❌ Нет", "❌ Отмена",
            "🗑 Удалить этот отзыв", "🔙 Назад в меню"
        ]
        
        if text in admin_menu_commands:
            if text in ["✅ Да, удалить", "❌ Нет", "🗑 Удалить этот отзыв", "🔙 Назад в меню", "❌ Отмена"]:
                await handle_admin_actions(update, context)
            else:
                await handle_admin_menu(update, context)
            return
        
        # Обработка ввода админа (ID и т.д.)
        if 'admin_action' in context.user_data or 'viewing_rep_id' in context.user_data:
            await handle_admin_input(update, context)
            return
    
    # Сохраняем всех пользователей (оригинальная логика)
    if update.message.from_user:
        save_user(update.message.from_user.id, update.message.from_user.username or "")
    
    # Сохраняем пользователя из реплая
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        reply_user = update.message.reply_to_message.from_user
        save_user(reply_user.id, reply_user.username or "")
    
    # Сохраняем оригинального отправителя пересланного сообщения
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
    
    # Определяем, кто реальный отправитель
    if update.message.forward_from:
        # Сообщение переслано от другого пользователя
        original_user = update.message.forward_from
        is_forwarded = True
        from_username = original_user.username or f"id{original_user.id}"
        from_user_id = original_user.id
        print(f"🔍 Сообщение ПЕРЕСЛАНО от: {from_username}")
    elif update.message.forward_sender_name:
        # РАЗРЕШАЕМ пересылку от скрытых пользователей!
        original_user = None
        is_forwarded = True
        from_username = f"{update.message.forward_sender_name} (скрытый)"
        from_user_id = None
        print(f"🔍 Сообщение переслано от скрытого пользователя: {from_username}")
    else:
        # Обычное сообщение
        original_user = update.message.from_user
        is_forwarded = False
        from_username = original_user.username or f"id{original_user.id}"
        from_user_id = original_user.id
    
    text = update.message.text or update.message.caption or ""
    
    # ОТЛАДКА
    print(f"\n{'='*60}")
    print(f"🔍 ПОЛУЧЕНО СООБЩЕНИЕ В ГРУППЕ")
    print(f"👤 Отправитель: {from_username} (ID: {from_user_id})")
    print(f"🔁 Переслано: {'Да' if is_forwarded else 'Нет'}")
    print(f"💬 Текст: '{text}'")
    print(f"📷 Есть фото: {bool(update.message.photo)}")
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
    
    # Проверяем, не пытается ли пользователь отправить репутацию самому себе
    if from_user_id and target_info["id"] == from_user_id:
        print(f"❌ Попытка отправить репутацию себе")
        await update.message.reply_text("❌ <b>Нельзя отправлять репутацию самому себе</b>", parse_mode='HTML')
        return
    
    print(f"💾 Сохраняем репутацию...")
    
    save_reputation(
        from_user=from_user_id,  # Может быть None для скрытых пользователей
        from_username=from_username,
        to_user=target_info["id"],
        to_username=target_info["username"],
        text=text,
        photo_id=update.message.photo[-1].file_id
    )
    
    print(f"✅ Репутация успешно сохранена!")
    
    # Отвечаем тому, кто отправил сообщение в чат
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
        [InlineKeyboardButton("🪄 Посмотреть репутацию", callback_data='view_found_user_reputation')],
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
    print(f"✅ Админы: {len(ADMINS)} пользователей") # 🆕
    
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
    
    # 🆕 Обработчик текстовых сообщений (для админ-панели)
    # Должен быть ВЫШЕ общего обработчика, чтобы перехватывать команды
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_all_messages), group=0)
    
    # Обработчик ВСЕХ сообщений (включая группы)
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_all_messages), group=1)
    
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
