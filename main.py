import os
import json
import asyncio
import firebase_admin
from firebase_admin import credentials, db
from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors.rpcerrorlist import PeerFloodError, UserPrivacyRestrictedError, FloodWaitError

# ================= SOZLAMALAR (Railway Variables'dan olinadi) =================
API_ID = int(os.getenv("API_ID", "1234567"))          
API_HASH = os.getenv("API_HASH", "API_HASH_KODINGIZ")   
BOT_TOKEN = os.getenv("BOT_TOKEN", "BOT_TOKENINGIZ")       
FIREBASE_URL = os.getenv("FIREBASE_URL", "https://telegram-inviting-default-rtdb.firebaseio.com/") 
MY_GROUP = os.getenv("MY_GROUP", "guruhingiz_nomi")   
FIREBASE_KEY_JSON = os.getenv("FIREBASE_KEY_JSON", "{}")
# ============================================================================

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ================= FIREBASE ULANISHI =================
try:
    firebase_dict = json.loads(FIREBASE_KEY_JSON)
    cred = credentials.Certificate(firebase_dict)
    firebase_admin.initialize_app(cred, {'databaseURL': FIREBASE_URL})
    print("✅ Firebase muvaffaqiyatli ulandi!")
except Exception as e:
    print(f"❌ Firebase ulanishida xatolik: {e}")

class BotStates(StatesGroup):
    waiting_for_group = State()
    waiting_for_phone = State()
    waiting_for_code = State()

def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("🔍 Parsing (Yig'ish)"), types.KeyboardButton("📱 Akkaunt Qo'shish"))
    keyboard.add(types.KeyboardButton("🚀 Invaytingni Boshlash"), types.KeyboardButton("📊 Statistika"))
    return keyboard

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    await message.answer("🤖 Telegram Invayter + Firebase Bot tizimiga xush kelibsiz!", reply_markup=get_main_keyboard())

# ================= 1. PARSING QISMI =================
@dp.message_handler(lambda m: m.text == "🔍 Parsing (Yig'ish)")
async def parse_start(message: types.Message):
    await message.answer("✍️ Odam yig'iladigan raqobatchi guruh usernamesini yuboring (@ belgisiz):")
    await BotStates.waiting_for_group.set()

@dp.message_handler(state=BotStates.waiting_for_group)
async def parse_process(message: types.Message, state: FSMContext):
    target = message.text.strip()
    await state.finish()
    
    msg = await message.answer(f"🔍 [{target}] guruhidan odamlar yig'ilmoqda, iltimos kuting...")
    
    accs = db.reference('accounts').get()
    if not accs:
        await msg.edit_text("❌ Tizimda hali faol akkaunt yo'q. Avval 'Akkaunt Qo'shish' orqali raqam kiriting.")
        return

    active_phones = [p for p, data in accs.items() if data.get('status') == 'faol']
    if not active_phones:
        await msg.edit_text("❌ Tizimda faol akkaunt qolmagan!")
        return
        
    first_phone = active_phones[0]
    session_str = accs[first_phone]['session']

    try:
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await client.connect()
        entity = await client.get_entity(target)
        participants = await client.get_participants(entity, aggressive=True)
        
        users_ref = db.reference('users')
        count = 0
        for u in participants:
            if u.username and not u.bot:
                if not users_ref.child(u.username).get():
                    users_ref.child(u.username).set({'status': 'yangi'})
                    count += 1
                
        await msg.edit_text(f"✅ Parsing muvaffaqiyatli yakunlandi!\n🔥 {count} ta yangi odam Firebase'ga yuklandi.")
        await client.disconnect()
    except Exception as e:
        await msg.edit_text(f"❌ Guruhni o'qishda xatolik yuz berdi: {e}")

# ================= 2. AKKAUNT QO'SHISH QISMI =================
@dp.message_handler(lambda m: m.text == "📱 Akkaunt Qo'shish")
async def add_acc_start(message: types.Message):
    await message.answer("📞 Telefon raqamingizni kiriting (xalqaro formatda, masalan: +998901234567):")
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
        await message.answer(f"❌ Xatolik yuz berdi: {e}")
        await state.finish()

