import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from tqdm import tqdm
from os.path import isfile
from os.path import join as joindir
from os import makedirs as mkdir
from datetime import date, timedelta
from scipy.stats import pearsonr
import urllib3
import os
import configparser
from matplotlib import font_manager
current_dir = os.path.dirname(os.path.dirname(__file__))
font_path ='fonts/MSYH.TTC' 
font_prop = font_manager.FontProperties(fname=font_path)
font_manager.fontManager.addfont(font_path)
font_name = font_prop.get_name()
matplotlib.rcParams['font.family'] = font_name
matplotlib.rcParams['axes.unicode_minus'] = False 
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
pathconfig = configparser.ConfigParser()
pathconfig.read(f'{current_dir}/config/pathconfig.ini') 
BASE_PATH=pathconfig.get('PATH','BASE_PATH_PQ')
OPT_PATH=pathconfig.get('PATH','OPT_PATH')


STYLE_LIST = ['COUNTRY','BETA','MOMENTUM','SIZE','EARNYILD','RESVOL','GROWTH','BTOP','LEVERAGE','LIQUIDTY','SIZENL']
IND_LIST = ['Agriculture','Automobiles','Banks','BuildMater','Chemicals',
            'Commerce','Computers','Conglomerates','ConstrDecor','Defense',
            'ElectricalEquip','Electronics','FoodBeverages','HealthCare','HomeAppliances',
            'Leisure','LightIndustry','MachineEquip','Media','Mining',
            'NonbankFinan','NonferrousMetals','RealEstate','Steel','Telecoms',
            'TextileGarment','Transportation','Utilities','BasicChemicals','BeautyCare',
            'Coal','EnvironProtect','Petroleum','PowerEquip','RetailTrade',
            'SocialServices','TextileApparel']

class Analysis(object):
    def __init__(self,date='',barraDate='',benchmark='zz1000'):
        self.date=date
        self.benchmark=benchmark
        self.barraDate=barraDate
        self.barra=pd.read_csv(fr'{OPT_PATH}/BarraStyleSW21/{self.barraDate}.csv').set_index('ticker').reindex(columns=STYLE_LIST+IND_LIST)
        self.benchmark=self.get_benchmark_weight()
        self.pure_ret=self.load_pure_ret()

    def get_benchmark_weight(self):
        Benchmarkweight=pd.read_csv(fr'{OPT_PATH}/indexweight/{self.benchmark}/{self.barraDate}.csv')
        Benchmarkweight=Benchmarkweight.set_index('ticker')['weight']
        return Benchmarkweight
    
    def load_pure_ret(self):
        pure_ret={}
        for mode in ['open_to_close','close_to_close','close_to_open']:
            pure_ret[mode]=pd.read_csv(fr'{OPT_PATH}/PureRetSW/BARRA_{mode}/{self.date}.csv').reindex(columns=STYLE_LIST+IND_LIST).T[0]
        return pure_ret

    def BarraExplosure(self,weights):
        date=self.date
        barra=self.barra[self.barra.index.isin(weights.index)]
        explosure=weights.loc[barra.index]@barra
        return explosure


class Trader(object):

    def __init__(self, transaction, init_cash=1e4):
        self.init_cash = init_cash
        self.cash = init_cash
        self.unrealized_pnl = init_cash
        self.holding_columns=['volume','holding_period','price_current','adj_factor']
        self.holdings = pd.DataFrame(columns=['ticker']+self.holding_columns).set_index('ticker')
        self.sell_buffer = []
        self._holding_records = []
        self._transaction_records = []
        self._stats = []
        self.id=0
        self.buy_transaction = transaction / 2 / 1000
        self.sell_transaction = transaction / 2 / 1000
            
    
    def get_available_cash(self):
        return self.cash

    def buy(self, buy_order):
        if not buy_order.empty:
            buy_order=buy_order.set_index('ticker')
            new_tickers = buy_order[~buy_order.index.isin(self.holdings.index)].index
            existing_tickers = buy_order[buy_order.index.isin(self.holdings.index)].index
            self.holdings=pd.concat([self.holdings,buy_order.loc[new_tickers]]).reindex(columns=self.holding_columns)
            self.holdings.loc[existing_tickers,'volume']+=buy_order.loc[existing_tickers,'volume']
            self.holdings['holding_period']=self.holdings['holding_period'].fillna(0)
            self.cash -= buy_order['amount'].sum()
            self.cash -= buy_order['transaction'].sum()
            self._transaction_records.append(buy_order.reset_index())

    def sell(self, sell_order):
        if not sell_order.empty:
            sell_order=sell_order.set_index('ticker')
            sell_tickers=sell_order.index
            self.holdings.loc[sell_tickers,'volume']-=sell_order['volume']
            self.cash += sell_order['amount'].sum()
            self.cash -= sell_order['transaction'].sum()
            self._transaction_records.append(sell_order.reset_index())

    def record(self, append_reason, **order):
        record_order = order.copy()
        record_order['reason'] = append_reason
        self._transaction_records.append(record_order)

    def balance(self, date, IC=None):

        unreal = (self.holdings['volume']*self.holdings['price_current']).sum()
        self.pre_unrealized_pnl=self.unrealized_pnl
        self.unrealized_pnl = self.cash + unreal
        self._stats.append({'date': date, 'cash': self.cash, 'unrealized_pnl': self.unrealized_pnl, 'IC': IC})
        c_holding=self.holdings.copy()
        c_holding['date']=date
        self._holding_records.append(c_holding)
        self.holdings=self.holdings[self.holdings['volume']>0]    

        return None

    @property
    def stats(self):
        stats = pd.DataFrame(self._stats)
        stats['date'] = pd.to_datetime(stats['date'].apply(str))
        return stats.set_index('date')

    @property
    def transaction_records(self):
        return pd.concat(self._transaction_records)

    @property
    def holding_records(self):
        holding_records=pd.concat(self._holding_records)
        return holding_records
    

