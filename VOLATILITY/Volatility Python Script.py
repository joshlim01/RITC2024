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
import os
import sys
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

def main():
    
    with requests.Session() as session:
        session.headers.update(API_KEY)
        pd.set_option('chained_assignment',None)
        while get_tick(session) < 600 and not shutdown:
            years_remaining = (600 - get_tick(session))/3600
            maturity_1month = (600 - get_tick(session))/3600 - (1/12)
            assets = pd.DataFrame(get_s(session))
            assets2 = assets.drop(columns=['size', 'position','vwap', 'nlv', 'bid_size', 'ask_size', 'volume', 'realized', 'unrealized', 'currency', 
                                           'total_volume', 'limits', 'is_tradeable', 'is_shortable', 'interest_rate', 'start_period', 'stop_period', 'unit_multiplier', 
                                           'description', 'unit_multiplier', 'display_unit', 'min_price', 'max_price', 'start_price', 'quoted_decimals', 'trading_fee', 'limit_order_rebate',
                                           'min_trade_size', 'max_trade_size', 'required_tickers', 'underlying_tickers', 'bond_coupon', 'interest_payments_per_period', 'base_security', 'fixing_ticker',
                                           'api_orders_per_second', 'execution_delay_ms', 'interest_rate_ticker', 'otc_price_range'])

            for row in assets2.index.values:
                if 'P' in assets2['ticker'].iloc[row]:
                    assets2['type'].iloc[row] = 'PUT'
                elif 'C' in assets2['ticker'].iloc[row]:
                    assets2['type'].iloc[row] = 'CALL'
            assets2_stock= assets2.iloc[0:1]
            assets2_options = assets2.iloc[1:]
            assets2_options['strike'] = assets2_options['ticker'].str[-2:]
            assets2_options['strike'] = assets2_options['strike'].astype(float)
            assets2_option_1m = assets2_options.iloc[:20]
            assets2_option_2m = assets2_options.iloc[21:]

            s = (assets2_stock["bid"] + assets2_stock["ask"])/2
            try:
                sigma = headline_vol(session)
            except Exception:
                pass
        
            assets2_option_1m['bs_model_price'] = assets2_option_1m.apply(lambda row: calculate_bs_price(row,
                                                                                                     s=s, sigma=sigma, 
                                                                                                     t = maturity_1month ), axis=1)

            assets2_option_2m['bs_model_price'] = assets2_option_2m.apply(lambda row: calculate_bs_price(row,
                                                                                                     s=s, sigma=sigma, 
                                                                                                     t = years_remaining ), axis=1)
            assets2_option = pd.concat([assets2_option_1m,assets2_option_2m])
            assets2_option['Bid Spread'] = assets2_option['bs_model_price'] - assets2_option['bid']
            assets2_option['Ask Spread'] = assets2_option['bs_model_price'] - assets2_option['ask']
            assets2_option['Decision'] = assets2_option.apply(lambda row: 'Sell' if row['Bid Spread'] < -0.1 else ('Buy' if row['Ask Spread'] > 0.1 else ''), axis=1)
            #
            assets2= pd.concat([assets2_stock,assets2_option])

            
            print(assets2.to_markdown(), end='\n'*2)
            print(sigma)
            sleep(1)
            
if __name__ == '__main__':
        main()


years_remaining = (600 - get_tick(session))/3600
maturity_1month = (600 - get_tick(session))/3600 - 1/12

assets = pd.DataFrame(get_s(session))
assets2 = assets.drop(columns=['size', 'position','vwap', 'nlv', 'bid_size', 'ask_size', 'volume', 'realized', 'unrealized', 'currency', 
                               'total_volume', 'limits', 'is_tradeable', 'is_shortable', 'interest_rate', 'start_period', 'stop_period', 'unit_multiplier', 
                               'description', 'unit_multiplier', 'display_unit', 'min_price', 'max_price', 'start_price', 'quoted_decimals', 'trading_fee', 'limit_order_rebate',
                               'min_trade_size', 'max_trade_size', 'required_tickers', 'underlying_tickers', 'bond_coupon', 'interest_payments_per_period', 'base_security', 'fixing_ticker',
                               'api_orders_per_second', 'execution_delay_ms', 'interest_rate_ticker', 'otc_price_range'])

for row in assets2.index.values:
    if 'P' in assets2['ticker'].iloc[row]:
        assets2['type'].iloc[row] = 'PUT'
    elif 'C' in assets2['ticker'].iloc[row]:
        assets2['type'].iloc[row] = 'CALL'
    
assets2_stock= assets2.iloc[0:1]
assets2_options = assets2.iloc[1:]
assets2_options['strike'] = assets2_options['ticker'].str[-2:]
assets2_options['strike'] = assets2_options['strike'].astype(float)
assets2_option_1m = assets2_options.iloc[:20]
assets2_option_2m = assets2_options.iloc[21:]

s = assets2_stock["last"][0]
sigma = headline_vol(session)
assets2_option_1m['bs_model_price'] = assets2_option_1m.apply(lambda row: calculate_bs_price(row,
                                                                                         s=s, sigma=sigma, 
                                                                                         t = maturity_1month ), axis=1)

assets2_option_2m['bs_model_price'] = assets2_option_2m.apply(lambda row: calculate_bs_price(row,
                                                                                         s=s, sigma=sigma, 
                                                                                         t = years_remaining ), axis=1)
#
assets2= pd.concat([assets2_stock,assets2_option_1m,assets2_option_2m])


