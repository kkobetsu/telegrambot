import os
import sqlite3
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# Railway ortam değişkeninden token'ı alıyoruz
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Rapor kanalının (topic) ID'si veya adı (İsteğe bağlı ID sabitlemek için kullanılabilir, şimdilik genel kontrol ekliyoruz)
# Eğer raporların sadece belirli bir konuda atılmasını istiyorsan topic_id kontrolü yapılabilir.

def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    # Beğeni tablosu
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            like_count INTEGER DEFAULT 0,
            last_updated TEXT
        )
    """)
    # Raporlar tablosu (Kim kimi raporladı)
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

init_db()

# Mesaj geldiğinde çalışacak fonksiyon (Etkileşim / Beğeni kontrolü veya Rapor kanalındaki kural dışı mesajlar)
async def check_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    user = update.message.from_user
    user_id = user.id
    username = user.username or user.first_name
    chat = update.message.chat
    message = update.message

    # Adminler mesaj atarken takılmasın
    if chat.type in ["group", "supergroup"]:
        try:
            member = await chat.get_member(user_id)
            if member.status in ["creator", "administrator"]:
                return
        except Exception:
            pass

    # 1. KURAL: Rapor kanalında (veya genel akışta) düz metin yazılmasını engellemek istiyorsak, 
    # Burada kanal/topic kontrolü yapabiliriz. Eğer burası Rapor başlığıysa ve komut değilse silebiliriz.
    # Telegram forum konularında her konunun bir message_thread_id'si vardır. 
    # Kullanıcı rapor kanalına düz yazı yazdıysa siliyoruz:
    
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()

    # Kullanıcının veritabanındaki beğeni durumunu kontrol et
    cursor.execute("SELECT like_count, last_updated FROM likes WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    now = datetime.now()

    if row:
        like_count, last_updated_str = row
        last_updated = datetime.fromisoformat(last_updated_str)

        # 24 saat geçmişse sayacı sıfırla
        if now - last_updated > timedelta(hours=24):
            like_count = 0
            last_updated = now

        # Eğer beğenisi 3'ten azsa mesajı sil ve uyar
        if like_count < 3:
            try:
                await message.delete()
                warning_msg = await context.bot.send_message(
                    chat_id=chat.id,
                    message_thread_id=message.message_thread_id, # Konu (topic) bütünlüğünü korur
                    text=f"@{username}, mesaj gönderebilmek için son 24 saat içinde en az 3 içerik beğenmelisin! (Mevcut beğeni: {like_count}/3)"
                )
            except Exception as e:
                print(f"Mesaj silme hatası: {e}")
    else:
        # Yeni kullanıcı, kaydını oluştur ve ilk mesajını engelle
        cursor.execute("INSERT INTO likes (user_id, username, like_count, last_updated) VALUES (?, ?, 0, ?)", 
                       (user_id, username, now.isoformat()))
        conn.commit()
        try:
            await message.delete()
            await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=message.message_thread_id,
                text=f"@{username}, sistemde kaydın yok veya son 24 saatte beğeni yapmadın. Mesaj atmak için en az 3 içerik beğenmelisin!"
            )
        except Exception as e:
            print(f"Yeni kullanıcı mesaj silme hatası: {e}")

    conn.close()

# /rapor komutu fonksiyonu (Sadece /rapor dışındaki yazıları rapor kanalında engellemek için filtre ekleyebiliriz)
async def rapor_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.reply_to_message:
        await message.reply_text(
            "⚠️ Lütfen rapor etmek istediğiniz kişinin **mesajına yanıt vererek** `/rapor` yazın.",
            message_thread_id=message.message_thread_id
        )
        return

    reporter = message.from_user
    reported_user = message.reply_to_message.from_user
    reported_username = reported_user.username or reported_user.first_name
    chat = message.chat

    if reporter.id == reported_user.id:
        await message.reply_text("❌ Kendini rapor edemezsin!", message_thread_id=message.message_thread_id)
        return

    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()

    # Bu kişi bu kullanıcıyı daha önce raporlamış mı kontrol et (Spam önlemi)
    cursor.execute("SELECT id FROM reports WHERE reporter_id = ? AND reported_username = ?", 
                   (reporter.id, reported_username))
    existing_report = cursor.fetchone()

    if existing_report:
        # Toplam rapor sayısını yine de çekip X/5 şeklinde gösterelim
        cursor.execute("SELECT COUNT(*) FROM reports WHERE reported_username = ?", (reported_username,))
        total_reports = cursor.fetchone()[0]
        await message.reply_text(
            f"⚠️ @{reporter.username or reporter.first_name}, bu kullanıcıyı zaten daha önce raporlamışsın! (Mevcut Durum: {total_reports}/5)",
            message_thread_id=message.message_thread_id
        )
    else:
        # Raporu kaydet
        cursor.execute("INSERT INTO reports (reporter_id, reported_username, timestamp) VALUES (?, ?, ?)",
                       (reporter.id, reported_username, datetime.now().isoformat()))
        conn.commit()

        # Toplam rapor sayısını al ve X/5 formatında hazırla
        cursor.execute("SELECT COUNT(*) FROM reports WHERE reported_username = ?", (reported_username,))
        total_reports = cursor.fetchone()[0]

        await message.reply_text(
            f"🚨 Rapor alındı! @{reported_username} için toplam rapor: {total_reports}/5",
            message_thread_id=message.message_thread_id
        )

        # Eğer rapor sayısı 5'e ulaştıysa 2 hafta (14 gün) sustur (mute)
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
                    message_thread_id=message.message_thread_id
                )
            except Exception as e:
                print(f"Mute atma hatası (Admin yetkisi eksik olabilir): {e}")
                await message.reply_text(
                    "❌ Kullanıcı susturulamadı. Botun grupta 'Üyeleri Yasakla/Sustur' yetkisi olduğundan emin olun.",
                    message_thread_id=message.message_thread_id
                )

    conn.close()

def main():
    # Bot uygulamasını başlatıyoruz
    app = ApplicationBuilder().token(TOKEN).build()

    # Komut ve mesaj dinleyicileri
    app.add_handler(CommandHandler("rapor", rapor_komutu))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), check_message))

    print("Bot çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
