import os
import json
import time
from threading import Thread, Lock
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

# =====================================================================
# 1. FLASK WEB SERVER (24/7 ishni ta'minlash uchun)
# =====================================================================
app = Flask("")

@app.route("/")
def home():
    return "Bot status: ACTIVE (24/7 running)"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# =====================================================================
# 2. BOT VA CONFIG SOZLAMALARI
# =====================================================================
BOT_TOKEN = "8558172277:AAHfiMmxmVcsOhzBbnYdxDp2jbFs0goGkBY"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None, threaded=True, num_threads=50)

CONFIG_FILE = "config_v2.json"
DEFAULT_ADMINS = [6297231747, 5632353347, 8655732501]

_config_cache = None
_config_lock = Lock()

# Vaqtinchalik tanlangan guruhlarni saqlash uchun kesh (Admin ID -> Set of Group IDs)
temp_selected_groups = {}

def load_config():
    global _config_cache
    with _config_lock:
        if _config_cache is not None:
            return _config_cache

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    if "admins" not in config: config["admins"] = DEFAULT_ADMINS
                    if "groups" not in config: config["groups"] = []
                    if "is_active" not in config: config["is_active"] = True
                    if "interval_hours" not in config: config["interval_hours"] = 1
                    if "known_chats" not in config: config["known_chats"] = {}
                    _config_cache = config
                    return _config_cache
            except Exception:
                pass
        
        default_config = {
            "admins": DEFAULT_ADMINS,
            "type": "text", 
            "text": "Iltimos, reklama matnini sozlang!", 
            "photo_id": None,
            "groups": [], 
            "is_active": True, 
            "interval_hours": 1,
            "known_chats": {}
        }
        _config_cache = default_config
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(default_config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Config yozishda xato: {e}")
        return _config_cache

def save_config(config_data):
    global _config_cache
    with _config_lock:
        _config_cache = config_data
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Config saqlashda xatolik: {e}")

def is_admin(user_id):
    hardcoded_admins = {6297231747, 5632353347, 8655732501}
    try:
        file_admins = set(load_config().get("admins", []))
    except Exception:
        file_admins = set()
    return (user_id in hardcoded_admins) or (user_id in file_admins)

# Markdown xatolarini oldini olish uchun guruh nomlarini tozalash funksiyasi
def escape_markdown(text):
    if not text:
        return "Noma'lum"
    for char in ["_", "*", "`", "["]:
        text = text.replace(char, "")
    return text

def register_chat(chat):
    if chat and chat.type in ["group", "supergroup"]:
        c = load_config()
        if "known_chats" not in c or not isinstance(c["known_chats"], dict):
            c["known_chats"] = {}
        chat_id_str = str(chat.id)
        clean_title = escape_markdown(chat.title)
        if chat_id_str not in c["known_chats"] or c["known_chats"][chat_id_str] != clean_title:
            c["known_chats"][chat_id_str] = clean_title
            save_config(c)

# =====================================================================
# 3. AVTOMATIK TARQATISH (SCHEDULER - PARALLEL FONDA)
# =====================================================================
scheduler = BackgroundScheduler(daemon=True)

def send_hourly_reminder():
    def worker():
        try:
            current_config = load_config()
            if not current_config.get("is_active", True): 
                return
                
            groups = current_config.get("groups", [])
            if not groups:
                return

            for group_id in groups:
                try:
                    if current_config.get("type") == "photo" and current_config.get("photo_id"):
                        bot.send_photo(group_id, current_config["photo_id"], caption=current_config.get("text", ""))
                    else:
                        bot.send_message(group_id, current_config.get("text", "Xabar matni kiritilmagan."))
                    time.sleep(1.0)
                except ApiTelegramException as e:
                    print(f"Telegram API xatosi guruh {group_id}: {e.description}")
                except Exception as e:
                    print(f"Kutilmagan xatolik guruh {group_id}: {e}")
        except Exception as e:
            print(f"Remind xizmatida xatolik: {e}")
            
    Thread(target=worker).start()

def restart_scheduler():
    try:
        current_config = load_config()
        scheduler.remove_all_jobs()
        interval = current_config.get("interval_hours", 1)
        if interval < 1: interval = 1
        scheduler.add_job(send_hourly_reminder, "interval", hours=interval, id="reminder_job")
    except Exception as e:
        print(f"Schedulerni qayta ishga tushirishda xato: {e}")

scheduler.start()
restart_scheduler()

# =====================================================================
# 4. ADMIN PANEL KLAVIATURALARI
# =====================================================================
def get_admin_keyboard():
    c = load_config()
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("📝 Xabarni ko'rish"), types.KeyboardButton("✍️ Yangi xabar yozish"))
    
    status_btn = "🟢 Status: FAOL" if c.get("is_active", True) else "🔴 Status: TO'XTATILGAN"
    interval_btn = f"⏱ Interval: {c.get('interval_hours', 1)} soat"
    keyboard.add(types.KeyboardButton(status_btn), types.KeyboardButton(interval_btn))
    
    keyboard.add(types.KeyboardButton("👥 Guruhlarni boshqarish"), types.KeyboardButton("🔐 Adminlarni boshqarish"))
    keyboard.add(types.KeyboardButton("🚀 Hozir yo'llash (Test)"))
    return keyboard

