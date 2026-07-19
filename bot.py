import os
import json
import time
from threading import Thread
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

# =====================================================================
# 1. KOYEB VA SERVER SOZLAMALARI (WEB SERVER)
# =====================================================================
app = Flask('')

@app.route('/')
def home():
    return "Bot status: OK (24/7 ishlamoqda)"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# =====================================================================
# 2. BOT SOZLAMALARI VA MA'LUMOTLARNI SAQLASH (JSON)
# =====================================================================
BOT_TOKEN = "8558172277:AAHfiMmxmVcsOhzBbnYdxDp2jbFs0goGkBY"  # @BotFather bergan token
ADMIN_ID = 6297231747  # Telegram ID raqamingiz

bot = telebot.TeleBot(BOT_TOKEN)
CONFIG_FILE = "config_v2.json"
DEFAULT_MESSAGE = "⚠️ [Iltimos, bot menyusidan ushbu xabarni tahrirlang!]"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "type": "text",
        "text": DEFAULT_MESSAGE,
        "photo_id": None,
        "groups": [],         # Guruh ID lari ro'yxati
        "is_active": True,    # Tarqatish holati (ON/OFF)
        "interval_hours": 1   # Tarqatish intervali (soatda)
    }

def save_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

# =====================================================================
# 3. DINAMIK INTERVALLI TARQATISH REJALASHTIRUVCHISI
# =====================================================================
scheduler = BackgroundScheduler()

def send_hourly_reminder():
    current_config = load_config()
    
    if not current_config.get("is_active", True):
        print("Tarqatish o'chirilgan (OFF holatida).")
        return
        
    groups = current_config.get("groups", [])
    if not groups:
        print("Guruhlar ro'yxati bo'sh. Xabar yuborilmadi.")
        return

    print("Xabarlarni guruhlarga yuborish boshlandi...")
    for group_id in groups:
        try:
            if current_config["type"] == "photo":
                bot.send_photo(
                    chat_id=group_id, 
                    photo=current_config["photo_id"], 
                    caption=current_config["text"], 
                    parse_mode="Markdown"
                )
            else:
                bot.send_message(
                    chat_id=group_id, 
                    text=current_config["text"], 
                    parse_mode="Markdown"
                )
            time.sleep(1.5)  # Spamdan himoya
        except ApiTelegramException as e:
            if "can't parse entities" in str(e):
                try:
                    if current_config["type"] == "photo":
                        bot.send_photo(chat_id=group_id, photo=current_config["photo_id"], caption=current_config["text"])
                    else:
                        bot.send_message(chat_id=group_id, text=current_config["text"])
                    time.sleep(1.5)
                except Exception as ex:
                    print(f"Guruhda xatolik {group_id}: {ex}")
            else:
                print(f"Guruhda xatolik {group_id}: {e}")
        except Exception as e:
            print(f"Kutilmagan xatolik {group_id}: {e}")
    print("Barcha xabarlar tarqatildi.")

def restart_scheduler():
    current_config = load_config()
    hours = current_config.get("interval_hours", 1)
    
    scheduler.remove_all_jobs()
    scheduler.add_job(send_hourly_reminder, 'interval', hours=hours, id='reminder_job')
    print(f"Scheduler yangilandi. Xabarlar har {hours} soatda yuboriladi.")

# Schedulerni boshlash
scheduler.start()
restart_scheduler()

# =====================================================================
# 4. ADMIN MENYUSI (Klaviaturasi)
# =====================================================================
def get_admin_keyboard():
    current_config = load_config()
    status_text = "🟢 Status: ON" if current_config.get("is_active", True) else "🔴 Status: OFF"
    interval_text = f"⏱ Interval: {current_config.get('interval_hours', 1)} soat"
    
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_view = types.KeyboardButton("📝 Xabarni ko'rish")
    btn_edit = types.KeyboardButton("✍️ Yangi xabar yozish")
    btn_status = types.KeyboardButton(status_text)
    btn_interval = types.KeyboardButton(interval_text)
    btn_groups = types.KeyboardButton("👥 Guruhlarni boshqarish")
    btn_send_now = types.KeyboardButton("🚀 Hozir yo'llash (Test)")
    
    keyboard.add(btn_view, btn_edit)
    keyboard.add(btn_status, btn_interval)
    keyboard.add(btn_groups, btn_send_now)
    return keyboard

