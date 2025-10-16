import asyncio
import aiosqlite
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ContentType


BOT_TOKEN = "8470870259:AAFi1WHDudG1Za7X4-BUMblkEugu_-mZdx0"


DB_PATH = "streaks.db"
STREAK_TIMEOUT = timedelta(hours=24)
MIN_STREAK_TO_ANNOUNCE = 3

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS streaks (
                chat_id INTEGER PRIMARY KEY,
                streak_count INTEGER DEFAULT 1,
                last_activity TIMESTAMP,
                last_user_id INTEGER,
                last_username TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS streak_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                chat_title TEXT,
                streak_count INTEGER,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                reason TEXT
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                username TEXT,
                activity_count INTEGER DEFAULT 1,
                last_activity TIMESTAMP
            )
        """)
        
        await db.commit()


def get_streak_emoji(streak_count: int) -> str:
    if streak_count >= 30:
        return "🔥💎"
    elif streak_count >= 20:
        return "🔥🏆"
    elif streak_count >= 10:
        return "🔥⭐"
    elif streak_count >= 5:
        return "🔥"
    else:
        return "✨"


async def get_current_streak(chat_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM streaks WHERE chat_id = ?",
            (chat_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def save_streak_to_history(chat_id: int, chat_title: str, streak_count: int, 
                                 start_date: datetime, reason: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO streak_history (chat_id, chat_title, streak_count, start_date, end_date, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, chat_title, streak_count, start_date, datetime.now(), reason))
        await db.commit()


async def update_user_activity(chat_id: int, user_id: int, username: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT activity_count FROM user_activity WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        row = await cursor.fetchone()
        
        if row:
            await db.execute("""
                UPDATE user_activity 
                SET activity_count = activity_count + 1, 
                    last_activity = ?,
                    username = ?
                WHERE chat_id = ? AND user_id = ?
            """, (datetime.now(), username, chat_id, user_id))
        else:
            await db.execute("""
                INSERT INTO user_activity (chat_id, user_id, username, activity_count, last_activity)
                VALUES (?, ?, ?, 1, ?)
            """, (chat_id, user_id, username, datetime.now()))
        
        await db.commit()


async def check_and_update_streak(message: Message) -> dict:
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    current_time = datetime.now()
    
    streak_data = await get_current_streak(chat_id)
    
    async with aiosqlite.connect(DB_PATH) as db:
        if not streak_data:
            await db.execute("""
                INSERT INTO streaks (chat_id, streak_count, last_activity, last_user_id, last_username)
                VALUES (?, 1, ?, ?, ?)
            """, (chat_id, current_time, user_id, username))
            await db.commit()
            return {'is_new_streak': True, 'count': 1, 'broken': False}
        
        last_activity = datetime.fromisoformat(streak_data['last_activity'])
        time_diff = current_time - last_activity
        
        if time_diff > STREAK_TIMEOUT:
            old_streak = streak_data['streak_count']
            
            await save_streak_to_history(
                chat_id, 
                message.chat.title or "Личные сообщения",
                old_streak,
                last_activity,
                "timeout"
            )
            
            # Начинаем новый стрик
            await db.execute("""
                UPDATE streaks 
                SET streak_count = 1, 
                    last_activity = ?,
                    last_user_id = ?,
                    last_username = ?
                WHERE chat_id = ?
            """, (current_time, user_id, username, chat_id))
            await db.commit()
            
            return {'is_new_streak': True, 'count': 1, 'broken': True, 'old_streak': old_streak}
        
        # Увеличиваем стрик
        new_count = streak_data['streak_count'] + 1
        await db.execute("""
            UPDATE streaks 
            SET streak_count = ?,
                last_activity = ?,
                last_user_id = ?,
                last_username = ?
            WHERE chat_id = ?
        """, (new_count, current_time, user_id, username, chat_id))
        await db.commit()
        
        return {'is_new_streak': False, 'count': new_count, 'broken': False}


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я бот для отслеживания стриков активности в чате.\n\n"
        "📊 Я считаю каждое сообщение, фото, видео и другой контент.\n"
        f"⏰ Стрик прерывается, если активности нет более {STREAK_TIMEOUT.total_seconds() / 3600:.0f} часов.\n\n"
        "Команды:\n"
        "/streak - показать текущий стрик\n"
        "/stats - статистика чата\n"
        "/history - история стриков\n"
        "/top - топ активных участников\n"
        "/reset - сбросить стрик (только для админов)"
    )


@dp.message(Command("streak"))
async def cmd_streak(message: Message):
    """Показывает текущий стрик чата"""
    chat_id = message.chat.id
    streak_data = await get_current_streak(chat_id)
    
    if not streak_data:
        await message.answer("📊 В этом чате еще нет активности!")
        return
    
    streak_count = streak_data['streak_count']
    last_activity = datetime.fromisoformat(streak_data['last_activity'])
    time_since = datetime.now() - last_activity
    
    emoji = get_streak_emoji(streak_count)
    
    hours_remaining = STREAK_TIMEOUT.total_seconds() - time_since.total_seconds()
    hours_remaining = max(0, hours_remaining / 3600)
    
    minutes_ago = time_since.seconds // 60
    
    await message.answer(
        f"{emoji} <b>Текущий стрик: {streak_count}</b>\n"
        f"👤 Последняя активность: {streak_data['last_username']}\n"
        f"🕐 Время: {minutes_ago} минут назад\n"
        f"⏳ До сброса осталось: {hours_remaining:.1f} часов",
        parse_mode="HTML"
    )


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Показывает статистику чата"""
    chat_id = message.chat.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        # Текущий стрик
        streak_data = await get_current_streak(chat_id)
        
        # Лучший стрик
        cursor = await db.execute("""
            SELECT MAX(streak_count) as best_streak 
            FROM streak_history 
            WHERE chat_id = ?
        """, (chat_id,))
        best_row = await cursor.fetchone()
        best_streak = best_row['best_streak'] if best_row['best_streak'] else 0
        
        # Общее количество активностей
        cursor = await db.execute("""
            SELECT SUM(activity_count) as total_activities
            FROM user_activity
            WHERE chat_id = ?
        """, (chat_id,))
        activity_row = await cursor.fetchone()
        total_activities = activity_row['total_activities'] if activity_row['total_activities'] else 0
        
        if not streak_data and best_streak == 0:
            await message.answer("📊 В этом чате еще нет статистики!")
            return
        
        current_streak = streak_data['streak_count'] if streak_data else 0
        if current_streak > best_streak:
            best_streak = current_streak
        
        await message.answer(
            f"📊 <b>Статистика чата</b>\n\n"
            f"🔥 Текущий стрик: {current_streak}\n"
            f"🏆 Лучший стрик: {best_streak}\n"
            f"📈 Всего активностей: {total_activities}",
            parse_mode="HTML"
        )


