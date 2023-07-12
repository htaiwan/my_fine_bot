from datetime import datetime

import pandas as pd
import requests
from flask import Flask, request, abort
import os

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction)

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ['CHANNEL_ACCESS_TOKEN'])
handler = WebhookHandler(os.environ['CHANNEL_SECRET'])

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    event.message.text = event.message.text.lower()
    token = event.reply_token
    if event.message.text == '@基金':
        handle_funds_quick_reply_message(token)
    elif '@基金' in event.message.text:
        category = event.message.text.replace('@基金-', '')
        handle_best_funds_message(token, category)
    elif event.message.text == '@股票':
        handle_my_stocks_message(token)
    elif event.message.text == '@外幣':
        handle_interest_rate_quick_reply_message(token)
    elif '@利率' in event.message.text:
        currency = event.message.text.replace('@利率-', '')
        handle_interest_rate_message(token, currency)
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextMessage(text=event.message.text)
        )


def handle_funds_quick_reply_message(token):
    text_message = TextSendMessage(text='請選擇基金類別',
                                   quick_reply=QuickReply(
                                       items=[
                                           QuickReplyButton(action=MessageAction(label="拉丁美洲股票",
                                                                                 text="@基金-拉丁美洲股票")),
                                           QuickReplyButton(action=MessageAction(label="全球新興市場股票",
                                                                                 text="@基金-全球新興市場股票"))
                                       ])
                                   )
    line_bot_api.reply_message(token, text_message)


def handle_best_funds_message(token, category):
    group_ids = {
        '拉丁美洲股票': 'EUCA000524',
        '全球新興市場股票': 'EUCA000507'
    }

    group_id = group_ids[category]
    df = get_best_funds(group_id)
    message = '【{}優質基金】'.format(category)
    num = 1
    for index, row in df.head(3).iterrows():
        message += '\n\n第{}名\n{}\n六個月：{}\n一年：{}\n三年：{}'.format(num,
                                                                        index,
                                                                        row['六個月'],
                                                                        row['一年'],
                                                                        row['三年'])

        num += 1

    line_bot_api.reply_message(token, TextMessage(text=message))


def handle_my_stocks_message(token):
    df = get_daily_prices(datetime.today())
    if df is None:
        line_bot_api.reply_message(token, TextSendMessage(text='今日沒有收盤行情'))
        return None

    期初投入 = 0
    目前淨值 = 0
    my_stocks = {
        '1101': 30.00,
        '1102': 22.50,
        '1103': 14.10
    }
    message = '【我的股票】'

    for stock_id, buy_price in my_stocks.items():
        current_price = df.loc[stock_id, '收盤價'].item()

        期初投入 += buy_price
        目前淨值 += current_price

        message += '\n\n證券代號：{}\n買入{}｜目前{}'.format(stock_id,
                                                           buy_price,
                                                           current_price)

    message += '\n\n投入{}元\n目前{}元\n賺（賠）{}元\n報酬率 {}%'.format(
        round(期初投入 * 1000),
        round(目前淨值 * 1000),
        round((目前淨值 - 期初投入) * 1000),
        round((目前淨值 - 期初投入) / 期初投入 * 100, 2)
    )

    line_bot_api.reply_message(token, TextSendMessage(text=message))


def handle_interest_rate_quick_reply_message(token):
    text_message = TextSendMessage(text='請選擇幣別',
                                   quick_reply=QuickReply(items=[
                                       QuickReplyButton(action=MessageAction(label="美元(USD)", text="@利率-USD")),
                                       QuickReplyButton(action=MessageAction(label="人民幣(CNY)", text="@利率-CNY")),
                                       QuickReplyButton(action=MessageAction(label="澳幣(AUD)", text="@利率-AUD")),
                                       QuickReplyButton(action=MessageAction(label="港幣(HKD)", text="@利率-HKD")),
                                       QuickReplyButton(action=MessageAction(label="新加坡幣(SGD)", text="@利率-SGD"))
                                   ]))
    line_bot_api.reply_message(token, text_message)


def handle_interest_rate_message(token, currency):
    df = get_best_fc_interest_rate(currency)

    message = '【最佳{}利率】\n'.format(currency)

    for index, row in df.iterrows():
        message += '\n{}｜{}｜{}'.format(index, row['銀行'][0], row['利率'])

    line_bot_api.reply_message(token, TextSendMessage(text=message))


