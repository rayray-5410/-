import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
import sqlite3
import hashlib
import google.generativeai as genai

# ================= 網頁基礎設定 =================
st.set_page_config(page_title="全能金融戰情室", layout="wide", page_icon="📈")

# 🔑 【請在這裡貼上你的 Gemini API Key】
GEMINI_API_KEY = "YOUR_API_KEY_HERE"

# ================= 🛡️ 輕量級資料庫與資安系統 =================
# 建立/連線到 SQLite 資料庫
conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT, password TEXT)')
conn.commit()

# 密碼雜湊加密 (保護資安)
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return hashed_text
    return False

def add_user(username, password):
    c.execute('INSERT INTO users (username, password) VALUES (?,?)', (username, make_hashes(password)))
    conn.commit()

def login_user(username, password):
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, make_hashes(password)))
    return c.fetchall()

# 初始化 Session State (記憶登入狀態)
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ""

# ================= 🚪 登入與註冊介面 =================
if not st.session_state['logged_in']:
    st.title("🔐 歡迎來到 AI 跨市場金融戰情室")
    st.markdown("請先登入或註冊以啟用專屬分析功能。")
    
    menu = ["登入", "註冊新帳號"]
    choice = st.selectbox("選擇操作", menu)

    if choice == "登入":
        username = st.text_input("帳號 (使用者名稱)")
        password = st.text_input("密碼", type='password')
        if st.button("登入系統"):
            result = login_user(username, password)
            if result:
                st.success(f"歡迎回來，{username}！即將為您載入戰情室...")
                st.session_state['logged_in'] = True
                st.session_state['username'] = username
                st.rerun() # 重新整理網頁載入主程式
            else:
                st.error("❌ 帳號或密碼錯誤，請重試！")

    elif choice == "註冊新帳號":
        new_user = st.text_input("設定新帳號")
        new_password = st.text_input("設定新密碼", type='password')
        if st.button("建立帳號"):
            if new_user and new_password:
                c.execute('SELECT * FROM users WHERE username = ?', (new_user,))
                if c.fetchone():
                    st.warning("⚠️ 此帳號已被註冊，請換一個名稱。")
                else:
                    add_user(new_user, new_password)
                    st.success("✅ 註冊成功！請切換到「登入」頁面進入系統。")
            else:
                st.warning("請完整輸入帳號與密碼！")
    
    st.stop() # 🛑 如果沒登入，程式就停在這裡，不會往下執行 (保護核心功能)

# ================= 以下為登入後才能看到的「主程式」 =================
st.sidebar.success(f"👤 目前登入身分：{st.session_state['username']}")
if st.sidebar.button("登出系統"):
    st.session_state['logged_in'] = False
    st.rerun()

st.title("📈 跨市場全能分析戰情室 (AI預測 & 側邊掃描)")

# ================= 側邊欄：全市場選擇器 =================
st.sidebar.header("1. 選擇投資市場與標的")
market_type = st.sidebar.selectbox("市場分類", ["台灣股市 (個股/ETF)", "美國股市", "大盤指數", "加密貨幣"])

if market_type == "台灣股市 (個股/ETF)":
    ticker_symbol = st.sidebar.selectbox("熱門台股/ETF", ["2330.TW (台積電)", "2317.TW (鴻海)", "2454.TW (聯發科)", "0050.TW (元大台灣50)", "0056.TW (元大高股息)"]).split(" ")[0]
elif market_type == "美國股市":
    ticker_symbol = st.sidebar.selectbox("熱門美股", ["AAPL (蘋果)", "NVDA (輝達)", "TSLA (特斯拉)", "MSFT (微軟)"]).split(" ")[0]
elif market_type == "大盤指數":
    ticker_symbol = st.sidebar.selectbox("全球大盤", ["^TWII (台灣加權指數)", "^GSPC (標普 500)", "^DJI (道瓊工業)"]).split(" ")[0]
elif market_type == "加密貨幣":
    ticker_symbol = st.sidebar.selectbox("熱門加密貨幣", ["BTC-USD (比特幣)", "ETH-USD (以太幣)", "SOL-USD (索拉納)", "DOGE-USD (狗狗幣)"]).split(" ")[0]

period = st.sidebar.select_slider("歷史數據範圍", options=["1mo", "3mo", "6mo", "1y", "2y", "5y"], value="1y")

