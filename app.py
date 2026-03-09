import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import datetime
import time
import json
import gspread
from google.oauth2.service_account import Credentials

# --- 1. 系統設定與 Google Sheets 連線 ---
st.set_page_config(page_title="金融股動態決策系統", layout="wide")

# 原本的金融股清單
stock_list = {
    "2880.TW": "華南金", "2886.TW": "兆豐金", "2892.TW": "第一金",
    "5880.TW": "合庫金", "2834.TW": "臺企銀", "2887.TW": "台新新光金",
    "2890.TW": "永豐金", "2885.TW": "元大金", "2883.TW": "凱基金"
}

# 🟢 新增：將 ETF 加入清單
etf_list = {
    "0056.TW": "元大高股息", "00713.TW": "元大台灣高息低波", "00919.TW": "群益台灣精選高息",
    "00878.TW": "國泰永續高股息", "00934.TW": "中信成長高股息", "00929.TW": "復華台灣科技優息",
    "00940.TW": "元大台灣價值高息"
}
# 🟢 新增：合併金融股與 ETF，作為庫存與側邊欄的總選單
all_targets = {**stock_list, **etf_list}

etf_base_data = [
    {"代號名稱": "0056 元大高股息", "symbol": "0056.TW", "基準股利": "3.23 元 (3年平均)", "合理價_6": 53.8, "便宜價_8": 40.4, "股災價_10": 32.3, "預設價格": 37.75},
    {"代號名稱": "00713 元大台灣高息低波", "symbol": "00713.TW", "基準股利": "4.13 元 (3年平均)", "合理價_6": 68.8, "便宜價_8": 51.6, "股災價_10": 41.3, "預設價格": 51.95},
    {"代號名稱": "00919 群益台灣精選高息", "symbol": "00919.TW", "基準股利": "2.44 元 (3年平均)", "合理價_6": 40.7, "便宜價_8": 30.5, "股災價_10": 24.4, "預設價格": 23.49},
    {"代號名稱": "00878 國泰永續高股息", "symbol": "00878.TW", "基準股利": "1.67 元 (3年平均)", "合理價_6": 27.8, "便宜價_8": 20.9, "股災價_10": 16.7, "預設價格": 22.07},
    {"代號名稱": "00934 中信成長高股息", "symbol": "00934.TW", "基準股利": "1.68 元 (年化推估)", "合理價_6": 28.0, "便宜價_8": 21.0, "股災價_10": 16.8, "預設價格": 21.11},
    {"代號名稱": "00929 復華台灣科技優息", "symbol": "00929.TW", "基準股利": "1.32 元 (年化推估)", "合理價_6": 22.0, "便宜價_8": 16.5, "股災價_10": 13.2, "預設價格": 18.69},
    {"代號名稱": "00940 元大台灣價值高息", "symbol": "00940.TW", "基準股利": "0.48 元 (年化推估)", "合理價_6": 8.0, "便宜價_8": 6.0, "股災價_10": 4.8, "預設價格": 9.45},
]

