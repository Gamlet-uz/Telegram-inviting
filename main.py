import os
import json
import asyncio
import firebase_admin
from firebase_admin import credentials, db
from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler

from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors.rpcerrorlist import PeerFloodError, UserPrivacyRestrictedError, FloodWaitError
from telethon.errors import SessionPasswordNeededError

# ================= SOZLAMALAR =================
API_ID = int(os.getenv("API_ID", "1234567"))          
API_HASH = os.getenv("API_HASH", "API_HASH_KODINGIZ")   
BOT_TOKEN = os.getenv("BOT_TOKEN", "BOT_TOKENINGIZ")       
FIREBASE_URL = os.getenv("FIREBASE_URL", "https://...firebaseio.com/") 
FIREBASE_KEY_JSON = os.getenv("FIREBASE_KEY_JSON", "{}")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) # SIZNING TELEGRAM ID RAQAMINGIZ
# ==============================================

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ================= ADMIN HIMOYA TIZIMI =================
class AdminMiddleware(BaseMiddleware):
    async def on_process_message(self, message: types.Message, data: dict):
        if ADMIN_ID != 0 and message.from_user.id != ADMIN_ID:
            await message.answer("⛔️ Kechirasiz, siz ushbu shaxsiy botdan foydalanish huquqiga ega emassiz.")
            raise CancelHandler()

dp.middleware.setup(AdminMiddleware())

# ================= FIREBASE ULANISHI =================
try:
    firebase_dict = json.loads(FIREBASE_KEY_JSON)
    cred = credentials.Certificate(firebase_dict)
    firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_URL})
    print("✅ Firebase muvaffaqiyatli ulandi!")
except Exception as e:
    print(f"❌ Firebase ulanishida xatolik: {e}")

# ================= HOLATLAR (FSM) =================
class BotStates(StatesGroup):
    waiting_for_groups = State()
    
    waiting_for_acc_role = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State() 
    
    waiting_for_invite_target = State() # Qaysi guruhga qo'shish kerakligi
    waiting_for_invite_limit = State()

def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(types.KeyboardButton("🔍 Parsing (Yig'ish)"), types.KeyboardButton("📱 Akkaunt Qo'shish"))
    keyboard.add(types.KeyboardButton("🚀 Invaytingni Boshlash"), types.KeyboardButton("📊 Statistika & Holat"))
    return keyboard

def get_role_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(types.KeyboardButton("🛠 Parser (Faqat odam yig'ish)"), types.KeyboardButton("🚀 Invayter (Odam qo'shish)"))
    keyboard.add(types.KeyboardButton("❌ Bekor qilish"))
    return keyboard