# ================= 核心運算與資料抓取 =================
def calculate_indicators(data):
    if len(data) < 20:
        return data 
    delta = data['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    rs = gain.ewm(com=13, adjust=False).mean() / loss.ewm(com=13, adjust=False).mean()
    data['RSI'] = 100 - (100 / (1 + rs))
    data['SMA20'] = data['Close'].rolling(window=20).mean()
    return data

@st.cache_data(ttl=1800) 
def fetch_data(ticker, period):
    ticker_obj = yf.Ticker(ticker)
    data = ticker_obj.history(period=period)
    news = ticker_obj.news 
    if not data.empty:
        data = calculate_indicators(data)
    return data, news

data, news_data = fetch_data(ticker_symbol, period)

# ================= 主畫面 UI (四個頁籤) =================
if not data.empty:
    latest_price = data['Close'].iloc[-1]
    
    if 'RSI' in data.columns and not pd.isna(data['RSI'].iloc[-1]):
        latest_rsi = data['RSI'].iloc[-1]
    else:
        latest_rsi = 50.0 

    st.subheader(f"📊 {ticker_symbol} - 最新報價: {latest_price:.2f}")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 專業圖表", "👑 策略回測", "🧠 Gemini AI 新聞分析", "🔌 IoT硬體對接"])
    
    # ---------- 第一頁：專業圖表 ----------
    with tab1:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name="K線"), row=1, col=1)
        if 'SMA20' in data.columns:
            fig.add_trace(go.Scatter(x=data.index, y=data['SMA20'], line=dict(color='orange', width=1.5), name='20日均線'), row=1, col=1)
        
        colors = ['green' if row['Close'] >= row['Open'] else 'red' for index, row in data.iterrows()]
        fig.add_trace(go.Bar(x=data.index, y=data['Volume'], marker_color=colors, name='成交量'), row=2, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, height=500, margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # ---------- 第二頁：實戰策略回測 ----------
    with tab2:
        st.markdown("### 👑 實戰派策略回測：20日均線順勢交易")
        df_ml = data.dropna().copy()
        if len(df_ml) > 0 and 'SMA20' in df_ml.columns:
            bt_data = df_ml.copy()
            bt_data['Position'] = np.where(bt_data['Close'] > bt_data['SMA20'], 1, 0)
            bt_data['Daily_Return'] = bt_data['Close'].pct_change()
            bt_data['Strategy_Return'] = bt_data['Position'].shift(1) * bt_data['Daily_Return']
            bt_data = bt_data.dropna()
            
            if not bt_data.empty:
                strategy_cum_return = (1 + bt_data['Strategy_Return']).cumprod()
                strategy_total_return = (strategy_cum_return.iloc[-1] - 1) * 100
                market_cum_return = (1 + bt_data['Daily_Return']).cumprod()
                market_total_return = (market_cum_return.iloc[-1] - 1) * 100
                
                col_a, col_b = st.columns(2)
                col_a.metric("📈 均線策略總報酬率", f"{strategy_total_return:.2f}%", f"勝過死抱不放 {strategy_total_return - market_total_return:.2f}%")
                col_b.metric("📊 單純死抱不放", f"{market_total_return:.2f}%")

    # ---------- 第三頁：🧠 Gemini AI 新聞情緒分析 ----------
    with tab3:
        st.markdown(f"### 📰 {ticker_symbol} 最新市場新聞與 AI 分析")
        if news_data:
            # 將新聞標題整理成清單
            news_titles = []
            for item in news_data[:5]:
                content = item.get('content') if item.get('content') is not None else {}
                title = item.get('title') or content.get('title', '無標題')
                click_url = content.get('clickThroughUrl') if content.get('clickThroughUrl') is not None else {}
                link = item.get('link') or click_url.get('url', '#')
                st.markdown(f"- **[{title}]({link})**")
                news_titles.append(title)
            
            st.markdown("---")
            st.markdown("#### ✨ Gemini AI 綜合情緒判定")
            if st.button("啟動大腦：分析上述新聞情緒"):
                if GEMINI_API_KEY == "YOUR_API_KEY_HERE":
                    st.error("⚠️ 請先在程式碼第 15 行填入你的 Gemini API Key！")
                else:
                    with st.spinner("Gemini 正在閱讀新聞並進行分析..."):
                        try:
                            # 呼叫 Gemini 模型
                            genai.configure(api_key=GEMINI_API_KEY)
                            model = genai.GenerativeModel('gemini-pro')
                            prompt = f"你是一個專業的華爾街金融分析師。請閱讀以下關於 {ticker_symbol} 的最新新聞標題，並給出一段簡短的繁體中文分析。判斷目前的市場情緒是看漲、看跌還是中立，並說明原因：\n\n" + "\n".join(news_titles)
                            
                            response = model.generate_content(prompt)
                            st.info(response.text)
                        except Exception as e:
                            st.error(f"AI 分析失敗，請檢查 API Key 是否正確。錯誤訊息：{e}")
        else:
            st.write("目前沒有找到相關新聞。")

    # ---------- 第四頁：IoT API 對接區 ----------
    with tab4:
        st.markdown("### 🔌 微控制器 (MCU) 資料拋轉介面")
        if latest_price > data['SMA20'].iloc[-1]: 
            action = "HOLD_OR_BUY"
        else: 
            action = "SELL_OR_WAIT"

        iot_payload = {
            "device_target": "ESP32",
            "ticker": ticker_symbol,
            "current_price": round(latest_price, 2),
            "sma20": round(data['SMA20'].iloc[-1], 2),
            "action_signal": action,
            "user_active": st.session_state['username']
        }
        st.json(iot_payload)

else:
    st.error("找不到資料，請確認代碼是否正確。")
