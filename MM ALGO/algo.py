import signal
import requests
from time import sleep
import threading

TICKERS = ["HAWK", "DOVE", "RIT_C", "RIT_U"]
POSITION_SIZE = 10000
POSITION_LIMITS = {"gross": 0, "net": 0}
SPEEDBUMP = 0.5
API_KEY = {'X-API-Key': 'GITHUB'}
shutdown = False
session = requests.Session()
session.headers.update(API_KEY)
exit_event = threading.Event()
tick = 0


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


def get_asset_info(session, ticker):
    resp = session.get(f'http://localhost:9999/v1/securities?ticker={ticker}')

    if resp.ok:
        order = resp.json()[0]
        return order["bid"], order["ask"], order["position"]


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
        session.post('http://localhost:9999/v1/orders',
                     params={'ticker': security_name, 'type': 'LIMIT', 'price': price,
                             'quantity': POSITION_SIZE, 'action': action})

    session.post('http://localhost:9999/v1/orders', params={'ticker': security_name, 'type': 'LIMIT', 'price': price,
                                                            'quantity': remainder, 'action': action})


def delete_all_orders(session, ticker):
    resp = session.get(f'http://localhost:9999/v1/orders?status=OPEN&ticker={ticker}')
    if resp.ok:
        orders = resp.json()
        for order in orders:
            id = order["order_id"]
            session.delete('http://localhost:9999/v1/orders/{}'.format(id))


def offload_inventory(session, ticker):
    bid, ask, volume = get_asset_info(session, ticker)
    action = "BUY" if volume < 0 else "SELL"
    market_order(session, ticker, volume, action)


# ------- TENDER OFFER -------- #
OFFER_THRESHOLD = 0.2
SPLIT = 20
SLEEP_AMOUNT = 0.5 #TODO: make this dynamic based on order size and price

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
    price = tender_offer["price"]
    quantity = tender_offer["quantity"]
    ticker = tender_offer["ticker"]
    id = tender_offer["tender_id"]
    bid, ask, _ = get_asset_info(session, ticker)

    # Client wants to buy from us
    if tender_offer["action"] == "SELL" and price > ask + OFFER_THRESHOLD:
        print(f"Accepted {quantity} buy offer with ask:", ask, "tender:", tender_offer)
        session.post(f'http://localhost:9999/v1/tenders/{id}')
        unroll_offer(session, quantity, ticker, "BUY")

    elif tender_offer["action"] == "BUY" and price < bid - OFFER_THRESHOLD:
        print(f"Accepted {quantity} sell offer with bid:", bid, "tender:", tender_offer)
        session.post(f'http://localhost:9999/v1/tenders/{id}')
        unroll_offer(session, quantity, ticker, "SELL")

def unroll_offer(session, quantity, ticker, action):
    round_quantity = quantity // SPLIT
    print("Unrolling")

    for i in range(SPLIT):
        market_order(session, ticker, round_quantity, action)
        sleep(SLEEP_AMOUNT)


# ---------- MARKET MAKER ------------ #
SPREAD_MULTIPLIER = 0.95  # Slightly narrower than market bid ask
MIN_SPREAD = {"RIT_C": 0.15, "HAWK": 0.1, "DOVE": 0.1}
INVENTORY_MULTIPLIER = 0.008
NUM_POSITIONS = 3
POS_MULT = 0.5

def make_market(session, tickers):
    while not exit_event.is_set():
        for ticker in tickers:
            bid, ask, position = get_asset_info(session, ticker)
            inventory_multiplier = (position / POSITION_LIMITS["gross"]) * INVENTORY_MULTIPLIER
            price_t = (bid + ask) / 2 #TODO: fix later?
            price_t = price_t * (1 - inventory_multiplier)
            spread = ask - bid
            set_spread = spread * SPREAD_MULTIPLIER / 2
            print(f"{ticker} Initial BID, ASK:", bid, ask)

            delete_all_orders(session, ticker)

            if spread > MIN_SPREAD[ticker]:
                bid = price_t - set_spread
                ask = price_t + set_spread
                bid_quantity = POSITION_SIZE*NUM_POSITIONS if position < 0 else max(0, POSITION_SIZE*NUM_POSITIONS - POS_MULT*position)
                ask_quantity = POSITION_SIZE*NUM_POSITIONS if position > 0 else max(0, POSITION_SIZE*NUM_POSITIONS - POS_MULT*position)
                # print(f"{ticker} Submitted BID {bid_quantity}: {bid}, ASK {ask_quantity}: {ask}")
                limit_order(session, ticker, bid, bid_quantity, "BUY")
                limit_order(session, ticker, ask, ask_quantity, "SELL")
            elif position < 0:
                limit_order(session, ticker, bid+0.01, position, "BUY")
            elif position > 0:
                limit_order(session, ticker, ask-0.01, position, "SELL")

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
        thread_mm = threading.Thread(target=make_market, args=(session, TICKERS))
        thread_mm.start()

        # TENDER OFFER STRAT
        thread_get_offers = threading.Thread(target=get_tender_offers, args=(session,))
        thread_get_offers.start()

        # while update_tick(session) < 295 and not shutdown:
        #     sleep(SPEEDBUMP)
        # exit_event.set()

        thread_mm.join()
        thread_get_offers.join()


if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()
