import asyncio, base64, json, logging, os, re, time, urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import sqlite3
from telegram import Bot, Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.constants import ParseMode
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, Defaults, filters
from dotenv import load_dotenv

load_dotenv()
TOKEN = (os.getenv('BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN') or os.getenv('TOKEN') or '').strip()
OWNER_ID = int(os.getenv('OWNER_ID', '0') or 0)
CHANNEL = os.getenv('CHANNEL', '').strip()  # optional @channel or numeric ID
DB_PATH = os.getenv('DATABASE_PATH', 'vynexa.sqlite3').strip() or 'vynexa.sqlite3'
SENDALL_MIN = int(os.getenv('SENDALL_MIN', '300'))
TZ = ZoneInfo('Asia/Tehran')

if not TOKEN or not OWNER_ID:
    raise SystemExit('لطفاً متغیرهای BOT_TOKEN و OWNER_ID را تنظیم کنید.')

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

HOME = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='🚀 سرویس جدید')],
    [KeyboardButton(text='🛍 سرویس های من'), KeyboardButton(text='👤 حساب کاربری')],
    [KeyboardButton(text='💎 افزایش رفرال')],
    [KeyboardButton(text='🎉 سکه روزانه'), KeyboardButton(text='📝 ماموریت‌ها')],
], resize_keyboard=True)
ADMIN_PANEL = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='📊 آمار ربات 📊')],
    [KeyboardButton(text='💬 بخش ارسال'), KeyboardButton(text='🤖 تنظیمات ربات'), KeyboardButton(text='👤 بخش کاربران')],
    [KeyboardButton(text='↩️ صفحه قبل')]], resize_keyboard=True)
USER_PANEL = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='📊 اطلاعات کاربر')], [KeyboardButton(text='➖ حذف کانفیگ'), KeyboardButton(text='➕ افزودن کانفیگ')],
    [KeyboardButton(text='➖ کاهش سکه'), KeyboardButton(text='➕ افزایش سکه')],
    [KeyboardButton(text='❌ حذف مسدودیت'), KeyboardButton(text='⚠️ مسدود کردن')], [KeyboardButton(text='برگشت 🔙')]], resize_keyboard=True)
SEND_PANEL = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='💬 ارسال پیام به کاربر')], [KeyboardButton(text='💬 پیام همگانی'), KeyboardButton(text='↗️ فوروارد همگانی')],
    [KeyboardButton(text='برگشت 🔙')]], resize_keyboard=True)
SETTINGS_PANEL = ReplyKeyboardMarkup(keyboard=[
    [KeyboardButton(text='💎 تنظیمات ربات')], [KeyboardButton(text='📣 مدیریت قفل ها'), KeyboardButton(text='👤 مدیریت ادمین ها')],
    [KeyboardButton(text='برگشت 🔙')]], resize_keyboard=True)
CHANNEL_PANEL = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='➕ افزودن چنل')], [KeyboardButton(text='📚 لیست چنل ها')], [KeyboardButton(text='👤 پنل مدیریت 👤')]], resize_keyboard=True)
ADMIN_MANAGE = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='➕ افزودن ادمین')], [KeyboardButton(text='📚 لیست ادمین ها')], [KeyboardButton(text='👤 پنل مدیریت 👤')]], resize_keyboard=True)
BACK = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='برگشت 🔙')]], resize_keyboard=True)

db_conn = None
_db_lock = asyncio.Lock()
application = None
bot = None

async def db(query, args=(), fetch='none'):
    """SQLite query helper; returns dictionaries for rows like the old MySQL helper."""
    global db_conn
    query = query.replace('%s', '?').replace('INSERT IGNORE INTO', 'INSERT OR IGNORE INTO')
    query = query.replace('ORDER BY RAND()', 'ORDER BY RANDOM()')
    async with _db_lock:
        cur = db_conn.execute(query, args)
        if fetch == 'one':
            row = cur.fetchone()
            return dict(row) if row is not None else None
        if fetch == 'all':
            return [dict(row) for row in cur.fetchall()]
        if fetch == 'last':
            db_conn.commit()
            return cur.lastrowid
        db_conn.commit()
        return cur.rowcount

