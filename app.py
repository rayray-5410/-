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

# ================= 網頁基礎與 UI 設定 =================
st.set_page_config(page_title="AI 跨市場金融戰情室", layout="wide", page_icon="📈")

# 🔑 【請在這裡貼上你的 Gemini API Key】 (記得保留前後的雙引號，且不要有空白)
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# ================= 🛡️ 輕量級資料庫與資安系統 =================
# 建立資料庫連線 (免費且內建)
conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT, password TEXT)')

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# ✨ 核心升級：建立一組永遠不會被雲端刪除的 VIP 評審/管理員專用帳號
c.execute('SELECT * FROM users WHERE username = "admin"')
if not c.fetchone(): 
    c.execute('INSERT INTO users (username, password) VALUES (?,?)', ("admin", make_hashes("1234")))

conn.commit()

def add_user(username, password):
    c.execute('INSERT INTO users (username, password) VALUES (?,?)', (username, make_hashes(password)))
    conn.commit()

def login_user(username, password):
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, make_hashes(password)))
    return c.fetchall()

# 初始化 Session State
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ""

# ================= 🚪 高級置中版：登入與註冊介面 =================
if not st.session_state['logged_in']:
    st.write("<br><br><br>", unsafe_allow_html=True) 
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("<h1 style='text-align: center;'>🔐 AI 金融戰情室</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: gray;'>企業級跨市場分析與邊緣運算系統</p>", unsafe_allow_html=True)
        st.write("---")
        
        tab_login, tab_register = st.tabs(["🔑 登入系統", "📝 註冊新帳號"])

        with tab_login:
            st.info("💡 提示：您可以使用內建 VIP 帳號登入 (帳號: admin / 密碼: 1234)")
            username = st.text_input("帳號", key="login_user")
            password = st.text_input("密碼", type='password', key="login_pass")
            if st.button("🚀 登入戰情室", use_container_width=True):
                if login_user(username, password):
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = username
                    st.rerun()
                else:
                    st.error("❌ 帳號或密碼錯誤，請重新確認。")

        with tab_register:
            st.write("初次使用？請建立一組安全的存取帳號：")
            new_user = st.text_input("設定帳號", key="reg_user")
            new_password = st.text_input("設定密碼", type='password', key="reg_pass")
            if st.button("✅ 建立帳號", use_container_width=True):
                if new_user and new_password:
                    c.execute('SELECT * FROM users WHERE username = ?', (new_user,))
                    if c.fetchone():
                        st.warning("⚠️ 此帳號已被註冊，請換一個名稱。")
                    else:
                        add_user(new_user, new_password)
                        st.success("🎉 註冊成功！請切換到「🔑 登入系統」頁籤進行登入。")
                else:
                    st.warning("⚠️ 請完整輸入帳號與密碼！")
    
    st.stop() # 🛑 阻擋未授權存取

# ================= 以下為登入後的主程式 =================
st.toast(f"歡迎回來，{st.session_state['username']}！系統已解鎖。", icon="🔓")

# 側邊欄：使用者資訊與市場選擇
st.sidebar.markdown(f"### 👤 使用者：**{st.session_state['username']}**")
if st.sidebar.button("🚪 登出系統"):
    st.session_state['logged_in'] = False
    st.rerun()

st.sidebar.markdown("---")
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

# ================= 核心運算與資料抓取 (🔥 終極防護裝甲) =================
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
    data = pd.DataFrame()
    news = []
    
    # 裝甲1：捕捉股價抓取錯誤，改用 yf.download() 降低被封鎖機率
    try:
        data = yf.download(ticker, period=period, progress=False)
        # 處理新版 yfinance 多層索引問題
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
            
        if not data.empty:
            data = calculate_indicators(data)
    except Exception as e:
        pass # 被擋住就安靜回傳空資料，不報錯

    # 裝甲2：捕捉新聞抓取錯誤
    try:
        ticker_obj = yf.Ticker(ticker)
        news = ticker_obj.news 
    except Exception as e:
        pass # 新聞抓不到就算了
        
    return data, news

