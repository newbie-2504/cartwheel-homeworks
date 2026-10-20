"""Tests for the student's own HW1 additions: get_store_info and store_name in list_my_orders."""

from __future__ import annotations

from agent import agent, db, tools
from agent.auth import AuthContext

SHOPPER_1 = AuthContext(user_id=1, role="shopper")
MERCHANT_STORE_2 = AuthContext(user_id=9002, role="merchant", store_id=2)
SUPPORT = AuthContext(user_id=9501, role="support")


def test_list_my_orders_includes_store_names(world: dict) -> None:
    result = tools.list_my_orders(SHOPPER_1)
    assert result["ok"] is True
    with db.connection() as conn:
        for order in result["orders"]:
            assert order["store_name"] == db.get_store(conn, order["store_id"]).name


def test_get_store_info_by_name_slug_and_id_agree(world: dict) -> None:
    by_name = tools.get_store_info(SHOPPER_1, "Juniper Home Goods")
    by_slug = tools.get_store_info(SHOPPER_1, "juniper-home-goods")
    by_id = tools.get_store_info(SHOPPER_1, "2")
    assert by_name["ok"] is True
    assert by_name == by_slug == by_id
    assert by_name["store_id"] == 2


def test_get_store_info_resolves_a_unique_partial_name(world: dict) -> None:
    assert tools.get_store_info(SHOPPER_1, "juniper")["store_id"] == 2


def test_get_store_info_applies_return_window_override(world: dict) -> None:
    juniper = tools.get_store_info(SHOPPER_1, "Juniper Home Goods")
    assert juniper["return_window_days"] == 14
    assert juniper["has_return_window_override"] is True
    assert juniper["policy_id"] == "store-juniper-home-goods-policy"

    blue_heron = tools.get_store_info(SHOPPER_1, "1")
    assert blue_heron["return_window_days"] == 30  # platform default, no override
    assert blue_heron["has_return_window_override"] is False


def test_get_store_info_restocking_fee_only_when_opted_in(world: dict) -> None:
    cascade = tools.get_store_info(SHOPPER_1, "Cascade Audio")
    assert cascade["restocking_fee"] == {"opted_in": True, "max_percent": 15}
    blue_heron = tools.get_store_info(SHOPPER_1, "Blue Heron Ceramics")
    assert blue_heron["restocking_fee"] == {"opted_in": False, "max_percent": None}


def test_get_store_info_states_missing_contact_details(world: dict) -> None:
    result = tools.get_store_info(SHOPPER_1, "Blue Heron Ceramics")
    assert result["contact"] is None
    assert "address" in result["note"]


def test_get_store_info_errors(world: dict) -> None:
    assert tools.get_store_info(SHOPPER_1, "   ")["error"] == "invalid_argument"
    missing = tools.get_store_info(SHOPPER_1, "No Such Store")
    assert missing["error"] == "not_found"
    assert "No Such Store" in missing["reason"]
    assert tools.get_store_info(SHOPPER_1, "999")["error"] == "not_found"


def test_get_store_info_available_to_every_role() -> None:
    for role, role_tools in agent.TOOLS_BY_ROLE.items():
        assert agent.get_store_info in role_tools, role
    for ctx in (SHOPPER_1, MERCHANT_STORE_2, SUPPORT):
        assert tools.get_store_info(ctx, "2")["ok"] is True


def test_list_my_orders_reports_truncation(world: dict) -> None:
    result = tools.list_my_orders(SHOPPER_1)
    with db.connection() as conn:
        total = len(db.list_order_search_candidates(conn, user_id=1))
    assert result["total"] == total
    assert result["truncated"] is (total > result["count"])


def test_find_order_matches_store_names_across_full_history(world: dict) -> None:
    with db.connection() as conn:
        expected = [o.id for o in db.list_order_search_candidates(conn, user_id=1) if o.store_id == 2]
    result = tools.find_order(SHOPPER_1, "my orders from Juniper")
    found = [o["order_id"] for o in result["orders"]]
    assert expected and set(expected) <= set(found)