def get_best_funds(group_id):
    url = 'https://www.sitca.org.tw/ROC/Industry/IN2422.aspx?txtGROUPID={}'.format(group_id)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.108 Safari/537.36',
    }

    response = requests.get(url, headers=headers)

    # 整理表格
    df = pd.read_html(response.text)[7]
    df.drop([0, 2], axis=1, inplace=True)
    df.columns = df.iloc[1]
    df.drop([0, 1], inplace=True)
    df = df.set_index('基金名稱')
    df = df.apply(pd.to_numeric, errors='coerce')

    # 篩選出長中短期前段班的基金(分別以三年,一年,六個月為基準依序篩選)
    三年 = df.sort_values('三年', ascending=False).head(int(len(df) * 1 / 2))
    一年 = 三年.sort_values('一年', ascending=False).head(int(len(三年) * 1 / 2))
    六個月 = 一年.sort_values('六個月', ascending=False).head(int(len(一年) * 1 / 2))

    # 最後用 年化標準差 做排序，數字越小，波動越小(ascending=True)
    return 六個月.sort_values('年化標準差三年(原幣)', ascending=True)


def get_daily_prices(date):
    url = 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX'

    payloads = {
        'response': 'html',
        'data': date,
        'type': 'ALLBUT0999'
    }

    headers = {
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36'
    }

    response = requests.get(url, headers=headers, params=payloads)

    try:
        df = pd.read_html(response.text)[-1]
    except:
        return None

    # 目前欄位名稱有兩行，刪除第一行
    df.columns = df.columns.droplevel(0)

    # 移除不要的欄位名稱
    df.drop(['漲跌(+/-)'], axis=1, inplace=True)

    # 增加日期欄位，將date轉換成日期型態
    df['日期'] = pd.to_datetime(date)

    # 設定index
    df = df.set_index(['證券代號', '日期'])

    # 將內容都轉換成數字，無法轉換的內容就用nan表示
    df = df.apply(pd.to_numeric, errors='coerce')

    # 清除nan的資料
    df.drop(df[df['收盤價'].isnull()].index, inplace=True)

    return df


def get_best_fc_interest_rate(currency):
    合作金庫 = tcb_bank()
    玉山銀行 = esun_bank()
    台灣銀行 = get_taiwan_bank()

    banks = pd.concat([合作金庫, 玉山銀行, 台灣銀行], sort=False)
    # 重新排序
    banks = banks[['活期', '一週', '二週', '三週', '一個月', '三個月', '六個月', '九個月', '一年']]

    外幣利率 = banks.iloc[banks.index.get_level_values('幣別') == currency.upper()]

    外幣最高利率 = pd.DataFrame({
        '銀行': 外幣利率.idxmax(),
        '利率': 外幣利率.max()
    })

    return 外幣最高利率


def tcb_bank():
    url = 'https://www.tcb-bank.com.tw/finance_info/Pages/foreign_deposit_loans_rate.aspx'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.108 Safari/537.36',
    }
    response = requests.get(url=url, headers=headers)

    df = pd.read_html(response.text)[0]
    df.dropna(inplace=True)
    # 修改欄位名稱
    df.columns = ['幣別', '活期', '一週', '一個月', '三個月', '六個月', '九個月', '一年']
    # 新增欄位
    df['銀行'] = '合作金庫'
    # 修改幣別，只出現英文 美元 USD -> USD
    df['幣別'] = df['幣別'].str.extract('([A-Z]+)')
    df = df.set_index(['銀行', '幣別'])
    # 去除%分號
    df = df.apply(lambda s: s.str.replace('%', ''))
    # 轉成數字
    df = df.apply(pd.to_numeric, errors='coerce')

    return df


def esun_bank():
    url = 'https://www.esunbank.com.tw/bank/personal/deposit/rate/foreign/deposit-rate'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.108 Safari/537.36',
    }

    response = requests.get(url=url, headers=headers)

    df = pd.read_html(response.text)[1]

    df = df.drop([0, 1])

    df.columns = ['幣別', '活期', '一週', '二週', '三週', '一個月', '三個月', '六個月', '九個月', '一年']

    df['幣別'] = df['幣別'].str.extract('([A-Z]+)')
    df['銀行'] = '玉山銀行'

    df = df.set_index(['銀行', '幣別'])

    df = df.apply(pd.to_numeric, errors='coerce')

    return df


def get_taiwan_bank():
    url = 'https://rate.bot.com.tw/ir?Lang=zh-TW'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.108 Safari/537.36',
    }
    response = requests.get(url=url, headers=headers)

    df = pd.read_html(response.text)[0]

    df = df.drop(df.columns[[-1, -2]], axis=1)

    df.columns = ['幣別', '活期', '一週', '二週', '三週', '一個月', '三個月', '六個月', '九個月', '一年']

    df = df.drop(1)

    df['幣別'] = df['幣別'].str.extract('([A-Z]+)')
    df['銀行'] = '臺灣銀行'
    df = df.set_index(['銀行', '幣別'])

    df = df.apply(pd.to_numeric, errors='coerce')

    return df


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
    
#if __name__ == "__main__":
#    app.run()
#    app.run(port=5000, debug=True)
