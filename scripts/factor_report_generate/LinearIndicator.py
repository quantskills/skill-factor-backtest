# -*- coding: gbk -*-
import os
import pandas as pd
import math
import numpy as np
from scipy.stats import spearmanr,pearsonr
import statsmodels.api as sm
from shapely.geometry import LineString






def get_ols_stats(group_data):
    stats=[]
    for i in range(10):
        X_data = pd.Series(range(len(group_data)),index=group_data.index)
        y_data = group_data[f'group_{i}']
        model = sm.OLS(y_data, X_data)
        results = model.fit()
        t_value=results.tvalues.values[0]
        r2=results.rsquared
        param=results.params.values[0]
        stats.append([f'group_{i}',t_value,r2,param])
    stats=pd.DataFrame(stats,columns=['group_name','t_value','r2','param'])
    return stats
def get_LS_indicator(group_data):
    group_data=group_data.diff().fillna(0)
    LS=group_data[f'group_9']-group_data[f'group_0']
    LS_mean=LS.mean()
    LS_SE=LS.std(ddof=1)/np.sqrt(len(LS))
    LS_tvalue=LS_mean/LS_SE
    return LS_mean,LS_tvalue


def get_linear_indicator(group_data):
    group_ret=group_data.diff().fillna(0)
    label = pd.DataFrame(
            np.tile(np.arange(10), (group_ret.shape[0], 1)),index=group_ret.index,
            columns=group_ret.columns)
    corr=group_ret.corrwith(label,axis=1)
    linear_indicator=corr.mean()
    linear_indicator_stability=linear_indicator/corr.std()
    return linear_indicator,linear_indicator_stability


def get_insec_point(group_data):
    x=list(range(len(group_data)))
    n_curves = group_data.shape[1]
    total_intersections = 0
    lines=[]
    for group in group_data.columns:
        points = list(zip(x, group_data[group].tolist()))
        line = LineString(points)
        lines.append(line)
    res=[]
    for i in range(n_curves):
        for j in range(i+1, n_curves):
            intersections = lines[i].intersection(lines[j])
            if intersections.geom_type == 'Point':
                count = 1
            elif intersections.geom_type == 'MultiPoint':
                count = len(intersections.geoms)
            else:
                count = 0
            res.append([i,j,count])
    res=pd.DataFrame(res,columns=['x','y','count'])
    return res

def get_group_stats(factor_name, folder_path,max_window = 1000):
    stats=[]
    all_type_list=['raw']

    for style in all_type_list:
            group_data=pd.read_csv(folder_path+'group_pnls/group_ret_window1.csv').set_index('date')

            if group_data.shape[0]<min(500,max_window):
                continue
            linear_indicator,linear_indicator_stability = get_linear_indicator(group_data)
            ols_stats=get_ols_stats(group_data)
            distribute_indicator=ols_stats['r2'].mean()
            insec=get_insec_point(group_data)
            insec_mean=insec['count'].mean()
            stats.append([factor_name,linear_indicator,linear_indicator_stability,distribute_indicator,insec_mean])
    stats=pd.DataFrame(stats,columns=['factor_name','线性指标','线性稳定性','非线性度量','交点均值'])
    return stats
