import os, re, sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

DB='zone_escape.db'
TZ=ZoneInfo('Asia/Tehran')
HOLD_MINUTES=15
SCENARIOS={
'فتنه عفریت': {'slots':['12:00','14:00','16:00','18:00','20:00','22:00','24:00'],'cap':(5,9),'prices':{'12:00':400000,'14:00':400000,'16:00':420000,'18:00':420000,'20:00':430000,'22:00':450000,'24:00':520000}},
'مرداب سایه ها': {'slots':['12:00','14:00','16:00','18:00','20:00','22:00','24:00'],'cap':(5,9),'prices':{'12:00':390000,'14:00':390000,'16:00':410000,'18:00':410000,'20:00':420000,'22:00':440000,'24:00':500000}},
'افسونگر': {'slots':['11:45','13:45','15:45','17:45','19:45','21:45'],'cap':(5,8),'prices':{'11:45':390000,'13:45':390000,'15:45':410000,'17:45':410000,'19:45':420000,'21:45':440000}},
'قوی سیاه': {'slots':['11:45','13:45','15:45','17:45','19:45','21:45'],'cap':(4,8),'prices':{'11:45':350000,'13:45':350000,'15:45':350000,'17:45':360000,'19:45':370000,'21:45':370000}},
'سینما ترس': {'slots':['11:45','13:45','15:45','17:45','19:45','21:45'],'cap':(4,12),'prices':{'11:45':330000,'13:45':330000,'15:45':350000,'17:45':350000,'19:45':350000,'21:45':350000}},
}

def connect():
    c=sqlite3.connect(DB)
    c.execute('''CREATE TABLE IF NOT EXISTS reservations(
      id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, customer TEXT, phone TEXT,
      scenario TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL, players INTEGER,
      total INTEGER, discount INTEGER DEFAULT 0, advance INTEGER DEFAULT 0,
      status TEXT NOT NULL, created_at TEXT NOT NULL, hold_until TEXT,
      UNIQUE(scenario,date,time))''')
    c.commit(); return c

def now(): return datetime.now(TZ)
def clean_holds():
    c=connect(); c.execute("DELETE FROM reservations WHERE status='hold' AND hold_until < ?",(now().isoformat(),)); c.commit(); c.close()
def norm(s): return s.replace('ي','ی').replace('ك','ک').replace('٬',',').strip()
def money(s):
    return int(re.sub(r'[^0-9]','',s)) if re.sub(r'[^0-9]','',s) else 0

def parse(text):
    t=norm(text)
    scenario=next((s for s in SCENARIOS if s in t),None)
    time=None
    if scenario:
        time=next((x for x in SCENARIOS[scenario]['slots'] if x in t),None)
        if not time:
            m=re.search(r'ساعت\s*(\d{1,2})(?::(\d{2}))?',t)
            if m:
                hh=int(m.group(1)); mm=int(m.group(2) or 0); candidate=f'{hh:02d}:{mm:02d}'
                if candidate in SCENARIOS[scenario]['slots']: time=candidate
    date=now().date().isoformat()
    # Version 1: explicit Gregorian YYYY-MM-DD if supplied; otherwise today.
    dm=re.search(r'(20\d{2})[/-](\d{1,2})[/-](\d{1,2})',t)
    if dm: date=f'{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}'
    players=None; pm=re.search(r'(\d+)\s*نفر',t)
    if pm: players=int(pm.group(1))
    phone=None
    for x in re.findall(r'\d[\d\s-]{9,}\d',t):
        d=re.sub(r'\D','',x)
        if len(d)>=10: phone=d; break
    advance=0
    am=re.search(r'([\d,]+)\s*(?:تومان)?\s*پیش',t)
    if am: advance=money(am.group(1))
    name=None
    if scenario:
        before=t.split(scenario)[0]
        before=re.sub(r'(رزرو|سانس|ساعت|امروز|فردا|جمعه|شنبه|یکشنبه|دوشنبه|سه‌شنبه|چهارشنبه|پنجشنبه)',' ',before)
        before=re.sub(r'\d[\d\s-]{9,}\d',' ',before)
        before=re.sub(r'\d+\s*نفر',' ',before)
        before=re.sub(r'[،,]',' ',before)
        before=before.strip()
        if before: name=before
    return scenario,time,date,players,phone,advance,name

def occupied(scenario,date,time):
    c=connect(); r=c.execute('SELECT id,status,hold_until FROM reservations WHERE scenario=? AND date=? AND time=?',(scenario,date,time)).fetchone(); c.close(); return r

def summary(p):
    scenario,time,date,players,phone,advance,name=p
    lo,hi=SCENARIOS[scenario]['cap']; n=players or lo
    total=SCENARIOS[scenario]['prices'][time]*n
    remaining=max(0,total-advance)
    return f'''🎟️ بررسی رزرو\n\nسناریو: {scenario}\nتاریخ: {date}\nساعت: {time}\nمشتری: {name or 'ثبت نشده'}\nموبایل: {phone or 'ثبت نشده'}\nتعداد: {n} نفر\nقیمت هر نفر: {SCENARIOS[scenario]['prices'][time]:,} تومان\nمبلغ کل: {total:,} تومان\nپیش‌پرداخت: {advance:,} تومان\nباقی‌مانده: {remaining:,} تومان\n\n«تایید» = ثبت قطعی\n«نگه دار» = نگه‌داشتن ۱۵ دقیقه'''