@dp.message_handler(commands=['start'], state="*")
async def start_cmd(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("🤖 Mukammal Telegram Invayter tizimiga xush kelibsiz!", reply_markup=get_main_keyboard())

@dp.message_handler(lambda m: m.text == "❌ Bekor qilish", state="*")
async def cancel_cmd(message: types.Message, state: FSMContext):
    await state.finish()
    await message.answer("Jarayon bekor qilindi.", reply_markup=get_main_keyboard())

# ================= 1. AKKAUNT QO'SHISH =================
@dp.message_handler(lambda m: m.text == "📱 Akkaunt Qo'shish")
async def add_acc_start(message: types.Message):
    await message.answer("Ushbu akkaunt qaysi vazifani bajaradi?\n\n"
                         "🛠 **Parser** - boshqa guruhlardan odamlarni yig'ish uchun.\n"
                         "🚀 **Invayter** - yig'ilgan odamlarni guruhingizga qo'shish uchun.", 
                         reply_markup=get_role_keyboard())
    await BotStates.waiting_for_acc_role.set()

@dp.message_handler(state=BotStates.waiting_for_acc_role)
async def add_acc_role(message: types.Message, state: FSMContext):
    role = "parser" if "Parser" in message.text else "inviter"
    await state.update_data(role=role)
    await message.answer("📞 Telefon raqamingizni kiriting (masalan: +998901234567):", reply_markup=types.ReplyKeyboardRemove())
    await BotStates.waiting_for_phone.set()

@dp.message_handler(state=BotStates.waiting_for_phone)
async def add_acc_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip().replace("+", "")
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    
    try:
        sent_code = await client.send_code_request("+" + phone)
        await state.update_data(phone=phone, hash=sent_code.phone_code_hash, session=client.session.save())
        await message.answer("📩 Telegramdan kelgan 5 xonali kodni kiriting:")
        await BotStates.waiting_for_code.set()
    except Exception as e:
        await message.answer(f"❌ Xatolik yuz berdi: {e}", reply_markup=get_main_keyboard())
        await state.finish()

@dp.message_handler(state=BotStates.waiting_for_code)
async def add_acc_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    client = TelegramClient(StringSession(data['session']), API_ID, API_HASH)
    await client.connect()
    
    try:
        await client.sign_in("+" + data['phone'], code, phone_code_hash=data['hash'])
    except SessionPasswordNeededError:
        await state.update_data(session=client.session.save())
        await message.answer("🔐 Bu akkauntda 2-bosqichli parol (2FA) o'rnatilgan ekan. Parolni kiriting:")
        await BotStates.waiting_for_password.set()
        await client.disconnect()
        return
    except Exception as e:
        await message.answer(f"❌ Kod xato: {e}", reply_markup=get_main_keyboard())
        await client.disconnect()
        await state.finish()
        return

    session_str = client.session.save() 
    db.reference('accounts').child(data['phone']).set({'session': session_str, 'status': 'faol', 'role': data['role']})
    await message.answer(f"🎉 +{data['phone']} ({data['role'].upper()}) tizimga qo'shildi!", reply_markup=get_main_keyboard())
    await client.disconnect()
    await state.finish()

@dp.message_handler(state=BotStates.waiting_for_password)
async def add_acc_password(message: types.Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    client = TelegramClient(StringSession(data['session']), API_ID, API_HASH)
    await client.connect()
    
    try:
        await client.sign_in(password=password)
        session_str = client.session.save() 
        db.reference('accounts').child(data['phone']).set({'session': session_str, 'status': 'faol', 'role': data['role']})
        await message.answer(f"🎉 +{data['phone']} ({data['role'].upper()}) tizimga qo'shildi!", reply_markup=get_main_keyboard())
    except Exception as e:
        await message.answer(f"❌ Parol xato: {e}", reply_markup=get_main_keyboard())
    finally:
        await client.disconnect()
        await state.finish()

# ================= 2. PARSING =================
@dp.message_handler(lambda m: m.text == "🔍 Parsing (Yig'ish)")
async def parse_start(message: types.Message):
    await message.answer("✍️ Odam yig'iladigan raqobatchi guruhlarni ustun shaklida yuboring:\n\n"
                         "Masalan:\n@guruh_bir\nhttps://t.me/guruh_ikki", 
                         reply_markup=types.ReplyKeyboardRemove())
    await BotStates.waiting_for_groups.set()

@dp.message_handler(state=BotStates.waiting_for_groups)
async def parse_process(message: types.Message, state: FSMContext):
    raw_text = message.text.strip().split('\n')
    await state.finish()
    
    groups = [g.replace("https://t.me/", "").replace("@", "").strip() for g in raw_text if g.strip()]
    await message.answer(f"🔍 {len(groups)} ta guruhdan odam yig'ish boshlandi...", reply_markup=get_main_keyboard())
    
    accs = db.reference('accounts').get() or {}
    parser_phones = [p for p, data in accs.items() if data.get('status') == 'faol' and data.get('role') == 'parser']
    
    if not parser_phones:
        await message.answer("❌ Tizimda faol 'Parser' akkaunti topilmadi. Avval akkaunt qo'shing!")
        return
        
    session_str = accs[parser_phones[0]]['session'] 
    users_ref = db.reference('users')
    total_added = 0

    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        
        for target in groups:
            await message.answer(f"⏳ [@{target}] guruhidan o'qilmoqda...")
            try:
                entity = await client.get_entity(target)
                participants = await client.get_participants(entity, aggressive=True)
                
                count = 0
                for u in participants:
                    if u.username and not u.bot:
                        if not users_ref.child(u.username).get():
                            users_ref.child(u.username).set({'status': 'yangi'})
                            count += 1
                total_added += count
                await message.answer(f"✅ [@{target}] dan {count} ta yangi odam olindi.")
            except Exception as e:
                await message.answer(f"❌ [@{target}] xatolik yuz berdi: {e}")
                
        await message.answer(f"🎉 Umumiy parsing yakunlandi! Jami: {total_added} ta toza odam.")
        await client.disconnect()
    except Exception as e:
        await message.answer(f"❌ Parser xatoligi: {e}")

# ================= 3. INVAYTING =================
@dp.message_handler(lambda m: m.text == "🚀 Invaytingni Boshlash")
async def start_inviting_ask_target(message: types.Message):
    await message.answer("🎯 Odamlar qaysi guruhga qo'shilsin?\n"
                         "O'z guruhingiz usernamesini yozing (masalan: @mening_guruhim):", 
                         reply_markup=types.ReplyKeyboardRemove())
    await BotStates.waiting_for_invite_target.set()

@dp.message_handler(state=BotStates.waiting_for_invite_target)
async def start_inviting_ask_limit(message: types.Message, state: FSMContext):
    target_group = message.text.strip().replace("@", "").replace("https://t.me/", "")
    await state.update_data(target_group=target_group)
    
    await message.answer("🔢 Har bir akkaunt nechta odam qo'shsin? (Masalan: 10)")
    await BotStates.waiting_for_invite_limit.set()

@dp.message_handler(state=BotStates.waiting_for_invite_limit)
async def start_inviting_process(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Faqat raqam kiriting. Qaytadan urinib ko'ring.", reply_markup=get_main_keyboard())
        await state.finish()
        return
        
    limit_per_acc = int(message.text.strip())
    data = await state.get_data()
    target_group = data['target_group']
    await state.finish()
    
    await message.answer(f"🚀 Invayting boshlandi. Guruh: @{target_group} | Limit: {limit_per_acc} ta.", reply_markup=get_main_keyboard())
    
    accs = db.reference('accounts').get() or {}
    users_data = db.reference('users').get() or {}
    
    inviter_accs = {p: d for p, d in accs.items() if d.get('status') == 'faol' and d.get('role') == 'inviter'}
    target_users = [uname for uname, udata in users_data.items() if udata.get('status') == 'yangi']
    
    if not inviter_accs:
        await message.answer("❌ Bazada faol 'Invayter' akkauntlari yo'q!")
        return
    if not target_users:
        await message.answer("❌ Bazada qo'shiladigan yangi odamlar qolmadi. Parsing qiling!")
        return

    user_idx = 0
    total_accs = len(inviter_accs)
    current_acc_num = 0
    
    for phone, acc_info in inviter_accs.items():
        if user_idx >= len(target_users): 
            break
            
        current_acc_num += 1
        await message.answer(f"📱 Ishga tushdi [{current_acc_num}/{total_accs}]: +{phone}")
        client = TelegramClient(StringSession(acc_info['session']), API_ID, API_HASH)
        await client.connect()
        
        added = 0
        
        while added < limit_per_acc and user_idx < len(target_users):
            user = target_users[user_idx]
            user_idx += 1
            try:
                await client(InviteToChannelRequest(target_group, [user]))
                db.reference('users').child(user).update({'status': 'qo_shildi'})
                added += 1
                await message.answer(f"   ✅ @{user} qo'shildi ({added}/{limit_per_acc}) -> ⏳ 25 soniya pauza...")
                await asyncio.sleep(25) 
                
            except PeerFloodError:
                db.reference('accounts').child(phone).update({'status': 'flood_block'})
                await message.answer(f"   ⚠️ +{phone} Telegram blokiga tushdi (Flood Block).")
                break
            except FloodWaitError as e:
                await message.answer(f"   ⏳ Telegram {e.seconds} soniya kutishni so'radi. Akkaunt almashadi.")
                break
            except UserPrivacyRestrictedError:
                db.reference('users').child(user).update({'status': 'yopiq_profil'})
                await asyncio.sleep(3)
            except Exception:
                db.reference('users').child(user).update({'status': 'xato'})
                await asyncio.sleep(3)
                
        await client.disconnect()
        
        if current_acc_num < total_accs and user_idx < len(target_users):
            await message.answer("🔄 Akkaunt almashmoqda... Xavfsizlik uchun 60 soniya tanaffus.")
            await asyncio.sleep(60)

    await message.answer("🎉 Invayting tsikli to'liq yakunlandi.")

# ================= 4. STATISTIKA =================
@dp.message_handler(lambda m: m.text == "📊 Statistika & Holat")
async def show_stats(message: types.Message):
    accs = db.reference('accounts').get() or {}
    users_data = db.reference('users').get() or {}
    
    parser_faol = [p for p, d in accs.items() if d.get('role') == 'parser' and d.get('status') == 'faol']
    inv_faol = [p for p, d in accs.items() if d.get('role') == 'inviter' and d.get('status') == 'faol']
    inv_blok = [p for p, d in accs.items() if d.get('status') == 'flood_block']
    
    yangi = sum(1 for u in users_data.values() if u.get('status') == 'yangi')
    qoshingan = sum(1 for u in users_data.values() if u.get('status') == 'qo_shildi')
    yopiq = sum(1 for u in users_data.values() if u.get('status') == 'yopiq_profil')
    
    text = f"📊 **REAL TIZIM HOLATI** 📊\n\n"
    text += f"📱 **Akkauntlar:**\n"
    text += f"   🛠 Faol Parserlar: {len(parser_faol)} ta\n"
    text += f"   🚀 Faol Invayterlar: {len(inv_faol)} ta\n"
    text += f"   🔴 Flood-blokda: {len(inv_blok)} ta\n\n"
    
    text += f"👥 **Odamlar Bazasi:**\n"
    text += f"   🆕 Hali qo'shilmaganlar: {yangi} ta\n"
    text += f"   ✅ Muvaffaqiyatli: {qoshingan} ta\n"
    text += f"   🔒 Yopiq profillar: {yopiq} ta\n"
    
    await message.answer(text, parse_mode="Markdown")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
