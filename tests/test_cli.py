import pytest

from src.cli import main


def test_validate_config_defaults_to_paper(capsys):
    assert main(["validate-config"]) == 0
    assert "configuration valid (paper)" in capsys.readouterr().out


def test_validate_config_live_requires_credentials():
    with pytest.raises(ValueError, match="KIS_CANO"):
        main(["validate-config", "--live"])


def test_check_kis_auth_calls_token_without_submitting_orders(monkeypatch, capsys):
    from src.config import Settings

    class FakeClient:
        def __init__(self, *args):
            self.args = args

        def access_token(self):
            return "token"

    monkeypatch.setattr(
        "src.cli.Settings",
        lambda: Settings(
            paper_trading=False,
            kis_cano="12345678",
            kis_appkey="key",
            kis_appsecret="secret",
        ),
    )
    monkeypatch.setattr("src.cli.KISRestClient", FakeClient)

    assert main(["check-kis-auth"]) == 0
    assert "KIS authentication succeeded" in capsys.readouterr().out


def test_check_kis_price_is_read_only(monkeypatch, capsys):
    from src.config import Settings

    class FakeClient:
        def __init__(self, *args):
            pass

        def current_price(self, symbol):
            assert symbol == "005930"
            return 70000.0

    monkeypatch.setattr(
        "src.cli.Settings",
        lambda: Settings(
            paper_trading=False,
            kis_cano="12345678",
            kis_appkey="key",
            kis_appsecret="secret",
        ),
    )
    monkeypatch.setattr("src.cli.KISRestClient", FakeClient)

    assert main(["check-kis-price", "005930"]) == 0
    assert "005930=70000" in capsys.readouterr().out


def test_check_kis_price_rejects_invalid_symbol():
    with pytest.raises(ValueError, match="6-digit"):
        main(["check-kis-price", "ABC"])
