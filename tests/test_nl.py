"""Tests for the deterministic natural-language scenario parser."""
import pytest

from src.nl import parse_scenario


def test_close_road_phrase(small_net):
    result = parse_scenario("What happens if Village Road is closed during an emergency?", small_net)
    assert result == {"action": "close", "road": "Village Road", "question": "What happens if Village Road is closed during an emergency?"}


def test_close_short_phrase(small_net):
    result = parse_scenario("Close Main Road", small_net)
    assert result["action"] == "close"
    assert result["road"] == "Main Road"


def test_interventions_phrase(small_net):
    result = parse_scenario("Which intervention helps the most?", small_net)
    assert result["action"] == "interventions"


def test_reopen_phrase(small_net):
    result = parse_scenario("reopen High Street", small_net)
    assert result["action"] == "reopen"
    assert result["road"] == "High Street"


def test_coverage_phrase(small_net):
    result = parse_scenario("Show baseline coverage", small_net)
    assert result["action"] == "coverage"


def test_help_when_road_unknown(small_net):
    result = parse_scenario("What if some mystery road is closed", small_net)
    assert result["action"] == "help"
    assert result["roads"]


def test_empty_query(small_net):
    result = parse_scenario("   ", small_net)
    assert result["action"] == "help"