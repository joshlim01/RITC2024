There are currently 3 "strategies". I have only tried running one at a time
The losses are pretty bad... -$30000

0. How to run 
- There are three threads in the main function that each run a different strat, uncomment the ones you want to run (can run multiple simultaneously)

1. Market making
- Puts out limit orderes for bid ask if spread is big enough
- There is a check_loss function that limits how much we lose in case one side doesn't get filled but it causes a lot of sharp drops since we exit at market
  - The stop loss value shifts with price, e.g. if I am long and price is rising, the stop loss also rises
- Center of bid/ask is shifted by current inventory
- Playing with other traders: spread basically disappears

2. Tender offer
- If give price better than market by certain threshold, enter, then immediately sell
- Should check bid/ask volumes to see if market can take such a big order (though may not be as big of a problme with more players)
- So far not profitable

3. Arbitrage
- Playing with 2 traders last night, no arbitrage opportunities exist...

4. Possible ideas
- Hold onto positions and take profit as you go, don't wait until hit stop loss to exit everything
- Try the market making algo with different assets. So far only with RITC
- Market making, really narrow the spread to ensure we get filled on both sides...

5. TODOs
- Currently quantity is fixed... may want to adjust with market