# 🟢 初始化 Google Sheets 連線
@st.cache_resource
def init_gsheets():
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds_info = json.loads(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        client = gspread.authorize(creds)
        sheet_url = st.secrets["sheet_url"]
        return client.open_by_url(sheet_url)
    except Exception as e:
        st.error(f"⚠️ Google Sheets 連線失敗，請檢查 Secrets 設定。錯誤訊息: {e}")
        return None

sh = init_gsheets()

if sh:
    try:
        ws_portfolio = sh.worksheet("Portfolio")
        ws_history = sh.worksheet("History")
    except:
        st.error("⚠️ 找不到 'Portfolio' 或 'History' 分頁，請確保您在試算表中有建立這兩個工作表！")
        st.stop()

    # 從雲端讀取庫存
    portfolio_records = ws_portfolio.get_all_records()
    df_portfolio = pd.DataFrame(portfolio_records)
    if df_portfolio.empty:
        df_portfolio = pd.DataFrame(columns=["股票代號", "買進價格", "持有張數"])

    # 從雲端讀取歷史
    history_records = ws_history.get_all_records()
    df_history = pd.DataFrame(history_records)
    if df_history.empty:
        df_history = pd.DataFrame(columns=["股票代號", "買進價格", "賣出價格", "賣出張數"])
else:
    st.stop()

# 🟢 寫入雲端的函式
def save_df_to_ws(df, ws):
    ws.clear()
    if not df.empty:
        ws.update(values=[df.columns.values.tolist()] + df.values.tolist(), range_name='A1')
    else:
        ws.update(values=[df.columns.values.tolist()], range_name='A1')


# --- 2. 自動化爬蟲引擎 ---
def get_real_time_price_from_yahoo(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        price = data['chart']['result'][0]['meta']['regularMarketPrice']
        return round(price, 2)
    except:
        return None

@st.cache_data(ttl=30)  
def fetch_stock_intelligence(symbol):
    stock_id = symbol.replace('.TW', '')
    stock = yf.Ticker(symbol)
    
    hist = stock.history(period="1y")
    if hist.empty: return None

    current_price = get_real_time_price_from_yahoo(symbol)
    if current_price is None:
        current_price = round(hist['Close'].iloc[-1], 2)

    ma20 = round(hist['Close'].tail(20).mean(), 2)
    ma240 = round(hist['Close'].tail(240).mean(), 2)

    try:
        bps = stock.info.get('bookValue', 15.0)
        if bps is None: bps = 15.0
    except:
        bps = 15.0

    start_date = (datetime.datetime.now() - datetime.timedelta(days=700)).strftime('%Y-%m-%d')
    finmind_url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockDividend", "data_id": stock_id, "start_date": start_date}

    cash_div, stock_div = 0.0, 0.0
    try:
        response = requests.get(finmind_url, params=params, timeout=10)
        data = response.json().get('data', [])
        if data:
            data = sorted(data, key=lambda x: x['date'])
            latest_dividend = data[-1]
            cash_keys = ['CashEarningsDistribution', 'CashStatutoryReserveDistribution', 'CashDividend', 'TotalCash']
            stock_keys = ['StockEarningsDistribution', 'StockStatutoryReserveDistribution', 'StockDividend', 'TotalStock']
            cash_div = sum(float(latest_dividend.get(k) or 0.0) for k in cash_keys if k in latest_dividend)
            stock_div = sum(float(latest_dividend.get(k) or 0.0) for k in stock_keys if k in latest_dividend)
    except Exception as e:
        pass

    return {
        "current_price": current_price,
        "ma20": ma20,
        "ma240": ma240,
        "bps": round(bps, 2),
        "cash_div": round(cash_div, 2),
        "stock_div": round(stock_div, 2)
    }

@st.cache_data(ttl=30)
def fetch_live_price(symbol, default_price):
    live_price = get_real_time_price_from_yahoo(symbol)
    if live_price is not None:
        return live_price
    try:
        return round(yf.Ticker(symbol).fast_info['last_price'], 2)
    except:
        return default_price


# --- 3. 側邊欄：輸入區 ---
st.sidebar.header("⚙️ 雲端庫存與交易紀錄")
action_type = st.sidebar.radio("請選擇操作：", ["➕ 更新持有庫存", "💰 紀錄已賣出標的"])
st.sidebar.markdown("---")

# 🟢 這裡修改成使用 all_targets，讓選單包含 ETF
input_symbol = st.sidebar.selectbox("選擇標的", list(all_targets.keys()), format_func=lambda x: f"{x} {all_targets[x]}")

if action_type == "➕ 更新持有庫存":
    input_buy_price = st.sidebar.number_input("平均買進價格 (元)", min_value=0.0, value=20.0, step=0.05)
    input_shares = st.sidebar.number_input("目前持有張數", min_value=1, value=1, step=1)
    if st.sidebar.button("確認存入雲端庫存"):
        if input_symbol in df_portfolio["股票代號"].values:
            df_portfolio.loc[df_portfolio["股票代號"] == input_symbol, ["買進價格", "持有張數"]] = [input_buy_price, input_shares]
        else:
            new_row = pd.DataFrame([{"股票代號": input_symbol, "買進價格": input_buy_price, "持有張數": input_shares}])
            df_portfolio = pd.concat([df_portfolio, new_row], ignore_index=True)
        # 同步寫入 Google Sheets
        save_df_to_ws(df_portfolio, ws_portfolio)
        # 🟢 這裡也修改成 all_targets
        st.sidebar.success(f"☁️ {all_targets[input_symbol]} 持股已同步至雲端！")

elif action_type == "💰 紀錄已賣出標的":
    input_buy_price = st.sidebar.number_input("當時買進價格 (元)", min_value=0.0, value=20.0, step=0.05)
    input_sell_price = st.sidebar.number_input("實際賣出價格 (元)", min_value=0.0, value=25.0, step=0.05)
    input_sell_shares = st.sidebar.number_input("賣出張數", min_value=1, value=1, step=1)
    if st.sidebar.button("確認寫入歷史紀錄"):
        new_row = pd.DataFrame([{"股票代號": input_symbol, "買進價格": input_buy_price, "賣出價格": input_sell_price, "賣出張數": input_sell_shares}])
        df_history = pd.concat([df_history, new_row], ignore_index=True)
        save_df_to_ws(df_history, ws_history)
        
        if input_symbol in df_portfolio["股票代號"].values:
            current_shares = df_portfolio.loc[df_portfolio["股票代號"] == input_symbol, "持有張數"].values[0]
            new_shares = current_shares - input_sell_shares
            if new_shares > 0:
                df_portfolio.loc[df_portfolio["股票代號"] == input_symbol, "持有張數"] = new_shares
            else:
                df_portfolio = df_portfolio[df_portfolio["股票代號"] != input_symbol]
            save_df_to_ws(df_portfolio, ws_portfolio)
        st.sidebar.success(f"☁️ 已記錄獲利並同步雲端！")

# --- 4. 主畫面：三頁面架構 ---
st.title("📈 金融股 API 雙引擎決策系統")
# 🟢 強制轉換成台灣時間 (UTC+8)
tw_tz = datetime.timezone(datetime.timedelta(hours=8))
current_time = datetime.datetime.now(tw_tz).strftime("%Y-%m-%d %H:%M:%S")
st.markdown(f"**⏱️ 資料最後更新時間：** `{current_time}`")

tab1, tab2, tab3 = st.tabs(["⚡ 買進決策 (大盤掃描 & 雙指標接回)", "📊 賣出決策 (庫存與停利)", "🎯 高股息 ETF 監控"])

# ==========================================
# 標籤頁 1：買進決策 (只掃描金融股)
# ==========================================
with tab1:
    st.markdown("### 🔍 每日尋找買點：結合基本面與【歷史折價5% + 20MA】雙指標")
    overview_data = []

    progress_bar = st.progress(0)
    for i, (symbol, name) in enumerate(stock_list.items()):
        intel = fetch_stock_intelligence(symbol)
        if not intel: continue

        current_price = intel['current_price']
        ma20 = intel['ma20']

        total_div = intel['cash_div'] + (intel['stock_div'] / 10 * current_price)
        model1_cheap = round(total_div / 0.06, 2) if total_div > 0 else 0
        pass1 = "✅" if current_price <= model1_cheap and model1_cheap > 0 else "❌"
        model2_cheap = round(intel['bps'] * 1.15, 2)
        pass2 = "✅" if current_price <= model2_cheap else "❌"
        pass3 = "✅" if current_price <= intel['ma240'] else "❌"

        buy_score = sum([current_price <= model1_cheap, current_price <= model2_cheap, current_price <= intel['ma240']])
        if buy_score == 3:
            signal = "🔥 強烈買進"
        elif buy_score == 2:
            signal = "🟢 建議建倉"
        elif buy_score == 1:
            signal = "🔵 分批佈局"
        else:
            signal = "🟡 偏貴觀望"

        past_sell_str = "-"
        radar_signal = "-"
        diff_ma20 = round(((current_price - ma20) / ma20) * 100, 2)

        if not df_history.empty and symbol in df_history["股票代號"].values:
            latest_sell = df_history[df_history["股票代號"] == symbol].iloc[-1]
            past_sell = latest_sell["賣出價格"]
            past_sell_str = f"{past_sell} 元"

            discount_pct = round(((past_sell - current_price) / past_sell) * 100, 2)
            is_discounted = discount_pct >= 5.0
            is_near_ma20 = diff_ma20 <= 2.0

            if is_discounted and is_near_ma20:
                radar_signal = f"🔥 雙指標達成! (折價{discount_pct}%+靠月線) 強烈接回"
            elif is_discounted:
                radar_signal = f"🟢 已折價{discount_pct}% (但偏離月線+{diff_ma20}%) 考慮建倉"
            elif is_near_ma20:
                radar_signal = f"🔵 靠近月線 (但折價僅{discount_pct}%) 分批佈局"
            else:
                radar_signal = f"🟡 未達5%折價且偏離月線 (+{diff_ma20}%)"
        else:
            radar_signal = f"⚪ 無賣出紀錄 (距月線 {diff_ma20}%)"

        overview_data.append({
            "股名": f"{name} ({symbol.replace('.TW', '')})",
            "最新股價": current_price,
            "殖利便宜價": f"{model1_cheap} {pass1}",
            "淨值便宜價": f"{model2_cheap} {pass2}",
            "年線": f"{intel['ma240']} {pass3}",
            "基本面判定": signal,
            "歷史賣出價": past_sell_str,
            "雙指標雷達": radar_signal
        })
        progress_bar.progress((i + 1) / len(stock_list))

    progress_bar.empty()
    if overview_data:
        st.dataframe(pd.DataFrame(overview_data), use_container_width=True, hide_index=True)

# ==========================================
# 標籤頁 2：賣出決策
# ==========================================
with tab2:
    if not df_portfolio.empty:
        for index, row in df_portfolio.iterrows():
            symbol = row["股票代號"]
            buy_price = row["買進價格"]
            shares = row["持有張數"]
            # 🟢 這裡修改成使用 all_targets，這樣 ETF 才能抓到名字
            stock_name = all_targets.get(symbol, symbol)

            intel = fetch_stock_intelligence(symbol)
            if not intel: continue

            current_price = intel['current_price']
            profit_pct = round(((current_price - buy_price) / buy_price) * 100, 2)
            profit_amount = round((current_price - buy_price) * shares * 1000)
            target_8pct = round(buy_price * 1.08, 2)

            total_div_value = intel['cash_div'] + (intel['stock_div'] / 10 * current_price)
            expensive_price_4pct = round(total_div_value / 0.04, 2) if total_div_value > 0 else current_price

            is_profit_reached = profit_pct >= 8.0
            is_price_expensive = current_price >= expensive_price_4pct and total_div_value > 0

            if is_profit_reached and is_price_expensive:
                card_color = "#ffcccc"
                signal_text = f"🚨 雙重賣訊達標！獲利達 {profit_pct}% 且進入昂貴區，強烈建議獲利了結 💰"
            elif is_profit_reached:
                card_color = "#d9ead3"
                signal_text = f"🟢 獲利已達 {profit_pct}%！尚未變貴可續抱讓獲利奔跑 🏃‍♂️"
            elif is_price_expensive:
                card_color = "#fff0b3"
                signal_text = f"🟡 偏貴提醒：已達 4% 昂貴價 ({expensive_price_4pct}元)，留意回檔風險。"
            else:
                card_color = "#f9f9f9"
                signal_text = "🛡️ 安全區間：持續抱緊，等待雙指標達標。"

            profit_color = "#d32f2f" if profit_pct > 0 else ("#388e3c" if profit_pct < 0 else "#333333")
            
            st.markdown(f"""
            <div style='background-color: {card_color}; padding: 12px 18px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #ccc; color: #222;'>
                <div style='font-size: 16px; font-weight: 700; margin-bottom: 8px;'>{stock_name} ({symbol.replace('.TW', '')}) | {signal_text}</div>
                <div style='display: flex; flex-wrap: wrap; gap: 20px; font-size: 15px;'>
                    <div>📥 買價：<b>{buy_price}</b></div>
                    <div>📦 張數：<b>{shares}</b></div>
                    <div>📈 現價：<b>{current_price}</b> (<span style='color: {profit_color}; font-weight: bold;'>{profit_pct}%</span>)</div>
                    <div>💰 損益：<b style='color: {profit_color};'>{profit_amount} 元</b></div>
                    <div>🎯 8%停利：<b>{target_8pct}</b></div>
                    <div>🚨 4%警戒：<b>{expensive_price_4pct}</b></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("👈 您的庫存目前為空。請從左側邊欄輸入持股資料，或到「買進決策」尋找標的！")

# ==========================================
# 標籤頁 3：高股息 ETF 監控表
# ==========================================
with tab3:
    st.markdown("### 🎯 台灣高股息 ETF 估價位階監控表")
    st.markdown("基於圖片設定之殖利率區間：6% (合理)、8% (便宜)、10% (股災)")
    
    etf_display_data = []
    
    etf_prog = st.progress(0)
    for i, etf in enumerate(etf_base_data):
        live_price = fetch_live_price(etf["symbol"], etf["預設價格"])
        
        status = ""
        if live_price <= etf["股災價_10"]:
            status = "🔥 股災價區間 (<10%)"
        elif live_price <= etf["便宜價_8"]:
            status = "🟢 便宜價區間 (<8%)"
        elif live_price <= etf["合理價_6"]:
            status = "🔵 合理價區間 (<6%)"
        else:
            status = "🟡 昂貴偏高 (>6%)"

        etf_display_data.append({
            "代號名稱": etf["代號名稱"],
            "基準股利": etf["基準股利"],
            "6% 合理價": f"{etf['合理價_6']} 元",
            "8% 便宜價": f"{etf['便宜價_8']} 元",
            "10% 股災價": f"{etf['股災價_10']} 元",
            "(即時) 價格": f"{live_price} 元",
            "位階判定": status
        })
        etf_prog.progress((i + 1) / len(etf_base_data))
    
    etf_prog.empty()
    st.dataframe(pd.DataFrame(etf_display_data), use_container_width=True, hide_index=True)
