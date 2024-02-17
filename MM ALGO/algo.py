import signal
import requests
from time import sleep
import pandas as pd
import matplotlib.pyplot as plt

TICKERS = ["USD", "HAWK", "DOVE", "RIT_C", "RIT_U"]
CONVERTER_FEE = 1500
POSITION_SIZE = 10000
MARKET_FEE = 0.02
ETF_LIMIT_FEE = 0.03
STOCK_LIMIT_FEE = 0.04
POSITION_LIMITS = {"gross": 0, "net": 0}

# TODO: tune parameters
ARB_THRESHOLD = 0.3
ETF_ARB_THRESHOLD = 0.3
SPREAD_MULTIPLIER = 0.9 #Slightly narrower than market bid ask
MIN_PRICE_MOVEMENT = 0.1
MAX_INVENTORY = POSITION_LIMITS["gross"]*0.7
SPEEDBUMP = 0.5
MAX_ORDERS = 5

API_KEY = {'X-API-Key': 'GITHUB'}
shutdown = False
session = requests.Session()
session.headers.update(API_KEY)

#Stores latest and previous price
market_prices = {ticker: (0, 0) for ticker in TICKERS}
curr_positions = {ticker: 0 for ticker in TICKERS}
sum_positions = {"gross": 0, "net": 0}
buy_orders = {ticker: {"price": 0, "order_id": None} for ticker in TICKERS}
sell_orders = {ticker: {"price": 0, "order_id": None} for ticker in TICKERS}
tick = 0
prev_price = 0

class ApiException(Exception):
    pass


# code that lets us shut down if CTRL C is pressed
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True


# ---------- GET DATA FROM SERVER ------------ #
def get_tick(session):
    global tick
    resp = session.get('http://localhost:9999/v1/case')
    if resp.ok:
        case = resp.json()
        return case['tick']
    raise ApiException('fail - cant get tick')


def get_bid_ask_volumes(session, ticker):
    payload = {'ticker': ticker, 'limit': 3}
    resp = session.get('http://localhost:9999/v1/securities/book', params=payload)
    if resp.ok:
        book = resp.json()
        bid_volumes = sum(bid['volume'] for bid in book['bids'])
        ask_volumes = sum(ask['volume'] for ask in book['asks'])
        return bid_volumes, ask_volumes
    raise ApiException('API error')


# TODO: For now just takes the lastest one, doesn't care about volume
def get_bid_ask(session, ticker):
    payload = {'ticker': ticker, 'limit': 3}
    resp = session.get('http://localhost:9999/v1/securities/book', params=payload)
    if resp.ok:
        book = resp.json()
        if len(book) > 0:  # TODO fix this
            return book['bids'][0]['price'], book['asks'][0]['price']
    raise ApiException('API error')


# Gets estimate of market price - for now only uses first bid first ask
def get_market_prices(session):
    global market_prices
    for ticker in TICKERS:
        last_price = market_prices[ticker][1]
        bid, ask = get_bid_ask(session, ticker)
        new_price = (bid + ask) / 2
        market_prices[ticker] = (last_price, new_price)

def update_positions(session):
    global curr_positions
    global sum_positions
    global buy_orders
    global sell_orders

    # TODO: deal with limits
    gross_limit = 0
    net_limit = 0

    for ticker in buy_orders:
        id = buy_orders[ticker]["order_id"]
        if id:
            resp = session.get(f'http://localhost:9999/v1/orders/{id}')
            quantity = resp.json()["quantity_filled"]
            curr_positions[ticker] += quantity
            print("BUY", id, ticker, quantity, curr_positions[ticker])

    for ticker in sell_orders:
        id = sell_orders[ticker]["order_id"]
        if id:
            resp = session.get(f'http://localhost:9999/v1/orders/{id}')
            quantity = resp.json()["quantity_filled"]
            curr_positions[ticker] -= quantity
            print("SELL", id, ticker, quantity, curr_positions[ticker])

    print("Current Positions:", curr_positions)


def get_position_limits(session):
    global POSITION_LIMITS
    resp = session.get('http://localhost:9999/v1/limits')
    if resp.ok:
        limits = resp.json()
        POSITION_LIMITS["gross"] = limits["gross_limit"]
        POSITION_LIMITS["net"] = limits["net_limit"]
    raise ApiException('API error')


# ---------- TRADE EXECUTION ------------ #
def market_order(session, security_name, quantity, action):
    session.post('http://localhost:9999/v1/orders', params={'ticker': security_name, 'type': 'MARKET',
                                                            'quantity': quantity, 'action': action})


def limit_order(session, security_name, price, quantity, action):
    resp = session.post('http://localhost:9999/v1/orders', params={'ticker': security_name, 'type': 'LIMIT',
                                                                   'price': price, 'quantity': quantity,
                                                                   'action': action})
    if resp.ok:
        print("Made order", resp.json()["order_id"])
        return resp.json()["order_id"]


def delete_order(session, id):
    session.delete('http://localhost:9999/v1/orders/{}'.format(id))


