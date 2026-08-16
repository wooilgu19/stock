import pytest

from src.cli import main


def test_validate_config_defaults_to_paper(capsys):
    assert main(["validate-config"]) == 0
    assert "configuration valid (paper)" in capsys.readouterr().out


def test_validate_config_live_requires_credentials():
    with pytest.raises(ValueError, match="KIS_CANO"):
        main(["validate-config", "--live"])
