import pandas as pd
from datetime import datetime, timedelta

def convert_ohlcv(df, freq=60):
    freq = int(freq) if isinstance(freq, str) else int(freq)
    
    # 建立 session_type 與 session_start
    def classify_session(ts):
        try:
            # 確保無時區
            ts = ts.tz_localize(None) if ts.tzinfo else ts
            time = ts.time()
    
            # 明確定義時間邊界
            day_start = datetime.strptime("08:45", "%H:%M").time()
            day_end = datetime.strptime("13:45", "%H:%M").time()
            night_start = datetime.strptime("15:00", "%H:%M").time()
            night_end = datetime.strptime("05:00", "%H:%M").time()

            if day_start <= time <= day_end:
                session_type = "day"
                session_date = ts.date()
                session_start = datetime.combine(session_date, day_start)
            elif time >= night_start:
                session_type = "night"
                session_date = ts.date()
                session_start = datetime.combine(session_date, night_start)
            elif time <= night_end:
                session_type = "night"
                session_date = (ts - timedelta(days=1)).date()
                session_start = datetime.combine(session_date, night_start)
            else:
                session_type = "other"
                session_start = pd.NaT

            return pd.Series([session_type, session_start], index=["session_type", "session_start"])
        except Exception as e:
            print(f"時間轉換出現錯誤 {ts}: {e}")
            return pd.Series([None, None], index=["session_type", "session_start"])

    # 修改1: 使用 .loc 明確賦值
    df.loc[:, ["session_type", "session_start"]] = df.index.to_series().apply(classify_session)

    # 修改2: 過濾後強制創建副本
    df = df[df["session_type"].isin(["day", "night"])].copy()
    
    # ✅ 將 index 向前推 1 分鐘
    df.index = df.index - pd.Timedelta(minutes=1)

    # 設定 K 棒時間長度
    window = timedelta(minutes=freq)
    
    # 分段處理每個 session 的資料
    result = []

    for session_start, session_data in df.groupby("session_start"):
        current_time = session_start
        max_time = session_data.index.max()

        while current_time < max_time:
            next_time = current_time + window
            window_data = session_data[(session_data.index >= current_time) & (session_data.index < next_time)]

            if not window_data.empty:
                o = window_data["open"].iloc[0]
                h = window_data["high"].max()
                l = window_data["low"].min()
                c = window_data["close"].iloc[-1]
                v = window_data["volume"].sum()
                complete = window_data.index[-1] >= next_time - timedelta(minutes=1)

                result.append({
                    "ts": current_time,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": v,
                    "complete": complete
                })

            current_time = next_time

    # 建立新的 DataFrame
    agg_df = pd.DataFrame(result)
    if 'ts' in agg_df.columns:
        agg_df.set_index('ts', inplace=True)

    return agg_df
