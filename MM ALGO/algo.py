import signal
import requests
from time import sleep

# from multiprocessing import Pool
import sys

API_KEY = {'X-API_Key': 'QPALQPAL'}
TICKERS = ["USD", "HAWK", "DOVE", "RITC", "RITU"]
CONVERTER_FEE = 1500
MAX_POSITION_SIZE = 10000
MARKET_FEE = 0.02
ETF_LIMIT_FEE = 0.03
STOCK_LIMIT_FEE = 0.04
POSITION_LIMITS = {"gross": 0, "net": 0}

# Price difference in arbitrage required to enter
ARB_THRESHOLD = 0.3
ETF_ARB_THRESHOLD = 0.3
SPREAD = 0.3
MIN_PRICE_MOVEMENT = 0.05
SPEEDBUMP = 0.5
MAX_ORDERS = 5

shutdown = False
curr_prices = {ticker: 0 for ticker in TICKERS}
curr_positions = {ticker: 0 for ticker in TICKERS}
sum_positions = {"gross": 0, "net": 0}
buy_orders = {ticker: {"price": 0, "order_id": 0} for ticker in TICKERS}
sell_orders = {ticker: {"price": 0, "order_id": 0} for ticker in TICKERS}


class ApiException(Exception):
    # handler for api errors
    pass

# handles a shutdown for ^C
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True


# ---------- GET DATA FROM SERVER ------------ #
def get_tick(session):
    resp = session.get('http://localhost:9999/v1/case')
    if resp.ok:
        case = resp.json()
        return case['tick']
    raise ApiException('API error')


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
        return book['bids'][0], book['asks'][0]
    raise ApiException('API error')


# Gets estimate of market price - for now only uses first bid first ask
def get_market_prices(session):
    global curr_prices
    for ticker in TICKERS:
        bid, ask = get_bid_ask(session, ticker)
        curr_prices[ticker] = (bid + ask) / 2


def update_positions(session):
    global curr_positions
    global sum_positions
    global buy_orders
    global sell_orders

    # TODO: deal with limits
    gross_limit = 0
    net_limit = 0

    for ticker in buy_orders:
        price, id = buy_orders[ticker]
        resp = session.get('http://localhost:9999/v1/orders/{id}')
        quantity = resp["quantity_filled"]
        curr_positions[ticker] += quantity

    for ticker in sell_orders:
        price, id = sell_orders[ticker]
        resp = session.get('http://localhost:9999/v1/orders/{id}')
        quantity = resp["quantity_filled"]
        curr_positions[ticker] -= quantity

    print("Current Positions:", curr_positions)

    raise ApiException('API error')


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
        return resp.json()["order_id"]

def delete_order(session, id):
    session.delete('http://localhost:9999/v1/orders/{}'.format(id))


# ---------- ARBITRAGE OPS ------------ #
# TODO: this should also work for RITCU
def stock_ritc_arb(session):
    sum_stocks = curr_prices["HAWK"] + curr_prices["DOVE"]
    # Fees from buying 2 stocks, selling 1 etf
    if sum_stocks + 3 * MARKET_FEE + ARB_THRESHOLD < curr_prices["RITC"]:
        market_order(session, "HAWK", MAX_POSITION_SIZE, "BUY")
        market_order(session, "DOVE", MAX_POSITION_SIZE, "BUY")
        print("CONVERT STOCK -> RITC")
        market_order(session, "RITC", MAX_POSITION_SIZE, "SELL")

    elif sum_stocks > curr_prices["RITC"] + 3 * MARKET_FEE + ARB_THRESHOLD:
        market_order(session, "RITC", MAX_POSITION_SIZE, "BUY")
        print("CONVERT RITC -> STOCK")
        market_order(session, "HAWK", MAX_POSITION_SIZE, "SELL")
        market_order(session, "DOVE", MAX_POSITION_SIZE, "SELL")


# Differences in pricing between RITC
def ritc_ritu_arb(session):
    usd, ritc, ritu = curr_prices["USD"], curr_prices["RITC"], curr_prices["RITU"]
    if ritc * usd > ritu + 2 * MARKET_FEE + ETF_ARB_THRESHOLD:
        market_order(session, "RITC", MAX_POSITION_SIZE, "SELL")
        market_order(session, "RITU", MAX_POSITION_SIZE, "BUY")
        # TODO: get transacted orders to get how much usd i need to buy
        quantity_usd = 0
        market_order(session, "USD", quantity_usd, "SELL")
    elif ritc * usd < 2 * MARKET_FEE + ETF_ARB_THRESHOLD + ritu:
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

    price = curr_prices[ticker]
    bid, ask = get_bid_ask(session, ticker)

    # TODO: factor this into spread
    # bid_volumes, ask_volumes = get_bid_ask_volumes(session, ticker)
    # volume_imbalance = (sum(bid_volumes) - sum(ask_volumes)) / sum(bid_volumes + ask_volumes)
    # inventory_imbalance = curr_positions[ticker]
    spread = ask - bid
    m_bid = 1
    m_ask = 1

    prev_bid = buy_orders[ticker]["price"]
    prev_ask = sell_orders[ticker]["price"]
    bid = price - m_bid * spread
    ask = price + m_ask * spread

    orders = 1
    quantity = max(MAX_POSITION_SIZE, POSITION_LIMITS["gross"] - sum_positions["gross"],
                   POSITION_LIMITS["net"] - sum_positions["net"]) // 2

    # Delete old order if prices have moved too much
    if abs(bid - prev_bid) > MIN_PRICE_MOVEMENT:
        prev_bid_id = buy_orders[ticker]["id"]
        delete_order(session, prev_bid_id)
        new_id = limit_order(session, ticker, bid, quantity, "BUY")

    if abs(ask - prev_ask) > MIN_PRICE_MOVEMENT:
        prev_ask_id = sell_orders[ticker]["id"]
        delete_order(session, prev_ask_id)
        limit_order(session, ticker, ask, quantity, "SELL")


# #TODO: add safety feature: if price too far from purchase, offload at market
# def offload_inventory(session):
#   for ticker in tickers:
#     if open_position[ticker] > MAX_HOLD:
#   market_order(session, security_name, action):

# ---------- RUN ALGO ------------ #
def main():
    with requests.Session() as s:
        s.headers.update(API_KEY)
        tick = get_tick(s)
        get_position_limits(s)

    while (tick > 5) and (tick < 295) and not shutdown:
        print("Current tick:", tick)
        get_market_prices(s)
        update_positions(s)
        make_market(s, "RITC")
        sleep(SPEEDBUMP)
        tick = get_tick(s)


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
