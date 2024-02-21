import math
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
ARB_THRESHOLD = 0.05
ARB_GAP = 0.02
MIN_ARB_DIFF = ARB_THRESHOLD + 3 * MARKET_FEE
OFFER_THRESHOLD = 0.25

# MM thresholds
SPREAD_MULTIPLIER = 1  # Slightly narrower than market bid ask
MIN_SPREAD_PCT = 0.004  # Spread as percent of price
MIN_SPREAD = 0.2
INVENTORY_MULTIPLIER = 0.005
MAX_LOSS = 0.0025  # Price change 0.3% from best price -> force exit
STOP_LOSS = 0.1
NUM_POSITIONS = 3
SPEEDBUMP = 0.5

API_KEY = {'X-API-Key': 'LOJIC40A'}
shutdown = False
session = requests.Session()
session.headers.update(API_KEY)
exit_event = threading.Event()

tick = 0
curr_positions = {ticker: {"volume": 1, "bid": 1, "ask": 1, "cost": 1, "stop_loss": 1} for ticker in TICKERS}


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


def calc_stop_loss(market_price, cost, position):
    if position > 0:
        # return market_price * (1 - MAX_LOSS)
        return market_price - STOP_LOSS
    else:
        # return market_price * (1 + MAX_LOSS)
        return market_price + STOP_LOSS


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
                # elif prev_cost != 0 and abs((cost - prev_cost)/prev_cost) > 0.001: #Significant change in average cost
                #     stop_loss = calc_stop_loss(price, cost, volume)
                elif volume > 0:
                    stop_loss = max(stop_loss, calc_stop_loss(price, cost, volume))
                elif volume < 0:
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

    print("market order", action, quantity)


