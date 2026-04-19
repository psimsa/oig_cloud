"""Tests for box_mode_composite module - TDD RED phase."""

import sys
import unittest
from dataclasses import FrozenInstanceError

sys.path.insert(0, "custom_components/oig_cloud/core")
from box_mode_composite import (
    MainMode,
    SupplementaryState,
    parse_app_value,
    build_app_value,
    canonical_extended_state,
)


class TestMainModeEnum(unittest.TestCase):
    """Tests for MainMode enum."""

    def test_main_mode_has_correct_values(self):
        """MainMode should have exactly home_1, home_2, home_3, home_ups."""
        expected = {"home_1", "home_2", "home_3", "home_ups"}
        actual = {m.name for m in MainMode}
        self.assertEqual(expected, actual)

    def test_main_mode_count(self):
        """MainMode should have exactly 4 values."""
        self.assertEqual(4, len(list(MainMode)))


class TestSupplementaryState(unittest.TestCase):
    """Tests for SupplementaryState dataclass."""

    def test_is_frozen_dataclass(self):
        """SupplementaryState must be frozen (immutable)."""
        state = SupplementaryState(
            home_grid_v=False, home_grid_vi=False, flexibilita=False, raw=0
        )
        with self.assertRaises(FrozenInstanceError):
            state.home_grid_v = True  # type: ignore

    def test_constructor_requires_all_fields(self):
        """All fields must be provided at construction."""
        # home_grid_v, home_grid_vi, flexibilita, raw
        state = SupplementaryState(
            home_grid_v=True, home_grid_vi=False, flexibilita=True, raw=4
        )
        self.assertTrue(state.home_grid_v)
        self.assertFalse(state.home_grid_vi)
        self.assertTrue(state.flexibilita)
        self.assertEqual(4, state.raw)


class TestParseAppValue(unittest.TestCase):
    """Tests for parse_app_value function."""

    def test_none_returns_none(self):
        """None input returns None."""
        self.assertIsNone(parse_app_value(None))

    def test_raw_0_returns_home_grid_v_false_vi_false(self):
        """Raw value 0 means home_grid_v=False, home_grid_vi=False."""
        state = parse_app_value(0)
        self.assertIsNotNone(state)
        self.assertFalse(state.home_grid_v)
        self.assertFalse(state.home_grid_vi)
        self.assertFalse(state.flexibilita)
        self.assertEqual(0, state.raw)

    def test_raw_1_returns_home_grid_v_true_vi_false(self):
        """Raw value 1 means home_grid_v=True, home_grid_vi=False."""
        state = parse_app_value(1)
        self.assertIsNotNone(state)
        self.assertTrue(state.home_grid_v)
        self.assertFalse(state.home_grid_vi)
        self.assertFalse(state.flexibilita)
        self.assertEqual(1, state.raw)

    def test_raw_2_returns_home_grid_v_false_vi_true(self):
        """Raw value 2 means home_grid_v=False, home_grid_vi=True."""
        state = parse_app_value(2)
        self.assertIsNotNone(state)
        self.assertFalse(state.home_grid_v)
        self.assertTrue(state.home_grid_vi)
        self.assertFalse(state.flexibilita)
        self.assertEqual(2, state.raw)

    def test_raw_3_returns_home_grid_v_true_vi_true(self):
        """Raw value 3 means home_grid_v=True, home_grid_vi=True."""
        state = parse_app_value(3)
        self.assertIsNotNone(state)
        self.assertTrue(state.home_grid_v)
        self.assertTrue(state.home_grid_vi)
        self.assertFalse(state.flexibilita)
        self.assertEqual(3, state.raw)

    def test_raw_4_returns_flexibilita_true(self):
        """Raw value 4 means flexibilita=True."""
        state = parse_app_value(4)
        self.assertIsNotNone(state)
        self.assertFalse(state.home_grid_v)
        self.assertFalse(state.home_grid_vi)
        self.assertTrue(state.flexibilita)
        self.assertEqual(4, state.raw)

    def test_raw_5_unknown(self):
        """Raw value 5 is unknown - returns state with raw=5, all bools False."""
        state = parse_app_value(5)
        self.assertIsNotNone(state)
        self.assertFalse(state.home_grid_v)
        self.assertFalse(state.home_grid_vi)
        self.assertFalse(state.flexibilita)
        self.assertEqual(5, state.raw)

    def test_negative_raw_unknown(self):
        """Negative raw values are unknown - returns state with that raw."""
        state = parse_app_value(-1)
        self.assertIsNotNone(state)
        self.assertEqual(-1, state.raw)
        self.assertFalse(state.home_grid_v)
        self.assertFalse(state.home_grid_vi)
        self.assertFalse(state.flexibilita)

    def test_raw_999_unknown(self):
        """Raw value 999 is unknown - returns state with raw=999."""
        state = parse_app_value(999)
        self.assertIsNotNone(state)
        self.assertEqual(999, state.raw)
        self.assertFalse(state.home_grid_v)
        self.assertFalse(state.home_grid_vi)
        self.assertFalse(state.flexibilita)


