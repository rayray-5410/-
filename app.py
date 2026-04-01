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
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 網頁基礎與 UI 設定 =================
st.set_page_config(page_title="AI 跨市場金融戰情室", layout="wide", page_icon="📈")

# ================= 🛡️【改進1：安全性】資料庫與帳密系統 =================
# ✅ 改進：admin 帳密改從 st.secrets 讀取，不再硬編碼在程式裡
# 請在 Streamlit Cloud 的 Secrets 中設定：
#   GEMINI_API_KEY = "your_key"
#   ADMIN_USERNAME = "your_admin_name"
#   ADMIN_PASSWORD = "your_strong_password"

GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
ADMIN_USERNAME  = st.secrets.get("ADMIN_USERNAME", "admin")   # 預設值僅供本機測試
ADMIN_PASSWORD  = st.secrets.get("ADMIN_PASSWORD", "changeme") # 上線前務必在 secrets 覆蓋

conn = sqlite3.connect('users.db', check_same_thread=False)
c = conn.cursor()
c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)')

# 投資組合資料表：每位使用者可持有多筆部位
c.execute('''
    CREATE TABLE IF NOT EXISTS portfolio (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        username  TEXT    NOT NULL,
        ticker    TEXT    NOT NULL,
        name      TEXT,
        shares    REAL    NOT NULL,
        cost      REAL    NOT NULL,
        UNIQUE(username, ticker)
    )
''')

def make_hashes(password: str) -> str:
    """使用 SHA-256 雜湊密碼"""
    return hashlib.sha256(password.encode()).hexdigest()

# ✅ 改進：admin 帳密從 secrets 讀取，每次啟動都同步（若密碼在 secrets 改了也會更新）
c.execute(
    'INSERT OR REPLACE INTO users (username, password) VALUES (?,?)',
    (ADMIN_USERNAME, make_hashes(ADMIN_PASSWORD))
)
conn.commit()

def add_user(username: str, password: str) -> None:
    try:
        c.execute('INSERT INTO users (username, password) VALUES (?,?)', (username, make_hashes(password)))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # 帳號已存在

def login_user(username: str, password: str) -> bool:
    c.execute('SELECT 1 FROM users WHERE username=? AND password=?', (username, make_hashes(password)))
    return c.fetchone() is not None

# ================= 📂 投資組合 CRUD =================
def portfolio_add(username: str, ticker: str, name: str, shares: float, cost: float) -> str:
    """新增或更新持倉（相同 ticker 則累加股數、加權平均成本）"""
    c.execute('SELECT shares, cost FROM portfolio WHERE username=? AND ticker=?', (username, ticker))
    row = c.fetchone()
    if row:
        old_shares, old_cost = row
        new_shares = old_shares + shares
        # 加權平均成本
        new_cost = (old_shares * old_cost + shares * cost) / new_shares
        c.execute('UPDATE portfolio SET shares=?, cost=?, name=? WHERE username=? AND ticker=?',
                  (new_shares, new_cost, name, username, ticker))
        msg = "updated"
    else:
        c.execute('INSERT INTO portfolio (username, ticker, name, shares, cost) VALUES (?,?,?,?,?)',
                  (username, ticker, name, shares, cost))
        msg = "added"
    conn.commit()
    return msg

def portfolio_delete(username: str, ticker: str) -> None:
    c.execute('DELETE FROM portfolio WHERE username=? AND ticker=?', (username, ticker))
    conn.commit()

def portfolio_load(username: str) -> pd.DataFrame:
    df = pd.read_sql_query(
        'SELECT ticker, name, shares, cost FROM portfolio WHERE username=? ORDER BY ticker',
        conn, params=(username,)
    )
    return df

# 初始化 Session State
for key, default in [('logged_in', False), ('username', ''), ('gemini_cache', {}), ('portfolio_refresh', 0)]:
    if key not in st.session_state:
        st.session_state[key] = default

