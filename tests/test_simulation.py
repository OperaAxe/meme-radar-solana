import pytest

from memeradar.simulation import run_monte_carlo


def test_simulation_is_reproducible_and_returns_all_scenarios():
    a = run_monte_carlo(paths=100, trades_per_path=20, seed=7)
    b = run_monte_carlo(paths=100, trades_per_path=20, seed=7)
    assert a == b
    assert set(a["results"]) == {"optimistic", "base", "adverse", "parameter_uncertainty"}
    assert a["results"]["base"]["probability_reach_target"] == 0


def test_invalid_simulation_inputs_raise():
    with pytest.raises(ValueError):
        run_monte_carlo(paths=0)