@dp.message_handler(state=BotStates.waiting_for_code)
async def add_acc_code(message: types.Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    
    client = TelegramClient(StringSession(data['session']), API_ID, API_HASH)
    await client.connect()
    
    try:
        await client.sign_in("+" + data['phone'], code, phone_code_hash=data['hash'])
        session_str = client.session.save() 
        
        db.reference('accounts').child(data['phone']).set({
            'session': session_str,
            'status': 'faol'
        })
        await message.answer(f"🎉 +{data['phone']} akkaunti tizimga qo'shildi!")
    except Exception as e:
        await message.answer(f"❌ Kod xato yoki 2-bosqichli parol yoniq: {e}")
    finally:
        await client.disconnect()
        await state.finish()

# ================= 3. INVAYTING QISMI =================
@dp.message_handler(lambda m: m.text == "🚀 Invaytingni Boshlash")
async def start_inviting(message: types.Message):
    msg = await message.answer("🚀 Avtomatik invayting boshlandi. Kuting...")
    
    accs = db.reference('accounts').get()
    users_data = db.reference('users').get()
    
    if not accs or not users_data:
        await msg.edit_text("❌ Akkauntlar yoki foydalanuvchilar bazasi bo'sh!")
        return

    target_users = [uname for uname, udata in users_data.items() if udata.get('status') == 'yangi']
    
    if not target_users:
        await msg.edit_text("❌ Bazada yangi odamlar qolmadi. Parsing qiling!")
        return

    user_idx = 0
    for phone, acc_info in accs.items():
        if acc_info.get('status') != 'faol': 
            continue 
            
        if user_idx >= len(target_users): 
            break
        
        await message.answer(f"📱 Ishga tushdi: +{phone}")
        client = TelegramClient(StringSession(acc_info['session']), API_ID, API_HASH)
        await client.connect()
        
        added = 0
        max_limit = 8 
        
        while added < max_limit and user_idx < len(target_users):
            user = target_users[user_idx]
            user_idx += 1
            try:
                await client(InviteToChannelRequest(MY_GROUP, [user]))
                db.reference('users').child(user).update({'status': 'qo_shildi'})
                added += 1
                await message.answer(f"   ✅ @{user} muvaffaqiyatli qo'shildi! ({added}/{max_limit})")
                await asyncio.sleep(25) 
                
            except PeerFloodError:
                db.reference('accounts').child(phone).update({'status': 'flood_block'})
                await message.answer(f"   ⚠️ +{phone} Flood Block oldi. Keyingi raqamga o'tiladi.")
                break
            except FloodWaitError as e:
                await message.answer(f"   ⏳ Telegram {e.seconds} soniya kutishni so'radi. Raqam almashadi.")
                break
            except UserPrivacyRestrictedError:
                db.reference('users').child(user).update({'status': 'yopiq_profil'})
                await asyncio.sleep(3)
            except Exception as e:
                db.reference('users').child(user).update({'status': 'xato'})
                await asyncio.sleep(3)
                
        await client.disconnect()
        
        if user_idx < len(target_users):
            await message.answer("🔄 Akkauntlar almashmoqda, 45 soniya tanaffus...")
            await asyncio.sleep(45)

    await message.answer("🎉 Invayting tsikli to'liq yakunlandi.")

# ================= 4. STATISTIKA QISMI =================
@dp.message_handler(lambda m: m.text == "📊 Statistika")
async def show_stats(message: types.Message):
    accs = db.reference('accounts').get() or {}
    users_data = db.reference('users').get() or {}
    
    faol_acc = sum(1 for a in accs.values() if a.get('status') == 'faol')
    blok_acc = sum(1 for a in accs.values() if a.get('status') == 'flood_block')
    
    yangi = sum(1 for u in users_data.values() if u.get('status') == 'yangi')
    qoshingan = sum(1 for u in users_data.values() if u.get('status') == 'qo_shildi')
    
    text = f"📊 **Tizim statistikasi:**\n\n"
    text += f"📱 Faol akkauntlar: {faol_acc} ta\n"
    text += f"🔴 Bloklanganlar: {blok_acc} ta\n\n"
    text += f"🆕 Navbatdagi odamlar: {yangi} ta\n"
    text += f"✅ Qo'shib bo'linganlar: {qoshingan} ta\n"
    
    await message.answer(text, parse_mode="Markdown")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