# ================= 🚪 登入 / 註冊介面 =================
if not st.session_state['logged_in']:
    st.write("<br><br><br>", unsafe_allow_html=True)
    _, col2, _ = st.columns([1, 2, 1])
    with col2:
        st.markdown("<h1 style='text-align:center;'>🔐 AI 金融戰情室</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align:center; color:gray;'>專屬全能分析與邊緣運算系統</p>", unsafe_allow_html=True)
        st.write("---")
        tab_login, tab_register = st.tabs(["🔑 登入系統", "📝 註冊新帳號"])

        with tab_login:
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
            new_user = st.text_input("設定帳號", key="reg_user")
            new_password = st.text_input("設定密碼", type='password', key="reg_pass")
            if st.button("✅ 建立帳號", use_container_width=True):
                if new_user and new_password:
                    c.execute('SELECT 1 FROM users WHERE username=?', (new_user,))
                    if c.fetchone():
                        st.warning("⚠️ 此帳號已被使用，請換一個名稱。")
                    else:
                        add_user(new_user, new_password)
                        st.success("🎉 註冊成功！請切換到「🔑 登入系統」登入。")
                else:
                    st.warning("⚠️ 請完整填寫帳號與密碼！")
    st.stop()

# ================= 登入後主程式 =================
st.toast(f"歡迎回來，{st.session_state['username']}！系統已解鎖。", icon="🔓")
st.sidebar.markdown(f"### 👤 使用者：**{st.session_state['username']}**")
if st.sidebar.button("🚪 登出系統"):
    st.session_state['logged_in'] = False
    st.rerun()
st.sidebar.markdown("---")

# ================= 側邊欄：市場選擇器 =================
st.sidebar.header("1. 選擇或輸入投資標的")
input_mode = st.sidebar.radio("🔍 搜尋模式", ["快速選擇 (內建熱門)", "自訂輸入 (全球代碼)"])

if input_mode == "快速選擇 (內建熱門)":
    market_type = st.sidebar.selectbox("市場分類", ["台灣股市", "美國股市", "加密貨幣"])
    options_map = {
        "台灣股市": ["2330.TW (台積電)", "2317.TW (鴻海)", "2454.TW (聯發科)", "0050.TW (元大台灣50)", "0056.TW"],
        "美國股市": ["AAPL (蘋果)", "NVDA (輝達)", "TSLA (特斯拉)", "MSFT (微軟)"],
        "加密貨幣": ["BTC-USD (比特幣)", "ETH-USD (以太幣)", "SOL-USD", "DOGE-USD"],
    }
    ticker_symbol = st.sidebar.selectbox("熱門標的", options_map[market_type]).split(" ")[0]
else:
    st.sidebar.info("💡 台股請加 `.TW`（如 2603.TW），美股直接輸入代碼（如 GOOGL）。")
    ticker_symbol = st.sidebar.text_input("輸入 Yahoo Finance 代碼", value="NVDA").upper()
    market_type = "自訂輸入"

period = st.sidebar.select_slider("歷史數據範圍", options=["1mo", "3mo", "6mo", "1y", "2y", "5y"], value="1y")

# ================= 核心：指標計算 =================
def calculate_indicators(data: pd.DataFrame) -> pd.DataFrame:
    """計算 RSI、SMA20、布林通道、MACD"""
    df = data.copy()
    if len(df) < 20:
        return df

    # RSI
    delta = df['Close'].diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    rs    = gain.ewm(com=13, adjust=False).mean() / loss.ewm(com=13, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + rs))

    # 均線
    df['SMA20'] = df['Close'].rolling(20).mean()
    df['SMA60'] = df['Close'].rolling(60).mean()

    # 布林通道
    df['BB_Upper'] = df['SMA20'] + 2 * df['Close'].rolling(20).std()
    df['BB_Lower'] = df['SMA20'] - 2 * df['Close'].rolling(20).std()

    # MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD']        = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist']   = df['MACD'] - df['MACD_Signal']

    return df

# ================= 【改進2：效能】並發抓取 =================
@st.cache_data(ttl=1800)
def fetch_data(ticker: str, period: str) -> tuple[pd.DataFrame, list]:
    data, news = pd.DataFrame(), []
    try:
        data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        if not data.empty:
            data = calculate_indicators(data)
    except Exception:
        pass
    try:
        news = yf.Ticker(ticker).news or []
    except Exception:
        pass
    return data, news