@dp.message(Command("history"))
async def cmd_history(message: Message):
    """Показывает историю стриков"""
    chat_id = message.chat.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT streak_count, start_date, end_date, reason
            FROM streak_history
            WHERE chat_id = ?
            ORDER BY end_date DESC
            LIMIT 10
        """, (chat_id,))
        rows = await cursor.fetchall()
        
        if not rows:
            await message.answer("📜 История стриков пока пуста!")
            return
        
        history_text = "📜 <b>История стриков</b>\n\n"
        for i, row in enumerate(rows, 1):
            end_date = datetime.fromisoformat(row['end_date'])
            history_text += (
                f"{i}. 🔥 <b>{row['streak_count']}</b> "
                f"({end_date.strftime('%d.%m.%Y')})\n"
            )
        
        await message.answer(history_text, parse_mode="HTML")


@dp.message(Command("top"))
async def cmd_top(message: Message):
    """Показывает топ активных участников"""
    chat_id = message.chat.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT username, activity_count
            FROM user_activity
            WHERE chat_id = ?
            ORDER BY activity_count DESC
            LIMIT 10
        """, (chat_id,))
        rows = await cursor.fetchall()
        
        if not rows:
            await message.answer("👥 Статистика участников пока пуста!")
            return
        
        top_text = "👥 <b>Топ активных участников</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i+1}."
            top_text += f"{medal} {row['username']}: <b>{row['activity_count']}</b>\n"
        
        await message.answer(top_text, parse_mode="HTML")


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    """Сбрасывает стрик (только для админов)"""
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status not in ["administrator", "creator"]:
            await message.answer("❌ Только администраторы могут сбрасывать стрики!")
            return
    except:
        pass
    
    streak_data = await get_current_streak(chat_id)
    if not streak_data:
        await message.answer("📊 Нечего сбрасывать!")
        return
    
    # Сохраняем в историю
    await save_streak_to_history(
        chat_id,
        message.chat.title or "Личные сообщения",
        streak_data['streak_count'],
        datetime.fromisoformat(streak_data['last_activity']),
        "manual_reset"
    )
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM streaks WHERE chat_id = ?", (chat_id,))
        await db.commit()
    
    await message.answer(f"🔄 Стрик сброшен! Предыдущий стрик: {streak_data['streak_count']}")


@dp.message(F.content_type.in_({
    ContentType.TEXT,
    ContentType.PHOTO,
    ContentType.VIDEO,
    ContentType.DOCUMENT,
    ContentType.AUDIO,
    ContentType.VOICE,
    ContentType.VIDEO_NOTE,
    ContentType.STICKER,
    ContentType.ANIMATION
}))
async def track_activity(message: Message):
    """Отслеживает любую активность в чате"""
    # Игнорируем команды
    if message.text and message.text.startswith('/'):
        return
    
    result = await check_and_update_streak(message)
    
    username = message.from_user.username or message.from_user.first_name
    await update_user_activity(message.chat.id, message.from_user.id, username)
    
    if result['broken'] and result['old_streak'] >= MIN_STREAK_TO_ANNOUNCE:
        await message.answer(
            f"💔 Стрик прерван! Предыдущий стрик: {result['old_streak']}\n"
            f"🆕 Начинаем новый стрик!"
        )
    
    # Объявляем о важных вехах
    count = result['count']
    if count in [5, 10, 25, 50, 100, 200, 500, 1000]:
        emoji = get_streak_emoji(count)
        await message.answer(
            f"{emoji} <b>Вау! Стрик достиг {count}!</b>\n"
            f"Продолжайте в том же духе! 💪",
            parse_mode="HTML"
        )


async def main():
    """Запуск бота"""
    await init_db()
    print("🤖 Бот запущен!")
    print("📊 База данных инициализирована!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())