def get_cancel_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("❌ Bekor qilish"))
    return keyboard

# =====================================================================
# 5. BUYRUQLAR & MONITORING CHAT TIZIMI
# =====================================================================
@bot.message_handler(commands=["start", "admin"])
def send_welcome(message):
    if message.chat.type in ["group", "supergroup"]:
        register_chat(message.chat)
        return
        
    try:
        if is_admin(message.from_user.id):
            bot.send_message(message.chat.id, "Boshqaruv paneliga xush kelibsiz:", reply_markup=get_admin_keyboard())
        else:
            bot.send_message(
                message.chat.id, 
                f"Siz admin emassiz.\nUshbu chat ID raqami: `{message.chat.id}`", 
                parse_mode="Markdown"
            )
    except Exception as e:
        print(f"Start buyrug'ida xato: {e}")

@bot.my_chat_member_handler()
def handle_left_join_status(message):
    if message.new_chat_member.status in ["member", "administrator"]:
        register_chat(message.chat)

@bot.message_handler(func=lambda msg: True, content_types=["text", "photo", "new_chat_members"])
def monitor_chats(message):
    if message.chat.type in ["group", "supergroup"]:
        register_chat(message.chat)
        return
        
    if is_admin(message.from_user.id):
        handle_admin_buttons(message)

# =====================================================================
# 6. ASOSIY REACTION HANDLER (ADMIN TUGMALARI)
# =====================================================================
def handle_admin_buttons(message):
    try:
        c = load_config()
        text = message.text
        
        if text == "🔐 Adminlarni boshqarish":
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("➕ Admin qo'shish", callback_data="add_admin"),
                types.InlineKeyboardButton("➖ Adminni o'chirish", callback_data="del_admin")
            )
            bot.send_message(message.chat.id, "Adminlarni boshqarish menyusi:", reply_markup=markup)

        elif text == "📝 Xabarni ko'rish":
            if c.get("type") == "photo" and c.get("photo_id"):
                bot.send_photo(message.chat.id, c["photo_id"], caption=c.get("text", ""))
            else:
                bot.send_message(message.chat.id, c.get("text", "Xabar matni bo'sh!"))
            
        elif text == "✍️ Yangi xabar yozish":
            sent = bot.send_message(
                message.chat.id, 
                "Menga yangi matn kiriting yoki rasm yuboring (bekor qilish uchun pastdagi tugmani bosing):", 
                reply_markup=get_cancel_keyboard()
            )
            bot.register_next_step_handler(sent, save_new_message)
            
        elif text and (text.startswith("🟢 Status") or text.startswith("🔴 Status")):
            c["is_active"] = not c.get("is_active", True)
            save_config(c)
            holat_matni = "FAOL" if c["is_active"] else "TO'XTATILDI"
            bot.send_message(
                message.chat.id, 
                f"Holat o'zgardi: {holat_matni}", 
                reply_markup=get_admin_keyboard()
            )
            
        elif text and text.startswith("⏱ Interval:"):
            markup = types.InlineKeyboardMarkup(row_width=3)
            intervals = [1, 2, 3, 6, 12, 24]
            buttons = [types.InlineKeyboardButton(text=f"{h} soat", callback_data=f"set_int_{h}") for h in intervals]
            markup.add(*buttons)
            bot.send_message(message.chat.id, "Xabarlar guruhlarga necha soatda bir yuborilsin?", reply_markup=markup)

        elif text == "👥 Guruhlarni boshqarish":
            groups = c.get("groups", [])
            known_chats = c.get("known_chats", {})
            
            groups_list = ""
            for i, g_id in enumerate(groups, 1):
                title = known_chats.get(str(g_id), "Noma'lum guruh")
                groups_list += f"{i}. {title} `({g_id})`\n"
            
            if groups_list:
                msg_text = f"**Hozirgi faol guruhlar ro'yxati:**\n\n{groups_list}"
            else:
                msg_text = "**Hozirgi faol guruhlar ro'yxati:**\n\nRo'yxat bo'sh. Guruh qo'shing."
            
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("➕ Guruh qo'shish (Tanlash)", callback_data="group_select_flow"),
                types.InlineKeyboardButton("➖ Guruhni o'chirish", callback_data="group_del")
            )
            bot.send_message(message.chat.id, msg_text, reply_markup=markup, parse_mode="Markdown")
            
        elif text == "🚀 Hozir yo'llash (Test)":
            bot.send_message(message.chat.id, "Xabar barcha guruhlarga tarqatilmoqda...")
            send_hourly_reminder()
            bot.send_message(message.chat.id, "Tarqatish yakunlandi!")
            
    except Exception as e:
        bot.send_message(message.chat.id, f"Xatolik yuz berdi: {e}")