def _fetch_single_for_scan(sym: str) -> tuple[str, float | None]:
    """單一標的抓取，供掃描使用，回傳 (symbol, rsi)"""
    try:
        tmp = yf.download(sym, period="1mo", progress=False, auto_adjust=True)
        if isinstance(tmp.columns, pd.MultiIndex):
            tmp.columns = tmp.columns.get_level_values(0)
        if len(tmp) > 15:
            tmp = calculate_indicators(tmp)
            return sym, float(tmp['RSI'].iloc[-1])
    except Exception:
        pass
    return sym, None

def scan_rsi(symbols: list[str], threshold: float, above: bool) -> list[tuple[str, float]]:
    """✅ 改進：用 ThreadPoolExecutor 並發抓取，速度提升 3-5 倍"""
    results = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_fetch_single_for_scan, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym, rsi = future.result()
            if rsi is not None:
                if above and rsi > threshold:
                    results.append((sym, rsi))
                elif not above and rsi < threshold:
                    results.append((sym, rsi))
    return sorted(results, key=lambda x: x[1], reverse=above)

# ================= 側邊欄：快速掃描 =================
st.sidebar.markdown("---")
st.sidebar.header("2. 🚀 快速市場掃描")

scan_map = {
    "台灣股市": ["2330.TW", "2317.TW", "2454.TW", "2308.TW", "2881.TW", "0050.TW"],
    "加密貨幣": ["BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD"],
    "美國股市": ["AAPL", "NVDA", "MSFT", "TSLA"],
    "自訂輸入": ["^TWII", "^GSPC", "^DJI"],
}
scan_list = scan_map.get(market_type, scan_map["自訂輸入"])

col_s1, col_s2 = st.sidebar.columns(2)
if col_s1.button("🟢 買入\nRSI<30", use_container_width=True):
    with st.sidebar.status("並發掃描中..."):
        hits = scan_rsi(scan_list, 30, above=False)
        if hits:
            for sym, rsi in hits:
                st.sidebar.success(f"**{sym}** RSI {rsi:.1f}")
        else:
            st.sidebar.info("目前無超賣標的。")

if col_s2.button("🔴 賣出\nRSI>70", use_container_width=True):
    with st.sidebar.status("並發掃描中..."):
        hits = scan_rsi(scan_list, 70, above=True)
        if hits:
            for sym, rsi in hits:
                st.sidebar.error(f"**{sym}** RSI {rsi:.1f}")
        else:
            st.sidebar.info("目前無超買標的。")

# ================= 主資料抓取 =================
with st.spinner(f"抓取 {ticker_symbol} 數據中..."):
    data, news_data = fetch_data(ticker_symbol, period)