class TradingSystem(object):
    LOCKED_LIMIT = 0.095
    def __init__(self,input_file,col,output_dir,savemode,timespan,longx, stock_pool,trade_price_type, buy_sell_shift,transaction,benchmark,keep,turnover_mode, 
                 hedgesell=True,
                 hratio=1,
                 hbili=1,
                 addtwap=True,
                 init_cash=1e4,
                 mindvol=100,
                 reverse=False,
                 pure_alpha=False):


        self.input_file = input_file
        self.output_dir = output_dir
        self.addtwap=addtwap
        self.col = col
        self.longx = longx
        self.stock_pool = stock_pool
        self.trade_price_type = trade_price_type
        self.buy_sell_shift = buy_sell_shift
        self.buy_transaction = transaction / 2 / 1000
        self.sell_transaction = transaction / 2 / 1000
        self.reverse=reverse
        self.benchmark = benchmark
        self.hratio = hratio
        self.init_cash=init_cash
        self.hbili = hbili
        self.keep=keep
        self.turnover_mode=turnover_mode
        self.pure_alpha=pure_alpha
        self.trader = Trader(transaction,init_cash=init_cash)
        self.savemode =savemode
        self.timespan = timespan
        self.hedgesell = hedgesell
        self.mindvol = mindvol
        self._risk_return_attributes=[]
        self._explo=[]


    def run(self):
        flag = self.load_data()
        if not flag:
            return []
        self.load_date_list()
        self.load_auxilliary()
        self.preclean_data()
        self.calculate_IC()
        self.calc_group()
        self.main_loop()
        self.plot()
        self.save()
        if self.pure_alpha:
            self.Pure_alpha_analysis()


    def calculate_IC(self):
        all_IC=[]
        for window in [1,2,5,10,20]:
            rets = (self.trade_price.shift(-window) - self.trade_price) / (self.trade_price)
            IC=self.buy_data.rank(axis=1).corrwith(rets.rank(axis=1),axis=1)
            IC.name=f'{window}d'
            all_IC.append(IC)
            
        for window in [1,2,3,4,5,10,20,30,60]:
            rets = (self.trade_price.shift(-window) - self.trade_price.shift(-window+1)) / (self.trade_price)
            IC=self.buy_data.rank(axis=1).corrwith(rets.rank(axis=1),axis=1)
            IC.name=f'single_{window}d'
            all_IC.append(IC)
        
        all_IC=pd.concat(all_IC,axis=1)
        self.ICs=all_IC
        self.ICs.to_csv(f'{self.output_dir}/ICs.csv',index=True)


    @staticmethod
    def calc_index(stat):
        stat = stat.dropna()
        stat.index = pd.to_datetime(stat.index)
        years = (stat.index[-1] - stat.index[0]).days / 365
        total_return = stat.values[-1] / stat.values[0]
        annualized_return = np.exp(np.log(total_return) / years) - 1
        annualized_volatility = (stat.shift(1) / stat).std() * np.sqrt((stat.shape[0] - 1) / years)
        MMD = 1 - (stat / stat.rolling(10000, min_periods=1).max()).min()
        starpe = annualized_return / annualized_volatility
        add_col = '_AnnReturn:%.2f_SharpeRatio:%.3f_MDD:%.2f'%(annualized_return * 100,starpe,MMD * 100)
        return add_col,annualized_return * 100,starpe,MMD * 100

    @staticmethod
    def plot_group(group_return,save_path):
        colors = plt.cm.coolwarm(np.linspace(0, 1, len(group_return.columns)))
        plt.figure(figsize=(12,4))
        plt.tick_params(labelsize=10)
        for i,col in enumerate(group_return.columns):
            df=group_return[[col]].copy()
            label1=col
            plt.plot(df.index, df[col].dropna().values,label= label1,color=colors[i])

        plt.title(f'简易因子分层图')
        plt.legend(fontsize=5)
        plt.grid(True,linestyle='--')
        plt.savefig(f'{save_path}/group_return.png') 

    @staticmethod
    def _get_info_str(stat, IC=None, name=''):
        years = (stat.index[-1] - stat.index[0]).days / 365
        total_return = stat.values[-1] / stat.values[0]
        annualized_return = np.exp(np.log(total_return) / years) - 1
        annualized_volatility = (stat.shift(1) / stat).std() * np.sqrt((stat.shape[0] - 1) / years)
        MMD = 1 - (stat / stat.rolling(10000, min_periods=1).max()).min()
        if IC is not None:
            mean_IC = IC.mean()
            std_IC = IC['1d'].std()
            ICIR = mean_IC['1d'] / std_IC
        
            info_str = (
                '[%s]\n'
                'annualized return = %.1f %% \n'
                'annualized volatility = %.1f %% \n'
                'Sharpe ratio = %.3f \n' 
                'MDD = %.2f %% \n'
                'mean IC = %.2f %% \n'
                'std IC = %.4f \n'
                'ICIR = %.4f'
            ) % (
                name,
                annualized_return * 100,
                annualized_volatility * 100,
                annualized_return / annualized_volatility,
                MMD * 100,
                mean_IC['1d'] * 100,
                std_IC,
                ICIR,
            )
        else:
            info_str = (
                '[%s]\n'
                'annualized return = %.1f %% \n'
                'annualized volatility = %.1f %% \n'
                'Sharpe ratio = %.3f \n' 
                'MDD = %.2f %%'
            ) % (
                name,
                annualized_return * 100,
                annualized_volatility * 100,
                annualized_return / annualized_volatility,
                MMD * 100,
            )
    
        return info_str
    
    def calc_weekly_winrate(self,df):

        temp=df.copy()
        temp.index=pd.to_datetime(temp.index)
        temp['year']=temp.index.year
        temp['month']=temp.index.month
        temp['week']=temp.index.week
        temp['month']=temp['year'].astype(str)+'-'+temp['month'].astype(str).str.zfill(2)
        temp['week']=temp['year'].astype(str)+'-'+temp['week'].astype(str).str.zfill(2)
        week_series=temp.groupby('week')['hedged_unrealized_pnl'].apply(lambda x : (x[-1]-x[0])/x[0] )
        week_winrate=len(week_series[week_series>0])/len(week_series)
        month_series=temp.groupby('month')['hedged_unrealized_pnl'].apply(lambda x : (x[-1]-x[0])/x[0])
        month_winrate=len(month_series[month_series>0])/len(month_series)
        plt.figure(figsize=(12, 4))
        plt.title(f'月超额收益 月胜率为：{month_winrate*100 :.2f}% 周胜率为：{week_winrate*100 :.2f}%')
        plt.bar(month_series.index,month_series)
        plt.xticks(rotation=45)
        plt.xticks(np.arange(0, len(month_series), step=max(int(len(month_series)/12),1)))
        plt.grid(True,linestyle='--')
        plt.show()
        plt.savefig(joindir(self.output_dir, 'winrate.png'), bbox_inches='tight')

        return week_winrate,month_winrate,month_series

    def calc_MDD_DDD(self,stats):
        stats['DailyPCT'] = stats['hedged_unrealized_pnl'].diff(1)/stats['hedged_unrealized_pnl']
        stats['MaxDrawdown'] = 1-(stats['hedged_unrealized_pnl'] / stats['hedged_unrealized_pnl'].rolling(10000, min_periods=1).max())
        return stats
        
    def calc_group(self):
        signal=self.buy_data.stack().reset_index()
        signal.columns=['date','ticker','signal']
        signal.dropna(inplace=True)
        signal['signal_rank']=signal.groupby('date')['signal'].rank(pct=True)
        label = (self.trade_price.shift(-self.buy_sell_shift) - self.trade_price) / (self.trade_price)
        label = label.stack().reset_index()
        label.columns=['date','ticker','label']
        merge=pd.merge(signal,label,on=['ticker','date'],how='left')
        merge['group']=merge['signal_rank']//(1/10)
        group_ret=merge.groupby(['date','group'])['label'].mean().unstack(1).fillna(0)
        group_ret.columns=[f'group_{int(x)}' for x in group_ret.columns]
        group_ret=group_ret.apply(lambda x : x-x.mean(),axis=1)
        group_ret.index=pd.to_datetime(group_ret.index.astype(str))
        group_ret=group_ret.cumsum()
        group_ret.to_csv(f'{self.output_dir}/group_ret.csv',index=True)
        self.plot_group(group_ret,self.output_dir)
        return None

    def plot(self):
        self.stats = self.trader.stats
        if self.benchmark:
            benchmark_name = self.benchmark
            benchmark = self.get_close_index(benchmark_name, self.date_list[0], self.date_list[-1])
            self.stats['benchmark'] = benchmark['benchmark']
            if self.hedgesell:
                self.benchmark_balance.index = [pd.to_datetime(str(k)) for k in self.benchmark_balance.index]
                hedged_curve = (self.stats['unrealized_pnl'].pct_change() * self.hratio - benchmark['benchmark'].pct_change() *self.benchmark_balance['ratio'] * self.hratio * self.hbili) + 1
            else:
                hedged_curve = (self.stats['unrealized_pnl'].pct_change() * self.hratio - benchmark['benchmark'].pct_change() * self.hratio * self.hbili) + 1
            hedged_curve.iloc[0] = 1.0
            self.stats['hedged_unrealized_pnl'] = hedged_curve.cumprod().dropna() * self.trader.init_cash
            info_str = '\n\n'.join([
                self._get_info_str(self.stats['unrealized_pnl'], self.ICs, 'unrealized_pnl'), 
                self._get_info_str(self.stats['hedged_unrealized_pnl'], name='hedged_unrealized_pnl'),
            ])
        else:
            if self.stock_pool == 'whole':
                benchmark_name = 'zz800'
            else:
                benchmark_name = self.stock_pool
            benchmark = self.get_close_index(benchmark_name, self.date_list[0], self.date_list[-1])
            self.stats['benchmark'] = benchmark['benchmark']
            info_str = self._get_info_str(self.stats['unrealized_pnl'], self.ICs, 'unrealized_pnl')

        self.stats = self.calc_MDD_DDD(self.stats)
        stat = self.stats
        self.calc_weekly_winrate(stat)
        self.benchmark_name = benchmark_name
        # 画图
        dates = matplotlib.dates.date2num(list(stat.index))
        fig, ax1 = plt.subplots(figsize=(12, 6))
        ax2 = ax1.twinx()
        ax1.plot_date(dates, stat['unrealized_pnl'].values/stat['unrealized_pnl'].iloc[0]* self.init_cash, 'C1-', label='unrealized_pnl')
        ax1.plot_date(dates, stat['benchmark'].values, 'C2-', label='benchmark:{}'.format(benchmark_name))
        if self.benchmark:
            ax1.plot_date(dates, stat['hedged_unrealized_pnl'].values, 'C3-', label='hedged_unrealized_pnl')
        ax2.bar(dates, stat['IC'].values, alpha=0.3, label='IC')
        handles1, labels1 = ax1.get_legend_handles_labels()
        handles2, labels2 = ax2.get_legend_handles_labels()
        plt.legend(handles1 + handles2, labels1 + labels2,loc='upper left')
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)
        ax1.text(1.1, 0.5, info_str, 
            horizontalalignment='left',
            verticalalignment='bottom',
            transform=ax1.transAxes,
            bbox=props)
        holding= self.trader.holding_records
        holding['amount']=holding['volume']*holding['price_current']
        holding=holding[holding['volume']!=0]
        avg_holding_count=holding.groupby('date')['volume'].count().mean()
        daily_amount=holding.groupby('date')['amount'].sum()
        trans=self.trader.transaction_records
        trans=trans[trans['B/S']=='buy']
        daily_buy=trans.groupby('date')['amount'].sum()
        turnoverSeries=daily_buy/daily_amount
        turnoverRate=(daily_buy/daily_amount).mean()
        converge_rate=(self.buy_data.count(axis=1)/self.mask_isopen.sum(axis=1)).mean()
        plt.title(f'average_holding:{avg_holding_count: .2f}  turnoverRate:{turnoverRate: .2f} factor_ConvergeRate:{converge_rate: .2f}')
        plt.gcf().autofmt_xdate()
        if self.savemode != 0:
            plt.savefig(joindir(self.output_dir, 'Pnl.png'), bbox_inches='tight')

    def save(self):
        if self.savemode >= 2:
            self.stats.to_csv(joindir(self.output_dir, 'stats.csv'))
        if self.savemode == 3:
            self.transaction_records = self.trader.transaction_records
            self.transaction_records.to_csv(joindir(self.output_dir, 'transaction.csv'))
            self.holding_records = self.trader.holding_records.reset_index()
            self.holding_records.to_csv(joindir(self.output_dir, 'holdings.csv'),index=False)

    def plot_pure_alpha(self,stats):

        plt.rcParams['figure.dpi'] = 150
        fig = plt.figure(figsize=(16, 5))
        date_locator = mdates.AutoDateLocator()  
        date_formatter = mdates.AutoDateFormatter(date_locator)  
        for col in ['hedged_unrealized_pnl','pure_ratio','risk_ratio']:
            summary=self.calc_index(stats[col])
            plt.plot(pd.to_datetime(stats.index),stats[col],label=f'{col}_{summary[0]}')


        plt.gca().xaxis.set_major_locator(date_locator)  
        plt.gca().xaxis.set_major_formatter(date_formatter)  
        plt.gcf().autofmt_xdate()
        plt.legend(loc='upper left')
        plt.xlabel('Date')
        plt.ylabel('Returns')
        plt.title(f'Pure_alpha cummulative')
        plt.grid(True,linestyle='--')
        plt.savefig(joindir(self.output_dir, f'Pure_alpha.png'), bbox_inches='tight')
        
        return None

    def plot_style_risk(self):
        risk_return_attributes=(self.risk_return_attributes+1).cumprod()
        risk_return_attributes.to_csv(joindir(self.output_dir, f'Explo_return.csv'),index=True)
        risk_return_attributes.index=pd.to_datetime(risk_return_attributes.index)
        plt.rcParams['figure.dpi'] = 150
        fig = plt.figure(figsize=(16, 5))
        date_locator = mdates.AutoDateLocator()  
        date_formatter = mdates.AutoDateFormatter(date_locator)  
        select_cols=['BETA', 'MOMENTUM', 'SIZE','EARNYILD', 'RESVOL', 'GROWTH', 'BTOP', 'LEVERAGE', 'LIQUIDTY','SIZENL']

        for col in select_cols:
            plt.plot(risk_return_attributes.index,risk_return_attributes[col],label=f'{col}')


        plt.gca().xaxis.set_major_locator(date_locator)  
        plt.gca().xaxis.set_major_formatter(date_formatter)  
        plt.gcf().autofmt_xdate()
        plt.legend(loc='upper left')
        plt.xlabel('Date')
        plt.ylabel('Returns')
        plt.title(f'Risk_cummulative')
        plt.grid(True,linestyle='--')
        plt.savefig(joindir(self.output_dir, f'Explo_return.png'), bbox_inches='tight')

        return None

    def plot_style_radar(self):

        categories = ['BETA', 'MOMENTUM', 'SIZE', 'EARNYILD', 'RESVOL', 'GROWTH','BTOP','LEVERAGE','LIQUIDTY','SIZENL']  # 类别标签
        N = len(categories)
        df=self.explo.copy().reset_index()
        df.rename(columns={'index':'factor'},inplace=True)
        df['date']=df['date'].apply(lambda x:int(x.replace('-','')))
        port_explo=df.groupby('factor')['port'].mean().loc[categories].tolist()
        benchmark_explo=df.groupby('factor')['benchmark'].mean().loc[categories].tolist()

        angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()  
        port_explo += port_explo[:1]
        benchmark_explo += benchmark_explo[:1]
        angles += angles[:1]  


        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))  
        line1,=ax.plot(angles, port_explo, color="blue", linewidth=0.5)  
        ax.fill(angles, port_explo, color="blue", alpha=0.25)  


        ax.set_yticklabels([])  
        ax.set_xticks(angles[:-1])  
        ax.set_xticklabels(categories)

        line2,=ax.plot(angles, benchmark_explo, color="red", linewidth=0.5)  
        ax.fill(angles, benchmark_explo, color="red", alpha=0.15)
        for i, v in enumerate(port_explo):
            ax.annotate(f'{v:.2f}', (angles[i], port_explo[i]), xytext=(0.05, 0.05), textcoords='offset points', ha='center', va='bottom')

        for i, v in enumerate(benchmark_explo):
            ax.annotate(f'{v:.2f}', (angles[i], benchmark_explo[i]), xytext=(0.05, 0.05), textcoords='offset points', ha='center', va='bottom')



        plt.title(f'Strategy Style Explo')
        lines = [line1, line2]  
        labels = ['portfolio', 'benchmark']  
        ax.legend(lines, labels, loc='upper right', bbox_to_anchor=(1.1, 1.1))
        plt.plot()
        plt.savefig(joindir(self.output_dir, f'Style_radar.png'), bbox_inches='tight')
        return None

    def plot_ind_radar(self):

        df=self.explo.copy().dropna().reset_index()
        df.rename(columns={'index':'factor'},inplace=True)
        ind_list=df['factor'].unique().tolist()
        ind_list=[x for x in ind_list if x in IND_LIST]
        N=len(ind_list)
        df['date']=df['date'].apply(lambda x:int(x.replace('-','')))
        port_explo=df.groupby('factor')['port'].mean().loc[ind_list].tolist()
        benchmark_explo=df.groupby('factor')['benchmark'].mean().loc[ind_list].tolist()

        angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()  
        port_explo += port_explo[:1]
        benchmark_explo += benchmark_explo[:1]
        angles += angles[:1]  


        fig, ax = plt.subplots(figsize=(6, 6), subplot_kw=dict(polar=True))  
        line1,=ax.plot(angles, port_explo, color="blue", linewidth=0.5)  
        ax.fill(angles, port_explo, color="blue", alpha=0.25)  


        ax.set_yticklabels([])  
        ax.set_xticks(angles[:-1])  
        ax.set_xticklabels(ind_list,fontsize=8)

        line2,=ax.plot(angles, benchmark_explo, color="red", linewidth=0.5)  
        ax.fill(angles, benchmark_explo, color="red", alpha=0.15)


        plt.title(f'Strategy Industry Explo')
        lines = [line1, line2]  
        labels = ['portfolio', 'benchmark']  
        ax.legend(lines, labels, loc='upper right', bbox_to_anchor=(1.1, 1.1))
        plt.plot()
        plt.savefig(joindir(self.output_dir, f'Industry_radar.png'), bbox_inches='tight')

        return None        
   
    def Pure_alpha_analysis(self):

        risk_returns=self.risk_return_attributes.sum(axis=1)
        risk_returns.index=pd.to_datetime(risk_returns.index)
        risk_returns.name='risk_ratio'
        stats=self.stats.copy()[['unrealized_pnl','benchmark','hedged_unrealized_pnl']]

        stats['unrealized_pnl']=stats['unrealized_pnl'].pct_change()    
        stats['benchmark']=stats['benchmark'].pct_change()  
        stats['hedged_unrealized_pnl']=stats['hedged_unrealized_pnl'].pct_change()
        stats=pd.concat([stats,risk_returns],axis=1)
        stats['pure_ratio']=stats['unrealized_pnl']-stats['benchmark']-stats['risk_ratio']
        stats.fillna(0,inplace=True)
        stats=stats[['unrealized_pnl','hedged_unrealized_pnl','risk_ratio','pure_ratio']]
        stats=(stats+1).cumprod()

        self.plot_pure_alpha(stats)
        self.plot_style_risk()
        self.explo.to_csv((joindir(self.output_dir, f'Explo.csv')),index=True)
        self.plot_ind_radar()
        self.plot_style_radar()

        return None

    def main_loop(self):
        if self.benchmark == '':
            self.benchmark = 'zz800'
        self.benchmarkdf = self.get_close_index(self.benchmark, self.date_list[0], self.date_list[-1])
        self.benchmarkdf.index = [int(str(k)[:4]+str(k)[5:7]+str(k)[8:10]) for k in self.benchmarkdf.index]
        self.benchmark_balance = pd.DataFrame(1,index=self.date_list,columns=['ratio'])
        for date1 in tqdm(self.date_list):
            self._adjustVolume(date1)
            buy_order,sell_order=self._Buy_Sell(date1)
            self._balance(date1)
            if self.pure_alpha and date1!=self.start_date:
                self._riskcommand(date1,buy_order,sell_order)
            self.pre_date=date1

    def prepare_holdings(self,date,signal_df,ideal_trade_price):
        holdings=self.trader.holdings.copy()[['volume']]
        holdings['signal']=signal_df
        holdings[['volume']]= holdings[['volume']].fillna(0)
        holdings['ideal_trade_price']=ideal_trade_price
        holdings['value']=holdings['volume']*holdings['ideal_trade_price']
        holdings['zt']=self.zt.loc[date]
        holdings['dt']=self.dt.loc[date]
        holdings['isOpen']=self.mask_isopen.loc[date]
        holdings['isST']=self.mask_isST.loc[date]
        holdings['inPool']=self.mask_inpool.loc[date]
        return holdings

    def get_equal_weights_list(self,date,signal_df,holdings):
        current_pool=holdings[holdings['volume']>0].index.tolist()
        current_num=len(current_pool)
        sell_holdings=holdings[(holdings['volume']>0)&(holdings['isOpen']==True)&(holdings['zt']==False)].copy()
        drop_out=sell_holdings[(sell_holdings['isST']==True)|(sell_holdings['inPool']==False)].index.tolist()
        sell_holdings=sell_holdings.drop(index=drop_out)
        unit=holdings['value'].sum()*(1-self.keep)
        drop_out_value=holdings.loc[drop_out]['value'].sum()
        unit-=drop_out_value
        if unit>0:
            sell_holdings.sort_values('signal',ascending=True,inplace=True)
            sell_holdings['cumsumvalue']=sell_holdings['value'].cumsum()
            to_sell=sell_holdings[sell_holdings['cumsumvalue']<unit].index.tolist()
            sell_tickers=drop_out+to_sell
        else:
            sell_tickers=drop_out

        if self.turnover_mode=='flex':
            keep_pool=[x for x in current_pool if x not in sell_tickers]
            ranked_ticker_list = signal_df.sort_values(ascending=False).index.tolist()
            ranked_ticker_list=[x for x in ranked_ticker_list if x not in keep_pool][0:self.longx-len(keep_pool)]
            weights_list = [1/ len(ranked_ticker_list+keep_pool)]*len(ranked_ticker_list+keep_pool)
            weights_list = pd.Series(weights_list,index=ranked_ticker_list+keep_pool)
        else:
            buy_num=max(self.longx-(current_num-len(sell_tickers)),0)
            ranked_ticker_list = signal_df.sort_values(ascending=False).index.tolist()
            buy_tickers=[x for x in ranked_ticker_list if x not in current_pool][0:buy_num]
            final_tickers=[x for x in current_pool if x not in sell_tickers]
            final_tickers.extend(buy_tickers)
            weights_list=pd.Series([1/len(final_tickers)]*len(final_tickers),index=final_tickers)
        
        return weights_list

    def build_position_order(self,adj_factor,trade_price,ideal_trade_price,weights_list,target_value_sum):
        target_position=weights_list.to_frame(name="target_weight")
        target_position['ideal_trade_price']=ideal_trade_price
        target_position['trade_price']=trade_price
        target_position['adj_factor']=adj_factor
        target_position['ticker']=target_position.index
        target_position=target_position.reset_index(drop=True)
        target_position['target_value']=target_value_sum * target_position['target_weight']
        target_position['one_lot'] = target_position['ticker'].apply(lambda ticker: 200 if str(ticker).zfill(6).startswith('688') else 100)
        target_position['trade_volume']=round(target_position['target_value'] / target_position['one_lot'] / target_position['ideal_trade_price']) * target_position['one_lot']
        target_position['B/S']='buy'
        target_position=target_position[target_position['trade_volume']!=0]
        buy=target_position[['ticker','B/S','trade_volume','trade_price','adj_factor']]
        return buy,pd.DataFrame()

    def calc_order(self,adj_factor,trade_price,ideal_trade_price,holdings,weights_list,target_value_sum):
        merge=pd.concat([holdings[['volume']],weights_list],axis=1)
        merge.columns=['volume','target_weight']
        merge.fillna(0,inplace=True)
        merge['ideal_trade_price']=ideal_trade_price
        merge['trade_price']=trade_price
        merge['adj_factor']=adj_factor
        merge['target_volume']=target_value_sum * merge['target_weight']/merge['ideal_trade_price']
        merge['trade_volume']=merge['target_volume']-merge['volume']
        merge['B/S'] = merge['trade_volume'].apply(lambda x: 'buy' if x > 0 else 'sell')
        merge['trade_volume']=merge['trade_volume'].abs()
        merge['ticker']=merge.index
        merge=merge.reset_index(drop=True)
        merge['one_lot'] = merge['ticker'].apply(lambda ticker: 200 if str(ticker).zfill(6).startswith('688') else 100)
        merge['trade_volume']=round(merge['trade_volume'] / merge['one_lot']) * merge['one_lot']
        merge.loc[merge['target_weight']==0,'trade_volume']= merge.loc[merge['target_weight'] == 0, 'volume']
        merge['trade_volume'] = merge.apply(lambda row: row['trade_volume'] if row['B/S'] == 'buy' else min(row['trade_volume'], row['volume']), axis=1)
        merge['value_final'] = merge['trade_volume'] * merge['ideal_trade_price']
        merge=merge[merge['trade_volume']!=0]
        order_df = merge[['ticker', 'B/S', 'trade_volume','trade_price','adj_factor']]
        buy=order_df[(order_df['B/S']=='buy')]
        sell=order_df[(order_df['B/S']=='sell')]
        return buy,sell

    def buyorder_filter(self,buy,date):
        if len(buy)!=0:
            buy=buy.set_index('ticker')
            buy['can_buy']=self.can_buy.loc[date]
            buy=buy[buy['can_buy']].reset_index()
            buy['amount']=buy['trade_volume']*buy['trade_price']
            buy['transaction']=buy['amount']*self.buy_transaction
            buy['date']=date
            buy.rename(columns={'trade_volume':'volume'},inplace=True)
            buy.drop(columns=['can_buy'],inplace=True)


        return buy

    def sellorder_filter(self,sell,date):

        if len(sell)!=0:
            sell=sell.set_index('ticker')
            sell['can_sell']=self.can_sell.loc[date]
            sell=sell[sell['can_sell']].reset_index()
            sell['amount']=sell['trade_volume']*sell['trade_price']
            sell['transaction']=sell['amount']*self.sell_transaction
            sell['date']=date
            sell.rename(columns={'trade_volume':'volume'},inplace=True)
            sell.drop(columns=['can_sell'],inplace=True)

        return sell

    def _Buy_Sell(self,date):

        if date not in self.buy_data.index:
            return  

        available_cash = self.trader.get_available_cash()
        date_str=pd.to_datetime(str(date)).strftime('%Y-%m-%d')
        ideal_trade_price=self.ideal_trade_price.loc[date]
        trade_price=self.real_trade_price.loc[date]
        signal_df=self.buy_data.loc[date].dropna()
        adj_factor=self.adjfactor.loc[date]

        if date==self.start_date:
            ranked_ticker_list = signal_df.dropna().sort_values(ascending=False).index.tolist()[0:self.longx]
            weights_list = [1/ len(ranked_ticker_list)]*len(ranked_ticker_list)
            weights_list = pd.Series(weights_list,index=ranked_ticker_list)
            target_value_sum=self.trader.cash 
            buy,sell=self.build_position_order(adj_factor,trade_price,ideal_trade_price,weights_list,target_value_sum)
        else:
            holdings=self.prepare_holdings(date,signal_df,ideal_trade_price)
            target_value_sum=holdings['value'].sum()+self.trader.cash    
            weights_list=self.get_equal_weights_list(date,signal_df,holdings)
            buy,sell=self.calc_order(adj_factor,trade_price,ideal_trade_price,holdings,weights_list,target_value_sum)

        buy_order=self.buyorder_filter(buy,date)
        sell_order=self.sellorder_filter(sell,date)
        self.trader.sell(sell_order)
        self.trader.buy(buy_order)

        return buy_order,sell_order

    def _adjustVolume(self,date):
        date_adj = self.adjfactor.loc[date,self.trader.holdings.index]
        mask = (np.isfinite(date_adj)) & (date_adj != self.trader.holdings['adj_factor'])
        self.trader.holdings.loc[mask, 'volume'] *= (date_adj[mask] / self.trader.holdings.loc[mask, 'adj_factor'])
        self.trader.holdings.loc[mask, 'adj_factor'] = date_adj[mask]

    def _balance(self, date):
        price_bal = self.balance_price.loc[date,self.trader.holdings.index]
        mask = np.isfinite(price_bal)
        self.trader.holdings.loc[mask, 'price_current'] = price_bal[mask] / self.trader.holdings.loc[mask, 'adj_factor']
        IC = self.ICs.loc[date,'1d'] if date in self.ICs.index else np.nan
        self.trader.balance(date, IC=IC)


    def calc_risk_return_attributes(self,an,weight,benchmark_explo,pr,mode):
        explo=pd.concat([an.BarraExplosure(weight),benchmark_explo],axis=1)
        explo.columns=['port','benchmark']
        explo['pure_ret']=pr[mode]
        explo['explo_ret']=(explo['port']-explo['benchmark'])*explo['pure_ret']
        return explo


    def _riskcommand(self,date,buy_order,sell_order):

        temp_holding=self.trader.holdings[['volume','price_current']].copy()
        adj_factor = self.adjfactor.loc[date]
        balance_price = self.balance_price.loc[date]
        pre_close = self.pre_close.loc[date]
        unrealized_pnl=self.trader.unrealized_pnl
        pre_unrealized_pnl=self.trader.pre_unrealized_pnl
        barraDate=pd.to_datetime(str(self.pre_date)).strftime('%Y-%m-%d')
        date_str=pd.to_datetime(str(date)).strftime('%Y-%m-%d')
        an=Analysis(date=date_str,barraDate=barraDate,benchmark=self.benchmark)
        benchmark_weight=an.benchmark
        barra=an.barra
        pr=an.pure_ret
        benchmark_explo=an.BarraExplosure(benchmark_weight)

        buy_position=buy_order.set_index('ticker')
        buy_position['weight']=buy_position['amount']/buy_position['amount'].sum()
        df_buy=self.calc_risk_return_attributes(an,buy_position['weight'],benchmark_explo,pr,'open_to_close')
        df_buy['explo_return']=df_buy['explo_ret']*(buy_position['amount'].sum())

        sell_position=sell_order.set_index('ticker')
        sell_position['weight']=sell_position['amount']/sell_position['amount'].sum()
        df_sell=self.calc_risk_return_attributes(an,sell_position['weight'],benchmark_explo,pr,'close_to_open')
        df_sell['explo_return']=df_sell['explo_ret']*(sell_position['amount'].sum())

        buy_position= buy_position.reindex(temp_holding.index)
        temp_holding.loc[buy_position.index.tolist(),'notradingvolume']=temp_holding.loc[buy_position.index.tolist(),'volume']-buy_position['volume']
        temp_holding['notradingvolume']=temp_holding['notradingvolume'].fillna(temp_holding['volume'])

        temp_holding['amount']=temp_holding['price_current']*temp_holding['notradingvolume']
        temp_holding['weight']=temp_holding['amount']/temp_holding['amount'].sum()
        temp_holding['amount1']=temp_holding['price_current']*temp_holding['volume']
        temp_holding['weight1']=temp_holding['amount1']/temp_holding['amount1'].sum()

        df_hold=self.calc_risk_return_attributes(an,temp_holding['weight'],benchmark_explo,pr,'close_to_close')
        df_hold['explo_return']=df_hold['explo_ret']*(temp_holding['amount'].sum())
        explo=pd.concat([an.BarraExplosure(temp_holding['weight1']),benchmark_explo],axis=1)
        explo.columns=['port','benchmark']
        explo['date']=date_str
        self._explo.append(explo)
        
        risk_return_attribute=(df_hold['explo_return']+df_sell['explo_return']+df_buy['explo_return'] )/pre_unrealized_pnl
        risk_return_attribute=pd.DataFrame(risk_return_attribute).reset_index()
        risk_return_attribute['date']=date_str
        risk_return_attribute.columns=['factor','explo_return','date']
        risk_return_attribute=risk_return_attribute.set_index(['date','factor'])['explo_return'].unstack(1)
        self._risk_return_attributes.append(risk_return_attribute) 
        return None


    
    def load_basic_data(self,name):
        data=pd.read_parquet(f'{BASE_PATH}/{name}.parquet').rename(columns=int).loc[self.start_date:self.end_date]
        return data

    def load_pool_data(self,pool):
        data=pd.read_parquet(f'{BASE_PATH}/stock_pool/{pool}.parquet').rename(columns=int).loc[self.start_date:self.end_date]
        return data

    def load_auxilliary(self):
        self.namedic=pd.read_parquet(f'{BASE_PATH}/name_dict.parquet').set_index('ticker')['secShortName'].to_dict()
        self.adjfactor=self.load_basic_data('adjfactor')
        self.pre_close=self.load_basic_data('pre_close')
        self.trade_price=self.load_basic_data('trade_price')
        self.balance_price=self.load_basic_data('balance_price')
        self.open_price=self.load_basic_data('open_price')
        self.zt = ((self.open_price / self.pre_close) > (1 + self.LOCKED_LIMIT))
        self.dt = ((self.open_price / self.pre_close) < (1 - self.LOCKED_LIMIT))
        self.ideal_trade_price=self.open_price/self.adjfactor
        self.real_trade_price=self.trade_price/self.adjfactor
        self.mask_isopen=self.load_basic_data('mask_isopen')
        self.ticker_list = sorted(self.mask_isopen.columns.tolist())        
        self.mask_isST = self.load_basic_data('mask_isST')
        if self.stock_pool != 'whole':
            self.mask_inpool=self.load_pool_data(self.stock_pool)
        else:
            self.mask_inpool = pd.DataFrame(True, index=self.date_list, columns=self.ticker_list)
        self.can_buy=(self.mask_isopen)&(~self.zt)
        self.can_sell=(self.mask_isopen)&(~self.dt)

    def preclean_data(self):
        augmented_date_list = sorted(list(set(self.date_list).union(self.data_date_list)))
        self.buy_data = self.data.reindex(index=augmented_date_list, columns=self.ticker_list)
        self.buy_data = self.buy_data.shift(self.buy_sell_shift).reindex(index=self.date_list, columns=self.ticker_list)
        self.buy_data = self.buy_data.where((~self.zt) & (~self.dt) & (self.mask_isopen) & (~self.mask_isST) & (self.mask_inpool))
        self.buy_data = self.buy_data.dropna(how='all',axis=0)

    def load_data(self):

        if self.input_file[-4:] == '.csv':
            data = pd.read_csv(self.input_file)
        elif self.input_file[-8:]=='.parquet':
            data = pd.read_parquet(self.input_file)
        else:
            filelist = os.listdir(self.input_file)
            filelist.sort()
            datalist = []
            for file in filelist:
                if file[-4:] == '.csv':
                    df = pd.read_csv(self.input_file+file)
                elif file[-8:]=='.parquet':
                    df =  pd.read_parquet(self.input_file+file)
                else:
                    return False
                datalist.append(df)
            data = pd.concat(datalist)
        if self.timespan != []:
            data = data.loc[(data['date']>=self.timespan[0])&(data['date']<=self.timespan[1]),:]
        if self.col not in data:
            return False
        if self.reverse:
            data['proba'] = -data[self.col]
        else:
            data['proba'] = data[self.col]
        data = data[['date','ticker','proba']]
        #去重
        data = data.set_index(['date','ticker'])
        data = data[~data.index.duplicated()]
        data = data.reset_index()
        self.data = data.pivot(index='date', columns='ticker', values='proba').astype(float)
        if self.stock_pool != 'whole' or self.pure_alpha:
            self.data=self.data.loc[20160101:]
        self.data_date_list = sorted(self.data.index.tolist())
        self.data_start_date = self.data_date_list[0]
        self.data_end_date = self.data_date_list[-1]
        #持仓权重df
        return True
 
    def load_date_list(self):
        date_list = self._get_trading_dates_uqer()
        start_index = date_list.index(self.data_start_date) + self.buy_sell_shift
        end_index = date_list.index(self.data_end_date) + self.buy_sell_shift-1
        self.date_list = date_list[start_index:end_index + 1]
        self.start_date = date_list[start_index]
        self.end_date = date_list[end_index]

    def _get_trading_dates_uqer(self, start_date=None, end_date=None):
        if start_date is None:
            start_date = 20000101
        if end_date is None:
            end_date = self._get_farthest_possible_date()   
        result=pd.read_parquet(f'{BASE_PATH}/calendar.parquet')
        beginDate=pd.to_datetime(str(start_date)).strftime('%Y-%m-%d')
        endDate=pd.to_datetime(str(end_date)).strftime('%Y-%m-%d')
        result=result[(result['calendarDate']>=beginDate)&(result['calendarDate']<=endDate)]
        date_list = result.loc[result.loc[:, 'isOpen'] == 1, 'calendarDate'].drop_duplicates().tolist()
        date_list = [int(''.join(item.split('-'))) for item in date_list]
        return sorted(date_list)

    def get_close_index(self, pool, start_date, end_date):
        data = self._get_index_uqer(pool, start_date, end_date)
        data = data / data.iloc[0] * self.trader.init_cash
        return data

    def _get_index_uqer(self, pool, start_date, end_date, mode='close'):
        data=pd.read_parquet(f'{BASE_PATH}/Benchmark/{pool}.parquet')
        beginDate=pd.to_datetime(str(start_date)).strftime('%Y-%m-%d')
        endDate=pd.to_datetime(str(end_date)).strftime('%Y-%m-%d')
        data=data[(data['tradeDate']>=beginDate)&(data['tradeDate']<=endDate)]
        data['date'] = pd.to_datetime(data['tradeDate'])
        col = 'closeIndex' if mode=='close' else 'openIndex'
        data['benchmark'] = data[col]
        data = data[['date', 'benchmark']].set_index('date')
        return data


    @staticmethod
    def _get_farthest_possible_date():
        return int((date.today() + timedelta(30)).strftime('%Y%m%d'))
    
    @property
    def risk_return_attributes(self):
        risk_return_attributes=pd.concat(self._risk_return_attributes)
        return risk_return_attributes
    
    @property
    def explo(self):
        explo=pd.concat(self._explo)
        return explo