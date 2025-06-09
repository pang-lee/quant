import numpy as np

def shift_log(close1, close2, log=False):
    if log:
        log_returns_df1 = np.log(close1 / close1.shift(1)).dropna()
        log_returns_df2 = np.log(close2 / close2.shift(1)).dropna()
        series1 = log_returns_df2 - log_returns_df1
        
    else:
        returns_df1 = (close1 / close1.shift(1)).dropna()
        returns_df2 = (close2 / close2.shift(1)).dropna()
        series1 = returns_df2 / returns_df1        
        
    series1 = series1.replace([np.inf, -np.inf], 0).dropna()
    return series1

def diff_change(close1, close2, pct=False):
    if pct:
        series1 = (close2 - close1).dropna().pct_change().dropna()
    else:
        series1 = (close2 - close1).diff().dropna()
        
    series1 = series1.replace([np.inf, -np.inf], 0)
    return series1

def diff_change_shift(close1, close2):
    diff = close2 / close1
    series1 = ((diff - diff.shift(1)) / diff.shift(1)).dropna()
    series1 = series1.replace([np.inf, -np.inf], 0)
    return series1

