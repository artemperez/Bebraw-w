import asyncio
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import aiosqlite
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from pyrogram.enums import ParseMode, ChatMemberStatus
import phonenumbers
import re
from contextlib import asynccontextmanager

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = "8203239986:AAF7fFMo5t6Io3sgll8NFaAlYlldfrP2zTM"
API_ID = 22778226
API_HASH = "9be02c55dfb4c834210599490dcd58a8"
CREATOR_ID = 8050595279
ADMIN_IDS = [CREATOR_ID]
DATABASE_NAME = "wenty_snow_bot.db"
LOG_CHANNEL = -1003688204597
SESSION_DIR = "sessions"

# Создаем директории
os.makedirs(SESSION_DIR, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_name: str = DATABASE_NAME):
        self.db_name = db_name
        
    @asynccontextmanager
    async def get_connection(self):
        conn = await aiosqlite.connect(self.db_name)
        try:
            yield conn
            await conn.commit()
        finally:
            await conn.close()
    
    async def init_db(self):
        async with self.get_connection() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    balance INTEGER DEFAULT 100,
                    total_complaints INTEGER DEFAULT 0,
                    banned INTEGER DEFAULT 0,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_complaint_time TIMESTAMP,
                    rules_accepted INTEGER DEFAULT 0,
                    subscribed INTEGER DEFAULT 0,
                    last_bonus_time TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id INTEGER PRIMARY KEY,
                    channel_username TEXT,
                    channel_title TEXT,
                    added_by INTEGER,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_name TEXT PRIMARY KEY,
                    phone_number TEXT,
                    user_id INTEGER,
                    is_active INTEGER DEFAULT 1,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    added_by INTEGER,
                    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS complaints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message_link TEXT,
                    status TEXT DEFAULT 'pending',
                    session_used TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            await conn.commit()
    
    async def add_user(self, user_id: int, username: str, full_name: str):
        async with self.get_connection() as conn:
            await conn.execute(
                'INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)',
                (user_id, username, full_name)
            )
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                'SELECT * FROM users WHERE user_id = ?',
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                columns = [description[0] for description in cursor.description]
                return dict(zip(columns, row))
            return None
    
    async def update_user_complaint(self, user_id: int):
        async with self.get_connection() as conn:
            await conn.execute(
                '''UPDATE users 
                SET total_complaints = total_complaints + 1,
                    last_complaint_time = CURRENT_TIMESTAMP 
                WHERE user_id = ?''',
                (user_id,)
            )
    
    async def set_rules_accepted(self, user_id: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'UPDATE users SET rules_accepted = 1 WHERE user_id = ?',
                (user_id,)
            )
    
    async def set_subscribed(self, user_id: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'UPDATE users SET subscribed = 1 WHERE user_id = ?',
                (user_id,)
            )
    
    async def update_balance(self, user_id: int, amount: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'UPDATE users SET balance = balance + ? WHERE user_id = ?',
                (amount, user_id)
            )
    
    async def set_last_bonus_time(self, user_id: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'UPDATE users SET last_bonus_time = CURRENT_TIMESTAMP WHERE user_id = ?',
                (user_id,)
            )
    
    async def ban_user(self, user_id: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'UPDATE users SET banned = 1 WHERE user_id = ?',
                (user_id,)
            )
    
    async def unban_user(self, user_id: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'UPDATE users SET banned = 0 WHERE user_id = ?',
                (user_id,)
            )
    
    async def add_channel(self, channel_id: int, username: str, title: str, added_by: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'INSERT OR REPLACE INTO channels (channel_id, channel_username, channel_title, added_by) VALUES (?, ?, ?, ?)',
                (channel_id, username, title, added_by)
            )
    
    async def get_channels(self) -> List[Dict]:
        async with self.get_connection() as conn:
            cursor = await conn.execute('SELECT * FROM channels')
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def remove_channel(self, channel_id: int):
        async with self.get_connection() as conn:
            await conn.execute('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
    
    async def add_session(self, session_name: str, phone_number: str, user_id: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'INSERT INTO sessions (session_name, phone_number, user_id) VALUES (?, ?, ?)',
                (session_name, phone_number, user_id)
            )
    
    async def get_sessions(self) -> List[Dict]:
        async with self.get_connection() as conn:
            cursor = await conn.execute('SELECT * FROM sessions WHERE is_active = 1')
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def get_active_session(self) -> Optional[str]:
        sessions = await self.get_sessions()
        if sessions:
            return sessions[0]['session_name']
        return None
    
    async def add_admin(self, user_id: int, username: str, added_by: int):
        async with self.get_connection() as conn:
            await conn.execute(
                'INSERT OR IGNORE INTO admins (user_id, username, added_by) VALUES (?, ?, ?)',
                (user_id, username, added_by)
            )
    
    async def is_admin(self, user_id: int) -> bool:
        if user_id in ADMIN_IDS:
            return True
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                'SELECT 1 FROM admins WHERE user_id = ?',
                (user_id,)
            )
            return await cursor.fetchone() is not None
    
    async def get_admins(self) -> List[Dict]:
        async with self.get_connection() as conn:
            cursor = await conn.execute('SELECT * FROM admins')
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def add_complaint(self, user_id: int, message_link: str, session_used: str):
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                '''INSERT INTO complaints (user_id, message_link, session_used) 
                VALUES (?, ?, ?)''',
                (user_id, message_link, session_used)
            )
            return cursor.lastrowid
    
    async def get_user_complaints(self, user_id: int, limit: int = 10) -> List[Dict]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                'SELECT * FROM complaints WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
                (user_id, limit)
            )
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def get_all_complaints(self, limit: int = 50) -> List[Dict]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                '''SELECT c.*, u.username, u.full_name 
                FROM complaints c 
                LEFT JOIN users u ON c.user_id = u.user_id 
                ORDER BY c.created_at DESC LIMIT ?''',
                (limit,)
            )
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def get_stats(self) -> Dict:
        async with self.get_connection() as conn:
            cursor = await conn.execute('SELECT COUNT(*) FROM complaints')
            total_complaints = (await cursor.fetchone())[0]
            
            cursor = await conn.execute('SELECT COUNT(*) FROM users')
            total_users = (await cursor.fetchone())[0]
            
            cursor = await conn.execute('SELECT COUNT(*) FROM sessions WHERE is_active = 1')
            active_sessions = (await cursor.fetchone())[0]
            
            cursor = await conn.execute('SELECT COUNT(*) FROM users WHERE banned = 1')
            banned_users = (await cursor.fetchone())[0]
            
            cursor = await conn.execute('SELECT COUNT(*) FROM users WHERE DATE(registration_date) = DATE("now")')
            today_users = (await cursor.fetchone())[0]
            
            return {
                'total_complaints': total_complaints,
                'total_users': total_users,
                'active_sessions': active_sessions,
                'banned_users': banned_users,
                'today_users': today_users
            }
    
    async def get_all_users(self) -> List[Dict]:
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                'SELECT user_id, username, full_name, total_complaints, banned, balance FROM users ORDER BY registration_date DESC'
            )
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