@bot.message_handler(commands=['start', 'admin'])
def send_welcome(message):
    if message.from_user.id == ADMIN_ID:
        bot.send_message(
            message.chat.id, 
            "Boshqaruv paneliga xush kelibsiz. Quyidagi menyudan foydalaning:", 
            reply_markup=get_admin_keyboard()
        )
    else:
        if message.chat.type in ['group', 'supergroup']:
            bot.send_message(
                message.chat.id, 
                f"Ushbu guruh ID raqami: `{message.chat.id}`\n"
                f"Admin ushbu ID ni bot boshqaruv panelida ro'yxatga qo'shishi mumkin.",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(message.chat.id, "Sizda ushbu botdan foydalanish huquqi yo'q.")

# =====================================================================
# 5. YORDAMCHI FUNKSIYALAR (Next step handlers)
# =====================================================================
def save_new_message(message):
    # Agar foydalanuvchi bekor qilish tugmasini bossa
    if message.content_type == 'text' and message.text == "❌ Bekor qilish":
        bot.send_message(
            message.chat.id, 
            "Xabar yozish bekor qilindi.", 
            reply_markup=get_admin_keyboard()
        )
        return

    if message.content_type == 'photo':
        photo_id = message.photo[-1].file_id
        caption = message.caption if message.caption else ""
        current_config = load_config()
        current_config["type"] = "photo"
        current_config["text"] = caption
        current_config["photo_id"] = photo_id
        save_config(current_config)
        bot.send_message(
            message.chat.id, 
            "✅ Rasm va uning tagidagi matn muvaffaqiyatli saqlandi!", 
            reply_markup=get_admin_keyboard()
        )
    elif message.content_type == 'text':
        current_config = load_config()
        current_config["type"] = "text"
        current_config["text"] = message.text
        current_config["photo_id"] = None
        save_config(current_config)
        bot.send_message(
            message.chat.id, 
            "✅ Yangi matnli xabar muvaffaqiyatli saqlandi!", 
            reply_markup=get_admin_keyboard()
        )
    else:
        bot.send_message(
            message.chat.id, 
            "❌ Xato! Iltimos, faqat oddiy matn yoki rasm yuboring.", 
            reply_markup=get_admin_keyboard()
        )

def process_group_addition(message):
    # Agar foydalanuvchi guruh qo'shishni bekor qilmoqchi bo'lsa
    if message.content_type == 'text' and message.text == "❌ Bekor qilish":
        bot.send_message(
            message.chat.id, 
            "Guruh qo'shish bekor qilindi.", 
            reply_markup=get_admin_keyboard()
        )
        return

    try:
        group_id = int(message.text.strip())
        current_config = load_config()
        groups = current_config.get("groups", [])
        
        if group_id in groups:
            bot.send_message(message.chat.id, "⚠️ Bu guruh allaqachon ro'yxatda bor!", reply_markup=get_admin_keyboard())
        else:
            groups.append(group_id)
            current_config["groups"] = groups
            save_config(current_config)
            bot.send_message(
                message.chat.id, 
                f"✅ Yangi guruh `{group_id}` muvaffaqiyatli qo'shildi!", 
                reply_markup=get_admin_keyboard(),
                parse_mode="Markdown"
            )
    except ValueError:
        bot.send_message(
            message.chat.id, 
            "❌ Xato format! Guruh ID faqat sonlardan iborat bo'lishi kerak (masalan: -100123456789).", 
            reply_markup=get_admin_keyboard()
        )

# =====================================================================
# 6. ADMIN BUTTONS HANDLERS
# =====================================================================
@bot.message_handler(func=lambda msg: msg.from_user.id == ADMIN_ID)
def handle_admin_buttons(message):
    current_config = load_config()
    
    if message.text == "📝 Xabarni ko'rish":
        if current_config["type"] == "photo":
            bot.send_photo(
                message.chat.id, 
                photo=current_config["photo_id"], 
                caption=f"**Hozirgi faol rasm ostidagi xabar:**\n\n{current_config['text'] if current_config['text'] else ''}", 
                parse_mode="Markdown"
            )
        else:
            bot.send_message(
                message.chat.id, 
                f"**Hozirgi faol matnli xabar:**\n\n{current_config['text']}", 
                parse_mode="Markdown"
            )
            
    elif message.text == "✍️ Yangi xabar yozish":
        # Bekor qilish tugmasi bilan vaqtinchalik klaviatura yaratamiz
        cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        cancel_markup.add(types.KeyboardButton("❌ Bekor qilish"))

        sent_msg = bot.send_message(
            message.chat.id, 
            "Guruhlarga yubormoqchi bo'lgan yangi matningizni yozib yuboring:\n\n"
            "💡 *Eslatma:* Oddiy matn yoki rasm yuklab tagiga matn yozib yuborishingiz mumkin.",
            reply_markup=cancel_markup,
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(sent_msg, save_new_message)
        
    elif message.text.startswith("🟢 Status:") or message.text.startswith("🔴 Status:"):
        current_config["is_active"] = not current_config.get("is_active", True)
        save_config(current_config)
        status_word = "yoqildi" if current_config["is_active"] else "o'chirildi"
        bot.send_message(
            message.chat.id, 
            f"Tarqatish holati o'zgartirildi: **{status_word.upper()}**", 
            reply_markup=get_admin_keyboard(),
            parse_mode="Markdown"
        )
        
    elif message.text.startswith("⏱ Interval:"):
        markup = types.InlineKeyboardMarkup(row_width=3)
        intervals = [1, 2, 3, 6, 12, 24]
        buttons = [types.InlineKeyboardButton(text=f"{h} soat", callback_data=f"set_int_{h}") for h in intervals]
        markup.add(*buttons)
        bot.send_message(
            message.chat.id, 
            "Xabarlar necha soatda bir marta guruhlarga yuborilishini tanlang:", 
            reply_markup=markup
        )
        
    elif message.text == "👥 Guruhlarni boshqarish":
        groups = current_config.get("groups", [])
        groups_list = ""
        for i, g_id in enumerate(groups, 1):
            groups_list += f"{i}. `{g_id}`\n"
            
        text = f"**Hozirgi faol guruhlar ID ro'yxati:**\n\n{groups_list if groups_list else 'Guruhlar qoshilmagan.'}\n" \
               f"Yangi guruh qo'shish yoki o'chirish uchun quyidagi tugmalarni bosing:"
               
        markup = types.InlineKeyboardMarkup()
        btn_add = types.InlineKeyboardButton("➕ Guruh qo'shish", callback_data="group_add")
        btn_del = types.InlineKeyboardButton("➖ Guruhni o'chirish", callback_data="group_del")
        markup.add(btn_add, btn_del)
        
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")
        
    elif message.text == "🚀 Hozir yo'llash (Test)":
        bot.send_message(message.chat.id, "Xabar barcha guruhlarga yuborilmoqda...")
        send_hourly_reminder()
        bot.send_message(message.chat.id, "Tugatildi!", reply_markup=get_admin_keyboard())

# =====================================================================
# 7. INLINE CALLBACK HANDLERS (Guruh va vaqt sozlashlari)
# =====================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    current_config = load_config()
    
    if call.data.startswith("set_int_"):
        hours = int(call.data.replace("set_int_", ""))
        current_config["interval_hours"] = hours
        save_config(current_config)
        restart_scheduler()
        
        bot.answer_callback_query(call.id, "Interval yangilandi!")
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ Tarqatish intervali muvaffaqiyatli **{hours} soat** etib belgilandi!",
            parse_mode="Markdown"
        )
        bot.send_message(call.message.chat.id, "Asosiy menyu yangilandi:", reply_markup=get_admin_keyboard())
        
    elif call.data == "group_add":
        bot.answer_callback_query(call.id)
        
        # Guruh qo'shish jarayonida ham bekor qilish tugmasini chiqaramiz
        cancel_markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        cancel_markup.add(types.KeyboardButton("❌ Bekor qilish"))
        
        sent_msg = bot.send_message(
            call.message.chat.id, 
            "Qo'shmoqchi bo'lgan guruhingizning ID raqamini yozib yuboring (masalan: `-100123456789`):\n\n"
            "💡 *Maslahat:* Guruh ID sini bilish uchun botni o'sha guruhga qo'shib `/start` deb yozing.",
            reply_markup=cancel_markup
        )
        bot.register_next_step_handler(sent_msg, process_group_addition)
        
    elif call.data == "group_del":
        bot.answer_callback_query(call.id)
        groups = current_config.get("groups", [])
        if not groups:
            bot.send_message(call.message.chat.id, "O'chirish uchun guruhlar mavjud emas.")
            return
            
        markup = types.InlineKeyboardMarkup(row_width=1)
        for g_id in groups:
            markup.add(types.InlineKeyboardButton(text=f"❌ {g_id}", callback_data=f"del_g_{g_id}"))
            
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="O'chirmoqchi bo'lgan guruh ID sini tanlang:",
            reply_markup=markup
        )
        
    elif call.data.startswith("del_g_"):
        g_id_to_del = int(call.data.replace("del_g_", ""))
        groups = current_config.get("groups", [])
        if g_id_to_del in groups:
            groups.remove(g_id_to_del)
            current_config["groups"] = groups
            save_config(current_config)
            bot.answer_callback_query(call.id, "Guruh o'chirildi!")
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"✅ Guruh `{g_id_to_del}` ro'yxatdan muvaffaqiyatli o'chirildi!",
                parse_mode="Markdown"
            )
        else:
            bot.answer_callback_query(call.id, "Xatolik: guruh topilmadi.")

# =====================================================================
# 8. BOTNI ISHGA TUSHIRISH
# =====================================================================
if __name__ == "__main__":
    keep_alive()
    print("Bot yangi boshqaruv tizimi bilan ishga tushdi...")
    try:
        # Tarmoq uzilganda bot o'chib qolmasligi uchun timeout va long_polling parametrlarini sozlaymiz
        bot.infinity_polling(timeout=20, long_polling_timeout=10)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
