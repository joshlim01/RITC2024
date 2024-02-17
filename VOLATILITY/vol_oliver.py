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
            
            # Filter news for announcements and news
            announcements = [item for item in news if 'Announcement' in item['headline']]
            relevant_announcement = announcements[0] if announcements else None
            news_items = [item for item in news if 'Announcement' not in item['headline']]
            relevant_expected_volatility = news_items[0] if news_items else None
            
            # Get volatility from announcement
            if relevant_announcement:
                volatility = float(relevant_announcement['body'].split('is ')[1].split('%')[0]) / 100
                print(f"Volatility={volatility:.2f}", end=", ")
            else:
                print("No relevant announcement found.")
            
            # Get volatility range from news
            if relevant_expected_volatility:
                volatility_info = relevant_expected_volatility['body']
                volatility_text = volatility_info.split('between ')[1].split(', and')[0]
                volatility_range = [int(x.strip('%'))/100 for x in volatility_text.split(' ~ ')]
                if len(volatility_range) == 2:
                    E_vol1, E_vol2 = volatility_range
                    mean_volatility = sum(volatility_range) / len(volatility_range)
                    print(f"E_vol1={E_vol1:.2f}, E_vol2={E_vol2:.2f}, Mean of Volatility={mean_volatility:.3f}")
                else:
                    print("Invalid volatility range format.")
            else:
                print("No relevant expected volatility found.")
            
            # Sleep for 1 second
            sleep(1)

if __name__ == "__main__":
    main()