async def start(update,context):
    await update.message.reply_text('🎭 زون اسکیپ — نسخه اول\n\nمثال:\nجمعه ساعت ۱۸ فتنه عفریت، محمد رضایی، ۷ نفر، 09121234567، یک میلیون پیش پرداخت\n\nدستورها: /رزروها و /لغو شماره')
async def handle_text(update,context):
    clean_holds(); text=update.message.text.strip()
    if text in ('تایید','ثبت'):
        return await confirm(update,context)
    if text in ('نگه دار','نگه‌دار'):
        return await hold(update,context)
    p=parse(text)
    if not p[0] or not p[1]:
        await update.message.reply_text('⚠️ سناریو یا ساعت را متوجه نشدم. مثال: فتنه عفریت ساعت ۱۸، محمد رضایی، ۷ نفر، 0912...')
        return
    scenario,time,date,players,phone,advance,name=p
    lo,hi=SCENARIOS[scenario]['cap']
    if players is not None and not(lo<=players<=hi):
        await update.message.reply_text(f'⚠️ ظرفیت {scenario}: حداقل {lo} و حداکثر {hi} نفر است.')
        return
    if occupied(scenario,date,time):
        await update.message.reply_text('⛔ سانس تداخلی است؛ این سانس قبلاً رزرو یا نگه‌داشته شده.')
        return
    context.user_data['pending']=p
    await update.message.reply_text(summary(p))
async def confirm(update,context):
    clean_holds(); p=context.user_data.get('pending')
    if not p: return await update.message.reply_text('رزروی برای تایید ندارید.')
    scenario,time,date,players,phone,advance,name=p
    n=players or SCENARIOS[scenario]['cap'][0]; total=SCENARIOS[scenario]['prices'][time]*n
    c=connect()
    try:
        c.execute('INSERT INTO reservations(chat_id,customer,phone,scenario,date,time,players,total,advance,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(update.effective_chat.id,name,phone,scenario,date,time,n,total,advance,'confirmed',now().isoformat()))
        c.commit(); msg='✅ رزرو قطعی ثبت شد.'
    except sqlite3.IntegrityError: msg='⛔ سانس تداخلی است.'
    c.close(); context.user_data.pop('pending',None); await update.message.reply_text(msg)
async def hold(update,context):
    clean_holds(); p=context.user_data.get('pending')
    if not p: return await update.message.reply_text('رزروی برای نگه‌داشتن ندارید.')
    scenario,time,date,players,phone,advance,name=p
    n=players or SCENARIOS[scenario]['cap'][0]; total=SCENARIOS[scenario]['prices'][time]*n; until=now()+timedelta(minutes=HOLD_MINUTES)
    c=connect()
    try:
        c.execute('INSERT INTO reservations(chat_id,customer,phone,scenario,date,time,players,total,advance,status,created_at,hold_until) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(update.effective_chat.id,name,phone,scenario,date,time,n,total,advance,'hold',now().isoformat(),until.isoformat()))
        c.commit(); msg=f'🟡 سانس برای ۱۵ دقیقه نگه داشته شد.\nمهلت: {until.strftime("%H:%M:%S")}\nشماره تماس: {phone or "ثبت نشده"}'
    except sqlite3.IntegrityError: msg='⛔ سانس تداخلی است.'
    c.close(); context.user_data.pop('pending',None); await update.message.reply_text(msg)
async def reservations(update,context):
    clean_holds(); c=connect(); rows=c.execute("SELECT id,date,time,scenario,customer,phone,status,total,advance FROM reservations WHERE status IN ('confirmed','hold') ORDER BY date,time").fetchall(); c.close()
    if not rows: return await update.message.reply_text('📋 رزرو فعالی نداریم.')
    await update.message.reply_text('📋 رزروهای فعال:\n'+'\n'.join(f'#{r[0]} | {r[1]} {r[2]} | {r[3]} | {r[4] or "-"} | {r[5] or "-"} | {r[6]}' for r in rows))
async def cancel(update,context):
    if not context.args: return await update.message.reply_text('مثال: /لغو 12')
    c=connect(); cur=c.execute("UPDATE reservations SET status='cancelled' WHERE id=?",(context.args[0],)); c.commit(); c.close(); await update.message.reply_text('✅ لغو شد.' if cur.rowcount else 'رزرو پیدا نشد.')
async def cleanup(context): clean_holds()
def main():
    token=os.getenv('TELEGRAM_BOT_TOKEN')
    if not token: raise SystemExit('TELEGRAM_BOT_TOKEN تنظیم نشده است.')
    connect().close(); app=Application.builder().token(token).build()
    app.add_handler(CommandHandler('start',start)); app.add_handler(CommandHandler('رزروها',reservations)); app.add_handler(CommandHandler('لغو',cancel))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text))
    app.job_queue.run_repeating(cleanup,30,first=30)
    app.run_polling()
if __name__=='__main__': main()
