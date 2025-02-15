import os
import sqlite3
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# LINE API設定
line_bot_api = LineBotApi(os.getenv('UH9/CGcVZt4bnQKn3DX72uPH1i6AC0uKxSEWa2divzG7kyK3MfkOl1kc2K7bKhbbw0oIWnAk2K+/Mq/GJIq6RcBKBCPK025VD0S7ZPazgxcEI+fbA/ceLzDWorMGUFUPyaAyB/voU2GTKn23KUw8gwdB04t89/1O/w1cDnyilFU='))
handler = WebhookHandler(os.getenv('43ef859f4196c303b24b94f6052c4fa3'))


# データベース初期化
def init_db():
    conn = sqlite3.connect('alerts.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS alerts
                 (user_id TEXT, currency TEXT, target_price REAL)''')
    conn.commit()
    conn.close()


init_db()


# ビットバンクAPIから価格取得
def get_current_price(currency):
    url = f'https://public.bitbank.cc/{currency}_jpy/ticker'
    try:
        response = requests.get(url)
        data = response.json()
        return float(data['data']['last'])
    except Exception as e:
        print(f"Error fetching price: {e}")
        return None


# 価格チェック処理
def check_prices():
    conn = sqlite3.connect('alerts.db')
    c = conn.cursor()
    c.execute('SELECT * FROM alerts')
    alerts = c.fetchall()

    for user_id, currency, target_price in alerts:
        current_price = get_current_price(currency)
        if current_price and current_price >= target_price:
            message = f'{currency.upper()}が目標価格{target_price}円を達成！現在価格: {current_price}円'
            line_bot_api.push_message(user_id, TextSendMessage(text=message))
            c.execute('DELETE FROM alerts WHERE user_id=? AND currency=? AND target_price=?',
                      (user_id, currency, target_price))

    conn.commit()
    conn.close()


# スケジューラー起動
scheduler = BackgroundScheduler()
scheduler.add_job(check_prices, 'interval', minutes=1)
scheduler.start()


# LINE Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip().upper()

    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError

        currency, price = parts[0], float(parts[1])
        valid_currencies = ['BTC', 'ETH', 'XRP', 'XLM','FLR']  # 対応通貨

        if currency not in valid_currencies:
            raise ValueError

        conn = sqlite3.connect('alerts.db')
        c = conn.cursor()
        c.execute('INSERT INTO alerts VALUES (?, ?, ?)',
                  (user_id, currency.lower(), price))
        conn.commit()
        conn.close()

        reply = f'{currency}の価格アラートを{price}円で設定しました'

    except ValueError:
        reply = '不正な形式です。例：「BTC 5000000」のように入力してください\n対応通貨: BTC/ETH/XRP/LTC'

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)