import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

# ================= 網頁基礎設定 =================
st.set_page_config(page_title="全能金融戰情室", layout="wide", page_icon="📈")
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

period = st.sidebar.select_slider("歷史數據範圍", options=["1mo", "3mo", "6mo", "1y", "2y", "5y"], value="1y") # 預設拉長到 1y 看回測比較準

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
    return data, news, ticker_obj.info

data, news_data, stock_info = fetch_data(ticker_symbol, period)

# ================= 側邊欄：🚀 快速選股掃描 =================
st.sidebar.markdown("---")
st.sidebar.header("2. 🚀 快速市場掃描")
st.sidebar.write("點擊按鈕，自動列出目前市場中符合條件的標的：")

scan_list = []
if market_type == "台灣股市 (個股/ETF)":
    scan_list = ["2330.TW", "2317.TW", "2454.TW", "2308.TW", "2881.TW", "0050.TW", "0056.TW"]
elif market_type == "加密貨幣":
    scan_list = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "DOGE-USD", "ADA-USD"]
elif market_type == "美國股市":
    scan_list = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "TSLA"]
else:
    scan_list = ["^TWII", "^GSPC", "^DJI"]

if st.sidebar.button("🟢 掃描「建議買入」清單"):
    with st.sidebar.status("正在尋找超賣標的..."):
        found_any = False
        for sym in scan_list:
            try:
                temp_data = yf.Ticker(sym).history(period="1mo")
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

if st.sidebar.button("🔴 掃描「建議賣出」清單"):
    with st.sidebar.status("正在尋找超買標的..."):
        found_any = False
        for sym in scan_list:
            try:
                temp_data = yf.Ticker(sym).history(period="1mo")
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
    
    if 'RSI' in data.columns and not pd.isna(data['RSI'].iloc[-1]):
        latest_rsi = data['RSI'].iloc[-1]
    else:
        latest_rsi = 50.0 

    short_name = stock_info.get('shortName', ticker_symbol)
    st.subheader(f"{short_name} ({ticker_symbol}) - 最新報價: {latest_price:.2f}")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📊 專業圖表", "👑 實戰策略回測 & AI", "📰 相關新聞", "🔌 IoT硬體對接"])
    
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

    # ---------- 第二頁：實戰策略回測與 AI (🔥 全新獲利引擎) ----------
    with tab2:
        st.markdown("### 👑 實戰派策略回測：20日均線順勢交易")
        st.write("測試邏輯：收盤價站上 20 日均線就買入並持有，跌破就賣出空手 (避免大跌)。這能幫你抓住大波段利潤！")
        
        df_ml = data.dropna().copy()
        
        if len(df_ml) > 0 and 'SMA20' in df_ml.columns:
            bt_data = df_ml.copy()
            
            # 1. 產生持倉訊號 (大於均線 = 1 持有，小於均線 = 0 空手)
            bt_data['Position'] = np.where(bt_data['Close'] > bt_data['SMA20'], 1, 0)
            
            # 2. 計算每日市場的自然報酬率
            bt_data['Daily_Return'] = bt_data['Close'].pct_change()
            
            # 3. 策略每日報酬 = 昨天的持倉狀態 * 今天的市場報酬
            bt_data['Strategy_Return'] = bt_data['Position'].shift(1) * bt_data['Daily_Return']
            
            # 4. 計算總報酬率 (使用複利計算)
            bt_data = bt_data.dropna()
            if not bt_data.empty:
                # 策略報酬
                strategy_cum_return = (1 + bt_data['Strategy_Return']).cumprod()
                strategy_total_return = (strategy_cum_return.iloc[-1] - 1) * 100
                
                # 對照組：死抱不放的報酬
                market_cum_return = (1 + bt_data['Daily_Return']).cumprod()
                market_total_return = (market_cum_return.iloc[-1] - 1) * 100
                
                col_a, col_b = st.columns(2)
                col_a.metric("📈 均線策略總報酬率", f"{strategy_total_return:.2f}%", f"勝過死抱不放 {strategy_total_return - market_total_return:.2f}%")
                col_b.metric("📊 對照組 (單純死抱不放)", f"{market_total_return:.2f}%")
                
                if strategy_total_return > 0:
                    st.success("太棒了！這套均線策略在這個時間段內成功為你創造正報酬！")
                else:
                    st.warning("這段時間市場可能處於上下震盪的「盤整期」，均線策略在沒有明確趨勢時容易被頻繁洗出場。")

        st.markdown("---")
        st.markdown("### 🤖 機器學習趨勢預測")
        if len(df_ml) < 5:
            st.warning("⚠️ 歷史數據太短！請將「歷史數據範圍」調成 3mo 以上。")
            y_pred_value = 0.0
        else:
            df_ml['Days'] = np.arange(len(df_ml))
            X = df_ml[['Days']].values
            y = df_ml['Close'].values
            
            model = LinearRegression()
            model.fit(X, y)
            
            future_days = 5
            last_day = df_ml['Days'].max()
            X_future = np.array([[last_day + i] for i in range(1, future_days + 1)])
            y_pred = model.predict(X_future)
            y_pred_value = y_pred[0]
            
            st.info(f"👉 AI 模型預測明日可能價格落點： **{y_pred_value:.2f}**")

    # ---------- 第三頁：財經新聞 ----------
    with tab3:
        st.markdown("### 📰 最新市場新聞")
        if news_data:
            for item in news_data[:5]:
                content = item.get('content') if item.get('content') is not None else {}
                title = item.get('title') or content.get('title', '無標題')
                click_url = content.get('clickThroughUrl') if content.get('clickThroughUrl') is not None else {}
                link = item.get('link') or click_url.get('url', '#')
                provider = content.get('provider') if content.get('provider') is not None else {}
                publisher = item.get('publisher') or provider.get('displayName', '未知來源')
                st.markdown(f"- **[{title}]({link})** *(來源: {publisher})*")
        else:
            st.write("目前沒有找到相關新聞。")

    # ---------- 第四頁：IoT API 對接區 ----------
    with tab4:
        st.markdown("### 🔌 微控制器 (MCU) 資料拋轉介面")
        # 改以均線策略作為硬體觸發訊號
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
            "ai_predict": round(y_pred_value, 2) if 'y_pred_value' in locals() else 0.0
        }
        st.json(iot_payload)

else:
    st.error("找不到資料，請確認代碼是否正確。")