# -*- coding: gbk -*-
import os
import pandas as pd
import math
import numpy as np
import seaborn as sns
from scipy.stats import spearmanr,pearsonr
import glob
from datetime import datetime, timedelta
import statsmodels.api as sm
from shapely.geometry import LineString
from scipy.spatial.distance import pdist, squareform
from sklearn.metrics import mutual_info_score
import matplotlib.dates as mdates
from tqdm import tqdm
from typing import List, Optional
import warnings
warnings.filterwarnings('ignore') 



#=== 纯因子计算函数（保持不变） ====================

def _calc_single_period_pure_factor(
    df_period: pd.DataFrame,
    factor_cols: list,
    ind_col: str,
    cap_col: str,
    ret_col: str,
) -> pd.Series:
    cols_to_check = factor_cols + [ind_col, cap_col, ret_col]
    df = df_period.dropna(subset=cols_to_check).copy()
    if df.empty:
        return pd.Series(dtype=float)

    sqrt_cap = np.sqrt(df[cap_col].values)
    w_vec = sqrt_cap / np.sum(sqrt_cap)

    ind_dummies = pd.get_dummies(df[ind_col], dtype=float)
    ind_cols = ind_dummies.columns.tolist()

    X_df = pd.concat([df[factor_cols], ind_dummies], axis=1)
    X_df['nation'] = 1.0
    X = X_df.values
    columns_all = factor_cols + ind_cols + ['nation']

    ind_weights = df.groupby(ind_col)[cap_col].sum()
    ind_weights = ind_weights / ind_weights.sum()

    M = len(columns_all)
    C = np.eye(M)

    ind_start_idx = len(factor_cols)
    ind_end_idx = ind_start_idx + len(ind_cols)
    free_ind_idx = ind_end_idx - 1
    free_ind_name = ind_cols[-1]
    C = np.delete(C, free_ind_idx, axis=1)

    w_free = ind_weights[free_ind_name]
    for i, ind_name in enumerate(ind_cols[:-1]):
        col_idx = ind_start_idx + i
        C[free_ind_idx, col_idx] = -ind_weights[ind_name] / w_free

    XC = X @ C
    XC_T_W = XC.T * w_vec[None, :]
    mid_mat = XC_T_W @ XC

    try:
        mid_mat_inv = np.linalg.inv(mid_mat)
    except np.linalg.LinAlgError:
        print("截面矩阵接近奇异，采用伪逆(pinv)进行计算。")
        mid_mat_inv = np.linalg.pinv(mid_mat)

    Omega = C @ mid_mat_inv @ XC_T_W
    R = df[ret_col].values
    f_returns = Omega @ R

    return pd.Series(f_returns, index=columns_all)


def run_barra_pure_factor_model(
    panel_data: pd.DataFrame,
    factor_cols: list,
    ind_col: str = 'SW_L1',
    cap_col: str = 'circ_mv',
    ret_col: str = 'return_to_forecast',
    date_col: str = 'date',
    output_path: str = None,
) -> pd.DataFrame:
    results = []
    dates = []
    panel_data = panel_data.sort_values(by=date_col)
    grouped = panel_data.groupby(date_col)

    for current_date, group in grouped:
        period_pure_ret = _calc_single_period_pure_factor(
            df_period=group,
            factor_cols=factor_cols,
            ind_col=ind_col,
            cap_col=cap_col,
            ret_col=ret_col,
        )
        if not period_pure_ret.empty:
            results.append(period_pure_ret)
            dates.append(current_date)

    res_df = pd.DataFrame(results, index=dates)
    res_df.index.name = date_col
    cumulative_returns = res_df.fillna(0).cumsum()

    if output_path is not None:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cumulative_returns.to_excel(output_path)

    return cumulative_returns


# ==================== 数据预处理函数（修正日期解析） ====================

def get_valid_dates(
    barra_folder: str,
    alpha_folder: str,
    stock_folder: str,
    start_date: str,
    end_date: str,
) -> List[str]:
    """
    获取所有有效日期（同时存在 Barra CSV、Alpha Parquet、行情 CSV 的日期）
    返回日期列表，格式为 YYYY-MM-DD（字符串）
    """
    date_range = pd.date_range(start=start_date, end=end_date, freq='B')
    possible_dates = [d.strftime('%Y-%m-%d') for d in date_range]

    valid_dates = []
    for date_str in possible_dates:
        barra_file = os.path.join(barra_folder, f"{date_str}.csv")
        alpha_file = os.path.join(alpha_folder, f"{date_str.replace('-', '')}.parquet")
        stock_file = os.path.join(stock_folder, f"{date_str.replace('-', '')}.csv")
        if os.path.exists(barra_file) and os.path.exists(alpha_file) and os.path.exists(stock_file):
            valid_dates.append(date_str)
    return valid_dates