# =====================================================================
# 7. MULTI-SELECT GURUH QO'SHISH INTERFEYS GENERATORI
# =====================================================================
def generate_group_selection_keyboard(admin_id):
    c = load_config()
    known_chats = c.get("known_chats", {})
    active_groups = set(c.get("groups", []))
    
    selected = temp_selected_groups.get(admin_id, set())
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    available_chats = False
    if isinstance(known_chats, dict):
        for chat_id_str, title in known_chats.items():
            chat_id = int(chat_id_str)
            if chat_id in active_groups:
                continue
                
            available_chats = True
            status_emoji = "✅" if chat_id in selected else "⬜️"
            button_text = f"{status_emoji} {title}"
            markup.add(types.InlineKeyboardButton(button_text, callback_data=f"toggle_grp_{chat_id}"))
        
    if not available_chats:
        return None
        
    markup.add(
        types.InlineKeyboardButton("💾 Tanlanganlarni saqlash", callback_data="save_selected_groups"),
        types.InlineKeyboardButton("❌ Bekor qilish", callback_data="cancel_group_select")
    )
    return markup

# =====================================================================
# 8. INLINE CALLBACK HANDLERS (MULTI-SELECT BILAN)
# =====================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    try:
        c = load_config()
        admin_id = call.from_user.id
        if not is_admin(admin_id):
            bot.answer_callback_query(call.id, "Siz admin emassiz!", show_alert=True)
            return

        # --- GURUH QO'SHISH TIZIMI (MULTI-SELECT FLOW) ---
        if call.data == "group_select_flow":
            temp_selected_groups[admin_id] = set()
            markup = generate_group_selection_keyboard(admin_id)
            if markup is None:
                bot.send_message(
                    call.message.chat.id, 
                    "Bot a'zo bo'lgan yangi guruhlar topilmadi.\n\n"
                    "💡 Botni biror guruhga qo'shing va u yerda xabar yozing."
                )
                bot.answer_callback_query(call.id)
                return
            
            bot.edit_message_text(
                "Tizimga qo'shmoqchi bo'lgan guruhlaringizni belgilang va pastdagi Saqlash tugmasini bosing:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
            bot.answer_callback_query(call.id)

        elif call.data.startswith("toggle_grp_"):
            chat_id = int(call.data.replace("toggle_grp_", ""))
            if admin_id not in temp_selected_groups:
                temp_selected_groups[admin_id] = set()
                
            if chat_id in temp_selected_groups[admin_id]:
                temp_selected_groups[admin_id].remove(chat_id)
            else:
                temp_selected_groups[admin_id].add(chat_id)
                
            markup = generate_group_selection_keyboard(admin_id)
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)
            bot.answer_callback_query(call.id)

        elif call.data == "save_selected_groups":
            selected = temp_selected_groups.get(admin_id, set())
            if not selected:
                bot.answer_callback_query(call.id, "Hech bo'lmaganda bitta guruh tanlang!", show_alert=True)
                return
                
            c = load_config()
            if "groups" not in c:
                c["groups"] = []
                
            added_count = 0
            for g_id in selected:
                if g_id not in c["groups"]:
                    c["groups"].append(g_id)
                    added_count += 1
                    
            save_config(c)
            temp_selected_groups.pop(admin_id, None)
            
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(
                call.message.chat.id, 
                f"🎉 {added_count} ta yangi guruh muvaffaqiyatli saqlandi!", 
                reply_markup=get_admin_keyboard()
            )
            bot.answer_callback_query(call.id)

        elif call.data == "cancel_group_select":
            temp_selected_groups.pop(admin_id, None)
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, "Guruh qo'shish bekor qilindi.", reply_markup=get_admin_keyboard())
            bot.answer_callback_query(call.id)

        # --- ADMIN BOSHQARUVI ---
        elif call.data == "add_admin":
            sent = bot.send_message(
                call.message.chat.id, 
                "Yangi adminning Telegram ID raqamini kiriting:", 
                reply_markup=get_cancel_keyboard()
            )
            bot.register_next_step_handler(sent, add_admin_logic)
            bot.answer_callback_query(call.id)
            
        elif call.data == "del_admin":
            admins = c.get("admins", [])
            if len(admins) <= 1:
                bot.answer_callback_query(call.id, "Ro'yxatda faqat 1 ta admin qoldi!", show_alert=True)
                return
            markup = types.InlineKeyboardMarkup()
            for aid in admins:
                markup.add(types.InlineKeyboardButton(str(aid), callback_data=f"remove_{aid}"))
            bot.edit_message_text("O'chirmoqchi bo'lgan adminni tanlang:", call.message.chat.id, call.message.message_id, reply_markup=markup)
            bot.answer_callback_query(call.id)
            
        elif call.data.startswith("remove_"):
            aid = int(call.data.split("_")[1])
            if aid in c["admins"]:
                c["admins"].remove(aid)
                save_config(c)
                bot.answer_callback_query(call.id, "Muvaffaqiyatli o'chirildi!")
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.send_message(call.message.chat.id, f"Admin {aid} o'chirildi.", reply_markup=get_admin_keyboard())

        # --- GURUHLARNI BAZADAN O'CHIRISH ---
        elif call.data == "group_del":
            groups = c.get("groups", [])
            known_chats = c.get("known_chats", {})
            if not groups:
                bot.answer_callback_query(call.id, "Guruhlar ro'yxati bo'sh!", show_alert=True)
                return
            markup = types.InlineKeyboardMarkup()
            for gid in groups:
                title = known_chats.get(str(gid), f"Guruh {gid}")
                markup.add(types.InlineKeyboardButton(f"❌ {title}", callback_data=f"delgroup_{gid}"))
            bot.edit_message_text("O'chiriladigan guruh ustiga bosing:", call.message.chat.id, call.message.message_id, reply_markup=markup)
            bot.answer_callback_query(call.id)
            
        elif call.data.startswith("delgroup_"):
            gid = int(call.data.split("_")[1])
            if gid in c.get("groups", []):
                c["groups"].remove(gid)
                save_config(c)
                bot.answer_callback_query(call.id, "Guruh o'chirildi!")
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.send_message(call.message.chat.id, f"Guruh ({gid}) muvaffaqiyatli o'chirildi.", reply_markup=get_admin_keyboard())

        # --- INTERVAL BOSHQARUVI ---
        elif call.data.startswith("set_int_"):
            hours = int(call.data.replace("set_int_", ""))
            c["interval_hours"] = hours
            save_config(c)
            restart_scheduler()
            bot.answer_callback_query(call.id, f"Interval {hours} soatga sozladi!")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, f"✅ Tarqatish intervali muvaffaqiyatli **{hours} soat** etib belgilandi!", reply_markup=get_admin_keyboard(), parse_mode="Markdown")

    except Exception as e:
        print(f"Callback xatosi: {e}")

