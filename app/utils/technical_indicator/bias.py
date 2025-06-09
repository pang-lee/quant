def calculate_bias_ratio(df_close1, df_close2, ma_period, use_ratio=False):
    """
    計算K棒的乖離率 (Bias Ratio)
    
    參數:
        df_close1 (pd.Series): 第一資產的K棒收盤價
        df_close2 (pd.Series): 第二資產的K棒收盤價
        ma_period (int): 移動平均的週期 (K棒數)
        use_ratio (bool): 若為True，使用價格比率 (df_close2 / df_close1)；若為False，使用價格差異 (df_close2 - df_close1)
    
    返回:
        pd.Series: 乖離率 (百分比)
    """
    # 確保輸入數據對齊
    df_close1, df_close2 = df_close1.align(df_close2, join='inner')
    
    if use_ratio:
        # 計算價格比率
        spread = df_close2 / df_close1
    else:
        # 計算價格差異
        spread = df_close2 - df_close1
    
    # 計算移動平均線
    ma_spread = spread.ewm(span=ma_period, adjust=False).mean()
    
    # 計算乖離率
    bias_ratio = (spread - ma_spread) / ma_spread * 100
    
    # 返回乖離率，去除NaN值
    return bias_ratio.dropna()
