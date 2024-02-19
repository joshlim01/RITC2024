import signal
import requests
from time import sleep
import threading

TICKERS = ["HAWK", "DOVE", "RIT_C", "RIT_U"]
POSITION_SIZE = 10000
MARKET_FEE = 0.02
ETF_LIMIT_FEE = 0.03
STOCK_LIMIT_FEE = 0.04
POSITION_LIMITS = {"gross": 0, "net": 0}

# Arb and tender offer thresholds
ARB_THRESHOLD = 0.01
MIN_ARB_DIFF = ARB_THRESHOLD + 3 * MARKET_FEE
ETF_ARB_THRESHOLD = 0.05
MIN_ETF_ARB = 0
OFFER_THRESHOLD = 0.2

# MM thresholds
SPREAD_MULTIPLIER = 0.95  # Slightly narrower than market bid ask
MIN_SPREAD_PCT = 0.004  # Spread as percent of price
MIN_SPREAD = 0.15
INVENTORY_MULTIPLIER = 0.005
MAX_LOSS = 0.003  # Price change 0.3% from best price -> force exit

SPEEDBUMP = 0.5
MAX_ORDERS = 5

API_KEY = {'X-API-Key': 'GITHUB'}
shutdown = False
session = requests.Session()
session.headers.update(API_KEY)
exit_event = threading.Event()

tick = 0
curr_positions = {ticker: {"volume": 0, "bid": 0, "ask": 0, "cost": 0, "stop_loss": 0} for ticker in TICKERS}

class ApiException(Exception):
    pass


# code that lets us shut down if CTRL C is pressed
def signal_handler(signum, frame):
    global shutdown
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    shutdown = True


# ---------- GET DATA FROM SERVER ------------ #
def get_position_limits(session):
    global POSITION_LIMITS
    resp = session.get('http://localhost:9999/v1/limits')
    if resp.ok:
        limits = resp.json()
        POSITION_LIMITS["gross"] = limits[0]["gross_limit"]
        POSITION_LIMITS["net"] = limits[0]["net_limit"]
    else:
        raise ApiException('API error')


def update_tick(session):
    global tick
    resp = session.get('http://localhost:9999/v1/case')
    if resp.ok:
        case = resp.json()
        tick = case['tick']
    else:
        raise ApiException("Cannot connect to server")


def get_bid_ask_volumes(session, ticker):
    payload = {'ticker': ticker, 'limit': 3}
    resp = session.get('http://localhost:9999/v1/securities/book', params=payload)
    if resp.ok:
        book = resp.json()
        bid_volumes = sum(bid['quantity'] for bid in book['bids'])
        ask_volumes = sum(ask['quantity'] for ask in book['asks'])
        return bid_volumes, ask_volumes
    raise ApiException('API error')


def calc_stop_loss(market_price, cost, position):
    if position > 0:
        # change = market_price - cost #TODO: maybe add to the multiplier
        return market_price * (1 - MAX_LOSS)
    else:
        return market_price * (1 + MAX_LOSS)


def update_positions(session):
    global curr_positions

    resp = session.get('http://localhost:9999/v1/securities')

    if resp.ok:
        orders = resp.json()
        for order in orders:
            ticker = order["ticker"]

            if ticker != "CAD" and ticker != "USD":
                volume = order["position"]
                cost = order["vwap"]
                price = order["last"]
                bid = order["bid"]
                ask = order["ask"]
                prev_volume = curr_positions[ticker]["volume"]
                stop_loss = curr_positions[ticker]["stop_loss"]

                if (prev_volume >= 0 and volume < 0) or (prev_volume <= 0 and volume > 0):
                    stop_loss = calc_stop_loss(price, cost, volume)
                elif volume > 0:
                    stop_loss = max(stop_loss, calc_stop_loss(price, cost, volume))
                else:
                    stop_loss = min(stop_loss, calc_stop_loss(price, cost, volume))

                curr_positions[ticker] = {"volume": volume, "bid": bid, "ask": ask,
                                          "cost": cost, "stop_loss": stop_loss}


