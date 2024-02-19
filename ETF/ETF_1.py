
import signal
import requests
from time import sleep
import pandas as pd

def Bidask_percentage(row):
    a = row['ask']
    b = row['bid']
    percentage = (a - b) * 100 / ((a + b) / 2)
    return percentage

def Market_depth_ratio(row):
    a_s = row['ask_size']
    b_s = row['bid_size']
    ratio = a_s / b_s
    return ratio



class ApiException(Exception):
    pass

API_KEY = {'X-API-Key': 'ASDFGH12'}
shutdown = False

def get_tick(session):
    resp = session.get('http://localhost:9999/v1/case')
    if resp.ok:
        case = resp.json()
        return case['tick']
    raise ApiException('fail - cant get tick')

def get_securities(session):
    book = session.get('http://localhost:9999/v1/securities')
    if book.ok:
        securities = book.json()
        return securities
    raise ApiException('Error retrieving basic security info')
def get_tenders(session):
    tenders_resp = session.get('http://localhost:9999/v1/tenders')
    if tenders_resp.ok:
        tenders = tenders_resp.json()
        return tenders
    raise ApiException('Error retrieving tenders')
  
    

def tender_pnl(row, quantity):
    if row['ten_offer'] == 'BUY':
        return (row['price'] - row['ask']) * quantity
    elif row['ten_offer'] == 'SELL':
        return (row['bid'] - row['price']) * quantity
    else:
        return 0    
    
class MarketDepthTracker:
    def __init__(self):
        self.previous_market_depth = {}
    
    def get_market_depth_slope(self, row):
        ticker = row.name
        current_market_depth = row['ask_size'] / row['bid_size']
        slope = 0
        
        if ticker in self.previous_market_depth:
            previous_market_depth = self.previous_market_depth[ticker]
            slope = (current_market_depth - previous_market_depth) / 0.5  # Assuming the time step is 0.2 seconds
        self.previous_market_depth[ticker] = current_market_depth
        return slope

def main():
    with requests.Session() as session:
        session.headers.update(API_KEY)
        etf = pd.DataFrame(columns=['position', 'last', 'bid_size', 'bid', 'ask', 'ask_size', 'volume'], index=['RITC', 'COMP'])
        market_depth_tracker = MarketDepthTracker()
        while get_tick(session) < 600 and not shutdown:
            if get_tick(session) == 0:
                print('Wait for Case')
                sleep(1)
            else:
                securities = get_securities(session)
                
                for i in securities:
                    etf.loc[i['ticker']] = pd.Series({'position': i['position'], 'last': i['last'], 'bid_size': i['bid_size'], 'bid': i['bid'], 'ask': i['ask'], 'ask_size': i['ask_size'], 'volume': i['volume']})
                
              
               
                # Retrieve tender offer data and add 'price' to DataFrame
                tenders = get_tenders(session)
                tender_prices = {}
                ten_offer = {}
                ten_type = {}
                tender_quantity={}
                for tender in tenders:
                    ticker = tender['ticker']
                    price = tender['price']
                    ten_offer[ticker] = tender['action']
                    ten_type[ticker] = tender['is_fixed_bid']
                    tender_prices[ticker] = price
                    tender_quantity=tender['quantity']
                etf['ten_offer'] = etf.index.map(ten_offer)
                etf['ten_type'] = etf.index.map(ten_type)
                etf['P_ten'] = etf.index.map(tender_prices)
                
                # Define decision-making functions
                def make_buy(row):
                    if row['ten_offer'] == 'BUY':
                        if not row['ten_type']:
                            return [row['ask']+0.1,row['ask'] + 0.04],
                        else:
                            return 'Take' if row['P_ten'] < row['ask'] else 'Decline'
                    else:
                        return 0
                
                def make_sell(row):
                    if row['ten_offer'] == 'SELL':
                        if not row['ten_type']:
                            return [row['bid'] - 0.04,row['bid']-0.01]
                        else:
                            return 'Take' if row['P_ten']>row['bid'] else 'Decline'
                    else:
                        return 0
                
                # Apply decision-making functions based on the type of tender offer (BUY or SELL)
                etf['Spread(%)'] = etf.apply(Bidask_percentage, axis=1)
                etf['Mkt Dpt'] = etf.apply(Market_depth_ratio, axis=1)
                etf['Market Depth Slope'] = etf.apply(market_depth_tracker.get_market_depth_slope, axis=1)
                etf['Direction'] = etf.apply(lambda row: 'UP' if row['Mkt Dpt'] < 0.09 else ('Down' if row['Mkt Dpt'] > 10 else ''), axis=1)
                etf['Decision'] = etf.apply(lambda row: make_buy(row) if row['ten_offer'] == 'BUY' else make_sell(row) if row['ten_offer'] == 'SELL' else '', axis=1)
                # Print the DataFrame with relevant columns
                print(etf[['position', 'last',  'bid', 'ask', 'Direction', 'P_ten', 'Decision']].to_markdown(), end='\n'*2)
                
                sleep(0.5)





if __name__ == '__main__':
    main()
