import os
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

TOKEN = os.getenv("TELEGRAM_TOKEN")

REPORT_THREAD_ID = 93 
POSTLAR_THREAD_ID = 122 

def init_db():
    try:
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                like_count INTEGER DEFAULT 0,
                last_updated TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER,
                reported_username TEXT,
                timestamp TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB init hatası: {e}")

init_db()

async def post_init(application):
    try:
        await application.bot.set_my_commands([
            BotCommand("rapor", "Bir mesaja yanıt vererek kullanıcıyı rapor et")
        ])
    except Exception as e:
        print(f"Komut set etme hatası: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.from_user:
            return

        if update.message.from_user.is_bot:
            return

        user = update.message.from_user
        user_id = user.id
        username = user.username or user.first_name
        chat = update.message.chat
        message = update.message
        thread_id = message.message_thread_id if hasattr(message, 'message_thread_id') else None
        message_text = message.text or ""

        # 1. RAPOR KANALI KONTROLÜ (93): /rapor haricinde atılan her şeye uyar ver ve çık, asla çökmez!
        if thread_id == REPORT_THREAD_ID and not message_text.startswith('/'):
            try:
                await message.delete()
            except Exception as del_err:
                print(f"Rapor mesajı silinemedi: {del_err}")

            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=thread_id,
                    text=f"@{username}, Bu kanal rapor kanalıdır, buraya sadece /rapor yazabilirsiniz."
                )
            except Exception as send_err:
                print(f"Rapor uyarı mesajı atılamadı: {send_err}")
            return

        # 2. POSTLAR KANALI KONTROLÜ (122): 3 Beğeni kuralı
        if thread_id == POSTLAR_THREAD_ID:
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()

            cursor.execute("SELECT like_count, last_updated FROM likes WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            now = datetime.now()

            if row:
                like_count, last_updated_str = row
                try:
                    last_updated = datetime.fromisoformat(last_updated_str)
                except:
                    last_updated = now

                if now - last_updated > timedelta(hours=24):
                    like_count = 0
                    last_updated = now

                if like_count < 3:
                    try:
                        await message.delete()
                    except:
                        pass
                    try:
                        await context.bot.send_message(
                            chat_id=chat.id,
                            message_thread_id=thread_id,
                            text=f"@{username}, mesaj gönderebilmek için son 24 saat içinde en az 3 içerik beğenmelisin! (Mevcut beğeni: {like_count}/3)"
                        )
                    except:
                        pass
            else:
                cursor.execute("INSERT INTO likes (user_id, username, like_count, last_updated) VALUES (?, ?, 0, ?)", 
                               (user_id, username, now.isoformat()))
                conn.commit()
                try:
                    await message.delete()
                except:
                    pass
                try:
                    await context.bot.send_message(
                        chat_id=chat.id,
                        message_thread_id=thread_id,
                        text=f"@{username}, sistemde kaydın yok. Mesaj atmak için en az 3 içerik beğenmelisin!"
                    )
                except:
                    pass

            conn.close()

    except Exception as e:
        print(f"handle_message genel hata yakalandı: {e}")

async def rapor_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.message
        if not message:
            return
        thread_id = message.message_thread_id if hasattr(message, 'message_thread_id') else None

        if not message.reply_to_message:
            try:
                await message.delete()
            except:
                pass
            try:
                await context.bot.send_message(
                    chat_id=message.chat.id,
                    message_thread_id=thread_id,
                    text="⚠️ Bu kanalda yalnızca şikayet etmek istediğiniz mesaja yanıt vererek `/rapor` yazabilirsiniz."
                )
            except:
                pass
            return

        reporter = message.from_user
        reported_user = message.reply_to_message.from_user
        reported_username = reported_user.username or reported_user.first_name
        chat = message.chat

        if reporter.id == reported_user.id:
            await message.reply_text("❌ Kendini rapor edemezsin!", message_thread_id=thread_id)
            return

        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM reports WHERE reporter_id = ? AND reported_username = ?", 
                       (reporter.id, reported_username))
        existing_report = cursor.fetchone()

        if existing_report:
            cursor.execute("SELECT COUNT(*) FROM reports WHERE reported_username = ?", (reported_username,))
            total_reports = cursor.fetchone()[0]
            await message.reply_text(
                f"⚠️ @{reporter.username or reporter.first_name}, bu kullanıcıyı zaten daha önce raporlamışsın! (Mevcut Durum: {total_reports}/5)",
                message_thread_id=thread_id
            )
        else:
            cursor.execute("INSERT INTO reports (reporter_id, reported_username, timestamp) VALUES (?, ?, ?)",
                           (reporter.id, reported_username, datetime.now().isoformat()))
            conn.commit()

            cursor.execute("SELECT COUNT(*) FROM reports WHERE reported_username = ?", (reported_username,))
            total_reports = cursor.fetchone()[0]

            await message.reply_text(
                f"🚨 Rapor alındı! @{reported_username} için toplam rapor: {total_reports}/5",
                message_thread_id=thread_id
            )

            if total_reports >= 5:
                try:
                    until_date = datetime.now() + timedelta(days=14)
                    await context.bot.restrict_chat_member(
                        chat_id=chat.id,
                        user_id=reported_user.id,
                        permissions={"can_send_messages": False},
                        until_date=until_date
                    )
                    await message.reply_text(
                        f"🔨 @{reported_username} 5 kez raporlandığı için **2 hafta süreyle** susturuldu!",
                        message_thread_id=thread_id
                    )
                except Exception as e:
                    print(f"Mute atma hatası: {e}")
                    await message.reply_text(
                        "❌ Kullanıcı susturulamadı. Botun grupta 'Üyeleri Yasakla/Sustur' yetkisi olduğundan emin olun.",
                        message_thread_id=thread_id
                    )

        conn.close()
    except Exception as e:
        print(f"rapor_komutu genel hata: {e}")

def main():
    try:
        app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

        app.add_handler(CommandHandler("rapor", rapor_komutu))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

        print("Bot çalışıyor...")
        app.run_polling()
    except Exception as e:
        print(f"Bot başlatılamadı: {e}")

if __name__ == "__main__":
    main()
