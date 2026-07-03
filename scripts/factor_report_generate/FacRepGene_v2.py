# -*- coding: gbk -*-
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.font_manager as fm
import math
import numpy as np
import seaborn as sns
from scipy.stats import spearmanr,pearsonr
import glob
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import statsmodels.api as sm
from shapely.geometry import LineString
from scipy.spatial.distance import pdist, squareform
from sklearn.metrics import mutual_info_score
import matplotlib.dates as mdates
from tqdm import tqdm
import LinearIndicator
import NonLinearIndicator
import PureFactorReturn


fm.fontManager.addfont('fonts/MSYH.TTC')
plt.rcParams['font.family'] = 'Microsoft YaHei'
plt.rcParams['axes.unicode_minus'] = False


def get_report(folder_path, factor_path, folder_path_comparison_factor, folder_path_comparison_backtest, mkt_data_path, STOCK_FOLDER, ALPHA_FOLDER, BARRA_FOLDER,
output_pdf, stock_price_daily, factor_name, reverse=False, insample_last_day = 20241231, outsample_last_day = 20260123):

    #导入因子数据
    if factor_path[-4:] == '.csv':
        df = pd.read_csv(factor_path)
    elif factor_path[-4:] == 'quet':
        df = pd.read_parquet(factor_path)
    else:
        search_path = os.path.join(factor_path, '*')
        files = glob.glob(search_path)
        fac_df = pd.DataFrame()
        for i in range(len(files)):
            file = files[i]
            if file[-4:] == '.csv':
                fac_df_cache = pd.read_csv(file)
            elif file[-4:] == 'quet':
                fac_df_cache = pd.read_parquet(file)
            fac_df=pd.concat([fac_df,fac_df_cache])
        df = fac_df.sort_values(by = ['ticker','date']).reset_index(drop=True)

    df = df.sort_values(by = ['ticker','date']).reset_index(drop=True)
    
    
    
    linear_stats = LinearIndicator.get_group_stats(factor_name, folder_path)
    linear_stats = linear_stats.round(4)
    linear_stats.to_excel(folder_path+'linear_indicator.xlsx')
    
    
    #计算因子自相关性
    def plot_factor_autocorrelation(
        df,
        factor_name,
        date_col='date',
        ticker_col='ticker',
        max_lag=20,
        use_rank=True,
        plot_ci=True,
        min_sample=5,
        figsize=(10,6)
    ):

        # 数据准备
        data = df[[ticker_col, date_col, factor_name]].copy()
        data['date'] = pd.to_datetime(data[date_col].astype(str), format='%Y%m%d')
        data = data.sort_values([ticker_col, 'date']).reset_index(drop=True)

        if use_rank:
            # 计算横截面排名（百分比排名）
            data['rank'] = data.groupby('date')[factor_name].rank(pct=True)
            # 透视：日期为行，股票为列，值为排名
            pivot = data.pivot(index='date', columns=ticker_col, values='rank')
            pivot = pivot.sort_index()
            value_label = 'rank'
        else:
            # 直接使用因子值
            pivot = data.pivot(index='date', columns=ticker_col, values=factor_name)
            pivot = pivot.sort_index()
            value_label = 'factor value'

        lags = range(1, max_lag + 1)
        acf_vals = []
        acf_stds = []

        for lag in lags:
            cors = []
            # 对齐 t 期与 t-lag 期
            shifted = pivot.shift(-lag)
            # 逐日期计算相关系数
            for idx in pivot.index[:-lag]:
                if idx not in shifted.index:
                    continue
                # 取出该日期和滞后日期的数据（Series）
                current = pivot.loc[idx]
                past = shifted.loc[idx]
                # 构建临时DataFrame，并删除任一列为nan的股票
                temp = pd.DataFrame({'current': current, 'past': past}).dropna()
                if len(temp) < min_sample:
                    continue
                # 计算 Spearman 相关系数
                try:
                    r, _ = pearsonr(temp['past'], temp['current'])
                    if not np.isnan(r):
                        cors.append(r)
                except Exception:
                    # 如果 spearmanr 出错（如常数序列），跳过该日期
                    continue

            if len(cors) > 0:
                acf_vals.append(np.mean(cors))
                acf_stds.append(np.std(cors, ddof=1) / np.sqrt(len(cors)))
            else:
                acf_vals.append(np.nan)
                acf_stds.append(np.nan)

        acf_df = pd.DataFrame({
            'lag': list(lags),
            'autocorr': acf_vals,
            'std_err': acf_stds
        })

        # 绘图
        fig, ax = plt.subplots(figsize=figsize)
        valid = acf_df['autocorr'].notna()
        if valid.any():
            ax.bar(acf_df.loc[valid, 'lag'], acf_df.loc[valid, 'autocorr'],
                   width=0.6, color='steelblue' if use_rank else 'seagreen', edgecolor='k')
            if plot_ci:
                ci = 1.96 * acf_df.loc[valid, 'std_err']
                ax.errorbar(acf_df.loc[valid, 'lag'], acf_df.loc[valid, 'autocorr'],
                            yerr=ci, fmt='none', ecolor='darkred', capsize=3)
        else:
            ax.text(0.5, 0.5, 'No valid data for any lag', ha='center', va='center')

        ax.axhline(y=0, linestyle='--', color='gray')
        ax.set_xlabel('Lag (trading days)')
        ax.set_ylabel(f'Average {value_label} autocorrelation')
        # title = f'Factor {"Rank" if use_rank else "Value"} Stability - {factor_name}'
        # if use_rank:
        #     title = '因子rank自相关性'
        # else:
        #     title = '因子值自相关性'
        # ax.set_title(title,fontsize = 11)
        ax.set_xticks(lags[::2] if max_lag > 10 else lags)
        plt.tight_layout()

        acf_df.to_csv(folder_path+'acf.csv')
        return acf_df, fig
    
    
    
    #因子年度分布
    def plot_consistent_yearly_distribution(df, factor_col, date_col='date', output_path=folder_path+'yearly_dist.png'):
        work_df = df.copy()

        # 1. 截面标准化
        work_df[factor_col] = work_df.groupby(date_col)[factor_col].transform(
            lambda x: (x - x.mean()) / x.std() if x.std() != 0 else 0
        )

        # 2. 时间处理
        work_df['year'] = pd.to_datetime(work_df[date_col].astype(str), format='%Y%m%d').dt.year
        years = sorted(work_df['year'].unique())
        num_years = len(years)

        if num_years == 0:
            print("No valid data")
            return

        # --- 关键调整：定义统一的箱体边界 ---
        # 我们固定在 -4 到 4 之间画 80 根柱子，这样每根柱子的宽度固定为 0.1
        fixed_bins = np.linspace(-4, 4, 81) 

        # 3. 布局计算
        cols = 3
        rows = math.ceil(num_years / cols)
        fig, axes = plt.subplots(rows, cols, figsize=(18, 5 * rows), squeeze=False)
        axes = axes.flatten()

        # 4. 循环绘图
        for i, year in enumerate(years):
            # 显式剔除空值，避免绘图报错
            year_data = work_df[work_df['year'] == year][factor_col].dropna()

            # 使用统一的 bins 序列，而不是整数
            axes[i].hist(year_data, bins=fixed_bins, color='#4C72B0', edgecolor='white', alpha=0.8)

            # 强制所有子图的 X 轴范围一致
            axes[i].set_xlim(-4, 4)

            axes[i].set_title(f"{year}", fontsize=15, fontweight='bold')
            axes[i].set_xlabel("value", fontsize=12)
            axes[i].set_ylabel("count", fontsize=12)
            axes[i].grid(axis='y', linestyle='--', alpha=0.3)

        # 5. 移除多余子图
        for j in range(i + 1, len(axes)):
            fig.delaxes(axes[j])

        plt.tight_layout()
        plt.savefig(output_path, bbox_inches='tight', dpi=300)
        plt.close()
        print(f"因子年度分布已保存至: {output_path}")
     
        
    #计算因子衰减    
    def calculate_ic_decay(ICs, output_path=None):
    
        # 1. 读取输入数据
        if isinstance(ICs, str):
            # 假设是 CSV 文件路径
            df = pd.read_csv(ICs)
        elif isinstance(ICs, pd.DataFrame):
            df = ICs.copy()
        else:
            raise TypeError("ICs 参数必须是 pandas DataFrame 或 CSV 文件路径字符串")
    
        # 2. 检查必要列
        if 'date' not in df.columns:
            raise KeyError("DataFrame 中缺少 'date' 列")
        ic_cols = [col for col in df.columns if col.startswith('single_')]
        if not ic_cols:
            raise ValueError("没有找到以 'single_' 开头的 IC 列")
    
        # 3. 计算各期限 IC 均值
        ic_means = df[ic_cols].mean()
    
        # 4. 提取天数并生成中文标签（用于绘图）
        # 列名格式如 'single_1d', 'single_10d' -> 提取数字部分
        days = []
        for col in ic_cols:
            # 去掉 'single_' 前缀，再去掉末尾的 'd'
            num_str = col.split('_')[1].replace('d', '')
            days.append(int(num_str))
        # 按天数排序
        sorted_indices = sorted(range(len(days)), key=lambda i: days[i])
        days_sorted = [days[i] for i in sorted_indices]
        means_sorted = ic_means.iloc[sorted_indices].values
        chinese_labels = [f'第{d}日' for d in days_sorted]
    
        # 5. 构建返回的 DataFrame
        ic_summary = pd.DataFrame({
            '天数': days_sorted,
            'IC均值': means_sorted
        })
    
    
        # 7. 保存 CSV（使用 UTF-8 BOM 以便 Excel 正常显示中文）
        ic_summary.to_csv(folder_path+'ic_summary.csv', index=False, encoding='utf-8-sig')
    
        # 8. 绘制条形图
        plt.figure(figsize=(10, 6))
        bars = plt.bar(chinese_labels, means_sorted, color='steelblue', alpha=1)
    
        # 在柱顶添加数值标签
        for bar, val in zip(bars, means_sorted):
            plt.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                     f'{val:.4f}', ha='center', va='bottom', fontsize=9)
    
        # plt.title('IC衰减', fontsize=14)
        plt.xlabel('预测时间', fontsize=12)
        plt.ylabel('IC 均值', fontsize=12)
        plt.xticks(rotation=45, ha='right')
        plt.grid(axis='y', linestyle='--', alpha=1)
        plt.tight_layout()
    
        # 保存图片
        plt.savefig(output_path, dpi=300)
        # plt.close()  # 关闭图形，避免交互式显示（若需要显示可注释）
    
        return ic_summary
        
        
    
    #生成因子年度分布
    plot_consistent_yearly_distribution(df, factor_name)
    # 生成排名自相关图（use_rank=True）
    acf_rank, fig_rank = plot_factor_autocorrelation(
        df,
        factor_name=factor_name,
        use_rank=True,
        max_lag=20
    )

    lag1_rank_autocorr = acf_rank.loc[acf_rank['lag'] == 1, 'autocorr'].values[0]
    print(f"Lag1 rank autocorrelation: {lag1_rank_autocorr:.4f}")
    fig_rank.savefig(folder_path+'rank_autocorrelation.png', dpi=300, bbox_inches='tight')
    plt.close(fig_rank)
    
    # 生成因子值自相关图（use_rank=False）
    acf_val, fig_val = plot_factor_autocorrelation(
        df,
        factor_name=factor_name,
        use_rank=False,
        max_lag=20
    )
    fig_val.savefig(folder_path+'value_autocorrelation.png', dpi=300, bbox_inches='tight')
    plt.close(fig_val)
    
    #IC衰减
    ICs_df_index = pd.read_csv(folder_path+'ICs.csv',index_col = 0)
    ICs_df = pd.read_csv(folder_path+'ICs.csv')
    ic_summary, ic_daily = calculate_ic_decay(ICs_df, output_path=folder_path+'ic_decay.png')
    
    
    #因子自相关
    df_insample = df[df['date']<=insample_last_day].reset_index(drop=True)
    df_outsample = df[df['date']>insample_last_day].reset_index(drop=True)


    acf_rank_insample, _ = plot_factor_autocorrelation(
        df_insample,
        factor_name=factor_name,
        use_rank=True,
        max_lag=20
    )
    plt.close(_)
    acf_rank_outsample, _ = plot_factor_autocorrelation(
        df_outsample,
        factor_name=factor_name,
        use_rank=True,
        max_lag=20
    )
    plt.close(_)
    lag1_rank_autocorr_insample = acf_rank_insample.loc[acf_rank_insample['lag'] == 1, 'autocorr'].values[0]
    lag1_rank_autocorr_outsample = acf_rank_outsample.loc[acf_rank_outsample['lag'] == 1, 'autocorr'].values[0]
    lag1_rank_autocorr_total = lag1_rank_autocorr
    
    
    
    #因子评价指标
    def calc_index1(stat):
        stat = stat.dropna()
        stat.index = pd.to_datetime(stat.index)
        years = (stat.index[-1] - stat.index[0]).days / 365
        total_return = stat.values[-1] / stat.values[0]
        annualized_return = np.exp(np.log(total_return) / years) - 1
        annualized_volatility = (stat.shift(1) / stat).std() * np.sqrt((stat.shape[0] - 1) / years)
        MMD = 1 - (stat / stat.rolling(10000, min_periods=1).max()).min()
        starpe = annualized_return / annualized_volatility
        add_col = '_AnnReturn:%.2f_SharpeRatio:%.3f_MDD:%.2f_annualized_volatility:%.2f'%(annualized_return * 100,starpe,MMD * 100,annualized_volatility*100)
        return add_col,annualized_return * 100,starpe,MMD * 100
    
    search_path = os.path.join(folder_path, 'stats*')
    stats_files = glob.glob(search_path)
    stat_df = pd.read_csv(stats_files[0],index_col = 0)


    stat_df_insample = stat_df[stat_df.index<=str(datetime.strptime(str(insample_last_day), '%Y%m%d'))[:10]]
    IC_insample = stat_df_insample['IC'].mean()
    ICIR_insample = stat_df_insample['IC'].mean()/stat_df_insample['IC'].std()
    AnnReturn_insample = calc_index1(stat_df_insample['hedged_unrealized_pnl'])[1]



    stat_df_outsample = stat_df[stat_df.index>str(datetime.strptime(str(insample_last_day), '%Y%m%d'))[:10]]
    IC_outsample = stat_df_outsample['IC'].mean()
    ICIR_outsample = stat_df_outsample['IC'].mean()/stat_df_outsample['IC'].std()
    AnnReturn_outsample = calc_index1(stat_df_outsample['hedged_unrealized_pnl'])[1]
    
    
    IC_total = stat_df['IC'].mean()
    ICIR_total = stat_df['IC'].mean()/stat_df['IC'].std()
    AnnReturn_total = calc_index1(stat_df['hedged_unrealized_pnl'])[1]
    
    
    
    #计算因子超额相关性
    if folder_path_comparison_backtest:
        search_path_comparison_backtest = os.path.join(folder_path_comparison_backtest, '*')
        stats_file_comparison_backtest = glob.glob(search_path_comparison_backtest)
    else:
        stats_file_comparison_backtest = []
    ex_factor_name_list = [stats_file_comparison_backtest[i].split('/')[-1] for i in range(len(stats_file_comparison_backtest))]
    
    stats_file = folder_path + 'stats.csv'
    stat_df = pd.read_csv(stats_file,index_col = 0)
    ex_df = stat_df[['hedged_unrealized_pnl']]
    
    
    factor_name_list = []
    corr_list = []
    for i in range(len(ex_factor_name_list)):
        factor_ex_df = pd.read_csv(folder_path_comparison_backtest+ex_factor_name_list[i]+'/stats.csv',index_col = 0)
        cal_ex_corr_df = pd.merge(ex_df,factor_ex_df[['hedged_unrealized_pnl']].rename(columns={'hedged_unrealized_pnl':ex_factor_name_list[i]}),left_index=True,right_index=True,how = 'inner')
        factor_name_list.append(ex_factor_name_list[i][:-4])
        corr_list.append(cal_ex_corr_df['hedged_unrealized_pnl'].pct_change().corr(cal_ex_corr_df[ex_factor_name_list[i]].pct_change()))
        
        
        
    
    factor_excorr_df = pd.DataFrame({'factor_name':factor_name_list,'corr':corr_list})
    factor_excorr_df['corr_abs'] = abs(factor_excorr_df['corr'])
    factor_excorr_df = factor_excorr_df.sort_values(by = 'corr_abs',ascending=False).reset_index(drop=True)
    factor_excorr_df.to_excel(folder_path+'factor_excorr.xlsx')
    factor_excorr_df_max = factor_excorr_df[['factor_name','corr']].iloc[:10]
    
    
    
    def analyze_multi_period_ic(stat_df, split_date, output_path=None):
        """
        计算多周期累计IC及1d回撤，返回样本内外统计指标DataFrame
        """
        df = stat_df.copy()
        if 'date' in df.columns:
            df = df.set_index('date')
        
        # 1. 日期格式转换 (int -> datetime)
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            # 假设日期在 index 中，如果是列请先 df.set_index('date')
            df.index = pd.to_datetime(df.index.astype(str), format='%Y%m%d')
        df = df.sort_index()
        
        ic_cols = ['1d', '2d', '5d', '10d', '20d']
        # 强制数值化并填充空值
        for col in ic_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        # 2. 计算累计指标
        cum_cols = []
        for col in ic_cols:
            cum_name = f'cum_{col}'
            df[cum_name] = df[col].cumsum()
            cum_cols.append(cum_name)
        
        # 特别计算 1d 的回撤
        df['cum_1d_max'] = df['cum_1d'].cummax()
        df['drawdown_1d'] = df['cum_1d'] - df['cum_1d_max']
        
        # 3. 统计逻辑定义 (IC Mean, ICIR, MaxDD)
        split_dt = pd.to_datetime(str(split_date))
        
        def get_metrics(data_slice, label):
            if data_slice.empty:
                return None
            
            metrics = {}
            for col in ic_cols:
                # 基础指标
                ic_mean = data_slice[col].mean()
                ic_std = data_slice[col].std()
                # 年化 ICIR (假设交易日为 252)
                ic_ir = (ic_mean / ic_std * np.sqrt(252)) if ic_std != 0 else 0
                
                # 独立计算该段内的最大回撤 (针对该列自身累计曲线)
                temp_cum = data_slice[col].cumsum()
                max_dd = (temp_cum - temp_cum.cummax()).min()
                
                metrics[f'{col[:-1]}日IC'] = ic_mean
                metrics[f'{col[:-1]}日ICIR'] = ic_ir
                metrics[f'{col[:-1]}日回撤'] = max_dd
                
            return pd.Series(metrics, name=label)
    
        # 构造结果表格
        res_df = pd.DataFrame([
            get_metrics(df[df.index < split_dt], '样本内'),
            get_metrics(df[df.index >= split_dt], '样本外'),
            get_metrics(df, '全样本')
        ])
    
        # 4. 绘图
        fig, ax1 = plt.subplots(figsize=(14, 7))
        x = df.index
        
        # 左轴：绘制 5 个周期的累计 IC
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#9467bd', '#8c564b']
        for col, color in zip(cum_cols, colors):
            ax1.plot(x, df[col], label=col.replace('cum_', ''), lw=1.5, color=color)
        
        ax1.set_ylabel('Cumulative IC (Multi-Period)', fontsize=12, fontweight='bold')
        ax1.grid(True, linestyle=':', alpha=0.6)
        
        # 样本分界线
        if x[0] < split_dt < x[-1]:
            ax1.axvline(split_dt, color='black', linestyle='--', alpha=0.5, label='Split Date')
    
        # 右轴：仅绘制 1d 的回撤
        ax2 = ax1.twinx()
        y_dd_1d = df['drawdown_1d'].values
        ax2.fill_between(x, y_dd_1d, 0, where=(y_dd_1d <= 0), color='red', alpha=0.15, label='1d Drawdown (R)')
        ax2.set_ylabel('1d IC Drawdown', color='red', fontsize=12, fontweight='bold')
        
        # 优化右轴量程
        if y_dd_1d.min() < 0:
            ax2.set_ylim(y_dd_1d.min() * 4, 0.05)
    
        plt.title('Factor Performance Analysis: Multi-Period IC & 1d Drawdown', fontsize=14)
        ax1.legend(loc='upper left', ncol=2)
        fig.tight_layout()
    
        # 保存并关闭，不显示
        if output_path:
            plt.savefig(output_path + 'cumIC_multi.png', dpi=300, bbox_inches='tight')
        plt.close(fig)
    
        return res_df
    
    
    def get_ICstatpic(df_raw, output_path = folder_path+'cum_IC_statistic.png'):
        # 步骤1：解析 index
        def parse_index(idx):
            # 例如 '2日IC' -> ('2日', 'IC')
            # 注意：ICIR 和 回撤 要正确匹配
            for period in ['2日', '5日', '10日', '20日']:
                if idx.startswith(period):
                    indicator = idx[len(period):]  # 剩余部分 'IC', 'ICIR', '回撤'
                    return period, indicator
            return None, None
    
        parsed = [parse_index(i) for i in df_raw.index]
        df_raw['持有期'] = [p[0] for p in parsed]
        df_raw['指标'] = [p[1] for p in parsed]
    
        # 步骤2：提取每个指标的数据透视表
        ic_data = df_raw[df_raw['指标'] == 'IC'][['持有期', '样本内', '样本外', '全样本']].set_index('持有期')
        icir_data = df_raw[df_raw['指标'] == 'ICIR'][['持有期', '样本内', '样本外', '全样本']].set_index('持有期')
        dd_data = df_raw[df_raw['指标'] == '回撤'][['持有期', '样本内', '样本外', '全样本']].set_index('持有期')
    
        # 确保持有期顺序正确
        order = ['2日', '5日', '10日', '20日']
        ic_data = ic_data.reindex(order)
        icir_data = icir_data.reindex(order)
        dd_data = dd_data.reindex(order)
    
        # 步骤3：绘图
        fig, axes = plt.subplots(1, 3, figsize=(15, 5), sharex=True)
        periods = order
        x = np.arange(len(periods))
        width = 0.25
    
        # 颜色定义
        colors = {'样本内': '#2c7bb6', '样本外': '#abd9e9', '全样本': '#fdae61'}
    
        # 子图1：IC
        ax = axes[0]
        for i, (sample, color) in enumerate(colors.items()):
            offset = (i - 1) * width
            bars = ax.bar(x + offset, ic_data[sample], width, label=sample, color=color)
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.00,
                        f'{height:.2f}', ha='center', va='bottom', fontsize=8)  # IC保留两位小数
        ax.set_xticks(x)
        ax.set_xticklabels(periods)
        ax.set_ylabel('IC')
        ax.set_title('IC')
        ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.5)
        ax.grid(axis='y', linestyle='--', alpha=0.6)
    
        # 子图2：ICIR
        ax = axes[1]
        for i, (sample, color) in enumerate(colors.items()):
            offset = (i - 1) * width
            bars = ax.bar(x + offset, icir_data[sample], width, label=sample, color=color)
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.2f}', ha='center', va='bottom', fontsize=8)  # ICIR保留两位
        ax.set_xticks(x)
        ax.set_xticklabels(periods)
        ax.set_ylabel('ICIR')
        ax.set_title('ICIR')
        ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.5)
        ax.grid(axis='y', linestyle='--', alpha=0.6)
    
        # 子图3：回撤
        ax = axes[2]
        for i, (sample, color) in enumerate(colors.items()):
            offset = (i - 1) * width
            bars = ax.bar(x + offset, dd_data[sample], width, label=sample, color=color)
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height - 0.02,
                        f'{height:.2f}', ha='center', va='top', fontsize=8)  # 回撤保留两位
        ax.set_xticks(x)
        ax.set_xticklabels(periods)
        ax.set_ylabel('回撤')
        ax.set_title('最大回撤')
        ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.5)
        ax.grid(axis='y', linestyle='--', alpha=0.6)
    
        # 全局图例
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc='lower left', bbox_to_anchor=(0.1, 0.0), ncol=3)
    
        # plt.suptitle('因子 IC 统计指标对比', fontsize=16, y=1.02)
        # plt.tight_layout()
        plt.subplots_adjust(bottom=0.15)   # 为左下角图例预留空间
        plt.savefig(output_path, bbox_inches=None)
        plt.close()
        
        
    # 各期IC指标统计：
    cum_IC_stat_df = analyze_multi_period_ic(ICs_df, insample_last_day, output_path=folder_path)
    cum_IC_stat_df = cum_IC_stat_df.iloc[:,3:].round(2).T
    # cum_IC_stat_df = cum_IC_stat_df.reset_index()
    cum_IC_stat_df.to_csv(folder_path+'cum_IC_statis.csv')
    get_ICstatpic(cum_IC_stat_df)
    
    
    def months_ago(date_int,months):
        dt = datetime.strptime(str(date_int), '%Y%m%d')
        result = dt - relativedelta(months = months)
        return int(result.strftime('%Y%m%d'))
        
    #计算因子间相关性
    def calc_daily_corr_mean(df_new, df_comparison, start_date, end_date):
        """
        计算区间内每日截面相关系数的均值
        df_new, df_comparison: DataFrame，包含 ticker, date, factor_name 三列
        start_date, end_date: int，起止日期（包含），格式 YYYYMMDD
        返回: float，日相关系数的均值
        """
        # 筛选日期范围
        new = df_new[(df_new['date'] >= start_date) & (df_new['date'] <= end_date)]
        comparison = df_comparison[(df_comparison['date'] >= start_date) & (df_comparison['date'] <= end_date)]

        # 按 ticker+date 合并两个因子值
        merged = pd.merge(new, comparison, on=['ticker', 'date'])

        name1 = new.columns[2]
        name2 = comparison.columns[2]


        # 按日期分组，计算每日相关系数，再取均值
        daily_corr = merged.groupby('date').apply(lambda g: g[name1].corr(g[name2],method = 'spearman'))
        return daily_corr.mean()



    if folder_path_comparison_factor:
        search_path_comparison_factor = os.path.join(folder_path_comparison_factor, '*')
        factor_file_comparison_factor = glob.glob(search_path_comparison_factor)
    else:
        factor_file_comparison_factor = []


    comparison_factor_name_list = []
    in_sample_corr_list = []
    out_sample_corr_list = []

    for file in tqdm(factor_file_comparison_factor):
        df_comparison_factor = pd.read_parquet(file)
        if df.columns[2] != df_comparison_factor.columns[2]:
            comparison_factor_name_list.append(df_comparison_factor.columns[2])
            in_sample_corr = calc_daily_corr_mean(df, df_comparison_factor, months_ago(insample_last_day,3), insample_last_day)
            out_sample_corr = calc_daily_corr_mean(df, df_comparison_factor, months_ago(outsample_last_day,6), outsample_last_day)
            in_sample_corr_list.append(in_sample_corr)
            out_sample_corr_list.append(out_sample_corr)


    factor_corr_df = pd.DataFrame()
    factor_corr_df['factor_name'] = comparison_factor_name_list
    factor_corr_df['样本内最后三个月'] = in_sample_corr_list
    factor_corr_df['样本外最后六个月'] = out_sample_corr_list


    factor_corr_df = factor_corr_df.sort_values(by = '样本外最后六个月',ascending=False).reset_index(drop=True)
    factor_corr_df.to_excel(folder_path+'comparison_factor_corr.xlsx')
    factor_corr_df_top10 = factor_corr_df.iloc[:10]
    
    
    
    #计算非线性指标nmi和dcor
      
    daily_df = pd.read_csv(stock_price_daily,index_col = 0)
    daily_df['date'] = pd.to_datetime(daily_df['tradeDate'])
    open_pivot = daily_df.pivot_table(index='date', columns='ticker', values='openPrice')
    
    def get_forward_returns(open_pivot, lags=[1,2,3]):
        ret_dict = {}
        for lag in lags:
            ret = (open_pivot.shift(-lag-1) - open_pivot.shift(-1)) / open_pivot.shift(-1)
            # 将收益率与因子日期对齐：因子在 t 日，对应未来 lag 日的收益率
            # 但 ret 的 index 是 t 日，value 是 t+lag 日收益率
            ret_dict[lag] = ret
        return ret_dict


    ret_dict = get_forward_returns(open_pivot, lags=[1,2,5,10,20])
    
    
    factor_df = df.copy()
    factor_df['date'] = pd.to_datetime(factor_df['date'], format='%Y%m%d')
    nonlinear_start_time = factor_df['date'].min().strftime('%Y%m%d')
    nonlinear_end_time = factor_df['date'].max().strftime('%Y%m%d')
    
    # 分别计算各滞后
    results = {}
    for lag, ret in ret_dict.items():
        mean_nmi, mean_dcor, _, _ = NonLinearIndicator.compute_metrics_for_lag(factor_df, ret, lag, start_time=nonlinear_start_time, end_time=nonlinear_end_time,factor_name = factor_name)
        results[lag] = {'NMI': mean_nmi, 'dCor': mean_dcor}
        print(f"Lag {lag} days: NMI = {mean_nmi:.4f}, dCor = {mean_dcor:.4f}")
        
        
    nonlinear_indi_df = pd.DataFrame(results).T.round(4).reset_index().rename(columns={'index': 'lag'})
    nonlinear_indi_df.to_excel(folder_path+'nonlinear_indi.xlsx')
    
    
    #计算多头换手率
    def calculate_top_turnover(df_alpha, factor_name, top_quantile=0.2):
        # 1. 获取排序后的唯一日期序列
        available_dates = sorted(df_alpha['date'].unique())
        
        turnover_results = {}
        prev_top_set = set()
        
        for d in tqdm(available_dates):

            current_df = df_alpha[df_alpha['date'] == d].dropna(subset=[factor_name])
            

            n_top = int(len(current_df) * top_quantile)
            
            if n_top == 0:
                continue
                
            # 选取因子值最大的前N只股票，获取其ticker集合
            # 显式转换为str，防止int和str混用导致交集为空
            current_top_set = set(
                current_df.sort_values(factor_name, ascending=False)
                ['ticker']
                .head(n_top)
                .astype(str)
            )
            
            # 2. 计算换手率 (从第二天开始计算)
            if prev_top_set:
                # 这里的逻辑是：1 - 留存率
                # 留存率 = (今天还在组合里的昨天的票) / 昨天的总票数
                # 如果前后两天总数 n_top 不一致（比如停牌导致），分母建议用当天的n_top
                common_count = len(current_top_set.intersection(prev_top_set))
                turnover = 1 - (common_count / n_top)
                turnover_results[d] = turnover
            
            # 更新前一期集合
            prev_top_set = current_top_set
            
        return pd.Series(turnover_results)
    
    # --- 使用示例 ---
    turnover_df = pd.DataFrame(columns = ['Top10%换手','Top20%换手','Top30%换手','Top50%换手','Top70%换手'],index = ['平均换手率','最大换手率'])
    turnover_series_10 = calculate_top_turnover(df, factor_name=factor_name, top_quantile=0.1)
    turnover_series_20 = calculate_top_turnover(df, factor_name=factor_name, top_quantile=0.2)
    turnover_series_30 = calculate_top_turnover(df, factor_name=factor_name, top_quantile=0.3)
    turnover_series_50 = calculate_top_turnover(df, factor_name=factor_name, top_quantile=0.5)
    turnover_series_70 = calculate_top_turnover(df, factor_name=factor_name, top_quantile=0.7)
    
    turnover_df['Top10%换手'] = [turnover_series_10.mean(),turnover_series_10.max()]
    turnover_df['Top20%换手'] = [turnover_series_20.mean(),turnover_series_20.max()]
    turnover_df['Top30%换手'] = [turnover_series_30.mean(),turnover_series_30.max()]
    turnover_df['Top50%换手'] = [turnover_series_50.mean(),turnover_series_50.max()]
    turnover_df['Top70%换手'] = [turnover_series_70.mean(),turnover_series_70.max()]
    
    
    
    # 设置绘图参数
    categories = turnover_df.columns          # 各个 Top% 分组
    x = np.arange(len(categories))   # 每组的位置
    width = 0.25                     # 柱子宽度
    
    # 创建图形
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # 绘制平均换手率和最大换手率的柱子
    bars1 = ax.bar(x - width/2, turnover_df.loc['平均换手率'], width, label='平均换手率', color='steelblue')
    bars2 = ax.bar(x + width/2, turnover_df.loc['最大换手率'], width, label='最大换手率', color='firebrick')
    
    # 添加数值标签（可选）
    for bar in bars1:
        height = bar.get_height()
        ax.annotate(f'{height:.3f}',
                    xy=(bar.get_x() + bar.get_width()/2, height),
                    xytext=(0, 3),  # 偏移量
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=9)
    for bar in bars2:
        height = bar.get_height()
        ax.annotate(f'{height:.3f}',
                    xy=(bar.get_x() + bar.get_width()/2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=9)
    
    # 设置标签、标题和图例
    # ax.set_xlabel('换手率分组', fontsize=12)
    ax.set_ylabel('换手率', fontsize=12)
    # ax.set_title('不同分组下的平均换手率与最大换手率对比', fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=45, ha='right')
    ax.legend()
    ax.grid(axis='y', linestyle='--', alpha=0.7)
    
    # 调整布局，避免标签被裁剪
    plt.tight_layout()
    plt.savefig(folder_path+'turnover.png')
    plt.close()
    
    
    
    try:
        #计算纯因子收益率
        # 风格因子列表（根据你的 Barra 文件列名）
        STYLE_FACTORS = ['BETA', 'MOMENTUM', 'SIZE', 'EARNYILD', 
                       'RESVOL', 'GROWTH', 'BTOP', 'LEVERAGE', 'LIQUIDTY', 'SIZENL']
    
        # 行业哑变量列名（根据你提供的列表）
        INDUSTRY_COLS = [
            'Agriculture', 'Automobiles', 'Banks', 'BuildMater', 'Chemicals',
            'Commerce', 'Computers', 'Conglomerates', 'ConstrDecor', 'Defense',
            'ElectricalEquip', 'Electronics', 'FoodBeverages', 'HealthCare',
            'HomeAppliances', 'Leisure', 'LightIndustry', 'MachineEquip', 'Media',
            'Mining', 'NonbankFinan', 'NonferrousMetals', 'RealEstate', 'Steel',
            'Telecoms', 'TextileGarment', 'Transportation', 'Utilities',
            'BasicChemicals', 'BeautyCare', 'Coal', 'EnvironProtect', 'Petroleum',
            'PowerEquip', 'RetailTrade', 'SocialServices', 'TextileApparel'
        ]
    
        # 构建面板数据
        panel = PureFactorReturn.build_panel_data(
            barra_folder=BARRA_FOLDER,
            stock_folder=STOCK_FOLDER,
            alpha_folder=ALPHA_FOLDER,
            start_date='2015-01-01',
            end_date='2026-01-23',
            style_factor_cols=STYLE_FACTORS,
            alpha_factor_name='alpha_191_FACTORS_alpha_002',
            industry_cols_in_barra=INDUSTRY_COLS,
            cap_col='negMarketValue',
            ticker_col='ticker',
            ret_type='close',               # 可选 'close' 或 'open'
            ret_col_output='return_to_forecast',
            industry_output_name='SW_L1'
        ).dropna().reset_index(drop=True)
    
    
        # 运行纯因子模型
        factor_cols = STYLE_FACTORS + ['alpha_factor']
        cum_returns = PureFactorReturn.run_barra_pure_factor_model(
            panel_data=panel,
            factor_cols=factor_cols,
            ind_col='SW_L1',
            cap_col='negMarketValue',
            ret_col='return_to_forecast',
            date_col='date',
            output_path=folder_path+'pure_factor_results.xlsx'
        )
    
    
        cum_returns = cum_returns.rename(columns={'nation':'COUNTRY','alpha_factor':factor_name})
    
        style_list = ['COUNTRY']+STYLE_FACTORS+[factor_name]
        pure_factor_returns_df = cum_returns[style_list]
    
        # 绘制所有因子的曲线图
        plt.figure(figsize=(14, 8))
        
        for column in pure_factor_returns_df.columns:
            if column == factor_name:
                plt.plot(pure_factor_returns_df.index, pure_factor_returns_df[column], 
                         label=column, color='black', linewidth=2.5)
            else:
                plt.plot(pure_factor_returns_df.index,pure_factor_returns_df[column], label=column, linewidth=1.5) 
        
        
        
    
        # 添加图例、网格、标签等
        plt.legend(loc='best', fontsize=10, ncol=3)  # ncol 控制图例列数，因子多时可避免重叠
        # plt.title('纯因子收益率时间序列曲线', fontsize=14)
        plt.ylabel('因子收益', fontsize=12)
        plt.grid(True, linestyle='--', alpha=0.6)
        # 处理x轴日期
        ax = plt.gca()
        # 如果日期间隔不规律，可以设置自动定位
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())          # 自动选择合适间隔
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)  # 旋转45度，避免重叠
    
        plt.tight_layout()
        plt.savefig(folder_path+'pure_factor_return.png')
        plt.close()
    
    
    except Exception as exc:
        print(f'Pure factor return skipped: {exc}')
    
    # ==================== 配置 ====================

    chinese_fonts = [f.name for f in fm.fontManager.ttflist 
                     if any(kw in f.name for kw in ['SimHei', 'Microsoft YaHei', 'WenQuanYi', 
                                                     'Noto Sans CJK SC', 'Hei', 'Kai', 'Song'])]
    if chinese_fonts:
        plt.rcParams['font.sans-serif'] = chinese_fonts
        use_chinese = True
    else:
        use_chinese = False
    plt.rcParams['axes.unicode_minus'] = False
    
    # 页面尺寸（A4）
    page_width = 8.27
    page_height = 11.69
    left_margin = 0.5
    right_margin = 0.5
    top_margin = 0.5
    bottom_margin = 0.5
    usable_width = page_width - left_margin - right_margin
    usable_height = page_height - top_margin - bottom_margin
    
    # ==================== 定义原始任务列表（含自定义标题）====================
    tasks_original = [
        {'type': 'title', 'height': 0.1},  # 因子名称标题
        {'type': 'sub_title', 'height': 0},  # 因子名称副标题
        {'type': 'table', 'height': 1.0},  # 绩效统计表
        {'type': 'linear_stats', 'height': 1.0,
        'title': '因子线性度量' if use_chinese else 'Factor Linear Stats'},  # 线性评价表
        {'type': 'corr_table', 'height': 2.5},  # 超额收益相关性分析表
        {'type': 'factor_corr_top10','height': 3,  
        'title': '因子值相关性TOP10' if use_chinese else 'Top 10 Factor Value Correlation'},  
        {'type': 'nonlinear_indi_df','height': 3,  
        'title': '非线性指标' if use_chinese else 'nonlinear indicators'},  
        # 单张图片
        {'type': 'single', 'name': 'yearly_dist.png',
         'height': 4.0, 'title': '因子值分布' if use_chinese else 'Excess Return Curve'},
        {'type': 'single', 'name': 'Pnl.png',
         'height': 3.0, 'title': '超额收益曲线' if use_chinese else 'Excess Return Curve'},
        {'type': 'single', 'name': 'cumIC_multi.png',
         'height': 3.0, 'title': '累计IC' if use_chinese else 'Cum IC'},
        {'type': 'single', 'name': 'cum_IC_statistic.png',
         'height': 2.5, 'title': 'IC指标统计' if use_chinese else 'Cum IC Statistics'},
        {'type': 'single', 'name': 'group_return.png',
         'height': 3.0, 'title': '分组收益(1日换仓)' if use_chinese else 'Group Excess Returns'},
        {'type': 'single', 'name': 'turnover.png',
         'height': 4, 'title': 'TopN换手率(1日)' if use_chinese else 'Group Excess Returns'},
        {'type': 'double', 'names': ['Industry_radar.png', 'Style_radar.png'],
         'height': 3.0, 'titles': ['行业暴露' if use_chinese else 'Industry Exposure',
                                   '风格暴露' if use_chinese else 'Style Exposure']},
        {'type': 'single', 'name': 'Explo_return.png',
         'height': 3.0, 'title': '收益归因' if use_chinese else 'Return Attribution'},
        {'type': 'single', 'name': 'pure_factor_return.png',
         'height': 4.0, 'title': '纯因子收益' if use_chinese else 'Return Attribution'},
        {'type': 'single', 'name': 'ic_decay.png',
         'height': 4.0, 'title': 'IC衰减' if use_chinese else 'IC Decay'},
        {'type': 'single', 'name': 'Pure_alpha.png',
         'height': 3.0, 'title': '纯Alpha' if use_chinese else 'Pure Alpha'},
        {'type': 'single', 'name': 'winrate.png',
         'height': 3.0, 'title': '胜率' if use_chinese else 'Win Rate'},
        {'type': 'double', 'names': ['rank_autocorrelation.png', 'value_autocorrelation.png'],
         'height': 4.0, 'titles': ['因子排名自相关' if use_chinese else 'Rank Autocorrelation',
                                   '因子值自相关' if use_chinese else 'Value Autocorrelation']},
    ]
    
    # ==================== 检查图片是否存在，构建有效任务列表 ====================
    valid_tasks = []
    for task in tasks_original:
        if task['type'] in ['title', 'sub_title', 'table', 'factor_corr_top10','linear_stats','nonlinear_indi_df']:
            valid_tasks.append(task)
        elif task['type'] == 'single':
            path = os.path.join(folder_path, task['name'])
            if os.path.exists(path):
                task['img'] = mpimg.imread(path)
                valid_tasks.append(task)
            else:
                print(f'警告：图片 {task["name"]} 不存在，跳过')
        elif task['type'] == 'double':
            imgs = []
            for name in task['names']:
                path = os.path.join(folder_path, name)
                if os.path.exists(path):
                    imgs.append(mpimg.imread(path))
                else:
                    print(f'警告：图片 {name} 不存在，将留空')
                    imgs.append(None)
            if any(img is not None for img in imgs):
                task['imgs'] = imgs
                valid_tasks.append(task)
    
    # ==================== 插入相关性表格任务 ====================
    table_index = None
    for i, task in enumerate(valid_tasks):
        if task['type'] == 'table':
            table_index = i
            break
    if table_index is not None:
        corr_task = {
            'type': 'corr_table',
            'height': 3,  
            'title': '超额收益相关性TOP10(hold:200)' if use_chinese else 'Top 10 Excess Return Correlation'
        }
        valid_tasks.insert(table_index + 1, corr_task)
    else:
        print('警告：未找到绩效表格任务，无法插入相关性表格')
    
    # ==================== 重新分页 ====================
    pages = []
    current_page = []
    remaining = usable_height
    
    for task in valid_tasks:
        if task['height'] <= remaining:
            current_page.append(task)
            remaining -= task['height']
        else:
            pages.append(current_page)
            current_page = [task]
            remaining = usable_height - task['height']
    if current_page:
        pages.append(current_page)
    
    print(f'总页数：{len(pages)}')
    for i, page in enumerate(pages):
        print(f"第 {i+1} 页包含: {[t['type'] for t in page]}")
    
    # ==================== 生成PDF ====================
    with PdfPages(output_pdf) as pdf:
        for page_idx, page_tasks in enumerate(pages):
            fig = plt.figure(figsize=(page_width, page_height))
            y_top = page_height - top_margin
    
            
            gap = 0.6
            
            for task in page_tasks:
                if task['type'] == 'title':
                    ax = fig.add_axes([left_margin/page_width, (y_top - task['height'])/page_height,
                                       usable_width/page_width, task['height']/page_height])
                    ax.axis('off')
                    title_text = (factor_name if use_chinese else factor_name)
                    ax.text(0.5, 0.5, title_text, fontsize=13, ha='center', va='center', transform=ax.transAxes)
                    y_top -= task['height'] + gap
                    
                elif task['type'] == 'sub_title':
                    ax = fig.add_axes([left_margin/page_width, (y_top - task['height'])/page_height,
                                       usable_width/page_width, task['height']/page_height])
                    ax.axis('off')
                    title_text = ('样本内：'+'20150101'+'-'+'20241231'+'   '+'样本外：'+'20241231'+'-'+'20260123')
                    ax.text(0.5, 0.5, title_text, fontsize=10, ha='center', va='center', transform=ax.transAxes)
                    y_top -= task['height'] + gap    
                    
                
    
                elif task['type'] == 'table':
                    bottom = (y_top - task['height']) / page_height
                    ax = fig.add_axes([left_margin/page_width, bottom,
                                       usable_width/page_width, task['height']/page_height])
                    ax.axis('off')
                    ax.set_title(
                        '绩效统计' if use_chinese else 'Performance Statistics',
                        fontsize=10,
                        pad=2,
                        weight='bold'
                    )
    
    
                    col_headers = ['Period', 'IC(1日)', 'ICIR(1日)', '年化超额收益率', '自相关性']
                    table_data = [
                        ['样本内', IC_insample, ICIR_insample, AnnReturn_insample, lag1_rank_autocorr_insample],
                        ['样本外', IC_outsample, ICIR_outsample, AnnReturn_outsample, lag1_rank_autocorr_outsample],
                        ['全样本', IC_total, ICIR_total, AnnReturn_total, lag1_rank_autocorr_total]
                    ]
                    formatted_data = []
                    for row in table_data:
                        formatted_row = [str(row[0]), f"{row[1]:.3f}", f"{row[2]:.3f}", f"{row[3]:.2f}", f"{row[4]:.2f}"]
                        formatted_data.append(formatted_row)
                    full_table = [col_headers] + formatted_data
                    n_cols = len(col_headers)
                    colWidths = [0.1] + [0.12] * (n_cols - 1)
    
    
                    table = ax.table(
                        cellText=full_table,
                        cellLoc='center',
                        loc='center',
                        colWidths=[0.2,0.2,0.2,0.2,0.2],
                        bbox=[0,0,1,0.9]
                    )
    
                    table.auto_set_font_size(False)
                    table.set_fontsize(10)
    
                    # 自动调整高度
                    for key, cell in table.get_celld().items():
                        cell.set_height(0.2)
    
                    # 边框
                    for (row, col), cell in table.get_celld().items():
                        cell.set_linewidth(0.6)
                        cell.set_edgecolor('black')
    
                    # 表头背景
                    for j in range(n_cols):
                        table[(0, j)].set_facecolor('#f0f0f0')
                    for i in range(1, len(table_data)+1):
                        table[(i, 0)].set_facecolor('#f0f0f0')
    
                    y_top -= task['height'] + gap
    
                    
                    
                    
                elif task['type'] == 'cumIC_table':
                    bottom = (y_top - task['height']) / page_height
                    ax = fig.add_axes([left_margin/page_width, bottom,
                                       usable_width/page_width, task['height']/page_height])
                    ax.axis('off')
                    ax.set_title(task['title'], fontsize=9, pad=5, weight='bold')
    
                    table_data = res.values.tolist()
                    col_headers = res.columns.tolist()
                    full_table = [col_headers] + table_data
    
                    table = ax.table(
                        cellText=full_table,
                        cellLoc='center',
                        loc='center',
                        colWidths=[0.2]*12,
                        bbox=[0, 0, 1, 1]
                    )
    
                    table.auto_set_font_size(False)
                    table.set_fontsize(10)
    
                    n_rows = len(full_table)
    
                    for (row, col), cell in table.get_celld().items():
                        cell.set_height(1.3 / n_rows)
                        cell.set_linewidth(0.6)
    
                    # 表头背景
                    for j in range(len(col_headers)):
                        table[(0, j)].set_facecolor('#f0f0f0')
    
                    y_top -= task['height'] + gap
                    
                    
                elif task['type'] == 'corr_table':
                    bottom = (y_top - task['height']) / page_height
                    ax = fig.add_axes([left_margin/page_width, bottom,
                                       usable_width/page_width, task['height']/page_height])
                    ax.axis('off')
                    ax.set_title(task['title'], fontsize=9, pad=5, weight='bold')
    
                    table_data = factor_excorr_df_max.head(10).values.tolist()
                    col_headers = ['因子名称' if use_chinese else 'Factor', '超额收益相关性' if use_chinese else 'ExCorrelation']
                    full_table = [col_headers] + table_data
    
                    table = ax.table(
                        cellText=full_table,
                        cellLoc='center',
                        loc='center',
                        colWidths=[0.65, 0.35],
                        bbox=[0, 0, 1, 1]
                    )
    
                    table.auto_set_font_size(False)
                    table.set_fontsize(10)
    
                    n_rows = len(full_table)
    
                    for (row, col), cell in table.get_celld().items():
                        cell.set_height(1.3 / n_rows)
                        cell.set_linewidth(0.6)
    
                    # 表头背景
                    for j in range(len(col_headers)):
                        table[(0, j)].set_facecolor('#f0f0f0')
    
                    y_top -= task['height'] + gap
                    
                elif task['type'] == 'factor_corr_top10':
                    bottom = (y_top - task['height']) / page_height
                    ax = fig.add_axes([left_margin/page_width, bottom,
                                       usable_width/page_width, task['height']/page_height])
                    ax.axis('off')
                    ax.set_title(task['title'], fontsize=9, pad=5, weight='bold')
    
                    table_data = factor_corr_df_top10.head(10).values.tolist()
                    col_headers = ['因子名称' if use_chinese else 'Factor', '样本内最后三个月' if use_chinese else 'Insample last 3 month', '样本外最后六个月' if use_chinese else 'Outsample last 6 month']
                    full_table = [col_headers] + table_data
    
                    table = ax.table(
                        cellText=full_table,
                        cellLoc='center',
                        loc='center',
                        colWidths=[0.65, 0.35, 0.35],
                        bbox=[0, 0, 1, 1]
                    )
    
                    table.auto_set_font_size(False)
                    table.set_fontsize(10)
    
                    n_rows = len(full_table)
    
                    for (row, col), cell in table.get_celld().items():
                        cell.set_height(1.3 / n_rows)
                        cell.set_linewidth(0.6)
    
                    # 表头背景
                    for j in range(len(col_headers)):
                        table[(0, j)].set_facecolor('#f0f0f0')
    
                    y_top -= task['height'] + gap
                    
                elif task['type'] == 'linear_stats':
                    bottom = (y_top - task['height']) / page_height
                    ax = fig.add_axes([left_margin/page_width, bottom,
                                       usable_width/page_width, task['height']/page_height])
                    ax.axis('off')
                    ax.set_title(task['title'], fontsize=9, pad=5, weight='bold')
    
                    table_data = linear_stats.values.tolist()
                    col_headers = ['因子名称' , '线性指标','线性稳定性', '非线性度量','交点均值']
                    full_table = [col_headers] + table_data
    
                    table = ax.table(
                        cellText=full_table,
                        cellLoc='center',
                        loc='center',
                        colWidths=[0.5,0.2,0.2,0.2,0.2],
                        bbox=[0, 0, 1, 1]
                    )
    
                    table.auto_set_font_size(False)
                    table.set_fontsize(10)
    
                    n_rows = len(full_table)
    
                    for (row, col), cell in table.get_celld().items():
                        cell.set_height(1.3 / n_rows)
                        cell.set_linewidth(0.6)
    
                    # 表头背景
                    for j in range(len(col_headers)):
                        table[(0, j)].set_facecolor('#f0f0f0')
    
                    y_top -= task['height'] + gap
                    
                    
                elif task['type'] == 'nonlinear_indi_df':
                    bottom = (y_top - task['height']) / page_height
                    ax = fig.add_axes([left_margin/page_width, bottom,
                                       usable_width/page_width, task['height']/page_height])
                    ax.axis('off')
                    ax.set_title(task['title'], fontsize=9, pad=5, weight='bold')
    
                    table_data = nonlinear_indi_df.values.tolist()
                    col_headers = ['预测天数','NMI','dCor']
                    full_table = [col_headers] + table_data
    
                    table = ax.table(
                        cellText=full_table,
                        cellLoc='center',
                        loc='center',
                        colWidths=[0.34,0.33,0.33],
                        bbox=[0, 0.5, 1, 0.5]
                    )
    
                    table.auto_set_font_size(False)
                    table.set_fontsize(10)
    
                    n_rows = len(full_table)
    
                    for (row, col), cell in table.get_celld().items():
                        cell.set_height(1.3 / n_rows)
                        cell.set_linewidth(0.6)
    
                    # 表头背景
                    for j in range(len(col_headers)):
                        table[(0, j)].set_facecolor('#f0f0f0')
    
                    y_top -= task['height'] + gap
    
    
                elif task['type'] == 'single':
    
                    ax = fig.add_axes([left_margin/page_width, (y_top - task['height'])/page_height,
                                       usable_width/page_width, task['height']/page_height])
                    ax.imshow(task['img'], aspect='auto')
                    ax.axis('off')
                    ax.set_title(task['title'], fontsize=9, pad=0)
                    
                    y_top -= task['height'] + gap
    
                elif task['type'] == 'double':
    
                    img_width = (usable_width - 0.2) / 2
                    img_height = task['height']
    
                    bottom = (y_top - img_height) / page_height
    
                    # 左图
                    if task['imgs'][0] is not None:
                        ax1 = fig.add_axes([
                            left_margin/page_width,
                            bottom,
                            img_width/page_width,
                            img_height/page_height
                        ])
                        ax1.imshow(task['imgs'][0])
                        ax1.axis('off')
                        ax1.set_title(task['titles'][0], fontsize=9, pad=0)
    
                    # 右图
                    if task['imgs'][1] is not None:
                        ax2 = fig.add_axes([
                            (left_margin + img_width + 0.2)/page_width,
                            bottom,
                            img_width/page_width,
                            img_height/page_height
                        ])
                        ax2.imshow(task['imgs'][1])
                        ax2.axis('off')
                        ax2.set_title(task['titles'][1], fontsize=9, pad=0)
    
                    y_top -= task['height'] + gap
    
            pdf.savefig(fig, dpi=200)
            plt.close()
    
    print(f'PDF 报告已生成：{output_pdf}')