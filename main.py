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
from flask import Flask

# --- KONFİQURASİYA VƏ ƏTRAF DƏYİŞƏNLƏRİ (ENV) ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")


bot = telebot.TeleBot(BOT_TOKEN)
client = Groq(api_key=GROQ_API_KEY)

BAZA_FAYLI = "ict_knowledge.json"
DB_FILE = "tradebo.db"
LESSONS_FILE = "lessons_learned.txt"

user_context = {}

# --- FLASK KEEP-ALIVE SERVERİ (24/7 Uptime Robot üçün) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Tradebo v2 Buludda 24/7 Aktivdir!"

def run_flask():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

# --- SQLITE VERİLƏNLƏR BAZASI FUNKSİYALARI ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
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
            ders_cixarildi INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def save_trade_db(trade_data):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO trades 
        (id, symbol, trade_type, saat, entry_price, sl_price, tp_price, is_buy, status, sebeb, ders_cixarildi)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            "ders_cixarildi": bool(r[10])
        })
    return result

def check_and_update_trades_db():
    trades = get_trades_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    for t in trades:
        if t["status"] == "Açıq":
            try:
                ticker = yf.Ticker(t["symbol"])
                current_price = ticker.history(period="1d", interval="1m")['Close'].iloc[-1]
                
                new_status = None
                if t["is_buy"]:
                    if current_price <= t["sl_price"]:
                        new_status = "🔴 SL Oldu"
                    elif current_price >= t["tp_price"]:
                        new_status = "🟢 TP Oldu"
                else:
                    if current_price >= t["sl_price"]:
                        new_status = "🔴 SL Oldu"
                    elif current_price <= t["tp_price"]:
                        new_status = "🟢 TP Oldu"
                        
                if new_status:
                    cursor.execute("UPDATE trades SET status=? WHERE id=?", (new_status, t["id"]))
            except:
                continue
                
    conn.commit()
    conn.close()

# --- SMC VƏ MARKET DATA FUNKSİYALARI ---
def bazadan_ağıllı_ict_sec(axtaris_sozleri, max_chunks=30):
    if not os.path.exists(BAZA_FAYLI):
        return "Qeyd: Hələ heç bir strategiya PDF-i öyrənilməyib."
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

# --- TELEGRAM COMMAND HANDLERS ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.set_my_commands([
        telebot.types.BotCommand("/analiz", "Yeni paritə analizi et"),
        telebot.types.BotCommand("/history", "Son 10 əməliyyata bax"),
        telebot.types.BotCommand("/parite", "Paritə siyahısını gör"),
    ])
    bot.reply_to(message, "👋 Tradebo v2 (24/7 Cloud Version) aktivdir!")

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
    bot.reply_to(message, "⏳ Açıq əməliyyatların cari vəziyyəti yoxlanılır...")
    check_and_update_trades_db()
    trades = get_trades_db()
    if not trades:
        bot.reply_to(message, "Hələ heç bir əməliyyat arxivə əlavə edilməyib.")
        return
        
    last_10 = trades[::-1][:10]
    cavab = "📚 **Son 10 Əməliyyat Tarixçəsi (SQLite):**\n\n"
    for t in last_10:
        cavab += f"ID: `/bilgi {t['id']}` | {t['symbol']} | Saat: {t['saat']}\n"
        cavab += f"Giriş: {t['entry_price']} | SL: {t['sl_price']} | TP: {t['tp_price']}\n"
        cavab += f"Status: **{t['status']}**\n"
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
            f"**Status:** {tapilan['status']}\n\n"
            f"**Analiz Xülasəsi:**\n_{tapilan.get('sebeb', 'Səbəb qeyd olunmayıb')}_"
        )
        bot.reply_to(message, mesaj, parse_mode="Markdown")
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
        bot.reply_to(message, f"🕵️‍♂️ {symbol} üçün SMC analizi hazırlanır...")

        market_data = get_market_story_multi_tf(symbol)
        ict_bazasi = bazadan_ağıllı_ict_sec("mss choch orderblock liquidity fvg premium discount", max_chunks=30)
        
        trade_id = random.randint(10000, 99999)

        system_prompt = f"""Sən peşəkar SMC trading alqoritmisən. Bütün rəqəmləri dəqiq ver.
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
                "sebeb": parsed_data.get("yekun_institusional_hesabat")
            }
            save_trade_db(yeni_emeliyyat)
        
        user_context[message.chat.id] = {
            "symbol": symbol,
            "market_data": market_data,
            "last_analysis": ai_response
        }
        
        bot.reply_to(message, f"📊 **SMC Raportu (ID: `{trade_id}`):**\n```json\n{ai_response}\n```", parse_mode="Markdown")
        
    except Exception as e:
        bot.reply_to(message, f"Xəta baş verdi: {e}")

# --- AVTONOM ETH TRADER VƏ SELF-LEARNING ---
def learn_from_trade(trade):
    prompt = f"""ETH-USD əməliyyatı nəticələndi. Giriş: {trade['entry_price']}, SL: {trade['sl_price']}, TP: {trade['tp_price']}.
Səbəb: {trade['sebeb']} | Nəticə: {trade['status']}.
SMC prinsipi ilə 2 cümləlik dərs çıxar."""
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
            
            # Dərs çıxarma
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            for t in trades:
                if t["status"] in ["🔴 SL Oldu", "🟢 TP Oldu"] and not t["ders_cixarildi"]:
                    learn_from_trade(t)
                    cursor.execute("UPDATE trades SET ders_cixarildi=1 WHERE id=?", (t["id"],))
            conn.commit()
            conn.close()

            # Yeni əməliyyat yoxlanışı
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
                        "ders_cixarildi": False
                    }
                    save_trade_db(yeni_emeliyyat)
                    print(f"🤖 Auto ETH Trade Açıldı! ID: {trade_id}")
            
        except Exception as e:
            print(f"Avtonom bot xətası: {e}")
            
        time.sleep(900) # 15 dəqiqə

# --- SİSTEMİN BAŞLADILMASI ---
if __name__ == "__main__":
    print("🚀 Tradebo v2 Bulud Sistemi Başladılır...")
    
    # 1. SQLite Bazasını Yarat
    init_db()
    
    # 2. Flask Keep-Alive Serverini işə sal
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Keep-Alive Veb Server Aktivdir.")
    
    # 3. Auto ETH Trader Başlat
    eth_thread = threading.Thread(target=autonomous_eth_trader, daemon=True)
    eth_thread.start()
    print("📈 Avtonom ETH alqoritmi işləyir.")
    
    # 4. Telegram Bot
    bot.infinity_polling()