async def init_db():
    global db_conn
    db_dir = os.path.dirname(os.path.abspath(DB_PATH))
    os.makedirs(db_dir, exist_ok=True)
    db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    db_conn.row_factory = sqlite3.Row
    db_conn.execute('PRAGMA journal_mode=WAL')
    db_conn.execute('PRAGMA busy_timeout=30000')
    schema = [
      "CREATE TABLE IF NOT EXISTS `user` (id INTEGER PRIMARY KEY, coin REAL DEFAULT 0, ref_count INTEGER DEFAULT 0, ref_id INTEGER NULL, join_date TEXT NULL, spam TEXT NULL, step TEXT DEFAULT 'none', data TEXT NULL, daily_gift INTEGER NULL, create_at INTEGER DEFAULT 0, update_at INTEGER DEFAULT 0)",
      "CREATE TABLE IF NOT EXISTS `Services` (id INTEGER PRIMARY KEY AUTOINCREMENT, user INTEGER NOT NULL, config TEXT NOT NULL, reset INTEGER DEFAULT 0, time TEXT NOT NULL, date TEXT NOT NULL, create_at INTEGER DEFAULT 0)",
      "CREATE TABLE IF NOT EXISTS `Configs` (id INTEGER PRIMARY KEY AUTOINCREMENT, config TEXT NOT NULL UNIQUE, type TEXT DEFAULT 'vless', create_at INTEGER DEFAULT 0)",
      "CREATE TABLE IF NOT EXISTS `Missions` (id INTEGER PRIMARY KEY AUTOINCREMENT, user INTEGER NOT NULL, mission TEXT NOT NULL, create_at INTEGER DEFAULT 0)",
      "CREATE TABLE IF NOT EXISTS `channels` (idoruser TEXT PRIMARY KEY, link TEXT NOT NULL)",
      "CREATE TABLE IF NOT EXISTS `admin` (admin INTEGER PRIMARY KEY)",
      "CREATE TABLE IF NOT EXISTS `block` (id INTEGER NOT NULL)",
      "CREATE TABLE IF NOT EXISTS `sendall` (step TEXT DEFAULT NULL, admin INTEGER NULL, messageid INTEGER NULL, text TEXT NULL, chat TEXT NULL, sended INTEGER DEFAULT 0)",
      "CREATE TABLE IF NOT EXISTS `settings` (botname TEXT DEFAULT 'اینترنت آزاد', can_reset INTEGER DEFAULT 3, coin_need INTEGER DEFAULT 3, coin_daily INTEGER DEFAULT 1, coin_referral INTEGER DEFAULT 1, bot_mode TEXT DEFAULT 'on')",
    ]
    async with _db_lock:
        for q in schema:
            db_conn.execute(q)
        db_conn.execute('INSERT OR IGNORE INTO `admin` (admin) VALUES (?)', (OWNER_ID,))
        if not db_conn.execute('SELECT * FROM settings LIMIT 1').fetchone():
            db_conn.execute('INSERT INTO settings DEFAULT VALUES')
        if not db_conn.execute('SELECT * FROM sendall LIMIT 1').fetchone():
            db_conn.execute('INSERT INTO sendall DEFAULT VALUES')
        db_conn.execute("UPDATE `user` SET create_at=CAST(strftime('%s','now') AS INTEGER) WHERE create_at=0")
        db_conn.commit()

async def is_admin(uid): return bool(await db('SELECT admin FROM `admin` WHERE admin=%s', (uid,), 'one'))
async def get_settings(): return await db('SELECT * FROM settings LIMIT 1', fetch='one') or {}
async def set_step(uid, step, data=None): await db('UPDATE `user` SET step=%s, data=%s WHERE id=%s', (step, data, uid))
async def get_user(uid): return await db('SELECT * FROM `user` WHERE id=%s', (uid,), 'one') or {}
async def joined(uid):
    channels = await db('SELECT * FROM channels', fetch='all')
    for ch in channels:
        try:
            m = await bot.get_chat_member(ch['idoruser'], uid)
            if m.status not in ('creator','administrator','member'): return False
        except Exception: return False
    if CHANNEL:
        try:
            m = await bot.get_chat_member(CHANNEL, uid)
            if m.status not in ('creator','administrator','member'): return False
        except Exception: return False
    return True
async def join_markup(uid):
    rows=[]
    for ch in await db('SELECT * FROM channels', fetch='all'):
        try:
            member=await bot.get_chat_member(ch['idoruser'], uid)
            if member.status not in ('creator','administrator','member'):
                title=(await bot.get_chat(ch['idoruser'])).title
                rows.append([InlineKeyboardButton(text=title, url=ch['link'])])
        except Exception: rows.append([InlineKeyboardButton(text='عضویت در کانال', url=ch['link'])])
    if CHANNEL:
        try:
            m=await bot.get_chat_member(CHANNEL, uid)
            if m.status not in ('creator','administrator','member'):
                ch=await bot.get_chat(CHANNEL); rows.append([InlineKeyboardButton(text=ch.title, url=f'https://t.me/{CHANNEL.lstrip("@")}')])
        except Exception: rows.append([InlineKeyboardButton(text='عضویت در کانال', url=f'https://t.me/{CHANNEL.lstrip("@")}')])
    rows.append([InlineKeyboardButton(text='✅ تایید عضویت', callback_data='join')])
    return InlineKeyboardMarkup(inline_keyboard=rows)

