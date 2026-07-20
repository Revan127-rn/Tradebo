import telebot
from groq import Groq
import yfinance as yf
import json
import os
import random
import datetime
import threading
import time
import re
import sqlite3
import requests
from bs4 import BeautifulSoup
from flask import Flask

# --- KONFİQURASİYA VƏ ƏTRAF DƏYİŞƏNLƏRİ (ENV) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

BAZA_FAYLI = "ict_knowledge.json"
DB_FILE = "tradebo.db"
LESSONS_FILE = "lessons_learned.txt"
INITIAL_BALANCE = 10000.0  # Xəyali İlkin Balans ($)
TRADE_STAKE = 50.0         # Hər əməliyyata sabit daxil olunan məbləğ ($)

user_context = {}

# --- FLASK KEEP-ALIVE SERVERİ (24/7 Uptime Robot üçün) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Tradebo v3 Virtual Wallet & AI Research Server Aktivdir!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- SQLITE VERİLƏNLƏR BAZASI VƏ BALANS İDARƏSİ ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Əməliyyatlar Cədvəli
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            symbol TEXT,
            trade_type TEXT,
            saat TEXT,
            entry_price REAL,
            sl_price REAL,
            tp_price REAL,
            is_buy INTEGER,
            status TEXT,
            sebeb TEXT,
            pnl REAL DEFAULT 0.0,
            ders_cixarildi INTEGER DEFAULT 0
        )
    ''')
    # Balans və Mükafat Cədvəli
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallet (
            id INTEGER PRIMARY KEY,
            balance REAL,
            total_profit REAL,
            total_trades INTEGER,
            wins INTEGER,
            losses INTEGER
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM wallet")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO wallet (id, balance, total_profit, total_trades, wins, losses)
            VALUES (1, ?, 0.0, 0, 0, 0)
        ''', (INITIAL_BALANCE,))
        
    conn.commit()
    conn.close()

def get_wallet():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT balance, total_profit, total_trades, wins, losses FROM wallet WHERE id=1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "balance": row[0],
            "total_profit": row[1],
            "total_trades": row[2],
            "wins": row[3],
            "losses": row[4]
        }
    return {"balance": INITIAL_BALANCE, "total_profit": 0.0, "total_trades": 0, "wins": 0, "losses": 0}

def update_wallet_on_trade_close(pnl):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    wallet = get_wallet()
    
    new_balance = wallet["balance"] + pnl
    new_profit = wallet["total_profit"] + pnl
    new_trades = wallet["total_trades"] + 1
    new_wins = wallet["wins"] + (1 if pnl > 0 else 0)
    new_losses = wallet["losses"] + (1 if pnl < 0 else 0)
    
    cursor.execute('''
        UPDATE wallet 
        SET balance=?, total_profit=?, total_trades=?, wins=?, losses=?
        WHERE id=1
    ''', (new_balance, new_profit, new_trades, new_wins, new_losses))
    
    conn.commit()
    conn.close()

def save_trade_db(trade_data):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO trades 
        (id, symbol, trade_type, saat, entry_price, sl_price, tp_price, is_buy, status, sebeb, pnl, ders_cixarildi)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        str(trade_data["id"]),
        trade_data["symbol"],
        trade_data.get("trade_type", "USER"),
        trade_data["saat"],
        trade_data["entry_price"],
        trade_data["sl_price"],
        trade_data["tp_price"],
        1 if trade_data["is_buy"] else 0,
        trade_data["status"],
        trade_data["sebeb"],
        trade_data.get("pnl", 0.0),
        1 if trade_data.get("ders_cixarildi") else 0
    ))
    conn.commit()
    conn.close()

def get_trades_db(trade_type=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if trade_type:
        cursor.execute("SELECT * FROM trades WHERE trade_type=?", (trade_type,))
    else:
        cursor.execute("SELECT * FROM trades")
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "symbol": r[1],
            "trade_type": r[2],
            "saat": r[3],
            "entry_price": r[4],
            "sl_price": r[5],
            "tp_price": r[6],
            "is_buy": bool(r[7]),
            "status": r[8],
            "sebeb": r[9],
            "pnl": r[10],
            "ders_cixarildi": bool(r[11])
        })
    return result