# ---------- TRADE EXECUTION ------------ #
def market_order(session, security_name, quantity, action):
    orders = int(abs(quantity) // POSITION_SIZE)
    remainder = int(abs(quantity % POSITION_SIZE))

    for o in range(orders):
        session.post('http://localhost:9999/v1/orders', params={'ticker': security_name, 'type': 'MARKET',
                                                                'quantity': POSITION_SIZE, 'action': action})

    session.post('http://localhost:9999/v1/orders', params={'ticker': security_name, 'type': 'MARKET',
                                                            'quantity': remainder, 'action': action})


def limit_order(session, security_name, price, quantity, action):
    orders = int(abs(quantity) // POSITION_SIZE)
    remainder = int(abs(quantity % POSITION_SIZE))

    for o in range(orders):
        session.post('http://localhost:9999/v1/orders', params={'ticker': security_name, 'type': 'LIMIT', 'price': price,
                                                                'quantity': POSITION_SIZE, 'action': action})

    session.post('http://localhost:9999/v1/orders', params={'ticker': security_name, 'type': 'LIMIT', 'price': price,
                                                            'quantity': remainder, 'action': action})


def delete_orders(session, ticker):
    resp = session.get(f'http://localhost:9999/v1/orders?status=OPEN&ticker={ticker}')
    if resp.ok:
        orders = resp.json()
        for order in orders:
            id = order["order_id"]
            session.delete('http://localhost:9999/v1/orders/{}'.format(id))


def offload_inventory(session, ticker):
    quantity = curr_positions[ticker]["volume"]
    action = "BUY" if quantity < 0 else "SELL"

    market_order(session, ticker, quantity, action)


# ---------- ARBITRAGE OPS ------------ #
# TODO: This should also work with RIT_U
def stock_RITC_arb(session):
    while not exit_event.is_set():
        hawk_bid, hawk_ask = curr_positions["HAWK"]["bid"], curr_positions["HAWK"]["ask"]
        dove_bid, dove_ask = curr_positions["DOVE"]["bid"], curr_positions["DOVE"]["ask"]
        ritc_bid, ritc_ask = curr_positions["RIT_C"]["bid"], curr_positions["RIT_C"]["ask"]

        # In theory, stocks are undervalued, ritc is overvalued
        if MIN_ARB_DIFF < ritc_bid - (hawk_ask + dove_ask):
            print("RITC overpriced, difference:", ritc_bid - (hawk_ask + dove_ask))
            market_order(session, "HAWK", POSITION_SIZE, "BUY")
            market_order(session, "DOVE", POSITION_SIZE, "BUY")
            market_order(session, "RIT_C", POSITION_SIZE, "SELL")

        elif MIN_ARB_DIFF < (hawk_bid + dove_bid) - ritc_ask:
            print("RITC underpriced, difference:", (hawk_bid + dove_bid) - ritc_ask)
            market_order(session, "RIT_C", POSITION_SIZE, "BUY")
            market_order(session, "HAWK", POSITION_SIZE, "SELL")
            market_order(session, "DOVE", POSITION_SIZE, "SELL")

        sleep(SPEEDBUMP)


# Differences in pricing between RIT_C
# def RITC_RITU_arb(session):
#     USD, RIT_C, RIT_U = market_prices["USD"], market_prices["RIT_C"], market_prices["RIT_U"]
#     if RIT_C * USD > RIT_U + 2 * MARKET_FEE + ETF_ARB_THRESHOLD:
#         market_order(session, "RIT_C", POSITION_SIZE, "SELL")
#         usd_amount = market_order(session, "RIT_U", POSITION_SIZE, "BUY")
#         print("Bought", usd_amount)
#         market_order(session, "USD", usd_amount, "SELL")
#     # elif RIT_C * USD < 2 * MARKET_FEE + ETF_ARB_THRESHOLD + RIT_U:
#     #     pass
#     # TODO fill here


# ---------- TENDER OFFERS ------------ #
def get_tender_offers(session):
    while not exit_event.is_set():
        resp = session.get('http://localhost:9999/v1/tenders')
        if resp.ok:
            tenders = resp.json()
            if len(tenders) > 0:
                curr_tender = tenders[-1]
                process_offer(session, curr_tender)

        sleep(SPEEDBUMP)


def process_offer(session, tender_offer):
    print("New tender", tender_offer)

    price = tender_offer["price"]
    quantity = tender_offer["quantity"]
    ticker = tender_offer["ticker"]
    id = tender_offer["tender_id"]
    bid, ask = curr_positions[ticker]["bid"], curr_positions[ticker]["ask"]

    #Client wants to buy from us
    if tender_offer["action"] == "SELL" and price > ask + OFFER_THRESHOLD:
        resp = session.post(f'http://localhost:9999/v1/tenders/{id}')
        if resp.json()["success"]:
            market_order(session, ticker, quantity//2, "BUY")
            print("Accepted buy offer", quantity)

    elif tender_offer["action"] == "BUY" and price < bid - OFFER_THRESHOLD:
        resp = session.post(f'http://localhost:9999/v1/tenders/{id}')
        if resp.json()["success"]:
            market_order(session, ticker, quantity//2, "SELL")
            print("Accepted sell offer", quantity)


# ---------- MARKET MAKER ------------ #
def check_losses(session):
    for ticker in TICKERS:
        stop_loss = curr_positions[ticker]["stop_loss"]
        volume = curr_positions[ticker]["volume"]
        bid, ask = curr_positions[ticker]["bid"], curr_positions[ticker]["ask"]

        if volume > 0 and bid < stop_loss:
            print(f"TICK {tick}: {ticker} Hit stop loss {stop_loss}, unwinding position at", bid)
            offload_inventory(session, ticker)
        elif volume < 0 and ask > stop_loss:
            print(f"TICK {tick}: {ticker} Hit stop loss {stop_loss}, unwinding position at", ask)
            offload_inventory(session, ticker)


def make_market(session, ticker):
    while not exit_event.is_set():
        update_positions(session)
        check_losses(session)

        bid, ask = curr_positions[ticker]["bid"], curr_positions[ticker]["ask"]
        price_t = (bid + ask) / 2
        spread = ask - bid

        if spread > MIN_SPREAD:
            inventory = curr_positions[ticker]["volume"]
            inventory_multiplier = (inventory / POSITION_LIMITS["gross"]) * INVENTORY_MULTIPLIER

            price_t *= (1 - inventory_multiplier)
            quantity = POSITION_SIZE*3

            set_spread = spread * SPREAD_MULTIPLIER / 2

            # TODO: adjsut all of this - factor this into spread
            # bid_volumes, ask_volumes = get_bid_ask_volumes(session, ticker)
            # volume_imbalance = (sum(bid_volumes) - sum(ask_volumes)) / sum(bid_volumes + ask_volumes)
            # orders = 1
            # quantity = max(POSITION_SIZE, POSITION_LIMITS["gross"] - sum_positions["gross"],
            #                POSITION_LIMITS["net"] - sum_positions["net"]) // 2

            # TODO: uneven bid ask
            # bid_multiplier = min(0.0, inventory_multiplier)
            # ask_multiplier = max(0.0, inventory_multiplier)
            # bid = bid * (1 - bid_multiplier) * (1 + SPREAD_MULTIPLIER)
            # ask = ask * (1 - ask_multiplier) * (1 - SPREAD_MULTIPLIER)
            # print("Inventory:", inventory, "Bid multiplier:", bid_multiplier, "Ask multiplier:", ask_multiplier)

            print("Initial BID, ASK:", bid, ask)
            bid = price_t - set_spread
            ask = price_t + set_spread
            print("Inventory:", inventory, "Submitted BID, ASK:", bid, ask)

            # Adjust bid and ask
            delete_orders(session, ticker)
            limit_order(session, ticker, bid, quantity, "BUY")
            limit_order(session, ticker, ask, quantity, "SELL")

        sleep(SPEEDBUMP)


# ---------- RUN ALGO ------------ #
def main():
    global exit_event
    global tick

    with requests.Session() as session:
        session.headers.update(API_KEY)
        get_position_limits(session)
        update_tick(session)

        # MARKET MAKING STRAT
        thread_mm = threading.Thread(target=make_market, args=(session, "RIT_C"))
        thread_mm.start()

        #ARBITRAGE STRAT
        # thread_arb = threading.Thread(target=stock_RITC_arb, args=(session,))
        # thread_arb.start()

        # TENDER OFFER STRAT
        # thread_offers = threading.Thread(target=get_tender_offers, args=(session,))
        # thread_offers.start()

        while tick < 295 and not shutdown:
            sleep(SPEEDBUMP)
            update_tick(session)
        exit_event.set()

        thread_mm.join()
        #thread_arb.join()
        # thread_offers.join()


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