WELCOME = '👋 سلام، به {name} خوش اومدی؛\n\n🚀 ربات {name} برای دسترسی رایگان به اینترنت آزاد طراحی شده است. ❤️'
def home_for(admin=False):
    if not admin: return HOME
    kb = [list(row) for row in HOME.keyboard]
    kb.append([KeyboardButton(text='👤 پنل مدیریت 👤')])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def parse_config(s):
    s=s.strip().strip('"\'`').rstrip(', .()[]{}<>')
    m=re.match(r'^(vmess|vless|trojan|ss|socks|http|https)://',s,re.I)
    if not m: return None
    typ=m.group(1).lower()
    try:
        if typ=='vmess':
            raw=s[8:]; raw += '='*((4-len(raw)%4)%4)
            obj=json.loads(base64.urlsafe_b64decode(raw).decode())
            if not obj.get('add') or not str(obj.get('port','')).isdigit(): return None
        elif typ=='ss':
            body=s[5:].split('#')[0]
            if '@' not in body:
                raw=body.split('?')[0]; raw += '='*((4-len(raw)%4)%4)
                body=base64.urlsafe_b64decode(raw).decode()
            if '@' not in body: return None
        else:
            u=urllib.parse.urlparse(s)
            if not u.hostname or not u.port: return None
        return typ
    except Exception: return None

def safe_config(config, bot_username):
    code=int(time.time()*1000)%9000+1000
    label=urllib.parse.quote(f'🚀 ViP #{code} - @{bot_username}')
    out=[]
    raw=config.strip().strip('"\'`').rstrip(', .()[]{}<>')
    try:
        decoded=base64.urlsafe_b64decode(raw + '='*((4-len(raw)%4)%4)).decode()
        if re.search(r'(vmess|vless|trojan|ss|socks)://',decoded,re.I): raw=decoded
    except Exception: pass
    for line in raw.splitlines():
        line=line.strip()
        if not line: continue
        if line.lower().startswith('vmess://'):
            try:
                data=line[8:]; data += '='*((4-len(data)%4)%4)
                obj=json.loads(base64.urlsafe_b64decode(data).decode()); obj['ps']=f'🚀 ViP #{code} - @{bot_username}'
                line='vmess://'+base64.b64encode(json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode()).decode()
            except Exception: pass
        elif re.match(r'^(vless|trojan|ss|socks|http|https)://',line,re.I):
            line=line.split('#')[0]+'#'+label
        out.append(line)
    return '\n'.join(out)

async def ensure_user(message: Message):
    uid=message.from_user.id
    user=await get_user(uid)
    now=int(time.time())
    if not user:
        await db('INSERT INTO `user` (id,join_date,create_at,update_at,step,data) VALUES (%s,%s,%s,%s,%s,%s)',(uid,datetime.now(TZ).strftime('%Y/%m/%d'),now,now,'none','none'))
        user=await get_user(uid)
    else: await db('UPDATE `user` SET update_at=%s WHERE id=%s',(now,uid))
    return user

async def start(message: Message):
    user=await ensure_user(message); uid=message.from_user.id; admin=await is_admin(uid); st=await get_settings()
    parts=(message.text or '').split(maxsplit=1)
    if len(parts)>1 and parts[1].startswith('ref_'):
        try: ref=int(parts[1][4:])
        except ValueError: ref=0
        if not user.get('ref_id') and ref and ref!=uid:
            await db('UPDATE `user` SET ref_id=%s WHERE id=%s',(ref,uid))
            if await joined(uid):
                await db('UPDATE `user` SET coin=coin+(SELECT coin_referral FROM settings LIMIT 1), ref_count=ref_count+1 WHERE id=%s',(ref,))
                try: await bot.send_message(ref,'🎉 یک کاربر با لینک شما عضو ربات شد؛ پاداش رفرال اضافه شد.')
                except Exception: pass
            else: await db('UPDATE `user` SET data=%s WHERE id=%s',(f'ref_{ref}',uid))
    if not admin and st.get('bot_mode')=='off': return await message.reply_text('❌ ربات موقتاً خاموش است.')
    if not admin and not await joined(uid):
        return await message.reply_text(f'برای استفاده از ربات ابتدا عضو کانال‌های زیر شوید:\n{name if False else ""}', reply_markup=await join_markup(uid))
    await set_step(uid,'none','none')
    await message.reply_text(WELCOME.format(name=st.get('botname') or 'اینترنت آزاد'), reply_markup=home_for(admin))

async def join_check(call: CallbackQuery):
    if await joined(call.from_user.id):
        user=await get_user(call.from_user.id); st=await get_settings()
        if (user.get('data') or '').startswith('ref_'):
            ref=int(user['data'][4:]); s=await get_settings()
            await db('UPDATE `user` SET coin=coin+%s,ref_count=ref_count+1 WHERE id=%s',(s.get('coin_referral',1),ref))
            await db('UPDATE `user` SET data=%s WHERE id=%s',('none',call.from_user.id))
            try: await bot.send_message(ref,'🎉 یک کاربر با لینک شما عضو ربات شد و پاداش دریافت کرد.')
            except Exception: pass
        await call.message.delete()
        await call.message.reply_text(WELCOME.format(name=st.get('botname') or 'اینترنت آزاد'),reply_markup=home_for(await is_admin(call.from_user.id)))
        await call.answer('عضویت تایید شد.')
    else: await call.answer('لطفاً ابتدا عضو همه کانال‌ها شوید.',show_alert=True)