with st.spinner(f"正在穿透伺服器防線，抓取 {ticker_symbol} 最新數據..."):
    data, news_data = fetch_data(ticker_symbol, period)

# ================= 側邊欄：🚀 快速選股掃描 =================
st.sidebar.markdown("---")
st.sidebar.header("2. 🚀 快速市場掃描")
st.sidebar.write("點擊按鈕，自動列出目前符合條件的標的：")

scan_list = []
if market_type == "台灣股市 (個股/ETF)":
    scan_list = ["2330.TW", "2317.TW", "2454.TW", "2308.TW", "2881.TW", "0050.TW"]
elif market_type == "加密貨幣":
    scan_list = ["BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD"]
elif market_type == "美國股市":
    scan_list = ["AAPL", "NVDA", "MSFT", "TSLA"]
else:
    scan_list = ["^TWII", "^GSPC", "^DJI"]

if st.sidebar.button("🟢 掃描「建議買入」(RSI < 30)"):
    with st.sidebar.status("正在尋找超賣標的..."):
        found_any = False
        for sym in scan_list:
            try:
                temp_data = yf.download(sym, period="1mo", progress=False)
                if isinstance(temp_data.columns, pd.MultiIndex):
                    temp_data.columns = temp_data.columns.get_level_values(0)
                if len(temp_data) > 15:
                    temp_data = calculate_indicators(temp_data)
                    current_rsi = temp_data['RSI'].iloc[-1]
                    if current_rsi < 30:
                        st.sidebar.success(f"**{sym}** (RSI: {current_rsi:.1f})")
                        found_any = True
            except:
                pass
        if not found_any:
            st.sidebar.info("目前沒有符合買入條件的標的。")

if st.sidebar.button("🔴 掃描「建議賣出」(RSI > 70)"):
    with st.sidebar.status("正在尋找超買標的..."):
        found_any = False
        for sym in scan_list:
            try:
                temp_data = yf.download(sym, period="1mo", progress=False)
                if isinstance(temp_data.columns, pd.MultiIndex):
                    temp_data.columns = temp_data.columns.get_level_values(0)
                if len(temp_data) > 15:
                    temp_data = calculate_indicators(temp_data)
                    current_rsi = temp_data['RSI'].iloc[-1]
                    if current_rsi > 70:
                        st.sidebar.error(f"**{sym}** (RSI: {current_rsi:.1f})")
                        found_any = True
            except:
                pass
        if not found_any:
            st.sidebar.info("目前沒有符合賣出條件的標的。")

