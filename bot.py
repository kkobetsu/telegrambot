import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

TOKEN = "8800803293:AAF3dSlDMLtliGcTgOGIfyqfHXeZY2iXlPo"

def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    
    if not user or not message:
        return

    if user.is_bot:
        return

    print(f"Mesaj yakalandı: '{message.text}' (Gönderen: {user.first_name})")

    user_id = user.id
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) FROM interactions 
        WHERE user_id = ? AND timestamp >= ?
    """, (user_id, cutoff_time.isoformat()))
    
    count = cursor.fetchone()[0]
    conn.close()

    if count < 3:
        try:
            await message.delete()
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"@{user.username or user.first_name}, mesaj gönderebilmek için son 24 saat içinde en az 3 içerik beğenmelisin! (Mevcut beğeni: {count}/3)"
            )
        except Exception as e:
            print(f"Mesaj silinirken hata oluştu: {e}")

def main():
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    print("Bot çalışıyor ve mesajları dinliyor...")
    app.run_polling()

if __name__ == "__main__":
    main()