# ---------- ARBITRAGE OPS ------------ #
# TODO: this should also work for RIT_CU
def stock_RITC_arb(session):
    sum_stocks = market_prices["HAWK"] + market_prices["DOVE"]
    # Fees from buying 2 stocks, selling 1 etf
    if sum_stocks + 3 * MARKET_FEE + ARB_THRESHOLD < market_prices["RIT_C"]:
        market_order(session, "HAWK", POSITION_SIZE, "BUY")
        market_order(session, "DOVE", POSITION_SIZE, "BUY")
        print("CONVERT STOCK -> RIT_C")
        market_order(session, "RIT_C", POSITION_SIZE, "SELL")

    elif sum_stocks > market_prices["RIT_C"] + 3 * MARKET_FEE + ARB_THRESHOLD:
        market_order(session, "RIT_C", POSITION_SIZE, "BUY")
        print("CONVERT RIT_C -> STOCK")
        market_order(session, "HAWK", POSITION_SIZE, "SELL")
        market_order(session, "DOVE", POSITION_SIZE, "SELL")


# Differences in pricing between RIT_C
def RITC_RITU_arb(session):
    USD, RIT_C, RIT_U = market_prices["USD"], market_prices["RIT_C"], market_prices["RIT_U"]
    if RIT_C * USD > RIT_U + 2 * MARKET_FEE + ETF_ARB_THRESHOLD:
        market_order(session, "RIT_C", POSITION_SIZE, "SELL")
        market_order(session, "RIT_U", POSITION_SIZE, "BUY")
        # TODO: get transacted orders to get how much usd i need to buy
        quantity_usd = 0
        market_order(session, "USD", quantity_usd, "SELL")
    elif RIT_C * USD < 2 * MARKET_FEE + ETF_ARB_THRESHOLD + RIT_U:
        pass
        # TODO fill here


# ---------- TENDER OFFERS ------------ #
# def get_tender_offers(session)
#   resp = session.get('http://localhost:9999/v1/tenders')
#   if resp.ok:
#       tenders = resp.json()
#       print("received tenders", tenders) #TODO: check tender format
#       return tenders
#   raise ApiException('API error')

# #Accept under 3 conditions i
# def process_tender_offers(offers):
#   for offer in offers:
#     pass #TODO: how do you know what ticker

# #Price is optional if fixed bid
# def accept_offer(session, id, price=None):
#   session.post(f'http://localhost:9999/v1/tenders/{id}',params={'price': price})

# def decline_offer(session, id):
#   session.delete(f'http://localhost:9999/v1/tenders/{id}')


# ---------- MARKET MAKER ------------ #
def make_market(session, ticker):
    global buy_orders
    global sell_orders

    prev_price, curr_price = market_prices[ticker]
    
    #TODO: delete really just for debugging
    bid, ask = get_bid_ask(session, ticker)
    prev_bid = buy_orders[ticker]["price"]
    prev_ask = sell_orders[ticker]["price"]

    # Price change, recalculate bid ask
    if abs(curr_price - prev_price) > MIN_PRICE_MOVEMENT:
        print("Price moved from", prev_price, curr_price)
        update_positions(session) #get latest numbers for inventory
        quantity = POSITION_SIZE

        # TODO: adjsut all of this - factor this into spread
        # bid_volumes, ask_volumes = get_bid_ask_volumes(session, ticker)
        # volume_imbalance = (sum(bid_volumes) - sum(ask_volumes)) / sum(bid_volumes + ask_volumes)
        inventory = curr_positions[ticker]/POSITION_SIZE
        inventory_multiplier = inventory/MAX_INVENTORY
        spread = SPREAD_MULTIPLIER*(ask - bid)

        bid = (curr_price - spread/2)*(1-inventory_multiplier)
        ask = (curr_price + spread/2)*(1-inventory_multiplier)

        # orders = 1
        # quantity = max(POSITION_SIZE, POSITION_LIMITS["gross"] - sum_positions["gross"],
        #                POSITION_LIMITS["net"] - sum_positions["net"]) // 2


        #Adjust bid
        prev_bid_id = buy_orders[ticker]["order_id"]
        delete_order(session, prev_bid_id) 
        # TODO: don't delete if bid hasn't moved much, though prob not big problem
        new_id = limit_order(session, ticker, bid, quantity, "BUY")
        buy_orders[ticker] = {"price": bid, "order_id": new_id}
        print("Replace buy", bid, prev_bid)

        #Adjust ask
        prev_ask_id = sell_orders[ticker]["order_id"]
        delete_order(session, prev_ask_id)
        new_id = limit_order(session, ticker, ask, quantity, "SELL")
        sell_orders[ticker] = {"price": ask, "order_id": new_id}
        print("Replace sell", ask, prev_ask)


# #TODO: add safety feature: if price too far from purchase, offload at market
# def offload_inventory(session):
#   for ticker in tickers:
#     if open_position[ticker] > MAX_HOLD:
#   market_order(session, security_name, action)

# ---------- RUN ALGO ------------ #
def main():
    with requests.Session() as session:
        session.headers.update(API_KEY)

        while get_tick(session) < 295 and not shutdown:
            get_market_prices(session)
            make_market(session, "RIT_C")
            sleep(SPEEDBUMP)


if __name__ == '__main__':
    main()
