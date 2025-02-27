import os
import sqlite3
import requests
from flask import Flask, request, abort
from linebot.v3.messaging import LineBotApi
from linebot.v3.webhook import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import TextSendMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# 環境変数のロード
load_dotenv()

app = Flask(__name__)

# LINE API 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("LINEの環境変数が設定されていません！")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# データベース初期化
def init_db():
    with sqlite3.connect('alerts.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS alerts (
                        user_id TEXT, 
                        currency TEXT, 
                        target_price REAL)''')
        conn.commit()

init_db()

# ビットバンクAPIから価格取得
def get_current_price(currency):
    url = f'https://public.bitbank.cc/{currency}_jpy/ticker'
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()  # HTTPエラーがあれば例外を発生
        data = response.json()
        return float(data['data']['last'])
    except requests.RequestException as e:
        print(f"価格取得エラー: {e}")
        return None

# データベースからアラートを取得
def fetch_alerts():
    with sqlite3.connect('alerts.db') as conn:
        c = conn.cursor()
        c.execute('SELECT user_id, currency, target_price FROM alerts')
        return c.fetchall()

# 価格チェック & 通知送信
def check_prices():
    alerts = fetch_alerts()
    for user_id, currency, target_price in alerts:
        current_price = get_current_price(currency)
        if current_price and current_price >= target_price:
            message = f'{currency.upper()}が目標価格{target_price}円を達成！現在価格: {current_price}円'
            send_alert(user_id, message)
            with sqlite3.connect('alerts.db') as conn:
                c = conn.cursor()
                c.execute('DELETE FROM alerts WHERE user_id=? AND currency=? AND target_price=?',
                          (user_id, currency, target_price))
                conn.commit()

# LINE通知送信処理
def send_alert(user_id, message):
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text=message))
    except Exception as e:
        print(f"LINE通知エラー: {e}")

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
    send_alert(user_id, welcome_message)

# メッセージ受信処理
@handler.add(MessageEvent, message=TextMessageContent)
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

        with sqlite3.connect('alerts.db') as conn:
            c = conn.cursor()
            c.execute('INSERT INTO alerts VALUES (?, ?, ?)', (user_id, currency.lower(), price))
            conn.commit()

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
    try:
        app.run(host='0.0.0.0', port=port)
    except KeyboardInterrupt:
        print("アプリ終了: スケジューラー停止")
        scheduler.shutdown()
