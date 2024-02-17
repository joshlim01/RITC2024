import signal
import requests
from time import sleep
import pandas as pd

class ApiException(Exception):
    pass

# Function to handle Ctrl+C signal
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True

API_KEY = {'X-API-Key': 'ASDFGH12'}
shutdown = False

# Function to fetch data from the API
def fetch_data(session, endpoint):
    resp = session.get(f'http://localhost:9999/v1/{endpoint}')
    if resp.ok:
        return resp.json()
    raise ApiException(f'Failed to fetch data from {endpoint}')

# Function to get the current tick
def get_tick(session):
    resp = fetch_data(session, 'case')
    case = resp
    return case['tick'] + (case['period'] - 1) * 300

# Function to get securities or news via JSON
def get_data(session, endpoint):
    return fetch_data(session, endpoint)

def main():
    with requests.Session() as session:
        session.headers.update(API_KEY)
        pd.set_option('chained_assignment', None)
        while get_tick(session) < 600 and not shutdown:
            years_remaining = (600 - get_tick(session)) / 3600
            
            # Fetch securities data
            securities = get_data(session, 'securities')
            assets2 = pd.DataFrame(securities)
            
            # Filter out unnecessary columns
            assets2 = assets2.drop(columns=['vwap', 'nlv', 'bid_size', 'ask_size', 'volume', 'realized', 'unrealized', 'currency', 
                                           'total_volume', 'limits', 'is_tradeable', 'is_shortable', 'interest_rate', 'start_period', 'stop_period', 'unit_multiplier', 
                                           'description', 'unit_multiplier', 'display_unit', 'min_price', 'max_price', 'start_price', 'quoted_decimals', 'trading_fee', 'limit_order_rebate',
                                           'min_trade_size', 'max_trade_size', 'required_tickers', 'underlying_tickers', 'bond_coupon', 'interest_payments_per_period', 'base_security', 'fixing_ticker',
                                           'api_orders_per_second', 'execution_delay_ms', 'interest_rate_ticker', 'otc_price_range'])
            
            # Add type column based on ticker
            assets2['type'] = assets2['ticker'].apply(lambda x: 'PUT' if 'P' in x else ('CALL' if 'C' in x else None))
            
            # Print securities data
            print(assets2.to_markdown(), end='\n'*2)
            
            # Fetch news data
            news = get_data(session, 'news')
            
            # Function to extract volatility from news items
            def headline_vol(session):
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
            
            # Get volatility array
            volatility = headline_vol(session)
            print(f"Volatility: {volatility}")
            
            # Sleep for 1 second
            sleep(1)

if __name__ == "__main__":
    main()