async def back_home(message: Message):
    await ensure_user(message); await set_step(message.from_user.id,'none','none')
    st=await get_settings(); await message.reply_text(WELCOME.format(name=st.get('botname') or 'اینترنت آزاد'),reply_markup=home_for(await is_admin(message.from_user.id)))

async def text_router(message: Message):
    user=await ensure_user(message); uid=message.from_user.id; text=message.text or message.caption or ''; chat=message.chat.id
    admin=await is_admin(uid); st=await get_settings(); step=user.get('step') or 'none'; now=int(time.time())
    if await db('SELECT id FROM block WHERE id=%s LIMIT 1',(uid,),'one'): return
    if not admin and st.get('bot_mode')=='off': return await message.reply_text('❌ ربات به صورت موقت خاموش است.')
    if not admin and not await joined(uid): return await message.reply_text('برای استفاده ابتدا عضو کانال‌های زیر شوید.',reply_markup=await join_markup(uid))
    if step!='none' and text=='برگشت 🔙':
        await set_step(uid,'none','none'); return await message.reply_text('به منوی قبلی برگشتید.',reply_markup=home_for(admin))
    if text=='🚀 سرویس جدید':
        if float(user.get('coin') or 0)<int(st.get('coin_need') or 3): return await message.reply_text(f'برای دریافت سرویس به {st.get("coin_need")} سکه نیاز دارید. موجودی شما: {user.get("coin",0)}')
        cfg=await db('SELECT * FROM Configs ORDER BY RAND() LIMIT 1',fetch='one')
        if not cfg: return await message.reply_text('فعلاً کانفیگ آماده‌ای موجود نیست.')
        await db('UPDATE `user` SET coin=coin-%s WHERE id=%s',(st.get('coin_need',3),uid))
        sid=await db('INSERT INTO Services (user,config,time,date,create_at) VALUES (%s,%s,%s,%s,%s)',(uid,cfg['config'],datetime.now(TZ).strftime('%H:%M'),datetime.now(TZ).strftime('%Y/%m/%d'),now),'last')
        return await message.reply_text(f'✅ سرویس جدید شما ساخته شد.\n\nشناسه: <code>{sid}</code>\n\n<code>{cfg["config"]}</code>',reply_markup=home_for(admin))
    if text=='👤 حساب کاربری':
        return await message.reply_text(f'👤 اطلاعات حساب شما\nشناسه: <code>{uid}</code>\nتاریخ عضویت: {user.get("join_date")}\nسکه: {user.get("coin",0)}\nتعداد رفرال: {user.get("ref_count",0)}')
    if text=='💎 افزایش رفرال':
        me=await bot.get_me(); return await message.reply_text(f'لینک دعوت اختصاصی شما:\nhttps://t.me/{me.username}?start=ref_{uid}\n\nبا دعوت دوستان، {st.get("coin_referral",1)} سکه دریافت می‌کنید.')
    if text=='🎉 سکه روزانه':
        last=int(user.get('daily_gift') or 0); remain=86400-(now-last)
        if remain<=0:
            await db('UPDATE `user` SET coin=coin+%s,daily_gift=%s WHERE id=%s',(st.get('coin_daily',1),now,uid)); return await message.reply_text(f'🎊 {st.get("coin_daily",1)} سکه به شما اضافه شد.')
        return await message.reply_text(f'سکه امروز را دریافت کرده‌اید. {remain//3600} ساعت و {(remain%3600)//60} دقیقه دیگر برگردید.')
    if text=='📝 ماموریت‌ها':
        vals=[(10,3,'🎖'),(30,5,'🥉'),(50,7,'🥈'),(100,10,'🥇')]; rows=[]
        done={r['mission'] for r in await db('SELECT mission FROM Missions WHERE user=%s',(uid,),'all')}
        for n,b,_ in vals: rows.append([InlineKeyboardButton(text=f'{_} رسیدن به {n} رفرال '+('✅' if f'referral|{n}' in done else '❌'),callback_data=f'bonus|referral|{n}')])
        return await message.reply_text('👇 لیست ماموریت‌ها:',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    if text=='🛍 سرویس های من':
        rows=await db('SELECT id FROM Services WHERE user=%s ORDER BY id DESC',(uid,),'all')
        if not rows: return await message.reply_text('❌ شما سرویس فعالی ندارید.')
        kb=[[InlineKeyboardButton(text=f'🟢 Super ViP #{r["id"]}',callback_data=f'get_service|{r["id"]}')] for r in rows]
        return await message.reply_text('🔽 سرویس مورد نظر را انتخاب کنید:',reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    if admin and text in ('👤 پنل مدیریت 👤','/panel','برگشت 🔙'):
        await set_step(uid,'none','none'); return await message.reply_text('👋 به پنل مدیریت خوش آمدید.',reply_markup=ADMIN_PANEL)
    if admin and text=='👤 بخش کاربران': return await message.reply_text('مدیریت کاربران:',reply_markup=USER_PANEL)
    if admin and text=='💬 بخش ارسال': return await message.reply_text('مدیریت ارسال:',reply_markup=SEND_PANEL)
    if admin and text=='🤖 تنظیمات ربات': return await message.reply_text('تنظیمات ربات:',reply_markup=SETTINGS_PANEL)
    if admin and text=='📣 مدیریت قفل ها': return await message.reply_text('مدیریت کانال‌های قفل:',reply_markup=CHANNEL_PANEL)
    if admin and text=='👤 مدیریت ادمین ها': return await message.reply_text('مدیریت ادمین‌ها:',reply_markup=ADMIN_MANAGE)
    if admin and text=='💎 تنظیمات ربات':
        vals=await get_settings(); kb=[]
        for key,label in [('botname','نام ربات'),('bot_mode','وضعیت ربات'),('can_reset','حداکثر تغییر لینک'),('coin_need','هزینه سرویس'),('coin_daily','جایزه روزانه'),('coin_referral','جایزه رفرال')]: kb.append([InlineKeyboardButton(text=f'{label}: {vals.get(key)}',callback_data=f'set|{key}')])
        return await message.reply_text('تنظیمات عمومی:',reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    if admin and text=='📊 آمار ربات 📊':
        counts=[]
        for table in ('user','block','Services','Configs'): counts.append((await db(f'SELECT COUNT(*) n FROM `{table}`',fetch='one'))['n'])
        return await message.reply_text(f'📊 آمار ربات\nکاربران: {counts[0]}\nمسدودها: {counts[1]}\nسرویس‌ها: {counts[2]}\nکانفیگ‌ها: {counts[3]}')
    # Stateful admin operations
    if admin and text=='➕ افزودن کانفیگ': await set_step(uid,'add_config'); return await message.reply_text('کانفیگ یا لینک سابسکریپشن را ارسال کنید:',reply_markup=BACK)
    if admin and step=='add_config':
        candidates=re.findall(r'(?:vmess|vless|trojan|ss|socks|http|https)://[^\s<>"\'`]+',text,re.I); added=0; me=await bot.get_me()
        for c in candidates:
            typ=parse_config(c)
            if not typ: continue
            cfg=safe_config(c,me.username)
            added += await db('INSERT IGNORE INTO Configs (config,type,create_at) VALUES (%s,%s,%s)',(cfg,typ,now))
        await set_step(uid,'none'); return await message.reply_text(f'✅ تعداد {added} کانفیگ معتبر اضافه شد.')
    if admin and text=='➖ حذف کانفیگ':
        kb=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='❌ حذف همه')],[KeyboardButton(text='⏰ 24 ساعت اخیر'),KeyboardButton(text='📆 7 روز اخیر')],[KeyboardButton(text='برگشت 🔙')]],resize_keyboard=True)
        return await message.reply_text('نوع حذف را انتخاب کنید:',reply_markup=kb)
    if admin and text in ('❌ حذف همه','⏰ 24 ساعت اخیر','📆 7 روز اخیر'):
        if text=='❌ حذف همه': n=await db('SELECT COUNT(*) n FROM Configs',fetch='one'); await db('DELETE FROM Configs')
        else:
            sec=86400 if text=='⏰ 24 ساعت اخیر' else 604800
            n=await db('SELECT COUNT(*) n FROM Configs WHERE create_at>%s',(now-sec,),'one'); await db('DELETE FROM Configs WHERE create_at>%s',(now-sec,))
        return await message.reply_text(f'✅ تعداد {n["n"]} کانفیگ حذف شد.',reply_markup=USER_PANEL)
    if admin and text in ('⚠️ مسدود کردن','❌ حذف مسدودیت','📊 اطلاعات کاربر','➕ افزایش سکه','➖ کاهش سکه','💬 ارسال پیام به کاربر','💬 پیام همگانی','↗️ فوروارد همگانی','➕ افزودن ادمین','📚 لیست ادمین ها','📚 لیست چنل ها','➕ افزودن چنل'):
        mapping={'⚠️ مسدود کردن':'block','❌ حذف مسدودیت':'unblock','📊 اطلاعات کاربر':'user_info','➕ افزایش سکه':'addamount','➖ کاهش سکه':'removeamount','💬 ارسال پیام به کاربر':'send_pm_user','💬 پیام همگانی':'broadcast','↗️ فوروارد همگانی':'forward_all','➕ افزودن ادمین':'add_admin','➕ افزودن چنل':'new_ch'}
        if text=='📚 لیست ادمین ها':
            rows=await db('SELECT admin FROM admin',fetch='all'); kb=[[InlineKeyboardButton(text=str(r['admin']),callback_data='noop'),InlineKeyboardButton(text='❌ حذف',callback_data=f'deladmin|{r["admin"]}')] for r in rows]
            return await message.reply_text('لیست ادمین‌ها:',reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        if text=='📚 لیست چنل ها':
            rows=await db('SELECT * FROM channels',fetch='all'); kb=[[InlineKeyboardButton(text=r['idoruser'],url=r['link']),InlineKeyboardButton(text='❌ حذف',callback_data=f'delchannel|{r["idoruser"]}')] for r in rows]
            return await message.reply_text('لیست کانال‌های قفل:',reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        if text in ('💬 پیام همگانی','↗️ فوروارد همگانی'):
            active=await db('SELECT * FROM sendall LIMIT 1',fetch='one')
            if active and active.get('admin'): return await message.reply_text('یک عملیات همگانی دیگر در حال اجراست.')
        await set_step(uid,mapping[text]); return await message.reply_text('اطلاعات مورد نیاز را ارسال کنید:',reply_markup=BACK)
    if admin and step in ('block','unblock'):
        try: target=int(text)
        except ValueError: return await message.reply_text('شناسه باید عددی باشد.')
        if step=='block': await db('INSERT INTO block (id) VALUES (%s)',(target,)); msg='کاربر مسدود شد.'
        else: await db('DELETE FROM block WHERE id=%s',(target,)); msg='مسدودیت برداشته شد.'
        await set_step(uid,'none'); return await message.reply_text(msg,reply_markup=USER_PANEL)
    if admin and step in ('addamount','removeamount'):
        try: target,amount=map(float,text.splitlines()[:2]); target=int(target)
        except Exception: return await message.reply_text('فرمت صحیح:\nشناسه کاربر\nمقدار سکه')
        exists=await get_user(target)
        if not exists: await set_step(uid,'none'); return await message.reply_text('کاربر پیدا نشد.')
        op='+' if step=='addamount' else '-'; await db(f'UPDATE `user` SET coin=coin{op}%s WHERE id=%s',(amount,target)); await set_step(uid,'none')
        try: await bot.send_message(target,f'تغییر موجودی شما: {op}{amount} سکه')
        except Exception: pass
        return await message.reply_text('موجودی به‌روزرسانی شد.',reply_markup=USER_PANEL)
    if admin and step=='user_info':
        try: target=int(text)
        except ValueError: return await message.reply_text('شناسه عددی وارد کنید.')
        u=await get_user(target); await set_step(uid,'none')
        return await message.reply_text(f'شناسه: {target}\nسکه: {u.get("coin")}\nرفرال: {u.get("ref_count")}\nتاریخ عضویت: {u.get("join_date")}') if u else await message.reply_text('کاربر پیدا نشد.')
    if admin and step=='send_pm_user':
        try: target=int(text)
        except ValueError: return await message.reply_text('شناسه عددی وارد کنید.')
        if not await get_user(target): await set_step(uid,'none'); return await message.reply_text('کاربر پیدا نشد.')
        await set_step(uid,'send_pm_content',str(target)); return await message.reply_text('پیام مورد نظر را ارسال کنید.')
    if admin and step=='send_pm_content':
        try: await bot.copy_message(int(user.get('data')),chat,message.message_id)
        except Exception as e: return await message.reply_text(f'ارسال ناموفق بود: {e}')
        await set_step(uid,'none'); return await message.reply_text('پیام ارسال شد.')
    if admin and step in ('add_admin','new_ch'):
        if step=='add_admin':
            try: target=int(text)
            except ValueError: return await message.reply_text('شناسه عددی وارد کنید.')
            if not await get_user(target): return await message.reply_text('ابتدا کاربر باید ربات را start کرده باشد.')
            await db('INSERT IGNORE INTO admin (admin) VALUES (%s)',(target,)); await set_step(uid,'none'); return await message.reply_text('ادمین اضافه شد.',reply_markup=ADMIN_MANAGE)
        origin=message.forward_origin
        if not origin or not hasattr(origin,'chat'): return await message.reply_text('یک پیام فورواردشده از کانال یا گروه بفرستید.')
        ch=origin.chat
        try:
            admins=await bot.get_chat_administrators(ch.id)
            me=await bot.get_me(); mine=next((a for a in admins if a.user.id==me.id),None)
            if not mine or not getattr(mine,'can_invite_users',False): return await message.reply_text('ربات باید ادمین و دارای دسترسی ساخت لینک دعوت باشد.')
            invite=await bot.create_chat_invite_link(ch.id,name=f'قفل ربات @{me.username}')
            await db('INSERT INTO channels (idoruser,link) VALUES (?,?) ON CONFLICT(idoruser) DO UPDATE SET link=excluded.link',(str(ch.id),invite.invite_link))
            await set_step(uid,'none'); return await message.reply_text(f'کانال {ch.title} اضافه شد.\n{invite.invite_link}',reply_markup=CHANNEL_PANEL)
        except Exception as e: return await message.reply_text(f'خطا: {e}')
    if admin and step in ('broadcast','forward_all'):
        targets=await db('SELECT id FROM user',fetch='all')
        send=await db('SELECT * FROM sendall LIMIT 1',fetch='one')
        if send and send.get('admin'): return await message.reply_text('یک ارسال همگانی دیگر فعال است.')
        status=await message.reply_text(f'ارسال همگانی در صف قرار گرفت. تعداد کاربران: {len(targets)}')
        await db('UPDATE sendall SET step=%s,admin=%s,messageid=%s,text=%s,chat=%s,sended=0',('copy' if step=='broadcast' else 'forward',uid,status.message_id,message.message_id,chat))
        await set_step(uid,'none'); return
    if admin and step=='send_settings':
        key=user.get('data'); allowed={'botname','can_reset','coin_need','coin_daily','coin_referral'}
        if key not in allowed: await set_step(uid,'none'); return
        await db(f'UPDATE settings SET `{key}`=%s',(text,)); await set_step(uid,'none'); return await message.reply_text('تنظیمات ذخیره شد.',reply_markup=SETTINGS_PANEL)
    if admin and step.startswith('change_'):
        key=step[7:]
        if key in ('botname','can_reset','coin_need','coin_daily','coin_referral'):
            await db(f'UPDATE settings SET `{key}`=%s',(text,)); await set_step(uid,'none'); return await message.reply_text('تنظیمات ذخیره شد.')
    # Cancel any other pending step safely
    if text.startswith('/'): return

async def service_detail(call: CallbackQuery):
    sid=int(call.data.split('|')[1]); row=await db('SELECT * FROM Services WHERE id=%s AND user=%s',(sid,call.from_user.id),'one')
    if not row: return await call.answer('سرویس پیدا نشد.',show_alert=True)
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='❌ حذف سرویس',callback_data=f'delservice|{sid}'),InlineKeyboardButton(text='♻️ تغییر لینک',callback_data=f'resetservice|{sid}')],[InlineKeyboardButton(text='↩️ بازگشت',callback_data='myservices')]])
    await call.message.edit_text(f'🚀 سرویس Super ViP #{sid}\n\n<code>{row["config"]}</code>\n\nتعداد تغییر لینک: {row["reset"]}',reply_markup=kb); await call.answer()