# ================= 主畫面 UI (四個頁籤) =================
if not data.empty:
    latest_price = data['Close'].iloc[-1]
    
    st.title("📈 跨市場全能分析戰情室")
    st.markdown(f"### 🎯 關注標的：**{ticker_symbol}** ｜ 最新報價：**{latest_price:.2f}**")
    st.write("---")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 專業圖表", "👑 策略回測 & AI", "🧠 Gemini AI 分析", "🔌 IoT 硬體對接"])
    
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

    # ---------- 第二頁：策略回測與基礎 AI ----------
    with tab2:
        st.markdown("#### 👑 實戰派策略回測：20日均線順勢交易")
        st.caption("邏輯說明：收盤價站上 20 日均線買入並持有，跌破賣出空手。截斷虧損，讓利潤奔跑。")
        
        df_ml = data.dropna().copy()
        if len(df_ml) > 0 and 'SMA20' in df_ml.columns:
            bt_data = df_ml.copy()
            bt_data['Position'] = np.where(bt_data['Close'] > bt_data['SMA20'], 1, 0)
            bt_data['Daily_Return'] = bt_data['Close'].pct_change()
            bt_data['Strategy_Return'] = bt_data['Position'].shift(1) * bt_data['Daily_Return']
            bt_data = bt_data.dropna()
            
            if not bt_data.empty:
                strategy_total_return = ((1 + bt_data['Strategy_Return']).cumprod().iloc[-1] - 1) * 100
                market_total_return = ((1 + bt_data['Daily_Return']).cumprod().iloc[-1] - 1) * 100
                
                col_a, col_b = st.columns(2)
                col_a.metric("📈 均線策略總報酬率", f"{strategy_total_return:.2f}%", f"勝過死抱不放 {strategy_total_return - market_total_return:.2f}%")
                col_b.metric("📊 大盤基準 (死抱不放)", f"{market_total_return:.2f}%")

        st.markdown("---")
        st.markdown("#### 🤖 機器學習 (線性迴歸) 趨勢預測")
        if len(df_ml) < 5:
            st.warning("⚠️ 歷史數據太短！請將「歷史數據範圍」調長。")
        else:
            df_ml['Days'] = np.arange(len(df_ml))
            model = LinearRegression()
            model.fit(df_ml[['Days']].values, df_ml['Close'].values)
            y_pred = model.predict(np.array([[df_ml['Days'].max() + 1]]))[0]
            st.info(f"👉 基礎 AI 模型預測下一交易日可能價格落點： **{y_pred:.2f}**")

    # ---------- 第三頁：🧠 Gemini AI 新聞情緒分析 ----------
    with tab3:
        st.markdown(f"#### 📰 {ticker_symbol} 最新市場新聞")
        if news_data:
            news_titles = []
            for item in news_data[:5]:
                content = item.get('content') if item.get('content') is not None else {}
                title = item.get('title') or content.get('title', '無標題')
                click_url = content.get('clickThroughUrl') if content.get('clickThroughUrl') is not None else {}
                link = item.get('link') or click_url.get('url', '#')
                st.markdown(f"- **[{title}]({link})**")
                news_titles.append(title)
            
            st.markdown("---")
            st.markdown("#### ✨ Gemini LLM 綜合情緒判定")
            if st.button("啟動大腦：分析上述新聞情緒", type="primary"):
                if GEMINI_API_KEY == "YOUR_API_KEY_HERE":
                    st.error("⚠️ 請先在程式碼第 16 行填入你的 Gemini API Key！")
                else:
                    with st.spinner("Gemini 正在閱讀新聞並進行深度推理..."):
                        try:
                            # 🔥 已經為你升級為最新強大的 gemini-2.5-flash 模型！
                            genai.configure(api_key=GEMINI_API_KEY)
                            model = genai.GenerativeModel('gemini-2.5-flash')
                            prompt = f"你是一個專業的華爾街金融分析師。請閱讀以下關於 {ticker_symbol} 的最新新聞標題，並給出一段簡短的繁體中文分析。判斷目前的市場情緒是看漲、看跌還是中立，並說明原因：\n\n" + "\n".join(news_titles)
                            response = model.generate_content(prompt)
                            st.success("分析完成！")
                            st.write(response.text)
                        except Exception as e:
                            st.error(f"AI 分析失敗，請檢查 API Key 是否正確。錯誤訊息：{e}")
        else:
            st.write("目前 Yahoo 伺服器繁忙，暫時無法獲取新聞。請稍後重試。")

    # ---------- 第四頁：IoT API 對接區 ----------
    with tab4:
        st.markdown("#### 🔌 微控制器 (MCU) 資料拋轉介面")
        st.caption("此區塊提供標準化 JSON 格式，供 ESP32 / Arduino 透過 HTTP GET 讀取並轉化為實體硬體作動 (如 LED 燈號指示)。")
        
        if latest_price > data['SMA20'].iloc[-1]: 
            action = "HOLD_OR_BUY"
        else: 
            action = "SELL_OR_WAIT"

        iot_payload = {
            "device_target": "ESP32",
            "ticker": ticker_symbol,
            "current_price": round(latest_price, 2),
            "sma20_threshold": round(data['SMA20'].iloc[-1], 2),
            "action_signal": action,
            "user_active": st.session_state['username']
        }
        st.json(iot_payload)

else:
    # 這是最後一道防線，如果真的全被鎖，畫面會優雅地提示，而不是崩潰跑出紅字
    st.warning("⚠️ Yahoo Finance 伺服器目前對雲端 IP 進行流量管制，暫時無法取得數據。請稍等幾分鐘後重新整理網頁！")