class TestCanonicalExtendedState(unittest.TestCase):
    """Tests for canonical_extended_state function."""

    def test_none_returns_none_string(self):
        """None input returns 'none'."""
        self.assertEqual("none", canonical_extended_state(None))

    def test_home_5_returns_home_5(self):
        """State with home_grid_v=True, home_grid_vi=False returns 'home_5'."""
        state = SupplementaryState(
            home_grid_v=True, home_grid_vi=False, flexibilita=False, raw=1
        )
        self.assertEqual("home_5", canonical_extended_state(state))

    def test_home_6_returns_home_6(self):
        """State with home_grid_v=False, home_grid_vi=True returns 'home_6'."""
        state = SupplementaryState(
            home_grid_v=False, home_grid_vi=True, flexibilita=False, raw=2
        )
        self.assertEqual("home_6", canonical_extended_state(state))

    def test_home_5_home_6_returns_home_5_home_6(self):
        """State with home_grid_v=True, home_grid_vi=True returns 'home_5_home_6'."""
        state = SupplementaryState(
            home_grid_v=True, home_grid_vi=True, flexibilita=False, raw=3
        )
        self.assertEqual("home_5_home_6", canonical_extended_state(state))

    def test_flexibilita_returns_flexibility(self):
        """State with flexibilita=True returns 'flexibility'."""
        state = SupplementaryState(
            home_grid_v=False, home_grid_vi=False, flexibilita=True, raw=4
        )
        self.assertEqual("flexibility", canonical_extended_state(state))

    def test_unknown_returns_unknown(self):
        """Unknown state (e.g., raw=5) returns 'unknown'."""
        state = SupplementaryState(
            home_grid_v=False, home_grid_vi=False, flexibilita=False, raw=5
        )
        self.assertEqual("unknown", canonical_extended_state(state))

    def test_zero_returns_home_5_home_6(self):
        """Raw 0 is (False, False) which is neither home_5 nor home_6 - unknown."""
        state = parse_app_value(0)
        self.assertEqual("none", canonical_extended_state(state))


class TestBuildAppValue(unittest.TestCase):
    """Tests for build_app_value function."""

    def test_raises_when_current_raw_none_and_toggle_specified(self):
        """ValueError if current_raw is None and any toggle is specified."""
        with self.assertRaises(ValueError):
            build_app_value(home_grid_v=True, home_grid_vi=None, current_raw=None)

        with self.assertRaises(ValueError):
            build_app_value(home_grid_v=None, home_grid_vi=True, current_raw=None)

    def test_none_toggles_raises_value_error(self):
        """None for all toggles raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            build_app_value(
                home_grid_v=None, home_grid_vi=None, current_raw=3
            )
        self.assertIn("At least one of home_grid_v or home_grid_vi must be specified", str(ctx.exception))

    def test_set_home_grid_v_true_preserves_vi_bit(self):
        """Setting home_grid_v=True preserves home_grid_vi bit from current_raw."""
        # current_raw=2 means home_grid_vi=True
        # setting home_grid_v=True should give raw=3 (bits for both)
        result = build_app_value(
            home_grid_v=True, home_grid_vi=None, current_raw=2
        )
        self.assertEqual(3, result)

    def test_set_home_grid_v_false_clears_v_bit(self):
        """Setting home_grid_v=False clears home_grid_v bit."""
        # current_raw=3 means both bits set
        # setting home_grid_v=False should give raw=2 (only home_grid_vi)
        result = build_app_value(
            home_grid_v=False, home_grid_vi=None, current_raw=3
        )
        self.assertEqual(2, result)

    def test_set_home_grid_vi_true_preserves_v_bit(self):
        """Setting home_grid_vi=True preserves home_grid_v bit from current_raw."""
        # current_raw=1 means home_grid_v=True
        # setting home_grid_vi=True should give raw=3
        result = build_app_value(
            home_grid_v=None, home_grid_vi=True, current_raw=1
        )
        self.assertEqual(3, result)

    def test_set_home_grid_vi_false_clears_vi_bit(self):
        """Setting home_grid_vi=False clears home_grid_vi bit."""
        # current_raw=3 means both bits set
        # setting home_grid_vi=False should give raw=1
        result = build_app_value(
            home_grid_v=None, home_grid_vi=False, current_raw=3
        )
        self.assertEqual(1, result)

    def test_combined_changes(self):
        """Multiple changes combine correctly."""
        # current_raw=0, set home_grid_v=True and home_grid_vi=True
        result = build_app_value(
            home_grid_v=True, home_grid_vi=True, current_raw=0
        )
        self.assertEqual(3, result)


if __name__ == "__main__":
    unittest.main()