def limit_order(session, security_name, price, quantity, action):
    orders = int(abs(quantity) // POSITION_SIZE)
    remainder = int(abs(quantity % POSITION_SIZE))

    for o in range(orders):
        session.post('http://localhost:9999/v1/orders',
                     params={'ticker': security_name, 'type': 'LIMIT', 'price': price,
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
def unwind_arb(session, positions):
    for ticker, action in positions:
        market_order(session, ticker, POSITION_SIZE, action)


def stock_RITC_arb(session):
    arb_positions = None
    while not exit_event.is_set():
        update_positions(session)
        check_losses(session)

        hawk_bid, hawk_ask = curr_positions["HAWK"]["bid"], curr_positions["HAWK"]["ask"]
        dove_bid, dove_ask = curr_positions["DOVE"]["bid"], curr_positions["DOVE"]["ask"]
        ritc_bid, ritc_ask = curr_positions["RIT_C"]["bid"], curr_positions["RIT_C"]["ask"]

        if arb_positions and abs(ritc_bid - (hawk_ask + dove_ask)) < ARB_GAP:
            print("UNWINDING:", ritc_bid, hawk_ask, dove_ask)
            print(ritc_bid - (hawk_ask + dove_ask))
            unwind_arb(session, arb_positions)
            arb_positions = None

        else:
            # In theory, stocks are undervalued, ritc is overvalued
            if MIN_ARB_DIFF < ritc_bid - (hawk_ask + dove_ask):
                print("RITC overpriced, difference:", ritc_bid - (hawk_ask + dove_ask))
                market_order(session, "HAWK", POSITION_SIZE, "BUY")
                market_order(session, "DOVE", POSITION_SIZE, "BUY")
                market_order(session, "RIT_C", POSITION_SIZE, "SELL")
                arb_positions = [("HAWK", "SELL"), ("DOVE", "SELL"), ("RIT_C", "BUY")]

            elif MIN_ARB_DIFF < (hawk_bid + dove_bid) - ritc_ask:
                print("RITC underpriced, difference:", (hawk_bid + dove_bid) - ritc_ask)
                market_order(session, "RIT_C", POSITION_SIZE, "BUY")
                market_order(session, "HAWK", POSITION_SIZE, "SELL")
                market_order(session, "DOVE", POSITION_SIZE, "SELL")
                arb_positions = [("HAWK", "BUY"), ("DOVE", "BUY"), ("RIT_C", "SELL")]

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
# Manually accept offer, unload this way
etf_positions = {ticker: {"volume": 1, "bid": 1, "ask": 1, "cost": 1, "stop_loss": 1} for ticker in
                     ["RIT_C", "RIT_U"]}

MARKET_PCT = 0.1
FIRST_INCREASE = 0.025
SECOND_INCREASE = 0.05
STOP_LOSS = 0.1

def manage_position(session):
    global etf_positions

    while not exit_event.is_set():
        update_positions(session)
        check_losses(session)
        resp = session.get('http://localhost:9999/v1/securities')

        if resp.ok:
            orders = resp.json()

            for order in orders:
                ticker = order["ticker"]

                if ticker == "RIT_C" or ticker == "RIT_U":
                    volume = order["position"]
                    cost = order["vwap"]
                    bid = curr_positions[ticker]["bid"]
                    ask = curr_positions[ticker]["ask"]
                    prev_volume = etf_positions[ticker]["volume"]
                    stop_loss = etf_positions[ticker]["stop_loss"]

                    if abs(prev_volume - volume) > 500:  # Accepted tender offer
                        delete_orders(session, ticker)
                        if volume > 0:
                            stop_loss = max(cost, bid - STOP_LOSS)
                        else:
                            stop_loss = min(cost, ask + STOP_LOSS)

                        market_quantity = math.floor(MARKET_PCT * volume)
                        rem_quantity = (volume - market_quantity)//2
                        
                        if volume > 500:
                            market_order(session, ticker, market_quantity, "SELL")
                            limit_order(session, ticker, ask + FIRST_INCREASE, rem_quantity, "SELL")
                            limit_order(session, ticker, ask + SECOND_INCREASE, rem_quantity, "SELL")
                            print("Selling curr volume:", volume, "sold market:", market_quantity, "limit 1:", ask+FIRST_INCREASE, 
                                  "limit 2:", ask+SECOND_INCREASE, "stop loss:", stop_loss)
                        elif volume < -500:
                            market_order(session, ticker, -market_quantity, "BUY")
                            limit_order(session, ticker, bid - FIRST_INCREASE, -rem_quantity, "BUY")
                            limit_order(session, ticker, bid - SECOND_INCREASE, -rem_quantity, "BUY")
                            print("Buying curr volume:", volume, "bought market:", -market_quantity, "limit 1:", bid-FIRST_INCREASE,
                                  "limit 2:", bid - SECOND_INCREASE, "stop loss:", stop_loss)
                        else:
                            print("Offload rest", volume)
                            offload_inventory(session, ticker)

                    etf_positions[ticker] = {"volume": volume, "bid": bid, "ask": ask,
                                             "cost": cost, "stop_loss": stop_loss}

        sleep(SPEEDBUMP)


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
    update_positions(session)
    price = tender_offer["price"]
    quantity = tender_offer["quantity"]
    ticker = tender_offer["ticker"]
    id = tender_offer["tender_id"]
    bid, ask = curr_positions[ticker]["bid"], curr_positions[ticker]["ask"]

    if tender_offer["action"] == "SELL":
        print("Ask:", ask, "New tender", tender_offer)
    else:
        print("Bid:", bid, "New tender", tender_offer)

    # Client wants to buy from us
    if tender_offer["action"] == "SELL" and price > ask + OFFER_THRESHOLD:
        session.post(f'http://localhost:9999/v1/tenders/{id}')
        print("Accepted buy offer", quantity)

    elif tender_offer["action"] == "BUY" and price < bid - OFFER_THRESHOLD:
        session.post(f'http://localhost:9999/v1/tenders/{id}')
        print("Accepted sell offer", quantity)


# ---------- MARKET MAKER ------------ #
def check_losses(session):
    for ticker in ["RIT_C", "RIT_U"]:
        stop_loss = curr_positions[ticker]["stop_loss"]
        volume = curr_positions[ticker]["volume"]
        bid, ask = curr_positions[ticker]["bid"], curr_positions[ticker]["ask"]

        if volume > 0 and bid < stop_loss:
            print(f"TICK {tick}: {ticker} Hit stop loss {stop_loss}, unwinding position at", bid)
            offload_inventory(session, ticker)
        elif volume < 0 and ask > stop_loss:
            print(f"TICK {tick}: {ticker} Hit stop loss {stop_loss}, unwinding position at", ask)
            offload_inventory(session, ticker)


def make_market(session, tickers):
    while not exit_event.is_set():
        update_positions(session)
        check_losses(session)
        
        for ticker in tickers:
            bid, ask = curr_positions[ticker]["bid"], curr_positions[ticker]["ask"]
            price_t = (bid + ask) / 2
            spread = ask - bid
    
            if spread > MIN_SPREAD:
                inventory = curr_positions[ticker]["volume"]
                inventory_multiplier = (inventory / POSITION_LIMITS["gross"]) * INVENTORY_MULTIPLIER
    
                price_t *= (1 - inventory_multiplier)
                quantity = POSITION_SIZE * NUM_POSITIONS
                set_spread = spread * SPREAD_MULTIPLIER / 2
    
                print(f"{ticker} Initial BID, ASK:", bid, ask)
                bid = price_t - set_spread
                ask = price_t + set_spread
                print(f"{ticker} Inventory:", inventory, "Submitted BID, ASK:", bid, ask)
    
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
        thread_mm = threading.Thread(target=make_market, args=(session, ["RIT_C", "HAWK", "DOVE"]))
        thread_mm.start()

        # ARBITRAGE STRAT
        # thread_arb = threading.Thread(target=stock_RITC_arb, args=(session,))
        # thread_arb.start()

        # TENDER OFFER STRAT
        # thread_offers = threading.Thread(target=get_tender_offers, args=(session,))
        # thread_offers.start()

        """
        thread_get_offers = threading.Thread(target=get_tender_offers, args=(session,))
        thread_get_offers.start()

        thread_offers = threading.Thread(target=manage_position, args=(session,))
        thread_offers.start()
        """

        while tick < 295 and not shutdown:
            sleep(SPEEDBUMP)
            # update_tick(session)
        exit_event.set()

        thread_mm.join()
        # thread_arb.join()
        #thread_get_offers.join()
        #thread_offers.join()


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
