def calculate_ema(df, span=5):
    return df.ewm(span=span, adjust=False).mean().dropna()