async def my_services_callback(call: CallbackQuery):
    rows=await db('SELECT id FROM Services WHERE user=%s',(call.from_user.id,),'all')
    kb=[[InlineKeyboardButton(text=f'Service #{r["id"]}',callback_data=f'get_service|{r["id"]}')] for r in rows]
    await call.message.edit_text('سرویس‌های شما:',reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await call.answer()

async def del_service(call: CallbackQuery):
    sid=int(call.data.split('|')[1]); n=await db('DELETE FROM Services WHERE id=%s AND user=%s',(sid,call.from_user.id))
    await call.answer('سرویس حذف شد.' if n else 'سرویس پیدا نشد.',show_alert=True)
    if n: await call.message.edit_text('سرویس حذف شد.')

async def reset_service(call: CallbackQuery):
    sid=int(call.data.split('|')[1]); row=await db('SELECT * FROM Services WHERE id=%s AND user=%s',(sid,call.from_user.id),'one'); st=await get_settings()
    if not row: return await call.answer('سرویس پیدا نشد.',show_alert=True)
    if row['reset']>=int(st.get('can_reset',3)): return await call.answer('به سقف تغییر لینک رسیده‌اید.',show_alert=True)
    cfg=await db('SELECT * FROM Configs WHERE config<>%s ORDER BY RAND() LIMIT 1',(row['config'],),'one')
    if not cfg: return await call.answer('کانفیگ جایگزین موجود نیست.',show_alert=True)
    await db('UPDATE Services SET config=%s,reset=reset+1 WHERE id=%s',(cfg['config'],sid))
    await call.message.edit_text(f'لینک سرویس به‌روزرسانی شد:\n\n<code>{cfg["config"]}</code>'); await call.answer('انجام شد.')

async def mission_bonus(call: CallbackQuery):
    _,kind,num=call.data.split('|'); num=int(num); bonuses={10:3,30:5,50:7,100:10}; u=await get_user(call.from_user.id)
    if kind!='referral' or num not in bonuses: return await call.answer('ماموریت نامعتبر است.')
    if int(u.get('ref_count') or 0)<num: return await call.answer(f'برای این ماموریت به {num} رفرال نیاز دارید.',show_alert=True)
    if await db('SELECT id FROM Missions WHERE user=%s AND mission=%s',(call.from_user.id,f'referral|{num}'),'one'): return await call.answer('قبلاً جایزه را دریافت کرده‌اید.',show_alert=True)
    await db('INSERT INTO Missions (user,mission,create_at) VALUES (%s,%s,%s)',(call.from_user.id,f'referral|{num}',int(time.time())))
    await db('UPDATE `user` SET coin=coin+%s WHERE id=%s',(bonuses[num],call.from_user.id)); await call.answer(f'{bonuses[num]} سکه دریافت کردید.',show_alert=True)

async def setting_callback(call: CallbackQuery):
    if not await is_admin(call.from_user.id): return await call.answer('دسترسی ندارید.',show_alert=True)
    key=call.data.split('|',1)[1]
    if key=='bot_mode':
        st=await get_settings(); mode='off' if st.get('bot_mode')=='on' else 'on'; await db('UPDATE settings SET bot_mode=%s',(mode,)); await call.answer(f'وضعیت ربات: {mode}')
    else:
        await set_step(call.from_user.id,'change_'+key); await call.message.reply_text(f'مقدار جدید {key} را ارسال کنید:',reply_markup=BACK); await call.answer()

async def delete_admin(call: CallbackQuery):
    if call.from_user.id!=OWNER_ID: return await call.answer('فقط مالک ربات مجاز است.',show_alert=True)
    target=int(call.data.split('|')[1])
    if target==OWNER_ID: return await call.answer('مالک اصلی قابل حذف نیست.',show_alert=True)
    await db('DELETE FROM admin WHERE admin=%s',(target,)); await call.answer('ادمین حذف شد.')
    try: await call.message.edit_text('ادمین حذف شد.')
    except Exception: pass

async def delete_channel(call: CallbackQuery):
    if not await is_admin(call.from_user.id): return await call.answer('دسترسی ندارید.',show_alert=True)
    target=call.data.split('|',1)[1]; await db('DELETE FROM channels WHERE idoruser=%s',(target,)); await call.answer('کانال حذف شد.')
    try: await call.message.edit_text('کانال حذف شد.')
    except Exception: pass

async def noop(call: CallbackQuery): await call.answer()

async def broadcast_worker():
    while True:
        try:
            job=await db('SELECT * FROM sendall LIMIT 1',fetch='one')
            if job and job.get('step') in ('copy','forward'):
                batch=await db('SELECT id FROM user ORDER BY id LIMIT %s OFFSET %s',(SENDALL_MIN,int(job.get('sended') or 0)),'all')
                if not batch:
                    try: await bot.send_message(job['admin'],'✅ ارسال همگانی به پایان رسید.')
                    except Exception: pass
                    await db("UPDATE sendall SET step='none',admin=NULL,messageid=NULL,text='',chat='',sended=0"); await asyncio.sleep(2); continue
                for target in batch:
                    try:
                        if job['step']=='copy': await bot.copy_message(target['id'],int(job['chat']),int(job['text']))
                        else: await bot.forward_message(target['id'],int(job['chat']),int(job['text']))
                    except Exception: pass
                    await db('UPDATE sendall SET sended=sended+1')
                    await asyncio.sleep(0.04)
                try: await bot.edit_message_text(f'ارسال شده: {int(job.get("sended") or 0)+len(batch)}',job['admin'],job['messageid'])
                except Exception: pass
            else: await asyncio.sleep(3)
        except Exception:
            logging.exception('broadcast worker error'); await asyncio.sleep(5)

async def post_init(app: Application):
    global bot
    bot = app.bot
    await init_db()
    app.create_task(broadcast_worker(), name="broadcast-worker")
    logging.info("Bot started with python-telegram-bot")


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update.effective_message)


