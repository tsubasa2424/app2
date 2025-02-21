import os
import sqlite3
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, FollowEvent
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# 環境変数のロード
load_dotenv()

app = Flask(__name__)

# LINE API 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('UH9/CGcVZt4bnQKn3DX72uPH1i6AC0uKxSEWa2divzG7kyK3MfkOl1kc2K7bKhbbw0oIWnAk2K+/Mq/GJIq6RcBKBCPK025VD0S7ZPazgxcEI+fbA/ceLzDWorMGUFUPyaAyB/voU2GTKn23KUw8gwdB04t89/1O/w1cDnyilFU=')
LINE_CHANNEL_SECRET = os.getenv('43ef859f4196c303b24b94f6052c4fa3')

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("LINEの環境変数が設定されていません！")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# データベース初期化
def init_db():
    conn = sqlite3.connect('alerts.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
                    user_id TEXT, 
                    currency TEXT, 
                    target_price REAL)''')
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
        print(f"価格取得エラー: {e}")
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
            try:
                line_bot_api.push_message(user_id, TextSendMessage(text=message))
                c.execute('DELETE FROM alerts WHERE user_id=? AND currency=? AND target_price=?',
                          (user_id, currency, target_price))
            except Exception as e:
                print(f"LINE通知エラー: {e}")

    conn.commit()
    conn.close()


# スケジューラー起動
scheduler = BackgroundScheduler()
scheduler.add_job(check_prices, 'interval', minutes=1)
scheduler.start()


# LINE Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    print("Webhook受信:", body)  # デバッグ用ログ出力

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("署名エラー: チャネルアクセストークン/シークレットを確認してください。")
        abort(400)

    return 'OK'


# 友達追加時のガイドメッセージ
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    welcome_message = ("ご利用ありがとうございます！\n"
                       "仮想通貨の価格通知を設定するには、\n"
                       "『BTC 5000000』のように送信してください。\n"
                       "対応通貨: BTC/ETH/XRP/XLM/FLR")
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text=welcome_message))
    except Exception as e:
        print(f"フォロー時のメッセージ送信エラー: {e}")


# メッセージ受信処理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip().upper()

    try:
        parts = text.split()
        if len(parts) != 2:
            raise ValueError("入力形式エラー")

        currency, price = parts[0], float(parts[1])
        valid_currencies = ['BTC', 'ETH', 'XRP', 'XLM', 'FLR']

        if currency not in valid_currencies:
            raise ValueError("対応していない通貨")

        conn = sqlite3.connect('alerts.db')
        c = conn.cursor()
        c.execute('INSERT INTO alerts VALUES (?, ?, ?)', (user_id, currency.lower(), price))
        conn.commit()
        conn.close()

        reply = f'{currency}の価格アラートを{price}円で設定しました'
    except ValueError:
        reply = "不正な形式です。例：「BTC 5000000」のように入力してください\n対応通貨: BTC/ETH/XRP/XLM/FLR"

    try:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except Exception as e:
        print(f"返信メッセージ送信エラー: {e}")


# アプリ起動
if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    print(f"アプリ起動: ポート {port}")
    app.run(host='0.0.0.0', port=port)