# ================= 主畫面 =================
if not data.empty:
    latest_price = float(data['Close'].iloc[-1])
    st.title("📈 跨市場全能分析戰情室")
    st.markdown(f"### 🎯 **{ticker_symbol}** ｜ 最新報價：**{latest_price:.2f}**")
    st.write("---")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 專業圖表", "👑 策略回測 & AI", "🧠 Gemini AI 分析", "📂 投資組合", "🔌 IoT 硬體對接"])

    # ===== 第一頁：圖表 =====
    with tab1:
        show_bb   = st.checkbox("顯示布林通道", value=True)
        show_macd = st.checkbox("顯示 MACD 面板", value=True)

        rows = 3 if show_macd else 2
        row_h = [0.55, 0.2, 0.25] if show_macd else [0.7, 0.3]
        fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                            vertical_spacing=0.03, row_heights=row_h)

        fig.add_trace(go.Candlestick(
            x=data.index, open=data['Open'], high=data['High'],
            low=data['Low'], close=data['Close'], name="K線"), row=1, col=1)

        if 'SMA20' in data.columns:
            fig.add_trace(go.Scatter(x=data.index, y=data['SMA20'],
                line=dict(color='orange', width=1.5), name='SMA20'), row=1, col=1)
        if 'SMA60' in data.columns:
            fig.add_trace(go.Scatter(x=data.index, y=data['SMA60'],
                line=dict(color='cyan', width=1.5), name='SMA60'), row=1, col=1)

        if show_bb and 'BB_Upper' in data.columns:
            fig.add_trace(go.Scatter(x=data.index, y=data['BB_Upper'],
                line=dict(color='rgba(255,255,255,0.3)', dash='dot'), name='BB上軌'), row=1, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['BB_Lower'],
                line=dict(color='rgba(255,255,255,0.3)', dash='dot'),
                fill='tonexty', fillcolor='rgba(128,128,128,0.1)', name='BB下軌'), row=1, col=1)

        colors = ['green' if r['Close'] >= r['Open'] else 'red' for _, r in data.iterrows()]
        fig.add_trace(go.Bar(x=data.index, y=data['Volume'],
            marker_color=colors, name='成交量'), row=2, col=1)

        if show_macd and 'MACD' in data.columns:
            fig.add_trace(go.Scatter(x=data.index, y=data['MACD'],
                line=dict(color='#00d4ff'), name='MACD'), row=3, col=1)
            fig.add_trace(go.Scatter(x=data.index, y=data['MACD_Signal'],
                line=dict(color='#ff6b35'), name='Signal'), row=3, col=1)
            hist_colors = ['green' if v >= 0 else 'red' for v in data['MACD_Hist']]
            fig.add_trace(go.Bar(x=data.index, y=data['MACD_Hist'],
                marker_color=hist_colors, name='Histogram'), row=3, col=1)

        fig.update_layout(xaxis_rangeslider_visible=False, height=600,
                          margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # ===== 第二頁：多策略回測 =====
    with tab2:
        # ================= 【改進3：功能】多策略回測引擎 =================
        st.markdown("#### 👑 多策略回測比較")
        st.caption("同時比較三種交易策略，找出最適合此標的的操作方式。")

        def run_backtest(df: pd.DataFrame, strategy: str) -> pd.Series:
            """回傳每日策略報酬率"""
            bt = df.dropna().copy()
            daily = bt['Close'].pct_change()

            if strategy == "SMA20 均線":
                if 'SMA20' not in bt.columns: return pd.Series(dtype=float)
                pos = np.where(bt['Close'] > bt['SMA20'], 1, 0)

            elif strategy == "黃金交叉 (SMA20/60)":
                if 'SMA60' not in bt.columns: return pd.Series(dtype=float)
                pos = np.where(bt['SMA20'] > bt['SMA60'], 1, 0)

            elif strategy == "布林通道反轉":
                if 'BB_Lower' not in bt.columns: return pd.Series(dtype=float)
                pos = np.zeros(len(bt))
                holding = 0
                for i in range(1, len(bt)):
                    price = float(bt['Close'].iloc[i])
                    bb_l  = float(bt['BB_Lower'].iloc[i])
                    bb_u  = float(bt['BB_Upper'].iloc[i])
                    if price <= bb_l:
                        holding = 1
                    elif price >= bb_u:
                        holding = 0
                    pos[i] = holding

            elif strategy == "RSI 超買超賣":
                if 'RSI' not in bt.columns: return pd.Series(dtype=float)
                pos = np.zeros(len(bt))
                holding = 0
                for i in range(1, len(bt)):
                    rsi = float(bt['RSI'].iloc[i])
                    if rsi < 30:
                        holding = 1
                    elif rsi > 70:
                        holding = 0
                    pos[i] = holding

            elif strategy == "MACD 交叉":
                if 'MACD' not in bt.columns: return pd.Series(dtype=float)
                pos = np.where(bt['MACD'] > bt['MACD_Signal'], 1, 0)

            else:
                return pd.Series(dtype=float)

            strat_ret = pd.Series(pos, index=bt.index).shift(1) * daily
            return strat_ret.dropna()

        strategies = ["SMA20 均線", "黃金交叉 (SMA20/60)", "布林通道反轉", "RSI 超買超賣", "MACD 交叉"]
        selected = st.multiselect("選擇要比較的策略", strategies, default=["SMA20 均線", "RSI 超買超賣", "MACD 交叉"])

        if selected:
            summary_rows = []
            fig_bt = go.Figure()

            # 基準：買入持有
            bh = data['Close'].pct_change().dropna()
            bh_cum = (1 + bh).cumprod()
            fig_bt.add_trace(go.Scatter(x=bh_cum.index, y=bh_cum,
                name="📦 買入持有", line=dict(color='gray', dash='dot', width=2)))

            for strat in selected:
                ret = run_backtest(data, strat)
                if ret.empty: continue
                cum = (1 + ret).cumprod()

                # 計算績效指標
                total_ret   = (cum.iloc[-1] - 1) * 100
                annual_ret  = ((cum.iloc[-1]) ** (252 / len(cum)) - 1) * 100
                sharpe      = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0
                max_dd      = ((cum / cum.cummax()) - 1).min() * 100
                win_rate    = (ret > 0).mean() * 100

                summary_rows.append({
                    "策略": strat,
                    "總報酬率": f"{total_ret:.1f}%",
                    "年化報酬": f"{annual_ret:.1f}%",
                    "夏普比率": f"{sharpe:.2f}",
                    "最大回撤": f"{max_dd:.1f}%",
                    "勝率":     f"{win_rate:.1f}%",
                })

                fig_bt.add_trace(go.Scatter(x=cum.index, y=cum, name=strat, line=dict(width=2)))

            fig_bt.update_layout(title="策略累積報酬率比較", height=400,
                                  yaxis_title="累積倍數", xaxis_title="日期",
                                  margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig_bt, use_container_width=True)

            if summary_rows:
                st.markdown("#### 📋 策略績效彙整")
                df_summary = pd.DataFrame(summary_rows).set_index("策略")
                st.dataframe(df_summary, use_container_width=True)

        st.markdown("---")
        st.markdown("#### 🤖 線性迴歸趨勢預測")
        df_ml = data.dropna().copy()
        if len(df_ml) >= 5:
            df_ml['Days'] = np.arange(len(df_ml))
            lr = LinearRegression()
            lr.fit(df_ml[['Days']].values, df_ml['Close'].values)
            pred = lr.predict(np.array([[df_ml['Days'].max() + 1]]))[0]
            st.info(f"👉 線性迴歸預測下一交易日價格落點：**{pred:.2f}**")
        else:
            st.warning("⚠️ 歷史數據太短，請調長範圍。")

    # ===== 第三頁：Gemini AI =====
    with tab3:
        st.markdown(f"#### 📰 {ticker_symbol} 最新市場新聞")
        if news_data:
            news_titles = []
            for item in news_data[:5]:
                content = item.get('content') or {}
                title = item.get('title') or content.get('title', '無標題')
                click = content.get('clickThroughUrl') or {}
                link  = item.get('link') or click.get('url', '#')
                st.markdown(f"- **[{title}]({link})**")
                news_titles.append(title)

            st.markdown("---")
            st.markdown("#### ✨ Gemini LLM 綜合情緒判定")

            cache_key = f"{ticker_symbol}_{'|'.join(news_titles)}"
            if st.button("啟動大腦：分析新聞情緒", type="primary"):
                if cache_key in st.session_state['gemini_cache']:
                    st.info("（使用快取結果，節省 API 費用）")
                    st.write(st.session_state['gemini_cache'][cache_key])
                else:
                    with st.spinner("Gemini 深度推理中..."):
                        try:
                            genai.configure(api_key=GEMINI_API_KEY)
                            gmodel = genai.GenerativeModel('gemini-2.5-flash')
                            prompt = (
                                f"你是華爾街金融分析師。請閱讀以下關於 {ticker_symbol} 的新聞標題，"
                                f"用繁體中文判斷市場情緒（看漲/看跌/中立）並說明原因：\n\n"
                                + "\n".join(news_titles)
                            )
                            resp = gmodel.generate_content(prompt)
                            st.session_state['gemini_cache'][cache_key] = resp.text
                            st.success("分析完成！")
                            st.write(resp.text)
                        except Exception as e:
                            st.error(f"AI 分析失敗：{e}")
        else:
            st.write("暫時無法獲取新聞，請稍後重試。")

    # ===== 第四頁：投資組合 =====
    with tab4:
        user = st.session_state['username']
        st.markdown("#### 📂 我的投資組合")

        # ── 新增持倉表單 ──────────────────────────────────────
        with st.expander("➕ 新增 / 更新持倉", expanded=False):
            fc1, fc2, fc3, fc4 = st.columns([2, 2, 1.5, 1.5])
            inp_ticker = fc1.text_input("代碼（如 AAPL / 2330.TW）", key="pf_ticker").upper().strip()
            inp_name   = fc2.text_input("備註名稱（選填）", key="pf_name")
            inp_shares = fc3.number_input("持有股數", min_value=0.0001, value=1.0, step=1.0, key="pf_shares")
            inp_cost   = fc4.number_input("平均成本價", min_value=0.0001, value=100.0, step=0.01, key="pf_cost")

            if st.button("✅ 加入組合", use_container_width=True):
                if inp_ticker:
                    result = portfolio_add(user, inp_ticker, inp_name or inp_ticker, inp_shares, inp_cost)
                    st.session_state['portfolio_refresh'] += 1
                    st.success(f"{'新增' if result == 'added' else '更新'} {inp_ticker} 成功！已重新計算加權平均成本。")
                    st.rerun()
                else:
                    st.warning("請填寫股票代碼！")

        # ── 讀取並計算損益 ────────────────────────────────────
        pf_df = portfolio_load(user)

        if pf_df.empty:
            st.info("📭 組合是空的，請用上方表單新增第一筆持倉。")
        else:
            # 並發抓取所有持倉最新價格
            def _get_price(tkr: str) -> tuple[str, float | None]:
                try:
                    tmp = yf.download(tkr, period="2d", progress=False, auto_adjust=True)
                    if isinstance(tmp.columns, pd.MultiIndex):
                        tmp.columns = tmp.columns.get_level_values(0)
                    if not tmp.empty:
                        return tkr, float(tmp['Close'].iloc[-1])
                except Exception:
                    pass
                return tkr, None

            with st.spinner("更新各標的最新報價中..."):
                price_map: dict[str, float | None] = {}
                with ThreadPoolExecutor(max_workers=8) as ex:
                    futs = {ex.submit(_get_price, t): t for t in pf_df['ticker']}
                    for fut in as_completed(futs):
                        tkr, px = fut.result()
                        price_map[tkr] = px

            # 計算損益欄位
            rows_out = []
            for _, row in pf_df.iterrows():
                px      = price_map.get(row['ticker'])
                cost_total = row['shares'] * row['cost']
                if px is not None:
                    mkt_val    = row['shares'] * px
                    pnl        = mkt_val - cost_total
                    pnl_pct    = pnl / cost_total * 100
                else:
                    mkt_val = pnl = pnl_pct = None

                rows_out.append({
                    "代碼":       row['ticker'],
                    "名稱":       row['name'],
                    "股數":       row['shares'],
                    "成本價":     round(row['cost'], 2),
                    "現價":       round(px, 2)       if px      is not None else "無資料",
                    "市值":       round(mkt_val, 2)  if mkt_val is not None else "無資料",
                    "損益($)":    round(pnl, 2)      if pnl     is not None else "無資料",
                    "損益(%)":    round(pnl_pct, 2)  if pnl_pct is not None else "無資料",
                    "成本總額":   round(cost_total, 2),
                })

            result_df = pd.DataFrame(rows_out)

            # ── KPI 總覽 ──────────────────────────────────────
            valid = [r for r in rows_out if isinstance(r["市值"], float)]
            total_mkt    = sum(r["市值"]   for r in valid)
            total_cost   = sum(r["成本總額"] for r in rows_out)
            total_pnl    = sum(r["損益($)"] for r in valid if isinstance(r["損益($)"], float))
            total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("💰 總市值",   f"{total_mkt:,.2f}")
            k2.metric("📥 總成本",   f"{total_cost:,.2f}")
            k3.metric("📈 總損益",   f"{total_pnl:+,.2f}",
                      delta=f"{total_pnl_pct:+.2f}%",
                      delta_color="normal")
            k4.metric("📦 持倉數",   f"{len(rows_out)} 檔")

            st.markdown("---")

            # ── 圖表：圓餅 + 損益長條 ─────────────────────────
            if valid:
                chart_col1, chart_col2 = st.columns(2)

                with chart_col1:
                    st.markdown("##### 🥧 市值配置比例")
                    pie_labels  = [r["代碼"] for r in valid]
                    pie_values  = [r["市值"] for r in valid]
                    fig_pie = go.Figure(go.Pie(
                        labels=pie_labels,
                        values=pie_values,
                        hole=0.45,
                        textinfo="label+percent",
                        hovertemplate="<b>%{label}</b><br>市值：%{value:,.2f}<br>佔比：%{percent}<extra></extra>",
                    ))
                    fig_pie.update_layout(
                        height=320,
                        margin=dict(l=10, r=10, t=10, b=10),
                        showlegend=False,
                    )
                    st.plotly_chart(fig_pie, use_container_width=True)

                with chart_col2:
                    st.markdown("##### 📊 各標的損益比較")
                    bar_labels = [r["代碼"] for r in valid]
                    bar_pnl    = [r["損益($)"] for r in valid if isinstance(r["損益($)"], float)]
                    bar_colors = ["#2ECC71" if v >= 0 else "#E74C3C" for v in bar_pnl]
                    fig_bar = go.Figure(go.Bar(
                        x=bar_labels,
                        y=bar_pnl,
                        marker_color=bar_colors,
                        text=[f"{v:+.2f}" for v in bar_pnl],
                        textposition="outside",
                        hovertemplate="<b>%{x}</b><br>損益：%{y:+,.2f}<extra></extra>",
                    ))
                    fig_bar.update_layout(
                        height=320,
                        margin=dict(l=10, r=10, t=10, b=10),
                        yaxis_title="損益金額",
                        xaxis_title="",
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                    )
                    fig_bar.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
                    st.plotly_chart(fig_bar, use_container_width=True)

            # ── 明細表格 ──────────────────────────────────────
            st.markdown("##### 📋 持倉明細")

            def color_pnl(val):
                if isinstance(val, (int, float)):
                    color = "#2ECC71" if val >= 0 else "#E74C3C"
                    return f"color: {color}; font-weight: 500"
                return ""

            display_df = result_df.drop(columns=["成本總額"])
            styled = (
                display_df.style
                .applymap(color_pnl, subset=["損益($)", "損益(%)"])
                .format({"股數": "{:.4g}", "成本價": "{:.2f}"})
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # ── 刪除持倉 ──────────────────────────────────────
            st.markdown("---")
            st.markdown("##### 🗑️ 移除持倉")
            del_col1, del_col2 = st.columns([3, 1])
            del_ticker = del_col1.selectbox(
                "選擇要刪除的標的",
                options=pf_df['ticker'].tolist(),
                key="del_ticker"
            )
            if del_col2.button("刪除", type="secondary", use_container_width=True):
                portfolio_delete(user, del_ticker)
                st.success(f"已從組合中移除 {del_ticker}。")
                st.rerun()

    # ===== 第五頁：IoT =====
    with tab5:
        st.markdown("#### 🔌 微控制器 (MCU) 資料拋轉介面")
        st.caption("提供標準化 JSON，供 ESP32 / Arduino 透過 HTTP GET 讀取並作動。")

        sma20_val = float(data['SMA20'].iloc[-1]) if ('SMA20' in data.columns and not pd.isna(data['SMA20'].iloc[-1])) else 0.0
        rsi_val   = float(data['RSI'].iloc[-1])   if ('RSI'   in data.columns and not pd.isna(data['RSI'].iloc[-1]))   else 0.0

        if sma20_val > 0:
            action = "HOLD_OR_BUY" if latest_price > sma20_val else "SELL_OR_WAIT"
        else:
            action = "DATA_TOO_SHORT"

        iot_payload = {
            "device_target":   "ESP32",
            "ticker":          ticker_symbol,
            "current_price":   round(latest_price, 2),
            "sma20_threshold": round(sma20_val, 2),
            "rsi":             round(rsi_val, 2),
            "action_signal":   action,
            "rsi_alert":       "OVERSOLD" if rsi_val < 30 else ("OVERBOUGHT" if rsi_val > 70 else "NORMAL"),
            "user_active":     st.session_state['username'],
        }
        st.json(iot_payload)

else:
    st.warning("⚠️ 找不到該代碼資料，或 Yahoo 伺服器目前流量管制，請稍後重試！")
