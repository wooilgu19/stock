from src.engine.portfolio import PortfolioState
from src.models import OrderRequest, Side


def order(side, quantity, price=100):
    return OrderRequest("005930", side, quantity, price, "test", 0.8)


def test_portfolio_tracks_buy_and_sell():
    portfolio = PortfolioState(cash=1_000)

    portfolio.apply(order(Side.BUY, 3, 100))
    assert portfolio.cash == 700
    assert portfolio.positions == {"005930": 3}

    portfolio.apply(order(Side.SELL, 2, 110))
    assert portfolio.cash == 920
    assert portfolio.positions == {"005930": 1}


def test_portfolio_rejects_insufficient_cash_and_position():
    portfolio = PortfolioState(cash=100)

    assert portfolio.check(order(Side.BUY, 2, 100)) == "insufficient cash"
    assert portfolio.check(order(Side.SELL, 1, 100)) == "insufficient position"