# =====================================================================
# 9. NEXT STEP LOGIKA
# =====================================================================
def add_admin_logic(message):
    try:
        raw_text = message.text.strip() if message.text else ""
        if raw_text == "❌ Bekor qilish":
            bot.send_message(message.chat.id, "Admin qo'shish bekor qilindi.", reply_markup=get_admin_keyboard())
            return

        new_id = int(raw_text)
        c = load_config()
        if new_id not in c["admins"]:
            c["admins"].append(new_id)
            save_config(c)
            bot.send_message(message.chat.id, f"✅ Yangi admin ({new_id}) muvaffaqiyatli qo'shildi!", reply_markup=get_admin_keyboard())
        else:
            bot.send_message(message.chat.id, "⚠️ Ushbu ID allaqachon admin.", reply_markup=get_admin_keyboard())
    except ValueError:
        bot.send_message(message.chat.id, "❌ Admin ID faqat raqamlardan iborat bo'lishi lozim.", reply_markup=get_admin_keyboard())
    except Exception as e:
        bot.send_message(message.chat.id, f"Xatolik: {e}", reply_markup=get_admin_keyboard())

def save_new_message(message):
    try:
        raw_text = message.text.strip() if message.text else ""
        if raw_text == "❌ Bekor qilish":
            bot.send_message(message.chat.id, "Yangi xabar yozish bekor qilindi.", reply_markup=get_admin_keyboard())
            return

        c = load_config()
        if message.content_type == "photo":
            c["type"] = "photo"
            c["text"] = message.caption or ""
            c["photo_id"] = message.photo[-1].file_id
        elif message.content_type == "text":
            c["type"] = "text"
            c["text"] = message.text
            c["photo_id"] = None
        else:
            bot.send_message(message.chat.id, "❌ Faqat matn yoki rasm qabul qilinadi.", reply_markup=get_admin_keyboard())
            return
            
        save_config(c)
        bot.send_message(message.chat.id, "✅ Yangi xabar muvaffaqiyatli saqlandi!", reply_markup=get_admin_keyboard())
    except Exception as e:
        bot.send_message(message.chat.id, f"Xatolik: {e}", reply_markup=get_admin_keyboard())

# =====================================================================
# 10. RUN ENGINE
# =====================================================================
if __name__ == "__main__":
    keep_alive()
    print("Maksimal tezlikdagi oqim tizimi ishga tushdi...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10)