async def on_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await join_check(update.callback_query)


async def on_back_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await back_home(update.effective_message)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await text_router(update.effective_message)


async def on_service_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await service_detail(update.callback_query)


async def on_my_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await my_services_callback(update.callback_query)


async def on_del_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await del_service(update.callback_query)


async def on_reset_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reset_service(update.callback_query)


async def on_mission_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await mission_bonus(update.callback_query)


async def on_setting(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await setting_callback(update.callback_query)


async def on_delete_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_admin(update.callback_query)


async def on_delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_channel(update.callback_query)


async def on_noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await noop(update.callback_query)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("Unhandled Telegram error: %s", context.error, exc_info=context.error)


def build_application() -> Application:
    app = (Application.builder()
           .token(TOKEN)
           .defaults(Defaults(parse_mode=ParseMode.HTML))
           .post_init(post_init)
           .build())

    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("panel", on_text))
    app.add_handler(CallbackQueryHandler(on_join, pattern=r"^join$"))
    app.add_handler(CallbackQueryHandler(on_service_detail, pattern=r"^get_service\|"))
    app.add_handler(CallbackQueryHandler(on_my_services, pattern=r"^myservices$"))
    app.add_handler(CallbackQueryHandler(on_del_service, pattern=r"^delservice\|"))
    app.add_handler(CallbackQueryHandler(on_reset_service, pattern=r"^resetservice\|"))
    app.add_handler(CallbackQueryHandler(on_mission_bonus, pattern=r"^bonus\|"))
    app.add_handler(CallbackQueryHandler(on_setting, pattern=r"^set\|"))
    app.add_handler(CallbackQueryHandler(on_delete_admin, pattern=r"^deladmin\|"))
    app.add_handler(CallbackQueryHandler(on_delete_channel, pattern=r"^delchannel\|"))
    app.add_handler(CallbackQueryHandler(on_noop, pattern=r"^noop$"))
    app.add_handler(MessageHandler(filters.Regex(r"^↩️ صفحه قبل$") & ~filters.COMMAND, on_back_home))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main():
    global application, bot
    if not TOKEN or not OWNER_ID:
        raise SystemExit("لطفاً متغیرهای BOT_TOKEN و OWNER_ID را تنظیم کنید.")
    application = build_application()
    bot = application.bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
