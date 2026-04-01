import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import sqlite3
import hashlib
import io
import datetime
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 頁面設定 =================
st.set_page_config(page_title="AI 跨市場金融戰情室 Pro", layout="wide", page_icon="📈")

# ================= 資料庫初始化 =================
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ADMIN_USERNAME = st.secrets.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "changeme")

conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()

c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)')
c.execute('''CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, ticker TEXT NOT NULL,
    name TEXT, shares REAL NOT NULL, cost REAL NOT NULL,
    UNIQUE(username, ticker))''')
c.execute('''CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, ticker TEXT NOT NULL,
    alert_high REAL, alert_low REAL,
    UNIQUE(username, ticker))''')
c.execute('''CREATE TABLE IF NOT EXISTS trade_diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL, trade_date TEXT,
    ticker TEXT, direction TEXT,
    price REAL, shares REAL, note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
conn.commit()

# ================= 認證函式 =================
def make_hashes(pw): return hashlib.sha256(pw.encode()).hexdigest()

c.execute('INSERT OR REPLACE INTO users VALUES (?,?)', (ADMIN_USERNAME, make_hashes(ADMIN_PASSWORD)))
conn.commit()

def add_user(u, p):
    try: c.execute('INSERT INTO users VALUES (?,?)', (u, make_hashes(p))); conn.commit(); return True
    except sqlite3.IntegrityError: return False

def login_user(u, p):
    c.execute('SELECT 1 FROM users WHERE username=? AND password=?', (u, make_hashes(p)))
    return c.fetchone() is not None

# ================= 投資組合 CRUD =================
def portfolio_add(user, ticker, name, shares, cost):
    c.execute('SELECT shares, cost FROM portfolio WHERE username=? AND ticker=?', (user, ticker))
    row = c.fetchone()
    if row:
        ns = row[0] + shares
        nc = (row[0]*row[1] + shares*cost) / ns
        c.execute('UPDATE portfolio SET shares=?,cost=?,name=? WHERE username=? AND ticker=?', (ns,nc,name,user,ticker))
        msg = "updated"
    else:
        c.execute('INSERT INTO portfolio VALUES (NULL,?,?,?,?,?)', (user,ticker,name,shares,cost))
        msg = "added"
    conn.commit(); return msg

def portfolio_delete(user, ticker):
    c.execute('DELETE FROM portfolio WHERE username=? AND ticker=?', (user, ticker)); conn.commit()

def portfolio_load(user):
    return pd.read_sql_query('SELECT ticker,name,shares,cost FROM portfolio WHERE username=? ORDER BY ticker', conn, params=(user,))

# ================= 價格警報 CRUD =================
def alert_set(user, ticker, high, low):
    c.execute('INSERT OR REPLACE INTO alerts VALUES (NULL,?,?,?,?)', (user,ticker,high or None,low or None)); conn.commit()

def alert_delete(user, ticker):
    c.execute('DELETE FROM alerts WHERE username=? AND ticker=?', (user,ticker)); conn.commit()

def alert_load(user):
    return pd.read_sql_query('SELECT ticker,alert_high,alert_low FROM alerts WHERE username=?', conn, params=(user,))

# ================= 交易日記 CRUD =================
def diary_add(user, date, ticker, direction, price, shares, note):
    c.execute('INSERT INTO trade_diary VALUES (NULL,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',
              (user, str(date), ticker, direction, price, shares, note)); conn.commit()

def diary_load(user):
    return pd.read_sql_query('SELECT id,trade_date,ticker,direction,price,shares,note FROM trade_diary WHERE username=? ORDER BY trade_date DESC', conn, params=(user,))

def diary_delete(user, rid):
    c.execute('DELETE FROM trade_diary WHERE id=? AND username=?', (rid, user)); conn.commit()

# ================= Session State =================
defaults = {'logged_in': False, 'username': '', 'gemini_cache': {}, 'portfolio_refresh': 0}
for k, v in defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# ================= 登入介面 =================
if not st.session_state['logged_in']:
    st.write("<br><br><br>", unsafe_allow_html=True)
    _, col2, _ = st.columns([1, 2, 1])
    with col2:
        st.markdown("<h1 style='text-align:center'>🔐 AI 金融戰情室 Pro</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center;color:gray'>全功能專業分析系統</p>", unsafe_allow_html=True)
        st.write("---")
        tl, tr = st.tabs(["🔑 登入", "📝 註冊"])
        with tl:
            u = st.text_input("帳號", key="lu")
            p = st.text_input("密碼", type='password', key="lp")
            if st.button("🚀 登入", use_container_width=True):
                if login_user(u, p):
                    st.session_state.update({'logged_in': True, 'username': u}); st.rerun()
                else: st.error("❌ 帳號或密碼錯誤")
        with tr:
            nu = st.text_input("設定帳號", key="ru")
            np_ = st.text_input("設定密碼", type='password', key="rp")
            if st.button("✅ 建立帳號", use_container_width=True):
                if nu and np_:
                    if add_user(nu, np_): st.success("🎉 註冊成功！請登入。")
                    else: st.warning("⚠️ 帳號已存在")
                else: st.warning("請完整填寫")
    st.stop()

# ================= 主程式（登入後）=================
st.toast(f"歡迎回來，{st.session_state['username']}！", icon="🔓")
user = st.session_state['username']

st.sidebar.markdown(f"### 👤 **{user}**")
if st.sidebar.button("🚪 登出"): st.session_state['logged_in'] = False; st.rerun()
st.sidebar.markdown("---")

# ── 側邊欄：標的選擇 ──
st.sidebar.header("1. 選擇投資標的")
mode = st.sidebar.radio("搜尋模式", ["快速選擇", "自訂輸入"])
if mode == "快速選擇":
    market_type = st.sidebar.selectbox("市場", ["台灣股市", "美國股市", "加密貨幣"])
    opts = {"台灣股市": ["2330.TW (台積電)","2317.TW (鴻海)","2454.TW (聯發科)","0050.TW","0056.TW"],
            "美國股市": ["AAPL (蘋果)","NVDA (輝達)","TSLA (特斯拉)","MSFT (微軟)","GOOGL (谷歌)"],
            "加密貨幣": ["BTC-USD","ETH-USD","SOL-USD","DOGE-USD"]}
    ticker_symbol = st.sidebar.selectbox("標的", opts[market_type]).split(" ")[0]
else:
    st.sidebar.info("台股加 .TW，美股直接輸代碼")
    ticker_symbol = st.sidebar.text_input("Yahoo Finance 代碼", value="NVDA").upper()
    market_type = "自訂輸入"

period = st.sidebar.select_slider("數據範圍", ["1mo","3mo","6mo","1y","2y","5y"], value="1y")

# ── 側邊欄：RSI 快速掃描 ──
st.sidebar.markdown("---")
st.sidebar.header("2. 🚀 快速掃描")
scan_map = {"台灣股市":["2330.TW","2317.TW","2454.TW","2308.TW","2881.TW","0050.TW"],
            "加密貨幣":["BTC-USD","ETH-USD","SOL-USD","DOGE-USD"],
            "美國股市":["AAPL","NVDA","MSFT","TSLA","GOOGL"],
            "自訂輸入":["^TWII","^GSPC","^DJI"]}
scan_list = scan_map.get(market_type, scan_map["自訂輸入"])

def _fetch_rsi(sym):
    try:
        tmp = yf.download(sym, period="1mo", progress=False, auto_adjust=True)
        if isinstance(tmp.columns, pd.MultiIndex): tmp.columns = tmp.columns.get_level_values(0)
        if len(tmp) > 15:
            d = tmp['Close'].diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
            rs = g.ewm(com=13,adjust=False).mean() / l.ewm(com=13,adjust=False).mean()
            rsi = float((100 - 100/(1+rs)).iloc[-1])
            return sym, rsi
    except: pass
    return sym, None

def scan_rsi(symbols, threshold, above):
    results = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, rsi in [f.result() for f in as_completed({ex.submit(_fetch_rsi,s):s for s in symbols})]:
            if rsi and ((above and rsi > threshold) or (not above and rsi < threshold)):
                results.append((sym, rsi))
    return sorted(results, key=lambda x: x[1], reverse=above)

cs1, cs2 = st.sidebar.columns(2)
if cs1.button("🟢 超賣\nRSI<30", use_container_width=True):
    with st.sidebar.status("掃描中..."):
        for sym, rsi in scan_rsi(scan_list, 30, False) or [("無符合", 0)]:
            if rsi: st.sidebar.success(f"**{sym}** {rsi:.1f}")
            else: st.sidebar.info(sym)
if cs2.button("🔴 超買\nRSI>70", use_container_width=True):
    with st.sidebar.status("掃描中..."):
        for sym, rsi in scan_rsi(scan_list, 70, True) or [("無符合", 0)]:
            if rsi: st.sidebar.error(f"**{sym}** {rsi:.1f}")
            else: st.sidebar.info(sym)

# ================= 指標計算 =================
def calculate_indicators(data):
    df = data.copy()
    if len(df) < 20: return df
    d = df['Close'].diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    rs = g.ewm(com=13,adjust=False).mean() / l.ewm(com=13,adjust=False).mean()
    df['RSI'] = 100 - (100/(1+rs))
    df['SMA20'] = df['Close'].rolling(20).mean()
    df['SMA60'] = df['Close'].rolling(60).mean()
    df['BB_Upper'] = df['SMA20'] + 2*df['Close'].rolling(20).std()
    df['BB_Lower'] = df['SMA20'] - 2*df['Close'].rolling(20).std()
    e12 = df['Close'].ewm(span=12,adjust=False).mean()
    e26 = df['Close'].ewm(span=26,adjust=False).mean()
    df['MACD'] = e12 - e26
    df['MACD_Signal'] = df['MACD'].ewm(span=9,adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    return df

@st.cache_data(ttl=1800)
def fetch_data(ticker, period):
    data, news = pd.DataFrame(), []
    try:
        data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        if not data.empty: data = calculate_indicators(data)
    except: pass
    try: news = yf.Ticker(ticker).news or []
    except: pass
    return data, news

@st.cache_data(ttl=1800)
def fetch_fundamentals(ticker):
    try:
        info = yf.Ticker(ticker).info
        return {k: info.get(k) for k in ['trailingPE','forwardPE','trailingEps','revenueGrowth',
                                          'grossMargins','operatingMargins','returnOnEquity',
                                          'debtToEquity','currentRatio','dividendYield','marketCap',
                                          'fiftyTwoWeekHigh','fiftyTwoWeekLow','shortName']}
    except: return {}

def _get_price(tkr):
    try:
        tmp = yf.download(tkr, period="2d", progress=False, auto_adjust=True)
        if isinstance(tmp.columns, pd.MultiIndex): tmp.columns = tmp.columns.get_level_values(0)
        if not tmp.empty: return tkr, float(tmp['Close'].iloc[-1])
    except: pass
    return tkr, None

# ── 技術面評分 ──
def tech_score(df):
    if df.empty or 'RSI' not in df.columns: return 50, {}
    scores = {}
    last = df.iloc[-1]
    rsi = last.get('RSI', 50)
    if rsi < 30: scores['RSI'] = 90
    elif rsi < 45: scores['RSI'] = 70
    elif rsi < 55: scores['RSI'] = 50
    elif rsi < 70: scores['RSI'] = 35
    else: scores['RSI'] = 15

    if 'SMA20' in df.columns and not pd.isna(last['SMA20']):
        scores['均線位置'] = 80 if last['Close'] > last['SMA20'] else 25
    if 'SMA60' in df.columns and not pd.isna(last['SMA60']):
        scores['中期趨勢'] = 80 if last['SMA20'] > last['SMA60'] else 25
    if 'MACD' in df.columns:
        scores['MACD'] = 75 if last['MACD'] > last['MACD_Signal'] else 30
    if 'BB_Upper' in df.columns and not pd.isna(last['BB_Upper']):
        bb_pct = (last['Close'] - last['BB_Lower']) / (last['BB_Upper'] - last['BB_Lower'])
        if bb_pct < 0.2: scores['布林位置'] = 85
        elif bb_pct < 0.5: scores['布林位置'] = 65
        elif bb_pct < 0.8: scores['布林位置'] = 45
        else: scores['布林位置'] = 20

    total = int(np.mean(list(scores.values()))) if scores else 50
    return total, scores

# ── 主資料抓取 ──
with st.spinner(f"抓取 {ticker_symbol} 數據..."):
    data, news_data = fetch_data(ticker_symbol, period)

# ================= 頂部警報橫幅 =================
alerts_df = alert_load(user)
if not alerts_df.empty and not data.empty:
    latest_p = float(data['Close'].iloc[-1])
    for _, ar in alerts_df[alerts_df['ticker'] == ticker_symbol].iterrows():
        if ar['alert_high'] and latest_p >= ar['alert_high']:
            st.error(f"🚨 價格警報！{ticker_symbol} 現價 {latest_p:.2f} 已突破高點目標 {ar['alert_high']:.2f}")
        if ar['alert_low'] and latest_p <= ar['alert_low']:
            st.warning(f"⚠️ 價格警報！{ticker_symbol} 現價 {latest_p:.2f} 已跌破低點目標 {ar['alert_low']:.2f}")

# ================= 大盤總覽（頂部常駐）=================
with st.expander("🌍 大盤總覽", expanded=False):
    indices = {"台灣加權": "^TWII", "S&P 500": "^GSPC", "納斯達克": "^IXIC", "道瓊": "^DJI", "比特幣": "BTC-USD", "黃金": "GC=F"}
    idx_cols = st.columns(len(indices))
    idx_data_map = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_get_price, sym): name for name, sym in indices.items()}
        for fut in as_completed(futs):
            name = futs[fut]; _, px = fut.result(); idx_data_map[name] = px
    for i, (name, sym) in enumerate(indices.items()):
        px = idx_data_map.get(name)
        idx_cols[i].metric(name, f"{px:,.2f}" if px else "—")

if data.empty:
    st.warning("⚠️ 找不到資料，請確認代碼或稍後重試。"); st.stop()

latest_price = float(data['Close'].iloc[-1])
prev_price   = float(data['Close'].iloc[-2]) if len(data) > 1 else latest_price
day_chg      = latest_price - prev_price
day_chg_pct  = day_chg / prev_price * 100

# ── 技術評分 ──
score, score_detail = tech_score(data)

# 主標題列
h1, h2, h3, h4 = st.columns([3,1,1,1])
h1.markdown(f"## 📈 {ticker_symbol}")
h2.metric("最新報價", f"{latest_price:.2f}", f"{day_chg:+.2f} ({day_chg_pct:+.2f}%)")
h3.metric("技術評分", f"{score}/100", "偏多" if score>=60 else ("偏空" if score<=40 else "中性"))
h4.metric("數據筆數", f"{len(data)} 根K線")
st.write("---")

# ================= 頁籤 =================
(tab_chart, tab_backtest, tab_compare, tab_fibo,
 tab_corr, tab_fundament, tab_risk, tab_ml,
 tab_portfolio, tab_alert, tab_diary, tab_gemini, tab_iot) = st.tabs([
    "📊 圖表", "👑 回測", "⚖️ 比較", "📐 費波納契",
    "🔗 相關性", "📑 財報", "📉 風險", "🤖 ML預測",
    "📂 組合", "🔔 警報", "📓 日記", "🧠 Gemini", "🔌 IoT"
])

# ══════════════════════════════════════════
# TAB 1：專業圖表
# ══════════════════════════════════════════
with tab_chart:
    show_bb   = st.checkbox("布林通道", value=True)
    show_macd = st.checkbox("MACD", value=True)
    show_fibo_quick = st.checkbox("費波納契快速標示", value=False)

    rows  = 3 if show_macd else 2
    row_h = [0.55, 0.2, 0.25] if show_macd else [0.7, 0.3]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=row_h)
    fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name="K線"), 1, 1)
    if 'SMA20' in data.columns:
        fig.add_trace(go.Scatter(x=data.index, y=data['SMA20'], line=dict(color='orange',width=1.5), name='SMA20'), 1, 1)
    if 'SMA60' in data.columns:
        fig.add_trace(go.Scatter(x=data.index, y=data['SMA60'], line=dict(color='cyan',width=1.5), name='SMA60'), 1, 1)
    if show_bb and 'BB_Upper' in data.columns:
        fig.add_trace(go.Scatter(x=data.index, y=data['BB_Upper'], line=dict(color='rgba(200,200,200,0.4)',dash='dot'), name='BB上'), 1, 1)
        fig.add_trace(go.Scatter(x=data.index, y=data['BB_Lower'], line=dict(color='rgba(200,200,200,0.4)',dash='dot'), fill='tonexty', fillcolor='rgba(128,128,128,0.08)', name='BB下'), 1, 1)

    # 成交量異常偵測
    if 'Volume' in data.columns and len(data) > 60:
        avg_vol = data['Volume'].rolling(60).mean()
        is_abnormal = data['Volume'] > avg_vol * 2
        colors = ['rgba(255,165,0,0.9)' if ab else ('green' if r['Close']>=r['Open'] else 'red')
                  for ab, (_, r) in zip(is_abnormal, data.iterrows())]
        fig.add_trace(go.Bar(x=data.index, y=data['Volume'], marker_color=colors, name='成交量'), 2, 1)
        # 爆量標示
        abn_dates = data.index[is_abnormal]
        if len(abn_dates):
            fig.add_trace(go.Scatter(x=abn_dates, y=data.loc[abn_dates,'High']*1.01,
                mode='markers', marker=dict(symbol='triangle-up', size=8, color='orange'),
                name='爆量'), 1, 1)

    if show_fibo_quick and len(data) >= 20:
        recent = data.tail(min(120, len(data)))
        hi, lo = float(recent['High'].max()), float(recent['Low'].min())
        fibs = [0, 0.236, 0.382, 0.5, 0.618, 1.0]
        for f in fibs:
            lvl = hi - (hi - lo) * f
            fig.add_hline(y=lvl, line_dash="dot", line_color="gold", line_width=1,
                          annotation_text=f"{f:.1%} {lvl:.2f}", annotation_position="left", row=1, col=1)

    if show_macd and 'MACD' in data.columns:
        fig.add_trace(go.Scatter(x=data.index, y=data['MACD'], line=dict(color='#00d4ff'), name='MACD'), 3, 1)
        fig.add_trace(go.Scatter(x=data.index, y=data['MACD_Signal'], line=dict(color='#ff6b35'), name='Signal'), 3, 1)
        hc = ['green' if v>=0 else 'red' for v in data['MACD_Hist']]
        fig.add_trace(go.Bar(x=data.index, y=data['MACD_Hist'], marker_color=hc, name='Hist'), 3, 1)

    fig.update_layout(xaxis_rangeslider_visible=False, height=600, margin=dict(l=0,r=0,t=30,b=0))
    st.plotly_chart(fig, use_container_width=True)

    # 技術面評分儀表板
    st.markdown("##### 🎯 技術面評分明細")
    gauge = go.Figure(go.Indicator(mode="gauge+number", value=score,
        title={'text': "綜合技術分"},
        gauge={'axis':{'range':[0,100]},
               'bar':{'color':'#00d4ff'},
               'steps':[{'range':[0,40],'color':'rgba(231,76,60,0.3)'},
                        {'range':[40,60],'color':'rgba(241,196,15,0.3)'},
                        {'range':[60,100],'color':'rgba(46,204,113,0.3)'}]}))
    gauge.update_layout(height=250, margin=dict(l=20,r=20,t=40,b=20))
    gc1, gc2 = st.columns([1,2])
    gc1.plotly_chart(gauge, use_container_width=True)
    with gc2:
        for indicator, s in score_detail.items():
            color = "🟢" if s>=60 else ("🔴" if s<40 else "🟡")
            st.markdown(f"{color} **{indicator}**：{s}/100")
            st.progress(s/100)

# ══════════════════════════════════════════
# TAB 2：多策略回測
# ══════════════════════════════════════════
with tab_backtest:
    st.markdown("#### 👑 多策略回測比較")

    def run_backtest(df, strategy):
        bt = df.dropna().copy()
        daily = bt['Close'].pct_change()
        if strategy == "SMA20 均線":
            if 'SMA20' not in bt.columns: return pd.Series(dtype=float)
            pos = np.where(bt['Close'] > bt['SMA20'], 1, 0)
        elif strategy == "黃金交叉 SMA20/60":
            if 'SMA60' not in bt.columns: return pd.Series(dtype=float)
            pos = np.where(bt['SMA20'] > bt['SMA60'], 1, 0)
        elif strategy == "布林通道反轉":
            if 'BB_Lower' not in bt.columns: return pd.Series(dtype=float)
            pos = np.zeros(len(bt)); h = 0
            for i in range(1, len(bt)):
                p, bl, bu = float(bt['Close'].iloc[i]), float(bt['BB_Lower'].iloc[i]), float(bt['BB_Upper'].iloc[i])
                if p <= bl: h = 1
                elif p >= bu: h = 0
                pos[i] = h
        elif strategy == "RSI 超買超賣":
            if 'RSI' not in bt.columns: return pd.Series(dtype=float)
            pos = np.zeros(len(bt)); h = 0
            for i in range(1, len(bt)):
                r = float(bt['RSI'].iloc[i])
                if r < 30: h = 1
                elif r > 70: h = 0
                pos[i] = h
        elif strategy == "MACD 交叉":
            if 'MACD' not in bt.columns: return pd.Series(dtype=float)
            pos = np.where(bt['MACD'] > bt['MACD_Signal'], 1, 0)
        else: return pd.Series(dtype=float)
        return (pd.Series(pos, index=bt.index).shift(1) * daily).dropna()

    strategies = ["SMA20 均線","黃金交叉 SMA20/60","布林通道反轉","RSI 超買超賣","MACD 交叉"]
    selected = st.multiselect("選擇策略", strategies, default=["SMA20 均線","RSI 超買超賣","MACD 交叉"])

    if selected:
        fig_bt = go.Figure()
        bh = data['Close'].pct_change().dropna()
        fig_bt.add_trace(go.Scatter(x=(1+bh).cumprod().index, y=(1+bh).cumprod(),
            name="買入持有", line=dict(color='gray',dash='dot',width=2)))
        rows_bt = []
        for strat in selected:
            ret = run_backtest(data, strat)
            if ret.empty: continue
            cum = (1+ret).cumprod()
            tr = (cum.iloc[-1]-1)*100
            ar = ((cum.iloc[-1])**(252/len(cum))-1)*100
            sh = (ret.mean()/ret.std()*np.sqrt(252)) if ret.std()>0 else 0
            md = ((cum/cum.cummax())-1).min()*100
            wr = (ret>0).mean()*100
            rows_bt.append({"策略":strat,"總報酬":f"{tr:.1f}%","年化":f"{ar:.1f}%",
                             "夏普":f"{sh:.2f}","最大回撤":f"{md:.1f}%","勝率":f"{wr:.1f}%"})
            fig_bt.add_trace(go.Scatter(x=cum.index, y=cum, name=strat, line=dict(width=2)))
        fig_bt.update_layout(title="累積報酬率", height=400, margin=dict(l=0,r=0,t=40,b=0))
        st.plotly_chart(fig_bt, use_container_width=True)
        if rows_bt: st.dataframe(pd.DataFrame(rows_bt).set_index("策略"), use_container_width=True)

    # ML 線性迴歸預測
    st.markdown("---")
    st.markdown("#### 🤖 線性迴歸趨勢預測")
    df_ml = data.dropna().copy()
    if len(df_ml) >= 5:
        df_ml['Days'] = np.arange(len(df_ml))
        lr = LinearRegression().fit(df_ml[['Days']].values, df_ml['Close'].values)
        pred = lr.predict([[df_ml['Days'].max()+1]])[0]
        st.info(f"👉 線性迴歸預測下一交易日：**{pred:.2f}**")

    # CSV 匯出
    st.markdown("---")
    st.markdown("#### 📤 CSV 資料匯出")
    ec1, ec2 = st.columns(2)
    csv_hist = data.reset_index().to_csv(index=False).encode('utf-8-sig')
    ec1.download_button("⬇️ 下載歷史K線 CSV", csv_hist, f"{ticker_symbol}_history.csv", "text/csv")
    if rows_bt:
        csv_bt = pd.DataFrame(rows_bt).to_csv(index=False).encode('utf-8-sig')
        ec2.download_button("⬇️ 下載回測結果 CSV", csv_bt, f"{ticker_symbol}_backtest.csv", "text/csv")

# ══════════════════════════════════════════
# TAB 3：多股走勢比較
# ══════════════════════════════════════════
with tab_compare:
    st.markdown("#### ⚖️ 多標的報酬率比較")
    st.caption("報酬率標準化為 100，方便比較不同價位的標的強弱。")
    compare_input = st.text_input("輸入最多 5 個代碼（逗號分隔）", value=f"{ticker_symbol},^GSPC")
    compare_tickers = [t.strip().upper() for t in compare_input.split(",") if t.strip()][:5]

    if st.button("📊 開始比較", key="btn_compare"):
        fig_cmp = go.Figure()
        with st.spinner("抓取比較數據..."):
            def _fetch_compare(tkr):
                try:
                    tmp = yf.download(tkr, period=period, progress=False, auto_adjust=True)
                    if isinstance(tmp.columns, pd.MultiIndex): tmp.columns = tmp.columns.get_level_values(0)
                    return tkr, tmp['Close'] if not tmp.empty else None
                except: return tkr, None
            with ThreadPoolExecutor(max_workers=5) as ex:
                results = [f.result() for f in as_completed({ex.submit(_fetch_compare,t):t for t in compare_tickers})]
        for tkr, series in results:
            if series is not None and len(series) > 1:
                normalized = series / series.iloc[0] * 100
                fig_cmp.add_trace(go.Scatter(x=normalized.index, y=normalized, name=tkr, line=dict(width=2)))
        fig_cmp.add_hline(y=100, line_dash="dash", line_color="gray", line_width=1)
        fig_cmp.update_layout(title="標準化報酬率比較（基準=100）", height=450,
                               yaxis_title="相對報酬率", margin=dict(l=0,r=0,t=40,b=0))
        st.plotly_chart(fig_cmp, use_container_width=True)

# ══════════════════════════════════════════
# TAB 4：費波納契回撤
# ══════════════════════════════════════════
with tab_fibo:
    st.markdown("#### 📐 費波納契回撤線")
    st.caption("自動找出選定期間的最高／最低點，計算並標示關鍵支撐壓力區。")
    fibo_period = st.slider("回撤計算週期（最近 N 根K線）", 20, min(250, len(data)), min(120, len(data)))
    recent_f = data.tail(fibo_period)
    hi_f = float(recent_f['High'].max())
    lo_f = float(recent_f['Low'].min())
    hi_dt = recent_f['High'].idxmax()
    lo_dt = recent_f['Low'].idxmin()
    st.info(f"區間最高：**{hi_f:.2f}**（{hi_dt.date()}）｜ 區間最低：**{lo_f:.2f}**（{lo_dt.date()}）")

    fibs = {0:"0%（高點）", 0.236:"23.6%", 0.382:"38.2%", 0.500:"50%（中間）", 0.618:"61.8%（黃金）", 0.786:"78.6%", 1.0:"100%（低點）"}
    fib_fig = go.Figure()
    fib_fig.add_trace(go.Candlestick(x=recent_f.index, open=recent_f['Open'], high=recent_f['High'],
                                      low=recent_f['Low'], close=recent_f['Close'], name="K線"))
    colors_f = ['#e74c3c','#e67e22','#f1c40f','#2ecc71','#3498db','#9b59b6','#1abc9c']
    for (ratio, label), clr in zip(fibs.items(), colors_f):
        lvl = hi_f - (hi_f - lo_f) * ratio
        fib_fig.add_hline(y=lvl, line_color=clr, line_width=1.5, line_dash="dash",
                          annotation_text=f"  {label}：{lvl:.2f}", annotation_position="right")
    fib_fig.add_hline(y=latest_price, line_color='white', line_width=2,
                      annotation_text=f"  現價 {latest_price:.2f}", annotation_position="left")
    fib_fig.update_layout(xaxis_rangeslider_visible=False, height=500, margin=dict(l=0,r=120,t=30,b=0))
    st.plotly_chart(fib_fig, use_container_width=True)

    # 費波納契表格
    fib_rows = []
    for ratio, label in fibs.items():
        lvl = hi_f - (hi_f - lo_f) * ratio
        dist = latest_price - lvl
        fib_rows.append({"層級": label, "價位": round(lvl,2),
                          "距現價": f"{dist:+.2f}", "距現價%": f"{dist/latest_price*100:+.2f}%"})
    st.dataframe(pd.DataFrame(fib_rows), use_container_width=True, hide_index=True)

# ══════════════════════════════════════════
# TAB 5：相關性熱力圖
# ══════════════════════════════════════════
with tab_corr:
    st.markdown("#### 🔗 多標的相關性分析")
    corr_input = st.text_input("輸入多個代碼（逗號分隔，最多 10 個）",
                                value="AAPL,NVDA,MSFT,TSLA,BTC-USD")
    corr_tickers = [t.strip().upper() for t in corr_input.split(",") if t.strip()][:10]

    if st.button("🔍 計算相關性", key="btn_corr"):
        with st.spinner("抓取所有標的數據..."):
            close_dict = {}
            def _fetch_close(tkr):
                try:
                    tmp = yf.download(tkr, period=period, progress=False, auto_adjust=True)
                    if isinstance(tmp.columns, pd.MultiIndex): tmp.columns = tmp.columns.get_level_values(0)
                    if not tmp.empty: return tkr, tmp['Close']
                except: pass
                return tkr, None
            with ThreadPoolExecutor(max_workers=10) as ex:
                for tkr, series in [f.result() for f in as_completed({ex.submit(_fetch_close,t):t for t in corr_tickers})]:
                    if series is not None: close_dict[tkr] = series

        if len(close_dict) >= 2:
            price_df = pd.DataFrame(close_dict).dropna()
            corr_matrix = price_df.pct_change().dropna().corr()
            fig_heat = px.imshow(corr_matrix, text_auto=".2f", color_continuous_scale='RdBu_r',
                                  zmin=-1, zmax=1, title="相關係數熱力圖（+1 完全正相關，-1 完全負相關）")
            fig_heat.update_layout(height=500, margin=dict(l=0,r=0,t=40,b=0))
            st.plotly_chart(fig_heat, use_container_width=True)
            st.caption("💡 相關係數接近 1 = 同漲同跌；接近 -1 = 反向；接近 0 = 無關聯，分散投資時選低相關標的。")
        else:
            st.warning("有效數據不足，請確認代碼是否正確。")

# ══════════════════════════════════════════
# TAB 6：財報快覽
# ══════════════════════════════════════════
with tab_fundament:
    st.markdown(f"#### 📑 {ticker_symbol} 財務基本面")
    with st.spinner("抓取財務數據..."):
        fi = fetch_fundamentals(ticker_symbol)

    if fi.get('shortName'):
        st.markdown(f"**{fi['shortName']}**")

    def fmt_pct(v): return f"{v*100:.2f}%" if v else "N/A"
    def fmt_num(v, dp=2): return f"{v:,.{dp}f}" if v else "N/A"
    def fmt_cap(v):
        if not v: return "N/A"
        if v >= 1e12: return f"{v/1e12:.2f}T"
        if v >= 1e9: return f"{v/1e9:.2f}B"
        return f"{v/1e6:.2f}M"

    fa1, fa2, fa3, fa4 = st.columns(4)
    fa1.metric("本益比 (PE)", fmt_num(fi.get('trailingPE'),1))
    fa2.metric("預估 PE", fmt_num(fi.get('forwardPE'),1))
    fa3.metric("每股盈餘 EPS", fmt_num(fi.get('trailingEps')))
    fa4.metric("市值", fmt_cap(fi.get('marketCap')))

    fb1, fb2, fb3, fb4 = st.columns(4)
    fb1.metric("毛利率", fmt_pct(fi.get('grossMargins')))
    fb2.metric("營業利益率", fmt_pct(fi.get('operatingMargins')))
    fb3.metric("ROE", fmt_pct(fi.get('returnOnEquity')))
    fb4.metric("營收成長率", fmt_pct(fi.get('revenueGrowth')))

    fc1, fc2, fc3, fc4 = st.columns(4)
    fc1.metric("負債比 D/E", fmt_num(fi.get('debtToEquity')))
    fc2.metric("流動比率", fmt_num(fi.get('currentRatio')))
    fc3.metric("殖利率", fmt_pct(fi.get('dividendYield')))
    fc4.metric("52週高/低", f"{fmt_num(fi.get('fiftyTwoWeekHigh'))} / {fmt_num(fi.get('fiftyTwoWeekLow'))}")

    # 簡易雷達圖
    radar_labels = ['獲利能力','成長力','股東報酬','財務健康','估值']
    def safe01(v, lo, hi, inv=False):
        if v is None: return 0.5
        n = max(0, min(1, (v-lo)/(hi-lo)))
        return 1-n if inv else n
    radar_vals = [
        safe01(fi.get('grossMargins'), 0, 0.8),
        safe01(fi.get('revenueGrowth'), -0.2, 0.5),
        safe01(fi.get('returnOnEquity'), 0, 0.4),
        safe01(fi.get('currentRatio'), 0, 3),
        safe01(fi.get('trailingPE'), 5, 50, inv=True),
    ]
    fig_radar = go.Figure(go.Scatterpolar(r=radar_vals + [radar_vals[0]],
        theta=radar_labels + [radar_labels[0]], fill='toself',
        line_color='#00d4ff', fillcolor='rgba(0,212,255,0.2)'))
    fig_radar.update_layout(polar=dict(radialaxis=dict(range=[0,1])), height=350,
                             title="基本面雷達圖", margin=dict(l=40,r=40,t=50,b=40))
    st.plotly_chart(fig_radar, use_container_width=True)

# ══════════════════════════════════════════
# TAB 7：風險指標
# ══════════════════════════════════════════
with tab_risk:
    st.markdown("#### 📉 風險指標分析")
    ret = data['Close'].pct_change().dropna()

    if len(ret) < 30:
        st.warning("數據不足，請調長數據範圍。")
    else:
        ann_vol = ret.std() * np.sqrt(252) * 100
        var_95  = np.percentile(ret, 5) * 100
        var_99  = np.percentile(ret, 1) * 100
        max_dd  = ((data['Close'] / data['Close'].cummax()) - 1).min() * 100
        pos_days = (ret > 0).mean() * 100

        # Beta（相對 S&P500）
        try:
            sp = yf.download("^GSPC", period=period, progress=False, auto_adjust=True)
            if isinstance(sp.columns, pd.MultiIndex): sp.columns = sp.columns.get_level_values(0)
            sp_ret = sp['Close'].pct_change().dropna()
            aligned = pd.concat([ret, sp_ret], axis=1, join='inner').dropna()
            aligned.columns = ['stock', 'market']
            beta = aligned.cov().iloc[0,1] / aligned['market'].var()
        except: beta = None

        r1,r2,r3,r4,r5 = st.columns(5)
        r1.metric("年化波動率", f"{ann_vol:.1f}%")
        r2.metric("VaR 95%（每日）", f"{var_95:.2f}%", help="95%信心水準下，單日最大虧損不超過此值")
        r3.metric("VaR 99%（每日）", f"{var_99:.2f}%")
        r4.metric("最大回撤", f"{max_dd:.1f}%")
        r5.metric("Beta（vs S&P）", f"{beta:.2f}" if beta else "N/A")

        st.markdown("---")
        rc1, rc2 = st.columns(2)
        with rc1:
            st.markdown("##### 報酬率分佈直方圖")
            fig_hist = go.Figure(go.Histogram(x=ret*100, nbinsx=60,
                marker_color='rgba(0,212,255,0.7)', name='日報酬率'))
            fig_hist.add_vline(x=var_95, line_dash="dash", line_color="orange", annotation_text=f"VaR95: {var_95:.2f}%")
            fig_hist.add_vline(x=var_99, line_dash="dash", line_color="red",    annotation_text=f"VaR99: {var_99:.2f}%")
            fig_hist.update_layout(height=320, xaxis_title="日報酬率 (%)", margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig_hist, use_container_width=True)
        with rc2:
            st.markdown("##### 水下曲線（回撤深度）")
            drawdown = (data['Close'] / data['Close'].cummax()) - 1
            fig_dd = go.Figure(go.Scatter(x=drawdown.index, y=drawdown*100,
                fill='tozeroy', fillcolor='rgba(231,76,60,0.3)', line_color='#e74c3c', name='回撤'))
            fig_dd.update_layout(height=320, yaxis_title="回撤 (%)", margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig_dd, use_container_width=True)

        # 情境模擬
        st.markdown("---")
        st.markdown("##### 🎲 漲跌情境模擬")
        pf_df_s = portfolio_load(user)
        if not pf_df_s.empty:
            st.caption("根據你的投資組合，模擬各種市場情境下的損益變化")
            scenarios = {"大跌 -20%":-0.20, "下跌 -10%":-0.10, "持平 0%":0.0,
                         "上漲 +10%":0.10, "大漲 +20%":0.20, "暴漲 +30%":0.30}
            # 抓取組合現價
            with st.spinner("計算情境損益..."):
                pm = {}
                with ThreadPoolExecutor(max_workers=8) as ex:
                    for t, p in [f.result() for f in as_completed({ex.submit(_get_price,row['ticker']):row['ticker'] for _,row in pf_df_s.iterrows()})]:
                        pm[t] = p
                total_mkt_val = sum(row['shares']*(pm.get(row['ticker']) or row['cost']) for _,row in pf_df_s.iterrows())
                sim_rows2 = []
                for scen_name, chg in scenarios.items():
                    new_val = total_mkt_val * (1 + chg)
                    sim_rows2.append({"情境":scen_name, "組合市值":f"{new_val:,.0f}",
                                       "損益變化":f"{new_val-total_mkt_val:+,.0f}",
                                       "損益%":f"{chg*100:+.0f}%"})
            st.dataframe(pd.DataFrame(sim_rows2), use_container_width=True, hide_index=True)
        else:
            st.info("請先在「📂 組合」頁籤建立投資組合，即可進行情境模擬。")

        # 蒙地卡羅模擬
        st.markdown("---")
        st.markdown("##### 🎰 蒙地卡羅模擬（未來 30 日）")
        n_sim = st.select_slider("模擬次數", [1000, 5000, 10000], value=5000)
        if st.button("🎲 執行蒙地卡羅", key="btn_mc"):
            with st.spinner(f"執行 {n_sim} 次隨機路徑模擬..."):
                mu    = ret.mean()
                sigma = ret.std()
                sims  = np.zeros((30, n_sim))
                sims[0] = latest_price
                for t_step in range(1, 30):
                    rand = np.random.normal(mu, sigma, n_sim)
                    sims[t_step] = sims[t_step-1] * (1 + rand)
                p5   = np.percentile(sims[-1], 5)
                p50  = np.percentile(sims[-1], 50)
                p95  = np.percentile(sims[-1], 95)

                fig_mc = go.Figure()
                # 抽樣 200 條路徑顯示
                for i in range(min(200, n_sim)):
                    fig_mc.add_trace(go.Scatter(y=sims[:,i], mode='lines',
                        line=dict(width=0.3, color='rgba(0,212,255,0.15)'), showlegend=False))
                days_x = list(range(30))
                fig_mc.add_trace(go.Scatter(y=np.percentile(sims, 95, axis=1), mode='lines',
                    name='95th', line=dict(color='#2ecc71', width=2)))
                fig_mc.add_trace(go.Scatter(y=np.percentile(sims, 50, axis=1), mode='lines',
                    name='中位數', line=dict(color='orange', width=2)))
                fig_mc.add_trace(go.Scatter(y=np.percentile(sims, 5, axis=1), mode='lines',
                    name='5th', line=dict(color='#e74c3c', width=2)))
                fig_mc.update_layout(title=f"30日蒙地卡羅模擬（{n_sim}次）", height=420,
                                      yaxis_title="預測價格", margin=dict(l=0,r=0,t=40,b=0))
                st.plotly_chart(fig_mc, use_container_width=True)

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("樂觀情境 (95%)", f"{p95:.2f}", f"{(p95-latest_price)/latest_price*100:+.1f}%")
                mc2.metric("中性情境 (50%)", f"{p50:.2f}", f"{(p50-latest_price)/latest_price*100:+.1f}%")
                mc3.metric("悲觀情境 (5%)", f"{p5:.2f}",  f"{(p5-latest_price)/latest_price*100:+.1f}%")

# ══════════════════════════════════════════
# TAB 8：ML 漲跌預測
# ══════════════════════════════════════════
with tab_ml:
    st.markdown("#### 🤖 Random Forest 漲跌預測")
    st.caption("使用過去技術指標作為特徵，預測下一交易日的漲跌方向。僅供參考，非投資建議。")

    df_rf = data.dropna().copy()
    if len(df_rf) < 60:
        st.warning("數據不足 60 筆，請調長數據範圍。")
    else:
        # 特徵工程
        df_rf['Return_1']  = df_rf['Close'].pct_change(1)
        df_rf['Return_5']  = df_rf['Close'].pct_change(5)
        df_rf['Return_20'] = df_rf['Close'].pct_change(20)
        df_rf['Vol_ratio'] = df_rf['Volume'] / df_rf['Volume'].rolling(20).mean()
        df_rf['Target']    = (df_rf['Close'].shift(-1) > df_rf['Close']).astype(int)
        feature_cols = ['RSI','Return_1','Return_5','Return_20','Vol_ratio','MACD','MACD_Hist']
        df_rf = df_rf[feature_cols + ['Target']].dropna()

        X = df_rf[feature_cols].values
        y = df_rf['Target'].values
        split = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        scaler = StandardScaler()
        X_train_sc = scaler.fit_transform(X_train)
        X_test_sc  = scaler.transform(X_test)

        rf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
        rf.fit(X_train_sc, y_train)
        acc = rf.score(X_test_sc, y_test)

        # 預測最新一筆
        latest_features = scaler.transform(X[-1:])
        pred_proba = rf.predict_proba(latest_features)[0]
        pred_dir   = "📈 看漲" if pred_proba[1] >= 0.5 else "📉 看跌"

        ml1, ml2, ml3 = st.columns(3)
        ml1.metric("模型測試準確率", f"{acc*100:.1f}%")
        ml2.metric("明日預測方向", pred_dir)
        ml3.metric("看漲機率", f"{pred_proba[1]*100:.1f}%")

        # 特徵重要性
        fi_df = pd.DataFrame({'特徵': feature_cols, '重要性': rf.feature_importances_}).sort_values('重要性', ascending=True)
        fig_fi = go.Figure(go.Bar(x=fi_df['重要性'], y=fi_df['特徵'], orientation='h',
            marker_color='rgba(0,212,255,0.7)'))
        fig_fi.update_layout(title="特徵重要性", height=300, margin=dict(l=0,r=0,t=40,b=0))
        st.plotly_chart(fig_fi, use_container_width=True)

        # 回測預測信號
        all_preds = rf.predict(scaler.transform(X))
        signal_ret = pd.Series(all_preds, index=df_rf.index).shift(1) * pd.Series(
            data.loc[df_rf.index, 'Close'].pct_change().values, index=df_rf.index)
        cum_ml = (1 + signal_ret.dropna()).cumprod()
        cum_bh = (1 + data['Close'].pct_change().loc[cum_ml.index]).cumprod()

        fig_ml_bt = go.Figure()
        fig_ml_bt.add_trace(go.Scatter(x=cum_bh.index, y=cum_bh, name="買入持有", line=dict(color='gray',dash='dot')))
        fig_ml_bt.add_trace(go.Scatter(x=cum_ml.index, y=cum_ml, name="ML策略", line=dict(color='#00d4ff',width=2)))
        fig_ml_bt.update_layout(title="ML策略 vs 買入持有", height=350, margin=dict(l=0,r=0,t=40,b=0))
        st.plotly_chart(fig_ml_bt, use_container_width=True)

# ══════════════════════════════════════════
# TAB 9：投資組合
# ══════════════════════════════════════════
with tab_portfolio:
    st.markdown("#### 📂 我的投資組合")
    with st.expander("➕ 新增 / 更新持倉", expanded=False):
        pc1,pc2,pc3,pc4 = st.columns([2,2,1.5,1.5])
        inp_ticker = pc1.text_input("代碼", key="pf_ticker").upper().strip()
        inp_name   = pc2.text_input("備註名稱（選填）", key="pf_name")
        inp_shares = pc3.number_input("持有股數", min_value=0.0001, value=1.0, step=1.0, key="pf_shares")
        inp_cost   = pc4.number_input("平均成本價", min_value=0.0001, value=100.0, step=0.01, key="pf_cost")
        if st.button("✅ 加入組合", use_container_width=True, key="btn_pf_add"):
            if inp_ticker:
                r = portfolio_add(user, inp_ticker, inp_name or inp_ticker, inp_shares, inp_cost)
                st.success(f"{'新增' if r=='added' else '更新'} {inp_ticker} 成功！"); st.rerun()
            else: st.warning("請填寫代碼")

    pf_df = portfolio_load(user)
    if pf_df.empty:
        st.info("📭 組合是空的，請新增第一筆持倉。")
    else:
        with st.spinner("更新最新報價..."):
            pm = {}
            with ThreadPoolExecutor(max_workers=8) as ex:
                for t,p in [f.result() for f in as_completed({ex.submit(_get_price,row['ticker']):row['ticker'] for _,row in pf_df.iterrows()})]:
                    pm[t]=p

        rows_pf = []
        for _, row in pf_df.iterrows():
            px = pm.get(row['ticker']); cost_t = row['shares']*row['cost']
            mv = row['shares']*px if px else None
            pnl = mv-cost_t if mv else None
            pnl_pct = pnl/cost_t*100 if pnl is not None else None
            rows_pf.append({"代碼":row['ticker'],"名稱":row['name'],"股數":row['shares'],
                             "成本價":round(row['cost'],2),"現價":round(px,2) if px else "N/A",
                             "市值":round(mv,2) if mv else "N/A","損益($)":round(pnl,2) if pnl is not None else "N/A",
                             "損益(%)":round(pnl_pct,2) if pnl_pct is not None else "N/A","_cost_t":cost_t})

        valid_pf = [r for r in rows_pf if isinstance(r["市值"],float)]
        total_mv   = sum(r["市值"] for r in valid_pf)
        total_cost = sum(r["_cost_t"] for r in rows_pf)
        total_pnl  = sum(r["損益($)"] for r in valid_pf if isinstance(r["損益($)"],float))
        pnl_pct_t  = total_pnl/total_cost*100 if total_cost>0 else 0

        k1,k2,k3,k4 = st.columns(4)
        k1.metric("💰 總市值",  f"{total_mv:,.2f}")
        k2.metric("📥 總成本",  f"{total_cost:,.2f}")
        k3.metric("📈 總損益",  f"{total_pnl:+,.2f}", delta=f"{pnl_pct_t:+.2f}%")
        k4.metric("📦 持倉數",  f"{len(rows_pf)} 檔")
        st.markdown("---")

        if valid_pf:
            cc1,cc2 = st.columns(2)
            with cc1:
                st.markdown("##### 🥧 市值配置")
                fig_pie = go.Figure(go.Pie(labels=[r["代碼"] for r in valid_pf],
                    values=[r["市值"] for r in valid_pf], hole=0.45,
                    textinfo="label+percent"))
                fig_pie.update_layout(height=300, margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
                st.plotly_chart(fig_pie, use_container_width=True)
            with cc2:
                st.markdown("##### 📊 各標的損益")
                bv = [r["損益($)"] for r in valid_pf if isinstance(r["損益($)"],float)]
                bl = [r["代碼"] for r in valid_pf if isinstance(r["損益($)"],float)]
                fig_bar = go.Figure(go.Bar(x=bl, y=bv,
                    marker_color=["#2ECC71" if v>=0 else "#E74C3C" for v in bv],
                    text=[f"{v:+.2f}" for v in bv], textposition="outside"))
                fig_bar.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
                fig_bar.update_layout(height=300, margin=dict(l=0,r=0,t=10,b=0),
                                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig_bar, use_container_width=True)

        disp = pd.DataFrame([{k:v for k,v in r.items() if k!="_cost_t"} for r in rows_pf])
        def cpnl(v):
            if isinstance(v,(int,float)): return f"color:{'#2ECC71' if v>=0 else '#E74C3C'};font-weight:500"
            return ""
        st.dataframe(disp.style.applymap(cpnl, subset=["損益($)","損益(%)"]), use_container_width=True, hide_index=True)

        # CSV 匯出組合
        csv_pf = disp.to_csv(index=False).encode('utf-8-sig')
        st.download_button("⬇️ 下載組合 CSV", csv_pf, "portfolio.csv", "text/csv")

        st.markdown("---")
        st.markdown("##### 🗑️ 移除持倉")
        d1,d2 = st.columns([3,1])
        dtk = d1.selectbox("選擇要刪除的標的", pf_df['ticker'].tolist(), key="del_tkr")
        if d2.button("刪除", type="secondary", use_container_width=True, key="btn_del"):
            portfolio_delete(user, dtk); st.success(f"已移除 {dtk}"); st.rerun()

# ══════════════════════════════════════════
# TAB 10：價格警報
# ══════════════════════════════════════════
with tab_alert:
    st.markdown("#### 🔔 價格警報設定")
    st.caption("設定目標價，每次載入頁面時自動比對並在頂部顯示警示橫幅。")

    with st.expander("➕ 新增警報", expanded=True):
        al1,al2,al3 = st.columns([2,1.5,1.5])
        al_ticker = al1.text_input("股票代碼", value=ticker_symbol, key="al_ticker").upper()
        al_high   = al2.number_input("突破高點警報（選填，0=不設定）", min_value=0.0, value=0.0, step=0.01, key="al_high")
        al_low    = al3.number_input("跌破低點警報（選填，0=不設定）", min_value=0.0, value=0.0, step=0.01, key="al_low")
        if st.button("🔔 儲存警報", use_container_width=True, key="btn_al"):
            if al_ticker:
                alert_set(user, al_ticker, al_high if al_high>0 else None, al_low if al_low>0 else None)
                st.success(f"{al_ticker} 警報設定成功！"); st.rerun()

    al_df = alert_load(user)
    if not al_df.empty:
        st.markdown("##### 目前警報清單")
        # 顯示目前各警報的現價狀態
        al_rows = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            al_prices = dict(f.result() for f in as_completed({ex.submit(_get_price,t):t for t in al_df['ticker']}))
        for _, ar in al_df.iterrows():
            px = al_prices.get(ar['ticker'])
            status = "正常 ✅"
            if px and ar['alert_high'] and px >= ar['alert_high']: status = "🚨 突破高點！"
            if px and ar['alert_low'] and px <= ar['alert_low']:  status = "⚠️ 跌破低點！"
            al_rows.append({"代碼":ar['ticker'],"現價":f"{px:.2f}" if px else "N/A",
                             "高點警報":ar['alert_high'] or "未設","低點警報":ar['alert_low'] or "未設","狀態":status})
        st.dataframe(pd.DataFrame(al_rows), use_container_width=True, hide_index=True)

        del_al = st.selectbox("選擇要刪除的警報", al_df['ticker'].tolist(), key="del_al")
        if st.button("🗑️ 刪除警報", key="btn_del_al"):
            alert_delete(user, del_al); st.success(f"已刪除 {del_al} 警報"); st.rerun()
    else:
        st.info("目前沒有設定任何警報。")

# ══════════════════════════════════════════
# TAB 11：交易日記
# ══════════════════════════════════════════
with tab_diary:
    st.markdown("#### 📓 交易日記")
    with st.expander("✍️ 新增交易記錄", expanded=False):
        dr1,dr2,dr3 = st.columns([1.5,1.5,1])
        dr_date   = dr1.date_input("交易日期", datetime.date.today(), key="dr_date")
        dr_ticker = dr2.text_input("代碼", value=ticker_symbol, key="dr_ticker").upper()
        dr_dir    = dr3.selectbox("方向", ["買入","賣出","觀察"], key="dr_dir")
        dr4,dr5   = st.columns(2)
        dr_price  = dr4.number_input("成交價格", min_value=0.0, value=float(latest_price), step=0.01, key="dr_price")
        dr_shares = dr5.number_input("股數", min_value=0.0, value=1.0, step=1.0, key="dr_shares")
        dr_note   = st.text_area("交易心得 / 理由", placeholder="記錄進場/出場理由、市場觀察、情緒狀態...", key="dr_note")
        if st.button("💾 儲存日記", use_container_width=True, key="btn_dr"):
            diary_add(user, dr_date, dr_ticker, dr_dir, dr_price, dr_shares, dr_note)
            st.success("✅ 記錄已儲存！"); st.rerun()

    diary_df = diary_load(user)
    if not diary_df.empty:
        st.markdown(f"##### 共 {len(diary_df)} 筆交易記錄")

        # 篩選器
        flt1,flt2 = st.columns(2)
        filter_ticker = flt1.text_input("依代碼篩選（留空=全部）", key="flt_tk").upper()
        filter_dir    = flt2.selectbox("依方向篩選", ["全部","買入","賣出","觀察"], key="flt_dir")

        show_df = diary_df.copy()
        if filter_ticker: show_df = show_df[show_df['ticker'].str.contains(filter_ticker)]
        if filter_dir != "全部": show_df = show_df[show_df['direction'] == filter_dir]

        # 顏色標示方向
        def dir_color(v):
            if v == "買入": return "color:#2ECC71;font-weight:500"
            if v == "賣出": return "color:#E74C3C;font-weight:500"
            return "color:#F39C12"

        styled_diary = show_df.rename(columns={'trade_date':'日期','ticker':'代碼',
            'direction':'方向','price':'價格','shares':'股數','note':'心得'}).drop(columns=['id'])
        st.dataframe(styled_diary.style.applymap(dir_color, subset=['方向']),
                     use_container_width=True, hide_index=True)

        # CSV 匯出日記
        csv_diary = styled_diary.to_csv(index=False).encode('utf-8-sig')
        st.download_button("⬇️ 下載日記 CSV", csv_diary, "trade_diary.csv", "text/csv")

        # 刪除
        del_id = st.number_input("輸入要刪除的記錄 ID", min_value=1, step=1, key="del_diary_id")
        if st.button("🗑️ 刪除此筆記錄", key="btn_del_diary"):
            diary_delete(user, int(del_id)); st.success("已刪除"); st.rerun()
    else:
        st.info("📭 尚無交易記錄，開始寫下第一筆日記吧！")

# ══════════════════════════════════════════
# TAB 12：Gemini AI
# ══════════════════════════════════════════
with tab_gemini:
    st.markdown(f"#### 🧠 Gemini AI 深度分析")
    analysis_mode = st.radio("分析模式", ["📰 新聞情緒分析","📊 技術面綜合解讀","💡 投資策略建議"], horizontal=True)

    if news_data:
        news_titles = []
        if analysis_mode == "📰 新聞情緒分析":
            st.markdown("**最新新聞：**")
            for item in news_data[:5]:
                content = item.get('content') or {}
                title = item.get('title') or content.get('title','無標題')
                click = content.get('clickThroughUrl') or {}
                link  = item.get('link') or click.get('url','#')
                st.markdown(f"- **[{title}]({link})**")
                news_titles.append(title)

    if st.button("✨ 啟動 Gemini 分析", type="primary", key="btn_gemini"):
        rsi_v = float(data['RSI'].iloc[-1]) if 'RSI' in data.columns else 0
        tech_summary = f"RSI:{rsi_v:.1f}, 技術評分:{score}/100, 現價:{latest_price:.2f}, 日漲跌:{day_chg_pct:+.2f}%"

        if analysis_mode == "📰 新聞情緒分析":
            prompt = f"你是華爾街金融分析師。請分析 {ticker_symbol} 最新新聞，判斷市場情緒（看漲/看跌/中立）並說明原因：\n" + "\n".join(news_titles)
        elif analysis_mode == "📊 技術面綜合解讀":
            prompt = f"你是技術分析師。請針對 {ticker_symbol} 的技術數據給出繁體中文分析：{tech_summary}。請說明目前趨勢、關鍵支撐壓力位、短線操作建議。"
        else:
            prompt = f"你是資深投資顧問。根據 {ticker_symbol} 的技術面數據（{tech_summary}），請提供三種不同風險偏好（保守/穩健/積極）投資者的操作策略建議，用繁體中文回覆。"

        cache_key = f"{ticker_symbol}_{analysis_mode}_{hash(prompt)}"
        if cache_key in st.session_state['gemini_cache']:
            st.info("（快取結果）"); st.write(st.session_state['gemini_cache'][cache_key])
        else:
            with st.spinner("Gemini 深度推理中..."):
                try:
                    genai.configure(api_key=GEMINI_API_KEY)
                    gm = genai.GenerativeModel('gemini-2.5-flash')
                    resp = gm.generate_content(prompt)
                    st.session_state['gemini_cache'][cache_key] = resp.text
                    st.success("分析完成！"); st.write(resp.text)
                except Exception as e:
                    st.error(f"AI 分析失敗：{e}")

# ══════════════════════════════════════════
# TAB 13：IoT
# ══════════════════════════════════════════
with tab_iot:
    st.markdown("#### 🔌 微控制器資料拋轉介面")
    st.caption("提供標準化 JSON，供 ESP32 / Arduino 透過 HTTP GET 讀取。")
    sma20_v = float(data['SMA20'].iloc[-1]) if ('SMA20' in data.columns and not pd.isna(data['SMA20'].iloc[-1])) else 0.0
    rsi_v   = float(data['RSI'].iloc[-1])   if ('RSI'   in data.columns and not pd.isna(data['RSI'].iloc[-1]))   else 0.0
    action  = ("HOLD_OR_BUY" if latest_price > sma20_v else "SELL_OR_WAIT") if sma20_v > 0 else "DATA_TOO_SHORT"
    st.json({"device":"ESP32","ticker":ticker_symbol,"price":round(latest_price,2),
             "sma20":round(sma20_v,2),"rsi":round(rsi_v,2),"signal":action,
             "tech_score":score,"rsi_alert":"OVERSOLD" if rsi_v<30 else ("OVERBOUGHT" if rsi_v>70 else "NORMAL"),
             "user":user})
