import os
import telebot
import google.generativeai as genai
from dotenv import load_dotenv

# .env faylındakı gizli açarları sistemə yükləyirik
load_dotenv()

# Açarları dəyişənlərə mənimsədirik
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# Təhlükəsizlik yoxlanışı
if not TELEGRAM_TOKEN or not GEMINI_KEY:
    print("XƏTA: .env faylında parollar tapılmadı! Lütfən yoxlayın.")
    exit()

# Gemini AI-ı tənzimləyirik
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Telegram botu başladırıq
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Botun ilk əmri: /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    Xos_geldiniz = (
        "Salam! Mən sənin süni intellektli Treydinq Köməkçinizəm. 🤖📈\n\n"
        "Hazırda ilk təməl bağlantımız uğurla quruldu.\n"
        "Mənə hər hansı bir mesaj yaz, Gemini beynimlə cavablandırım!"
    )
    bot.reply_to(message, Xos_geldiniz)

# Gələn bütün mətn mesajlarını Gemini-yə göndərib cavab almaq hissəsi
@bot.message_handler(func=lambda message: True)
def echo_all(message):
    try:
        # İstifadəçinin yazdığı mesajı Gemini-yə göndəririk
        response = model.generate_content(message.text)
        
        # Gemini-dən gələn cavabı Teleqramda istifadəçiyə qaytarırıq
        bot.reply_to(message, response.text)
    except Exception as e:
        bot.reply_to(message, f"Xəta baş verdi: {e}")

# Botun 24 saat canlı qalması və mesajları dinləməsi üçün sonsuz dövr
print("Bot hazırda aktivdir və mesajları gözləyir...")
bot.infinity_polling()
