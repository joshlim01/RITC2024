# -*- coding: utf-8 -*-
"""
Created on Fri Feb 16 01:07:49 2024

@author: nolan
"""
"""
Volatility Support File 3
Rotman BMO Finance Research and Trading Lab, Uniersity of Toronto (C)
"""

import signal
import requests
from time import sleep
import pandas as pd
import numpy as np
from library import*


# class that passes error message, ends the program
class ApiException(Exception):
    pass

# code that lets us shut down if CTRL C is pressed
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True
    
API_KEY = {'X-API-Key': '7ASCTY2D'}
shutdown = False
session = requests.Session()
session.headers.update(API_KEY)
    
#code that gets the current tick
def get_tick(session):
    resp = session.get('http://localhost:9999/v1/case')
    if resp.ok:
        case = resp.json()
        return case['tick'] + (case['period'] - 1) * 300
    raise ApiException('fail - cant get tick')

#code that gets the securities via json  
def get_s(session):
    price_act = session.get('http://localhost:9999/v1/securities')
    if price_act.ok:
        prices = price_act.json()
        return prices
    raise ApiException('fail - cant get securities')    

def main(margin = 0.15, delta_limit_threshold = 200, delta_hedge_switch = "ON"): # margin is in spread % terms
    
    with requests.Session() as session:
        session.headers.update(API_KEY)
        pd.set_option('chained_assignment',None)
        while get_tick(session) < 600 and not shutdown:
            time = get_tick(session)
            years_remaining = (600 - get_tick(session))/3600
            maturity_1month = (600 - get_tick(session))/3600 - (1/12)
            assets = pd.DataFrame(get_s(session))
            assets2 = assets.drop(columns=['vwap', 'nlv', 'bid_size', 'ask_size', 'volume', 'realized', 'unrealized', 'currency', 
                                           'total_volume', 'limits', 'is_tradeable', 'is_shortable', 'interest_rate', 'start_period', 'stop_period', 'unit_multiplier', 
                                           'description', 'unit_multiplier', 'display_unit', 'min_price', 'max_price', 'start_price', 'quoted_decimals', 'trading_fee', 'limit_order_rebate',
                                           'min_trade_size', 'max_trade_size', 'required_tickers', 'underlying_tickers', 'bond_coupon', 'interest_payments_per_period', 'base_security', 'fixing_ticker',
                                           'api_orders_per_second', 'execution_delay_ms', 'interest_rate_ticker', 'otc_price_range'])
              
            for row in assets2.index.values:
                if 'P' in assets2['ticker'].iloc[row]:
                    assets2['type'].iloc[row] = 'PUT'
                elif 'C' in assets2['ticker'].iloc[row]:
                    assets2['type'].iloc[row] = 'CALL'
            #stock data        
            assets2_stock= assets2.iloc[0:1]
            s = (assets2_stock["bid"] + assets2_stock["ask"])/2
            #options data
            assets2_options = assets2.iloc[1:]
            assets2_options['strike'] = assets2_options['ticker'].str[-2:]
            assets2_options['strike'] = assets2_options['strike'].astype(float)
            assets2_options["S-K"] = s.iloc[0] - assets2_options["strike"]

            
            #split and find ATM
            assets2_option_1m = assets2_options.iloc[:20]
            min_indices_1m = (assets2_option_1m["S-K"].abs()).idxmin()     
            assets2_option_1m.loc[min_indices_1m, "S-K"] = "ATM"
            
            assets2_option_2m = assets2_options.iloc[20:]
            min_indices_2m = (assets2_option_2m["S-K"].abs()).idxmin()     
            assets2_option_2m.loc[min_indices_2m, "S-K"] = "ATM"
            
              
            try:
                sigma = headline_vol(session)
                sigma_array = []
                sigma_array.append(sigma)
            except Exception:
                print("error")
            
            assets2_option_1m['bs_model_price'] = assets2_option_1m.apply(lambda row: calculate_bs_price(row,
                                                                                                     s=s, sigma=sigma, 
                                                                                                     t = maturity_1month,output = "price" ), axis=1)
            assets2_option_1m['delta'] = assets2_option_1m.apply(lambda row: calculate_bs_price(row,
                                                                                                     s=s, sigma=sigma, 
                                                                                                     t = maturity_1month, output = "delta"), axis=1)
            #assets2_option_1m['vega'] = assets2_option_1m.apply(lambda row: calculate_vega_per_row(row, s, t = 
            #maturity_1month,sigma = sigma), axis=1)
              
            assets2_option_2m['bs_model_price'] = assets2_option_2m.apply(lambda row: calculate_bs_price(row,
                                                                                                     s=s, sigma=sigma, 
                                                                                                     t = years_remaining, output = "price"), axis=1)
            assets2_option_2m['delta'] = assets2_option_2m.apply(lambda row: calculate_bs_price(row,
                                                                                                     s=s, sigma=sigma, 
                                                                                                     t = years_remaining, output = 'delta'), axis=1)
            #assets2_option_2m['vega'] = assets2_option_1m.apply(lambda row: calculate_vega_per_row(row, s, t = years_remaining, sigma = sigma), axis=1)
            
            # bid and ask spread and decisions
            margin = 0.15 #percentage
            assets2_options = pd.concat([assets2_option_1m,assets2_option_2m])
            assets2_options['Bid Spread'] = assets2_options['bs_model_price'] - assets2_options['bid']
            assets2_options['Bid Spread %'] = (assets2_options['bs_model_price'] - assets2_options['bid'])/assets2_options['bid']
            assets2_options['Ask Spread'] = assets2_options['bs_model_price'] - assets2_options['ask']
            assets2_options['Ask Spread %'] = (assets2_options['bs_model_price'] - assets2_options['ask']) /assets2_options['ask']
            assets2_options['Average Spread'] = (assets2_options['Bid Spread']+assets2_options['Ask Spread'])/2
            assets2_options['Average Spread %'] = (assets2_options['Bid Spread %']+assets2_options['Ask Spread %'])/2
            assets2_options['Average Spread % Abs'] = abs((assets2_options['Bid Spread %']+assets2_options['Ask Spread %'])/2)
            assets2_options['Decision'] = assets2_options.apply(lambda row: 'Sell' if row['Bid Spread %'] < -margin else ('Buy' if row['Ask Spread'] > margin else ''), axis=1)
            #hedge ratio
            assets2_options = calculate_hedge_ratios(assets2_options)
            
            #algo - buy 
            assets2_options2 =  assets2_options.sort_values(by='Average Spread % Abs', ascending=False)
            assets2_options2 = assets2_options2[(assets2_options2["Decision"] != '')]
            
            
            #finalize assets2 table
            assets2_stock['delta'] = 1
            assets2= pd.concat([assets2_stock,assets2_options])
            ticker_column = assets2.pop('ticker')
            ticker_column = ticker_column.str[-4:]
            assets2.insert(len(assets2.columns), 'ticker', ticker_column)
            
            a1 = np.array(assets2['position'].iloc[0:])
            a2 = np.array(assets2['size'].iloc[0:])
            a3 = np.array(assets2['delta'].iloc[0:])
            
            #helper
            helper = pd.DataFrame(index = range(1),columns = ['share_exposure', 'required_hedge'])
            helper['share_exposure'] = np.nansum(a1 * a2 * a3)
            helper['required_hedge'] = helper['share_exposure'].iloc[0] * -1
            

            #DYNAMIC DELTA HEDGE orders
            if delta_hedge_switch == "ON":                
                try:
                    delta_limit = get_delta_limit(session)
                except Exception:
                    pass
                threshhold = delta_limit_threshold
                if helper['share_exposure'].iloc[0] > threshhold:
                    excess_delta = helper['share_exposure'].iloc[0] - threshhold
                    market_order(session, "RTM", abs(excess_delta), "SELL")
                if helper['share_exposure'].iloc[0]  <  -threshhold:
                    excess_delta = helper['share_exposure'].iloc[0] + threshhold
                    market_order(session, "RTM", abs(excess_delta), "BUY")
                if assets2["position"].iloc[1:].sum() == 0 and abs(assets2["position"].iloc[0]) < 50000:
                    excess_delta = helper['share_exposure'].iloc[0]
                    market_order(session, "RTM", 100, "BUY", POSITION_SIZE = abs(excess_delta)) if excess_delta < 0 \
                    else market_order(session, "RTM", abs(excess_delta), "SELL")
            else: pass
            

            assets_refreshed = pd.DataFrame(get_s(session))
            assets2_refreshed = assets.drop(columns=['vwap', 'nlv', 'bid_size', 'ask_size', 'volume', 'realized', 'unrealized', 'currency', 
                                           'total_volume', 'limits', 'is_tradeable', 'is_shortable', 'interest_rate', 'start_period', 'stop_period', 'unit_multiplier', 
                                           'description', 'unit_multiplier', 'display_unit', 'min_price', 'max_price', 'start_price', 'quoted_decimals', 'trading_fee', 'limit_order_rebate',
                                           'min_trade_size', 'max_trade_size', 'required_tickers', 'underlying_tickers', 'bond_coupon', 'interest_payments_per_period', 'base_security', 'fixing_ticker',
                                           'api_orders_per_second', 'execution_delay_ms', 'interest_rate_ticker', 'otc_price_range'])
 
            
            #drop columns we dont need
            assets2.drop(columns = ["size",'Absolute Delta', 'bs_model_price', 'Bid Spread', 'Ask Spread', 'Bid Spread %', 'Ask Spread %', "Average Spread % Abs"], inplace=True)
            
            assets2_1m = assets2.iloc[0:20,:]
            assets2_2m = pd.concat([assets2.iloc[[0]], assets2.iloc[21:]])
            
            if time <300:
                print(assets2_1m.to_markdown(), end='\n'*2)
                print(assets2_2m.to_markdown(), end='\n'*2)
                print(helper.to_markdown(), end='\n'*2)
            elif time == 0:
                print("wait for case")
            else:
                print(assets2_2m.to_markdown(), end='\n'*2)
                print(helper.to_markdown(), end='\n'*2)
            #y = assets2['last']
            #plt.plot(y)
            #plt.plotsize(50, 30)
            print("Volatility is", sigma)
            sleep(0.5)

