# -*- coding: utf-8 -*-
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
from tqdm import tqdm




def get_forward_returns(open_pivot, lags=[1,2,3]):
    """返回一个字典：lag -> DataFrame (日期 × 股票，未来收益率)"""
    ret_dict = {}
    for lag in lags:
        # 计算 (t+lag) 开盘价 / t 开盘价 - 1
        ret = (open_pivot.shift(-lag+1) - open_pivot.shift(-1)) / open_pivot.shift(-1)
        # 将收益率与因子日期对齐：因子在 t 日，对应未来 lag 日的收益率
        # 但 ret 的 index 是 t 日，value 是 t+lag 日收益率
        ret_dict[lag] = ret 
    return ret_dict



def entropy(labels):
    _, counts = np.unique(labels, return_counts=True)
    probs = counts / len(labels)
    return -np.sum(probs * np.log(probs))

def clean_xy(x, y, min_samples=30):
    x = pd.to_numeric(pd.Series(x), errors='coerce').to_numpy(dtype=np.float64, copy=False)
    y = pd.to_numeric(pd.Series(y), errors='coerce').to_numpy(dtype=np.float64, copy=False)

    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < min_samples:
        return None, None

    x = x[mask]
    y = y[mask]

    if len(np.unique(x)) < 2 or len(np.unique(y)) < 2:
        return None, None

    return x, y

def build_nmi_labels(values, n_bins=10):
    values = np.asarray(values)
    unique_count = len(np.unique(values))
    if unique_count < 2:
        return None

    # 低离散度因子直接按类别编码，避免 qcut 把二值/多值离散信号压成单一分箱。
    if unique_count <= n_bins:
        return pd.factorize(values, sort=True)[0].astype(np.float64)

    try:
        labels = pd.qcut(values, q=n_bins, labels=False, duplicates='drop')
    except ValueError:
        effective_bins = min(n_bins, unique_count)
        if effective_bins < 2:
            return None
        labels = pd.qcut(values, q=effective_bins, labels=False, duplicates='drop')

    labels = np.asarray(labels, dtype=np.float64)
    finite = np.isfinite(labels)
    if finite.sum() == 0:
        return None

    if len(np.unique(labels[finite])) < 2:
        return pd.factorize(values, sort=True)[0].astype(np.float64)

    return labels

def calc_nmi(x, y, n_bins=10):
    if len(x) == 0 or len(y) == 0:
        return np.nan

    x_bins = build_nmi_labels(x, n_bins=n_bins)
    y_bins = build_nmi_labels(y, n_bins=n_bins)
    if x_bins is None or y_bins is None:
        return 0.0

    mask = np.isfinite(x_bins) & np.isfinite(y_bins)
    if mask.sum() == 0:
        return np.nan
    x_bins = x_bins[mask]
    y_bins = y_bins[mask]
    mi = mutual_info_score(x_bins, y_bins)
    hx = entropy(x_bins)
    hy = entropy(y_bins)
    if hx == 0 or hy == 0:
        return 0.0
    return mi / np.sqrt(hx * hy)

def distance_correlation(x, y):
    n = len(x)
    if n < 4:
        return np.nan
    # 计算距离矩阵
    a = squareform(pdist(x.reshape(-1,1), metric='euclidean'))
    b = squareform(pdist(y.reshape(-1,1), metric='euclidean'))
    # 双中心化
    A = a - a.mean(axis=0, keepdims=True) - a.mean(axis=1, keepdims=True) + a.mean()
    B = b - b.mean(axis=0, keepdims=True) - b.mean(axis=1, keepdims=True) + b.mean()
    # 距离协方差和方差
    dCov = np.sqrt((A * B).sum() / (n * n))
    dVarX = np.sqrt((A * A).sum() / (n * n))
    dVarY = np.sqrt((B * B).sum() / (n * n))
    if dVarX == 0 or dVarY == 0:
        return 0.0
    return dCov / np.sqrt(dVarX * dVarY)

def compute_metrics_for_lag(factor_df, ret_df, lag, start_time, end_time, factor_name, n_bins=10):
    """
    factor_df: 因子表，含 ticker, date, factor_name
    ret_df: DataFrame (日期 × 股票) 未来 lag 天的收益率
    返回该滞后下的 NMI 和 dCor 截面序列及均值
    """
    nmi_series = []
    dcor_series = []
    
    factor_df = factor_df[(factor_df['date']>=pd.Timestamp(start_time)) & (factor_df['date']<=pd.Timestamp(end_time))].reset_index(drop=True)
    ret_df = ret_df[(ret_df.index>=pd.Timestamp(start_time)) & (ret_df.index<=pd.Timestamp(end_time))]
    
    
    # 获取因子和收益率共有的日期
    common_dates = sorted(set(factor_df['date']).intersection(ret_df.index))
    
    for dt in tqdm(common_dates):
        # 该日期的因子值
        factor_slice = factor_df[factor_df['date'] == dt].set_index('ticker')[factor_name]
        # 该日期的未来收益率（对应 lag 天后的收益）
        ret_slice = ret_df.loc[dt].dropna()
        # 合并
        merged = pd.DataFrame({
            'factor': factor_slice,
            'return': ret_slice
        }).dropna()
        if len(merged) < 30:  # 样本太少则跳过
            continue
        # 计算
        x = merged['factor'].values
        y = merged['return'].values
        x, y = clean_xy(x, y, min_samples=30)
        if x is None:
            continue
        # 剔除异常值（可选，根据数据情况）
        x = np.clip(x, np.percentile(x, 1), np.percentile(x, 99))
        y = np.clip(y, np.percentile(y, 1), np.percentile(y, 99))
        x, y = clean_xy(x, y, min_samples=30)
        if x is None:
            continue
        nmi = calc_nmi(x, y, n_bins=n_bins)
        dcor = distance_correlation(x, y)
        if not np.isnan(nmi):
            nmi_series.append(nmi)
        if not np.isnan(dcor):
            dcor_series.append(dcor)
    return np.mean(nmi_series), np.mean(dcor_series), nmi_series, dcor_series