# ========== ИНИЦИАЛИЗАЦИЯ ==========
db = Database()
bot = Client("wenty_snow", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Красивое главное меню для Wenty snow ⛄️"""
    buttons = [
        [
            InlineKeyboardButton("👤 Профиль", callback_data="profile"),
            InlineKeyboardButton("⚠️ Жалоба", callback_data="send_complaint")
        ],
        [
            InlineKeyboardButton("📊 Мои жалобы", callback_data="my_complaints"),
            InlineKeyboardButton("🎁 Бонус", callback_data="bonus")
        ],
        [
            InlineKeyboardButton("👑 Админ-панель", callback_data="admin_panel"),
            InlineKeyboardButton("❓ Помощь", callback_data="help")
        ],
        [
            InlineKeyboardButton("📢 Наш канал", url="https://t.me/+example"),
            InlineKeyboardButton("⭐️ Оценить", callback_data="rate")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Админ-панель"""
    buttons = [
        [
            InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
            InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("📢 Каналы", callback_data="admin_channels"),
            InlineKeyboardButton("🔑 Сессии", callback_data="admin_sessions")
        ],
        [
            InlineKeyboardButton("👑 Админы", callback_data="admin_admins"),
            InlineKeyboardButton("⚠️ Жалобы", callback_data="admin_complaints")
        ],
        [
            InlineKeyboardButton("💰 Балансы", callback_data="admin_balance"),
            InlineKeyboardButton("⚙️ Рассылка", callback_data="admin_broadcast")
        ],
        [
            InlineKeyboardButton("◀️ В меню", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def get_back_keyboard(target: str = "main_menu") -> InlineKeyboardMarkup:
    """Кнопка Назад"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=target)]])

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка Отмена"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="main_menu")]])

async def check_subscription(user_id: int) -> bool:
    """Проверка подписки на каналы"""
    channels = await db.get_channels()
    if not channels:
        return True
    
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel['channel_id'], user_id)
            if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED]:
                return False
        except Exception as e:
            logger.error(f"Ошибка проверки подписки: {e}")
            continue
    return True

async def send_complaint_report(message_link: str, session_name: str) -> bool:
    """Отправка жалобы через сессию"""
    try:
        session_path = os.path.join(SESSION_DIR, f"{session_name}.session")
        if not os.path.exists(session_path):
            logger.error(f"Сессия {session_name} не найдена")
            return False
        
        # Парсим ссылку
        pattern = r't\.me/(?:c/)?([^/]+)/(\d+)'
        match = re.search(pattern, message_link)
        if not match:
            return False
        
        chat_identifier = match.group(1)
        message_id = int(match.group(2))
        
        async with Client(session_name, api_id=API_ID, api_hash=API_HASH, 
                         workdir=SESSION_DIR) as app:
            try:
                await app.report_message(
                    chat_id=chat_identifier,
                    message_id=message_id,
                    reason="spam"
                )
                logger.info(f"Жалоба отправлена через сессию {session_name}")
                return True
            except Exception as e:
                logger.error(f"Ошибка отправки жалобы: {e}")
                return False
                
    except Exception as e:
        logger.error(f"Ошибка в send_complaint_report: {e}")
        return False

async def log_to_channel(text: str, parse_mode: ParseMode = ParseMode.HTML):
    """Логирование в канал"""
    try:
        await bot.send_message(LOG_CHANNEL, text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Ошибка отправки лога: {e}")

async def send_welcome_animation(chat_id: int):
    """Отправка приветственной анимации/стикера"""
    try:
        # Стикер снежинки или зимней тематики
        await bot.send_sticker(
            chat_id,
            "CAACAgIAAxkBAAIBdWgHktv6iNf6wTcyYqfL9__t2cEOAAIMAAPBnGAMnWlRaxX0VrM1BA"
        )
    except:
        pass  # Если стикер не отправился, продолжаем без него

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@bot.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user = message.from_user
    await db.add_user(user.id, user.username, user.first_name)
    
    # Проверка бана
    user_data = await db.get_user(user.id)
    if user_data and user_data.get('banned'):
        await message.reply_text(
            "❌ <b>Вы заблокированы в боте Wenty snow ⛄️</b>\n\n"
            "Если вы считаете, что это ошибка, свяжитесь с администрацией.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Отправляем приветствие
    await send_welcome_animation(message.chat.id)
    
    welcome_text = f"""
    ❄️ <b>Добро пожаловать в Wenty snow ⛄️!</b> ❄️

    👋 <b>Привет, {user.first_name}!</b>

    🤖 <b>Я - умный бот для отправки жалоб в Telegram</b>
    ⚡️ Помогаю модераторам поддерживать чистоту в чатах

    🎯 <b>Возможности:</b>
    • Отправка жалоб на нарушителей
    • Статистика вашей активности
    • Бонусы за активность
    • Красивый зимний интерфейс

    📋 <b>Для начала работы примите правила:</b>
    """
    
    await message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Принять правила", callback_data="accept_rules")
        ]]),
        parse_mode=ParseMode.HTML
    )
    
    # Логируем старт
    log_text = f"❄️ Новый пользователь: {user.mention} (ID: {user.id})"
    await log_to_channel(log_text)

@bot.on_callback_query(filters.regex("^accept_rules$"))
async def accept_rules_callback(client: Client, callback_query: CallbackQuery):
    """Правила использования"""
    rules_text = """
    📜 <b>Правила Wenty snow ⛄️</b>

    1. ⚠️ <b>Использование по назначению</b>
    • Отправляйте жалобы только на реальные нарушения
    • Не используйте для спама или троллинга
    
    2. ⏳ <b>Кулдаун</b>
    • Между жалобами: 150 секунд
    • За нарушения кулдауна - предупреждение
    
    3. ❌ <b>Запрещено</b>
    • Массовая отправка жалоб
    • Использование автоматических скриптов
    • Обход ограничений
    
    4. ⚖️ <b>Ответственность</b>
    • Вы несете ответственность за свои жалобы
    • Администрация вправе заблокировать за нарушения
    
    5. 🎁 <b>Бонусная система</b>
    • +10 снежинок за каждую жалобу
    • Ежедневный бонус за вход
    
    ❄️ <b>Соглашаясь, вы принимаете эти правила!</b>
    """
    
    await callback_query.message.edit_text(
        rules_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Я согласен", callback_data="rules_accepted")],
            [InlineKeyboardButton("❌ Отказаться", callback_data="rules_declined")]
        ]),
        parse_mode=ParseMode.HTML
    )

@bot.on_callback_query(filters.regex("^rules_accepted$"))
async def rules_accepted_callback(client: Client, callback_query: CallbackQuery):
    """Пользователь принял правила"""
    user_id = callback_query.from_user.id
    await db.set_rules_accepted(user_id)
    
    # Проверка подписки
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await show_main_menu(callback_query)
        await db.set_subscribed(user_id)
    else:
        await show_subscription_request(callback_query)

@bot.on_callback_query(filters.regex("^rules_declined$"))
async def rules_declined_callback(client: Client, callback_query: CallbackQuery):
    """Отказ от правил"""
    await callback_query.message.edit_text(
        "❌ <b>Вы отказались от правил</b>\n\n"
        "Бот Wenty snow ⛄️ недоступен без принятия правил.",
        reply_markup=None,
        parse_mode=ParseMode.HTML
    )

async def show_subscription_request(callback_query: CallbackQuery):
    """Запрос подписки на каналы"""
    channels = await db.get_channels()
    
    if not channels:
        await show_main_menu(callback_query)
        return
    
    text = """
    📢 <b>Подписка на каналы</b> ❄️
    
    Для использования бота Wenty snow ⛄️
    необходимо подписаться на наши каналы:
    """
    
    buttons = []
    for channel in channels:
        if channel['channel_username']:
            url = f"https://t.me/{channel['channel_username']}"
        else:
            url = f"https://t.me/c/{str(channel['channel_id']).replace('-100', '')}"
        
        buttons.append([
            InlineKeyboardButton(
                f"📢 {channel['channel_title']}",
                url=url
            )
        ])
    
    buttons.append([
        InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription")
    ])
    buttons.append([
        InlineKeyboardButton("◀️ Назад", callback_data="accept_rules")
    ])
    
    await callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML
    )

@bot.on_callback_query(filters.regex("^check_subscription$"))
async def check_subscription_callback(client: Client, callback_query: CallbackQuery):
    """Проверка подписки"""
    user_id = callback_query.from_user.id
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        await db.set_subscribed(user_id)
        await show_main_menu(callback_query)
        await callback_query.answer("✅ Отлично! Вы подписаны на все каналы!", show_alert=True)
    else:
        await callback_query.answer("❌ Вы не подписались на все каналы!", show_alert=True)

async def show_main_menu(callback_query: CallbackQuery):
    """Главное меню"""
    menu_text = """
    ❄️ <b>Wenty snow ⛄️</b> - Главное меню
    
    🎯 <b>Выберите действие:</b>
    """
    
    await callback_query.message.edit_text(
        menu_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )

# ========== ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ ==========
@bot.on_callback_query(filters.regex("^profile$"))
async def profile_callback(client: Client, callback_query: CallbackQuery):
    """Профиль пользователя"""
    user = callback_query.from_user
    user_data = await db.get_user(user.id)
    
    if not user_data:
        await callback_query.answer("Ошибка загрузки профиля", show_alert=True)
        return
    
    # Проверяем кулдаун
    cooldown_text = ""
    if user_data.get('last_complaint_time'):
        last_time = datetime.fromisoformat(user_data['last_complaint_time'])
        cooldown = timedelta(seconds=150)
        
        if datetime.now() - last_time < cooldown:
            remaining = cooldown - (datetime.now() - last_time)
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            cooldown_text = f"\n⏳ До след. жалобы: {minutes:02d}:{seconds:02d}"
        else:
            cooldown_text = "\n✅ Можно отправлять жалобу"
    else:
        cooldown_text = "\n✅ Можно отправлять жалобу"
    
    profile_text = f"""
    👤 <b>Ваш профиль</b> ❄️
    
    ┌ <b>ID:</b> <code>{user.id}</code>
    ├ <b>Имя:</b> {user.first_name}
    ├ <b>Юзернейм:</b> @{user.username if user.username else 'Нет'}
    ├ <b>Баланс:</b> {user_data['balance']} ❄️
    ├ <b>Жалоб отправлено:</b> {user_data['total_complaints']}
    └ <b>Статус:</b> {'✅ Активен' if not user_data['banned'] else '❌ Заблокирован'}
    
    📅 <b>Регистрация:</b> {user_data['registration_date'][:10]}
    {cooldown_text}
    
    🎁 <b>Бонусы:</b> Доступны каждые 24 часа
    """
    
    buttons = [
        [InlineKeyboardButton("🎁 Получить бонус", callback_data="bonus")],
        [InlineKeyboardButton("◀️ В меню", callback_data="main_menu")]
    ]
    
    await callback_query.message.edit_text(
        profile_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML
    )

# ========== ОТПРАВКА ЖАЛОБЫ ==========
@bot.on_callback_query(filters.regex("^send_complaint$"))
async def send_complaint_callback(client: Client, callback_query: CallbackQuery):
    """Начало отправки жалобы"""
    user_id = callback_query.from_user.id
    user_data = await db.get_user(user_id)
    
    if not user_data or user_data.get('banned'):
        await callback_query.answer("❌ Вы заблокированы!", show_alert=True)
        return
    
    # Проверка кулдауна
    if user_data.get('last_complaint_time'):
        last_time = datetime.fromisoformat(user_data['last_complaint_time'])
        cooldown = timedelta(seconds=150)
        
        if datetime.now() - last_time < cooldown:
            remaining = cooldown - (datetime.now() - last_time)
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            await callback_query.answer(
                f"⏳ Кулдаун! Ждите {minutes}:{seconds:02d}",
                show_alert=True
            )
            return
    
    text = """
    ⚠️ <b>Отправка жалобы</b> ❄️
    
    📝 <b>Инструкция:</b>
    1. Найдите нарушение в Telegram
    2. Скопируйте ссылку на сообщение
    3. Отправьте ссылку боту
    
    🔗 <b>Формат ссылки:</b>
    <code>https://t.me/username/123</code>
    или
    <code>https://t.me/c/chat_id/123</code>
    
    ⏳ <b>Кулдаун:</b> 150 секунд
    🎁 <b>Награда:</b> +10 снежинок ❄️
    
    📨 <b>Отправьте ссылку сейчас:</b>
    """
    
    await callback_query.message.edit_text(
        text,
        reply_markup=get_cancel_keyboard(),
        parse_mode=ParseMode.HTML
    )
    
    # Устанавливаем состояние ожидания ссылки
    await client.send_message(
        user_id,
        "🔄 <b>Ожидаю ссылку на сообщение...</b>\n"
        "Отправьте ссылку или нажмите ❌ Отмена",
        parse_mode=ParseMode.HTML
    )

@bot.on_message(filters.private & filters.text & ~filters.command(["start", "help", "admin"]))
async def handle_message_link(client: Client, message: Message):
    """Обработка ссылки на сообщение"""
    user_id = message.from_user.id
    
    if not message.text.startswith("https://t.me/"):
        return
    
    # Проверяем кулдаун
    user_data = await db.get_user(user_id)
    if not user_data or user_data.get('banned'):
        await message.reply_text("❌ Вы заблокированы в боте!")
        return
    
    if user_data.get('last_complaint_time'):
        last_time = datetime.fromisoformat(user_data['last_complaint_time'])
        cooldown = timedelta(seconds=150)
        
        if datetime.now() - last_time < cooldown:
            remaining = cooldown - (datetime.now() - last_time)
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            await message.reply_text(
                f"⏳ Кулдаун! Подождите {minutes} мин {seconds} сек",
                reply_markup=get_back_keyboard()
            )
            return
    
    # Проверяем активные сессии
    session_name = await db.get_active_session()
    if not session_name:
        await message.reply_text(
            "❌ Нет активных сессий для отправки жалоб",
            reply_markup=get_back_keyboard()
        )
        return
    
    # Отправляем жалобу
    processing_msg = await message.reply_text("❄️ <b>Отправляю жалобу...</b>", parse_mode=ParseMode.HTML)
    
    success = await send_complaint_report(message.text, session_name)
    
    if success:
        # Сохраняем в БД
        complaint_id = await db.add_complaint(user_id, message.text, session_name)
        await db.update_user_complaint(user_id)
        await db.update_balance(user_id, 10)  # +10 снежинок за жалобу
        
        # Логируем
        log_text = f"""
        ❄️ <b>Новая жалоба #{complaint_id}</b>
        
        ├ <b>Пользователь:</b> {message.from_user.mention}
        ├ <b>ID:</b> <code>{user_id}</code>
        ├ <b>Ссылка:</b> <code>{message.text[:50]}...</code>
        ├ <b>Сессия:</b> {session_name}
        └ <b>Время:</b> {datetime.now().strftime('%H:%M:%S')}
        """
        await log_to_channel(log_text)
        
        await processing_msg.edit_text(
            f"""
            ✅ <b>Жалоба успешно отправлена!</b> ❄️
            
            📊 <b>Информация:</b>
            ├ Номер жалобы: <code>#{complaint_id}</code>
            ├ Снежинок получено: +10 ❄️
            ├ Новый баланс: {user_data['balance'] + 10} ❄️
            └ Следующая жалоба через: 2:30
            
            🎉 <b>Спасибо за помощь в модерации!</b>
            """,
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.HTML
        )
    else:
        await processing_msg.edit_text(
            """
            ❌ <b>Ошибка отправки жалобы</b>
            
            Возможные причины:
            • Неверная ссылка
            • Сообщение удалено
            • Ошибка сессии
            • Нет доступа к чату
            
            Попробуйте другую ссылку или обратитесь в поддержку.
            """,
            reply_markup=get_back_keyboard(),
            parse_mode=ParseMode.HTML
        )

# ========== МОИ ЖАЛОБЫ ==========
@bot.on_callback_query(filters.regex("^my_complaints$"))
async def my_complaints_callback(client: Client, callback_query: CallbackQuery):
    """Список жалоб пользователя"""
    user_id = callback_query.from_user.id
    complaints = await db.get_user_complaints(user_id, limit=10)
    
    if not complaints:
        text = """
        📭 <b>У вас пока нет жалоб</b> ❄️
        
        Отправьте свою первую жалобу и получите:
        • +10 снежинок ❄️
        • Статус активного пользователя
        • Доступ к бонусам
        """
        buttons = [
            [InlineKeyboardButton("⚠️ Отправить жалобу", callback_data="send_complaint")],
            [InlineKeyboardButton("◀️ В меню", callback_data="main_menu")]
        ]
    else:
        text = f"""
        📊 <b>Ваши последние жалобы</b> ❄️
        
        Всего отправлено: <b>{len(complaints)}</b>
        """
        
        for i, comp in enumerate(complaints[:5], 1):
            date = comp['created_at'][:16].replace('T', ' ')
            status_icon = "✅" if comp['status'] == 'success' else "🔄"
            text += f"\n{i}. {status_icon} {date} - {comp['message_link'][:30]}..."
        
        if len(complaints) > 5:
            text += f"\n\n... и еще {len(complaints) - 5} жалоб"
        
        buttons = [
            [InlineKeyboardButton("⚠️ Новая жалоба", callback_data="send_complaint")],
            [InlineKeyboardButton("◀️ В меню", callback_data="main_menu")]
        ]
    
    await callback_query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.HTML
    )

# ========== БОНУСЫ ==========
@bot.on_callback_query(filters.regex("^bonus$"))
async def bonus_callback(client: Client, callback_query: CallbackQuery):
    """Ежедневный бонус"""
    user_id = callback_query.from_user.id
    user_data = await db.get_user(user_id)
    
    if not user_data:
        await callback_query.answer("Ошибка загрузки профиля", show_alert=True)
        return
    
    # Проверяем