# --- PIPS VƏ MÜKAFAT KALKULYATORU ---
def check_and_update_trades_db():
    trades = get_trades_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    for t in trades:
        if t["status"] == "Açıq":
            try:
                ticker = yf.Ticker(t["symbol"])
                df = ticker.history(period="1d", interval="1m")
                if df.empty:
                    continue
                current_price = df['Close'].iloc[-1]
                
                entry = t["entry_price"]
                sl = t["sl_price"]
                tp = t["tp_price"]
                is_buy = t["is_buy"]
                
                new_status = None
                pnl = 0.0
                
                # $50 Sabit Məbləğlə Hesablama
                if is_buy:
                    if current_price <= sl:
                        new_status = "🔴 SL Oldu"
                        ratio = (sl - entry) / entry
                        pnl = TRADE_STAKE * ratio
                    elif current_price >= tp:
                        new_status = "🟢 TP Oldu"
                        ratio = (tp - entry) / entry
                        pnl = TRADE_STAKE * ratio
                else:
                    if current_price >= sl:
                        new_status = "🔴 SL Oldu"
                        ratio = (entry - sl) / entry
                        pnl = TRADE_STAKE * ratio
                    elif current_price <= tp:
                        new_status = "🟢 TP Oldu"
                        ratio = (entry - tp) / entry
                        pnl = TRADE_STAKE * ratio
                        
                if new_status:
                    cursor.execute("UPDATE trades SET status=?, pnl=? WHERE id=?", (new_status, round(pnl, 2), t["id"]))
                    update_wallet_on_trade_close(round(pnl, 2))
            except Exception as e:
                print(f"Qiymət yeniləmə xətası: {e}")
                continue
                
    conn.commit()
    conn.close()