with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=RuntimeWarning)        
    if __name__ == '__main__':
            main()


time = get_tick(session)
years_remaining = (600 - get_tick(session))/3600
maturity_1month = (600 - get_tick(session))/3600 - (1/12)
assets = pd.DataFrame(get_s(session))
assets2 = assets.drop(columns=['vwap', 'nlv', 'bid_size', 'ask_size', 'volume', 'realized', 'unrealized', 'currency', 
                               'total_volume', 'limits', 'is_tradeable', 'is_shortable', 'interest_rate', 'start_period', 'stop_period', 'unit_multiplier', 
                               'description', 'unit_multiplier', 'display_unit', 'min_price', 'max_price', 'start_price', 'quoted_decimals', 'trading_fee', 'limit_order_rebate',
                               'min_trade_size', 'max_trade_size', 'required_tickers', 'underlying_tickers', 'bond_coupon', 'interest_payments_per_period', 'base_security', 'fixing_ticker',
                               'api_orders_per_second', 'execution_delay_ms', 'interest_rate_ticker', 'otc_price_range'])
  
for row in assets2.index.values:
    if 'P' in assets2['ticker'].iloc[row]:
        assets2['type'].iloc[row] = 'PUT'
    elif 'C' in assets2['ticker'].iloc[row]:
        assets2['type'].iloc[row] = 'CALL'
#stock data        
assets2_stock= assets2.iloc[0:1]
s = (assets2_stock["bid"] + assets2_stock["ask"])/2
#options data
assets2_options = assets2.iloc[1:]
assets2_options['strike'] = assets2_options['ticker'].str[-2:]
assets2_options['strike'] = assets2_options['strike'].astype(float)
assets2_options["S-K"] = s.iloc[0] - assets2_options["strike"]


#split and find ATM
assets2_option_1m = assets2_options.iloc[:20]
min_indices_1m = (assets2_option_1m["S-K"].abs()).idxmin()     
assets2_option_1m.loc[min_indices_1m, "S-K"] = "ATM"

assets2_option_2m = assets2_options.iloc[20:]
min_indices_2m = (assets2_option_2m["S-K"].abs()).idxmin()     
assets2_option_2m.loc[min_indices_2m, "S-K"] = "ATM"

  
try:
    sigma = headline_vol(session)
    sigma_array = []
    sigma_array.append(sigma)
except Exception:
    print("error")
  