def load_stock_data(stock_folder: str, date_str: str, ticker_col: str, cap_col: str) -> pd.DataFrame:
    """加载单个日期的行情 CSV 文件（文件名 YYYYMMDD.csv）"""
    file_path = os.path.join(stock_folder, f"{date_str.replace('-', '')}.csv")
    if not os.path.exists(file_path):
        return pd.DataFrame()
    df = pd.read_csv(file_path)
    # 标准化股票代码列
    if ticker_col not in df.columns:
        for alias in ['symbol', 'stock_code', 'code']:
            if alias in df.columns:
                ticker_col = alias
                break
    if ticker_col not in df.columns:
        raise ValueError(f"Stock file {file_path} missing ticker column")
    required = [ticker_col, cap_col, 'openPrice', 'closePrice']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Stock file {file_path} missing columns: {missing}")
    df = df[[ticker_col, cap_col, 'openPrice', 'closePrice']].copy()
    df['date'] = pd.to_datetime(date_str)   # 直接使用传入的日期字符串，确保 datetime
    return df


def build_panel_data(
    barra_folder: str,
    stock_folder: str,
    alpha_folder: str,
    start_date: str,
    end_date: str,
    style_factor_cols: List[str],
    alpha_factor_name: str = 'alpha_191_factors_001',
    industry_cols_in_barra: List[str] = None,
    cap_col: str = 'negMarketValue',          # 行情文件中的市值列名
    ticker_col: str = 'ticker',
    ret_type: str = 'close',                  # 'close' 或 'open'
    ret_col_output: str = 'return_to_forecast',
    industry_output_name: str = 'SW_L1',
) -> pd.DataFrame:
    """
    构建与 mock_data 格式一致的 panel_data
    """
    valid_dates = get_valid_dates(barra_folder, alpha_folder, stock_folder, start_date, end_date)
    if len(valid_dates) < 2:
        raise ValueError("Need at least two valid dates to compute forward returns")
    print(f"Found {len(valid_dates)} valid trading dates")

    all_data = []

    for idx, date_str in enumerate(tqdm(valid_dates, desc="Processing dates")):
        # 确定下一个交易日（和 open 模式下下下个交易日）
        if idx == len(valid_dates) - 1:
            continue
        next_date = valid_dates[idx + 1]
        next_next_date = valid_dates[idx + 2] if ret_type == 'open' and idx + 2 < len(valid_dates) else None

        # ----- 1. 加载 Barra 数据，并统一日期格式 -----
        barra_file = os.path.join(barra_folder, f"{date_str}.csv")
        df_barra = pd.read_csv(barra_file)
        # 处理日期列：可能是字符串或整数
        if 'tradeDate' in df_barra.columns:
            if pd.api.types.is_integer_dtype(df_barra['tradeDate']):
                df_barra['date'] = pd.to_datetime(df_barra['tradeDate'].astype(str), format='%Y%m%d')
            else:
                df_barra['date'] = pd.to_datetime(df_barra['tradeDate'])
        else:
            # 如果没有 tradeDate 列，用文件名中的日期
            df_barra['date'] = pd.to_datetime(date_str)

        # 统一股票代码列名
        if ticker_col not in df_barra.columns:
            for alias in ['symbol', 'stock_code', 'code']:
                if alias in df_barra.columns:
                    ticker_col_barra = alias
                    break
            else:
                continue
        else:
            ticker_col_barra = ticker_col

        base_cols = [ticker_col_barra, 'date'] + style_factor_cols
        missing = [c for c in base_cols if c not in df_barra.columns]
        if missing:
            print(f"Barra file {barra_file} missing columns: {missing}, skip")
            continue
        df_barra_sub = df_barra[base_cols].copy()
        df_barra_sub.rename(columns={ticker_col_barra: ticker_col}, inplace=True)

        # 行业哑变量转分类列
        if industry_cols_in_barra is None:
            known_cols = set(base_cols + ['tradeDate'])
            candidate_industry_cols = [c for c in df_barra.columns if c not in known_cols and c[0].isupper()]
            industry_cols_in_barra = candidate_industry_cols
        industry_series = pd.Series(index=df_barra_sub.index, dtype=str)
        for ind in industry_cols_in_barra:
            if ind not in df_barra.columns:
                continue
            mask = df_barra[ind] == 1
            industry_series.loc[mask] = ind
        industry_series.fillna('Other', inplace=True)
        df_barra_sub[industry_output_name] = industry_series

        # ----- 2. 加载 Alpha 因子，正确解析整数日期 -----
        alpha_file = os.path.join(alpha_folder, f"{date_str.replace('-', '')}.parquet")
        if not os.path.exists(alpha_file):
            continue
        df_alpha = pd.read_parquet(alpha_file)

        # 处理 Alpha 文件中的日期列
        if 'date' in df_alpha.columns:
            if pd.api.types.is_integer_dtype(df_alpha['date']):
                df_alpha['date'] = pd.to_datetime(df_alpha['date'].astype(str), format='%Y%m%d')
            else:
                df_alpha['date'] = pd.to_datetime(df_alpha['date'])
        elif 'tradeDate' in df_alpha.columns:
            if pd.api.types.is_integer_dtype(df_alpha['tradeDate']):
                df_alpha['date'] = pd.to_datetime(df_alpha['tradeDate'].astype(str), format='%Y%m%d')
            else:
                df_alpha['date'] = pd.to_datetime(df_alpha['tradeDate'])
        else:
            # 如果没有日期列，则用文件名中的日期（date_str 已经是 YYYY-MM-DD）
            df_alpha['date'] = pd.to_datetime(date_str)

        # 统一股票代码列
        if ticker_col not in df_alpha.columns:
            for alias in ['symbol', 'stock_code', 'code']:
                if alias in df_alpha.columns:
                    ticker_col_alpha = alias
                    break
            else:
                continue
        else:
            ticker_col_alpha = ticker_col

        if alpha_factor_name not in df_alpha.columns:
            continue
        df_alpha_sub = df_alpha[[ticker_col_alpha, 'date', alpha_factor_name]].copy()
        df_alpha_sub.rename(columns={alpha_factor_name: 'alpha_factor', ticker_col_alpha: ticker_col}, inplace=True)

        # ----- 3. 加载行情数据并计算收益率 -----
        try:
            df_stock_cur = load_stock_data(stock_folder, date_str, ticker_col, cap_col)
            if df_stock_cur.empty:
                continue
            df_stock_next = load_stock_data(stock_folder, next_date, ticker_col, cap_col)
            if df_stock_next.empty:
                continue
        except Exception as e:
            print(f"Stock data error for {date_str}: {e}")
            continue

        if ret_type == 'close':
            # close-to-close
            merged_price = pd.merge(
                df_stock_cur[[ticker_col, cap_col, 'closePrice']],
                df_stock_next[[ticker_col, 'closePrice']],
                on=ticker_col, suffixes=('', '_next')
            )
            merged_price[ret_col_output] = merged_price['closePrice_next'] / merged_price['closePrice'] - 1
        elif ret_type == 'open':
            if next_next_date is None:
                continue
            try:
                df_stock_next = load_stock_data(stock_folder, next_date, ticker_col, cap_col)
                if df_stock_next.empty:
                    continue
                df_stock_next_next = load_stock_data(stock_folder, next_next_date, ticker_col, cap_col)
                if df_stock_next_next.empty:
                    continue
            except Exception as e:
                print(f"Stock data error for {next_date} or {next_next_date}: {e}")
                continue
            # open-to-open: (t+2 开盘价) / (t+1 开盘价) - 1
            merged_open = pd.merge(
                df_stock_next[[ticker_col, 'openPrice']].rename(columns={'openPrice': 'open_t1'}),
                df_stock_next_next[[ticker_col, 'openPrice']].rename(columns={'openPrice': 'open_t2'}),
                on=ticker_col, how='inner'
            )
            merged_open[ret_col_output] = merged_open['open_t2'] / merged_open['open_t1'] - 1
            # 与当前市值合并，使用 inner 保证有收益率的股票才保留
            merged_price = pd.merge(
                df_stock_cur[[ticker_col, cap_col]],
                merged_open[[ticker_col, ret_col_output]],
                on=ticker_col, how='inner'
            )
        else:
            raise ValueError("ret_type must be 'close' or 'open'")

        # ----- 4. 合并所有数据 -----
        merged = pd.merge(df_barra_sub, df_alpha_sub, on=[ticker_col, 'date'], how='inner')
        merged = pd.merge(merged, merged_price, on=[ticker_col], how='inner')
        merged = merged.dropna(subset=[ret_col_output])

        if merged.empty:
            continue

        final_cols = ['date', ticker_col] + style_factor_cols + ['alpha_factor', industry_output_name, cap_col, ret_col_output]
        merged = merged[final_cols]
        all_data.append(merged)

    if not all_data:
        raise ValueError("No data loaded for any date")

    panel_data = pd.concat(all_data, ignore_index=True)
    return panel_data
