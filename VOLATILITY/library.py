# -*- coding: utf-8 -*-
"""
Created on Fri Feb 16 18:08:22 2024

@author: nolan
"""

import pandas as pd
import numpy as np
from scipy.stats import norm
import numpy as np
import warnings

def black_scholes(s, k, t, r, sigma, option_type):
    """
    Calculate the theoretical price of a European option using the Black-Scholes formula.

    s: spot price of the underlying asset
    k: strike price
    t: time to expiration in years
    r: risk-free interest rate
    sigma: volatility of the underlying asset
    option_type: 'CALL' or 'PUT'
    """
    # Calculate d1 and d2 parameters
    d1 = (np.log(s / k) + (r + 0.5 * sigma ** 2) * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    
    # Calculate the call price
    if option_type == 'CALL':
        option_price = (s * norm.cdf(d1) - k * np.exp(-r * t) * norm.cdf(d2))
    # Calculate the put price
    elif option_type == 'PUT':
        option_price = (k * np.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1))
    else:
        raise ValueError("Invalid option type. Use 'CALL' or 'PUT'.")

    return option_price

def goal_seek_implied_volatility(s, k, t, market_price, option_type, r = 0 , tol=1e-6, max_iter=100):
    """
    Calculate implied volatility using a goal-seeking method.

    s: spot price of the underlying asset
    k: strike price
    t: time to expiration in years
    r: risk-free rate
    market_price: market price of the option
    option_type: 'CALL' or 'PUT'
    tol: tolerance for convergence
    max_iter: maximum number of iterations
    """
    lower_vol = 0
    upper_vol = 3  # A high upper bound for volatility (300%)
    sigma = (upper_vol + lower_vol) / 2

    for _ in range(max_iter):
        price = black_scholes(s, k, t, r, sigma, option_type)
        if abs(price - market_price) < tol:
            return sigma

        # Adjust bounds based on whether calculated price is higher or lower than market price
        if price > market_price:
            upper_vol = sigma
        else:
            lower_vol = sigma

        sigma = (upper_vol + lower_vol) / 2

    raise ValueError("Implied volatility not found within maximum iterations")
    
    
def calculate_iv(row):
    return goal_seek_implied_volatility(row['spot_price'], row['strike_price'], 
                                        row['time_to_expiry'], 0, row['option_price'], 
                                        row['option_type'])

def black_scholes_call(s, k, t, r, sigma, output="price"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        d1 = (np.log(s / k) + (r + 0.5 * sigma ** 2) * t) / (sigma * np.sqrt(t))
        d2 = d1 - sigma * np.sqrt(t)
        call_price = s * norm.cdf(d1) - k * np.exp(-r * t) * norm.cdf(d2)
        if output == "price":
            return call_price
        if output == "delta":
            return norm.cdf(d1)

def black_scholes_put(s, k, t, r, sigma, output="price"):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        d1 = (np.log(s / k) + (r + 0.5 * sigma ** 2) * t) / (sigma * np.sqrt(t))
        d2 = d1 - sigma * np.sqrt(t)
        put_price = k * np.exp(-r * t) * norm.cdf(-d2) - s * norm.cdf(-d1)
        if output == "price":
            return put_price
        if output == 'delta':
            return -norm.cdf(-d1)

def calculate_bs_price(row, s, sigma, t, r=0, output = "price"):
    k = row['strike']
    if row['type'] == 'CALL':
        return black_scholes_call(s, k, t, r, sigma, output = output)
    else:
        return black_scholes_put(s, k, t, r, sigma, output = output)

        
    
def fetch_data(session, endpoint):
    resp = session.get(f'http://localhost:9999/v1/{endpoint}')
    if resp.ok:
        return resp.json()
    raise ApiException(f'Failed to fetch data from {endpoint}')   
    
def get_data(session, endpoint):
    return fetch_data(session, endpoint)
    
    
def headline_vol(session):
    news = get_data(session, 'news')
    volatility_array = []
    for item in news:
        if 'Risk' in item['headline']:
            # Get the initial volatility
            int_volatility = float(item['body'].split('volatility is ')[1].split('%')[0]) / 100
            volatility_array.append(int_volatility)
        elif 'News' in item['headline']:
            news_items = [item for item in news if 'Announcement' not in item['headline']]

            relevant_expected_volatility = news_items[0] if news_items else None

            if relevant_expected_volatility:
                volatility_info = relevant_expected_volatility['body']
                volatility_text = volatility_info.split('between ')[1].split(', and')[0]
                volatility_range = [int(x.strip('%'))/100 for x in volatility_text.split(' ~ ')]
                if len(volatility_range) == 2:
                       E_vol1, E_vol2 = volatility_range
                       mean_volatility = sum(volatility_range) / 2
                       volatility_array.append(mean_volatility)

        elif 'Announcement' in item['headline']:
            # Get volatility from announcement
            ann_volatility = float(item['body'].split('RTM is ')[1].split('%')[0]) / 100
            volatility_array.append(ann_volatility)
        
    vol=volatility_array[0]      
    return vol


def calculate_hedge_ratios(df):
    
    # Function to extract and return the absolute first element of the delta array
    def extract_first_and_abs(delta_array):
        return abs(delta_array[0])

    # Adding a new column to the DataFrame with the absolute delta values
    df['Absolute Delta'] = df['delta'].apply(extract_first_and_abs)

    # List to store the hedge ratios
    hedge_ratios = []

    # Iterating over the DataFrame two rows at a time
    for i in range(1, len(df) + 1, 2):
        call_delta = df.loc[i, 'Absolute Delta']
        put_delta = df.loc[i + 1, 'Absolute Delta']

        # Calculating the hedge ratios
        if call_delta >= put_delta and put_delta != 0:  # Avoid division by zero
            call_hedge_ratio = 1
            put_hedge_ratio = call_delta / put_delta
        elif call_delta < put_delta:
            put_hedge_ratio = 1
            call_hedge_ratio = put_delta / call_delta
        else:
            call_hedge_ratio = None  # or some default value
            put_hedge_ratio = None

        # Adding the hedge ratios for call and put rows
        hedge_ratios.extend([call_hedge_ratio, put_hedge_ratio])

    # Adding the hedge ratios to the DataFrame
    df['Hedge Ratio'] = hedge_ratios
    df['Hedge Ratio'] = df['Hedge Ratio'].round(2)
    return df