# --- JSON BAZASI İDARƏSİ VƏ ARAŞDIRMA SİSTEMİ ---
def safe_clean_json():
    """Strategiyaları silmədən json faylı təmizləyir va lazımsız dublikat/boş mətnləri kənarlaşdırır."""
    if not os.path.exists(BAZA_FAYLI):
        return
    with open(BAZA_FAYLI, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except:
            return

    clean_data = []
    seen = set()
    for item in data:
        text = item.strip()
        # English studies və ya lazımsız akademik mətnləri süzgəcdən keçir
        if "English Studies" in text or "ISSN " in text or "Bulgarian University" in text:
            continue
        if len(text) > 30 and text not in seen:
            seen.add(text)
            clean_data.append(text)

    with open(BAZA_FAYLI, "w", encoding="utf-8") as f:
        json.dump(clean_data, f, ensure_ascii=False, indent=2)

def append_new_strategy_to_json(new_knowledge):
    """Əsas strategiyanı silmədən internetdən öyrənilən yeni konsepsiyanı JSON-a əlavə edir."""
    safe_clean_json()
    if not os.path.exists(BAZA_FAYLI):
        data = []
    else:
        with open(BAZA_FAYLI, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except:
                data = []

    if new_knowledge not in data:
        data.append(new_knowledge)

    with open(BAZA_FAYLI, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def web_research_smc_concept(topic):
    """Google/DuckDuckGo və ya AI daxili bilikləri vasitəsilə təhlükəsiz yeni strategiya öyrənir."""
    search_summary = ""
    
    # 1-ci cəhd: duckduckgo_search kitabxanası dənənir
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(f"SMC trading {topic}", max_results=3))
            for r in results:
                search_summary += f"- {r.get('title', '')}: {r.get('body', '')}\n"
    except Exception:
        # 2-ci cəhd: Əgər duckduckgo_search yoxdursa və ya bloklanarsa HTML scraping dənənir
        try:
            url = f"https://html.duckduckgo.com/html/?q=SMC+trading+{topic.replace(' ', '+')}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            req = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(req.text, 'html.parser')
            results = [a.text for a in soup.find_all('a', class_='result__snippet')[:3]]
            search_summary = "\n".join(results) if results else ""
        except Exception:
            search_summary = ""

    # Əgər internet axtarışı ümumiyyətlə alınmazsa, AI daxili SMC məlumatı ilə əvəzləyir (Fallback)
    if not search_summary.strip():
        search_summary = f"SMC (Smart Money Concepts) core principles regarding {topic}"

    try:
        prompt = f"""İnternet/Daxili araşdırmadan SMC ({topic}) haqqında məlumatlar tapıldı:
{search_summary}
Bu məlumatı təhlil et və bota gələcəkdə istifadə etməsi üçün 3 cümləlik İNGİLİS dilində dəqiq SMC qaydası formalaşdır. Yalnız qaydanı qaytar."""

        res = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.2
        )
        new_rule = res.choices[0].message.content.strip()
        append_new_strategy_to_json(new_rule)
        return new_rule
    except Exception as e:
        return f"Araşdırma zamanı xəta: {e}"

def bazadan_ağıllı_ict_sec(axtaris_sozleri, max_chunks=30):
    safe_clean_json()
    if not os.path.exists(BAZA_FAYLI):
        return "Qeyd: Hələ heç bir strategiya öyrənilməyib."
    with open(BAZA_FAYLI, "r", encoding="utf-8") as f:
        chunks = json.load(f)
    sozler = [s.lower() for s in axtaris_sozleri.split()]
    skorlanan_chunks = []
    for chunk in chunks:
        score = 0
        chunk_lower = chunk.lower()
        for soz in sozler:
            if soz in chunk_lower:
                score += chunk_lower.count(soz) * 2
        if score > 0:
            skorlanan_chunks.append((score, chunk))
    skorlanan_chunks.sort(key=lambda x: x[0], reverse=True)
    en_yaxsilar = [chunk for score, chunk in skorlanan_chunks[:max_chunks]]
    if not en_yaxsilar:
        return "\n---\n".join(chunks[:max_chunks])
    return "\n---\n".join(en_yaxsilar)

def get_market_story_multi_tf(symbol, limit_15m=20, limit_1h=10):
    try:
        ticker = yf.Ticker(symbol)
        df_1h = ticker.history(period="1mo", interval="1h").tail(limit_1h)
        story_1h = f"[MAKRO 1h]\n"
        for index, row in df_1h.iterrows():
            story_1h += f"{index.strftime('%d/%m %H:%M')} H:{row['High']:.2f} L:{row['Low']:.2f} C:{row['Close']:.2f}\n"
        df_15m = ticker.history(period="5d", interval="15m").tail(limit_15m)
        story_15m = f"\n[MİKRO 15m]\n"
        for index, row in df_15m.iterrows():
            story_15m += f"{index.strftime('%d/%m %H:%M')} H:{row['High']:.2f} L:{row['Low']:.2f} C:{row['Close']:.2f}\n"
        return story_1h + story_15m
    except Exception as e:
        return f"Bazar datası xətası: {e}"

def extract_json(text):
    try:
        match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return json.loads(text)
    except:
        return None

# --- TELEGRAM MENYU VƏ ƏMR HƏNDLERLƏRİ ---
def set_bot_commands():
    """Telegram mesaj yazma hissəsində / yazdıda bütün əmrlərin avtomatik görünməsi üçün."""
    commands = [
        telebot.types.BotCommand("/analiz", "Paritə analizi et ($50 risk)"),
        telebot.types.BotCommand("/balans", "Virtual portfel və mükafatlar"),
        telebot.types.BotCommand("/history", "Son əməliyyat tarixçəsi"),
        telebot.types.BotCommand("/bilgi", "Əməliyyat detalını göstər (ID ilə)"),
        telebot.types.BotCommand("/arastir", "SMC konsepsiyası araşdır"),
        telebot.types.BotCommand("/parite", "Mövcud paritələr siyahısı"),
        telebot.types.BotCommand("/start", "Bota yenidən başla / Menyu")
    ]
    try:
        bot.set_my_commands(commands)
    except Exception as e:
        print(f"Komandalar menyuya əlavə edilərkən xəta: {e}")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    set_bot_commands()
    bot.reply_to(message, "👋 **Tradebo v3 (Virtual Wallet & AI Research)** aktivdir!\n\n/balans - Botun xəyali 10,000$ kapitalı və qazanc statistikası")

@bot.message_handler(commands=['balans'])
def show_balance(message):
    check_and_update_trades_db()
    w = get_wallet()
    win_rate = (w["wins"] / w["total_trades"] * 100) if w["total_trades"] > 0 else 0.0
    
    txt = (
        "🏆 **VİRTUAL PORTFEL VƏ MÜKAFAT MEXANİZMİ**\n\n"
        f"💵 **Cari Balans:** `{w['balance']:.2f}$`\n"
        f"📈 **Ümumi PnL (Qazanc/İtki):** `{w['total_profit']:+.2f}$`\n"
        f"🎯 **Hər Giriş Riski:** `50.00$`\n"
        f"📊 **Ümumi Əməliyyat:** `{w['total_trades']}`\n"
        f"🟢 **Qazanılan (TP):** `{w['wins']}`\n"
        f"🔴 **İtirilən (SL):** `{w['losses']}`\n"
        f"🔥 **Uğur Nisbəti (Win Rate):** `{win_rate:.1f}%`\n"
    )
    bot.reply_to(message, txt, parse_mode="Markdown")

@bot.message_handler(commands=['arastir'])
def handle_research(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "⚠️ İzləmək istədiyiniz mövzunu yazın. Nümunə: `/arastir FVG Order Block`", parse_mode="Markdown")
        return
    topic = args[1]
    bot.reply_to(message, f"🔎 **{topic}** haqqında internetdə araşdırma aparılır...")
    res = web_research_smc_concept(topic)
    bot.reply_to(message, f"🧠 **Yeni strategiya öyrənildi və JSON-a əlavə edildi:**\n\n`{res}`", parse_mode="Markdown")

@bot.message_handler(commands=['parite'])
def send_parite_guide(message):
    guide_text = (
        "📋 **Əsas Paritələr:**\n"
        "`/analiz XAUUSD=X` (Qızıl)\n"
        "`/analiz EURUSD=X` (Avro)\n"
        "`/analiz BTC-USD` (Bitcoin)\n"
        "`/analiz ETH-USD` (Ethereum)"
    )
    bot.reply_to(message, guide_text, parse_mode="Markdown")

@bot.message_handler(commands=['history'])
def show_history(message):
    bot.reply_to(message, "⏳ Açıq əməliyyatların vəziyyəti yoxlanılır...")
    check_and_update_trades_db()
    trades = get_trades_db()
    if not trades:
        bot.reply_to(message, "Hələ heç bir əməliyyat yoxdur.")
        return
        
    last_10 = trades[::-1][:10]
    cavab = "📚 **Son 10 Əməliyyat və Mükafat Tarixçəsi:**\n\n"
    for t in last_10:
        pnl_str = f" | PnL: `{t['pnl']:+.2f}$`" if t['status'] != "Açıq" else ""
        cavab += f"ID: `/bilgi {t['id']}` | {t['symbol']} | Saat: {t['saat']}\n"
        cavab += f"Giriş: {t['entry_price']} | SL: {t['sl_price']} | TP: {t['tp_price']}\n"
        cavab += f"Status: **{t['status']}**{pnl_str}\n"
        cavab += "----------\n"
        
    bot.reply_to(message, cavab, parse_mode="Markdown")

@bot.message_handler(commands=['bilgi'])
def trade_info(message):
    hisseler = message.text.split()
    if len(hisseler) < 2:
        bot.reply_to(message, "⚠️ İD nömrəsini daxil edin. Nümunə: `/bilgi 54321`", parse_mode="Markdown")
        return
        
    axtarilan_id = hisseler[1]
    check_and_update_trades_db()
    trades = get_trades_db()
    
    tapilan = next((t for t in trades if str(t["id"]) == str(axtarilan_id)), None)
    
    if tapilan:
        mesaj = (
            f"🔍 **Əməliyyat Detalları (ID: {tapilan['id']})**\n\n"
            f"**Paritə:** {tapilan['symbol']}\n"
            f"**Ticarət Tipi:** {tapilan['trade_type']}\n"
            f"**Tarix/Saat:** {tapilan['saat']}\n"
            f"**Qərar:** {'BUY 🟢' if tapilan['is_buy'] else 'SELL 🔴'}\n"
            f"**Giriş:** {tapilan['entry_price']}\n"
            f"**Stop Loss:** {tapilan['sl_price']}\n"
            f"**Take Profit:** {tapilan['tp_price']}\n"
            f"**Giriş Həcmi:** 50.00$\n"
            f"**Nəticə PnL:** {tapilan['pnl']:+.2f}$\n"
            f"**Status:** {tapilan['status']}\n\n"
            f"**Analiz Səbəbi:**\n{tapilan.get('sebeb', 'Səbəb qeyd olunmayıb')}"
        )
        try:
            bot.reply_to(message, mesaj, parse_mode="Markdown")
        except Exception:
            bot.reply_to(message, mesaj)
    else:
        bot.reply_to(message, "❌ Bu ID ilə əməliyyat tapılmadı.")

@bot.message_handler(commands=['analiz'])
def analyze_single_market(message):
    try:
        mesaj_hisseleri = message.text.split()
        if len(mesaj_hisseleri) < 2:
            bot.reply_to(message, "⚠️ Paritə adını qeyd edin. Nümunə: `/analiz XAUUSD=X`", parse_mode="Markdown")
            return
            
        symbol = mesaj_hisseleri[1].upper()
        check_and_update_trades_db()
        bot.reply_to(message, f"🕵️‍♂️ {symbol} üçün SMC analizi aparılır...")

        market_data = get_market_story_multi_tf(symbol)
        ict_bazasi = bazadan_ağıllı_ict_sec("mss choch orderblock liquidity fvg premium discount", max_chunks=30)
        
        trade_id = random.randint(10000, 99999)

        system_prompt = f"""Sən peşəkar SMC trading alqoritmisən.
[BİLİKLƏR]
{ict_bazasi}
[DATA]
{market_data}

JSON formatında cavab ver:
{{
  "id": "{trade_id}",
  "symbol": "{symbol}",
  "qerar": "BUY / SELL",
  "tovsiye_statusu": "Tövsiyə olunur / Riskli / Tövsiyə olunmur",
  "entry_price": 0.00,
  "tp_price": 0.00,
  "sl_price": 0.00,
  "is_buy": true,
  "yekun_institusional_hesabat": "Səbəb"
}}"""

        response = client.chat.completions.create(
            messages=[{"role": "system", "content": system_prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.15
        )
        
        ai_response = response.choices[0].message.content
        parsed_data = extract_json(ai_response)
        
        if parsed_data and parsed_data.get("tovsiye_statusu", "").startswith("Tövsiyə olunur"):
            yeni_emeliyyat = {
                "id": str(trade_id),
                "symbol": symbol,
                "trade_type": "USER",
                "saat": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                "entry_price": parsed_data.get("entry_price"),
                "sl_price": parsed_data.get("sl_price"),
                "tp_price": parsed_data.get("tp_price"),
                "is_buy": parsed_data.get("is_buy"),
                "status": "Açıq",
                "sebeb": parsed_data.get("yekun_institusional_hesabat"),
                "pnl": 0.0
            }
            save_trade_db(yeni_emeliyyat)
        
        clean_json_text = ai_response.replace("```json", "").replace("```", "").strip()
        cavab_mesaji = f"📊 **SMC Raportu (ID: `{trade_id}` | Risk: 50$):**\n```json\n{clean_json_text}\n```"
        
        try:
            bot.reply_to(message, cavab_mesaji, parse_mode="Markdown")
        except Exception:
            bot.reply_to(message, f"📊 SMC Raportu (ID: {trade_id}):\n\n{clean_json_text}")
        
    except Exception as e:
        bot.reply_to(message, f"Xəta baş verdi: {e}")

# --- AVTONOM ETH TRADER VƏ ÖYRƏNMƏ ---
def learn_from_trade(trade):
    prompt = f"""ETH-USD əməliyyatı bitti. Giriş: {trade['entry_price']}, SL: {trade['sl_price']}, TP: {trade['tp_price']}.
Səbəb: {trade['sebeb']} | Nəticə: {trade['status']} | PnL: {trade['pnl']}$.
SMC prinsipi ilə 2 cümləlik ingiliscə dərs çıxar."""
    try:
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.3
        )
        ders = response.choices[0].message.content
        with open(LESSONS_FILE, "a", encoding="utf-8") as f:
            f.write(f"Tarix: {trade['saat']} | Nəticə: {trade['status']} | Dərs: {ders}\n---\n")
    except:
        pass

def autonomous_eth_trader():
    symbol = "ETH-USD"
    while True:
        try:
            check_and_update_trades_db()
            trades = get_trades_db("AUTO_ETH")
            has_open_trade = any(t["status"] == "Açıq" for t in trades)
            
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            for t in trades:
                if t["status"] in ["🔴 SL Oldu", "🟢 TP Oldu"] and not t["ders_cixarildi"]:
                    learn_from_trade(t)
                    cursor.execute("UPDATE trades SET ders_cixarildi=1 WHERE id=?", (t["id"],))
            conn.commit()
            conn.close()

            if not has_open_trade:
                market_data = get_market_story_multi_tf(symbol)
                ict_bazasi = bazadan_ağıllı_ict_sec("mss choch orderblock fvg liquidity", max_chunks=30)
                trade_id = random.randint(10000, 99999)
                
                system_prompt = f"""Avtonom ETH trader. Yalnız 'Tövsiyə olunur' qərarları ver.
[BİLİK] {ict_bazasi}
[DATA] {market_data}
JSON: {{"id":"{trade_id}", "qerar":"BUY/SELL/HOLD", "tovsiye_statusu":"Tövsiyə olunur/Riskli", "entry_price":0.0, "tp_price":0.0, "sl_price":0.0, "is_buy":true, "yekun_institusional_hesabat":"Səbəb"}}"""
                
                response = client.chat.completions.create(
                    messages=[{"role": "system", "content": system_prompt}],
                    model="llama-3.3-70b-versatile",
                    temperature=0.15
                )
                
                parsed_data = extract_json(response.choices[0].message.content)
                if parsed_data and parsed_data.get("tovsiye_statusu", "").startswith("Tövsiyə olunur"):
                    yeni_emeliyyat = {
                        "id": str(trade_id),
                        "symbol": symbol,
                        "trade_type": "AUTO_ETH",
                        "saat": datetime.datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "entry_price": parsed_data.get("entry_price"),
                        "sl_price": parsed_data.get("sl_price"),
                        "tp_price": parsed_data.get("tp_price"),
                        "is_buy": parsed_data.get("is_buy"),
                        "status": "Açıq",
                        "sebeb": parsed_data.get("yekun_institusional_hesabat"),
                        "pnl": 0.0,
                        "ders_cixarildi": False
                    }
                    save_trade_db(yeni_emeliyyat)
                    print(f"🤖 Auto ETH Trade Açıldı! ID: {trade_id} (Stake: 50$)")
            
        except Exception as e:
            print(f"Avtonom bot xətası: {e}")
            
        time.sleep(900)

# --- SİSTEMİN BAŞLADILMASI ---
if __name__ == "__main__":
    print("🚀 Tradebo v3 Virtual Wallet & AI Server Başladılır...")
    
    init_db()
    safe_clean_json()
    set_bot_commands()  # Bot açılan kimi / düymələrini Telegram menyusuna göndərir
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    eth_thread = threading.Thread(target=autonomous_eth_trader, daemon=True)
    eth_thread.start()
    
    bot.infinity_polling()
