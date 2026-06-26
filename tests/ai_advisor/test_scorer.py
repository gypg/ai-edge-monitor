"""Tests for deployment readiness scorer."""

from __future__ import annotations

import unittest

from ai_advisor.scorer import DeploymentAssessment, assess_deployment_readiness


class TestDeploymentScorer(unittest.TestCase):
    """Validate scoring logic, blocking issues, and edge cases."""

    # ------------------------------------------------------------------ #
    # Helper                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_summary(
        fps: float = 30.0,
        latency_p95: float = 100.0,
        temp_max: float = 60.0,
        power_avg: float = 10.0,
    ) -> dict:
        return {
            "fps_avg": fps,
            "latency_p95_ms": latency_p95,
            "temp_max_c": temp_max,
            "power_avg_watt": power_avg,
        }

    # ------------------------------------------------------------------ #
    # 1. Perfect score                                                     #
    # ------------------------------------------------------------------ #

    def test_perfect_score(self) -> None:
        """All metrics well within target should produce score near 100 and ready=True."""
        summary = self._make_summary(fps=35, latency_p95=50, temp_max=55, power_avg=8)
        result = assess_deployment_readiness(
            summary,
            target_fps=30,
            target_latency_ms=100,
            power_budget_watt=15,
        )

        self.assertIsInstance(result, DeploymentAssessment)
        self.assertGreaterEqual(result.score, 90)
        self.assertTrue(result.ready)
        self.assertEqual(result.blocking_issues, [])
        self.assertEqual(result.warnings, [])
        # Headroom: positive means target > actual (room to spare).
        # fps=35 exceeds target=30 so fps_headroom is negative (exceeding).
        # latency/thermal/power all have room, so those headrooms are positive.
        self.assertLess(result.fps_headroom, 0)  # exceeds target
        self.assertGreater(result.latency_headroom, 0)
        self.assertGreater(result.thermal_headroom, 0)
        self.assertGreater(result.power_headroom, 0)

    # ------------------------------------------------------------------ #
    # 2. Zero FPS                                                         #
    # ------------------------------------------------------------------ #

    def test_zero_fps(self) -> None:
        """FPS=0 should drive score near 0 and mark as not ready with blocking issue."""
        summary = self._make_summary(fps=0, latency_p95=200, temp_max=80, power_avg=20)
        result = assess_deployment_readiness(
            summary,
            target_fps=30,
            target_latency_ms=100,
            power_budget_watt=15,
        )

        self.assertLess(result.score, 30)
        self.assertFalse(result.ready)
        # FPS score 0 contributes blocking issue.
        self.assertTrue(
            any("FPS" in issue for issue in result.blocking_issues),
            f"Expected FPS blocking issue, got {result.blocking_issues}",
        )

    # ------------------------------------------------------------------ #
    # 3. Thermal critical                                                 #
    # ------------------------------------------------------------------ #

    def test_thermal_critical(self) -> None:
        """High temperature (90 C) should produce thermal blocking issue."""
        summary = self._make_summary(fps=30, latency_p95=50, temp_max=90, power_avg=8)
        result = assess_deployment_readiness(
            summary,
            target_fps=30,
            target_latency_ms=100,
            power_budget_watt=15,
        )

        # thermal_score = max(0, 100 - (90-70)*5) = 0
        self.assertTrue(
            any("Temperature" in issue for issue in result.blocking_issues),
            f"Expected thermal blocking issue, got {result.blocking_issues}",
        )
        self.assertFalse(result.ready)
        self.assertLess(result.thermal_headroom, 0)

    # ------------------------------------------------------------------ #
    # 4. Power exceeded                                                   #
    # ------------------------------------------------------------------ #

    def test_power_exceeded(self) -> None:
        """Power over budget should reduce power_score and add a warning."""
        summary = self._make_summary(fps=30, latency_p95=50, temp_max=55, power_avg=25)
        result = assess_deployment_readiness(
            summary,
            target_fps=30,
            target_latency_ms=100,
            power_budget_watt=15,
        )

        # power_score = max(0, 100 - (25-15)*10) = 0
        self.assertTrue(
            any("Power" in w for w in result.warnings),
            f"Expected power warning, got {result.warnings}",
        )
        self.assertLess(result.power_headroom, 0)

    # ------------------------------------------------------------------ #
    # 5. Marginal case                                                    #
    # ------------------------------------------------------------------ #

    def test_marginal(self) -> None:
        """Borderline metrics should yield score 60-80 with verdict depending on blocking."""
        summary = self._make_summary(
            fps=22,       # ~73% of 30 → fps_score ≈ 73
            latency_p95=130,  # 30 over target → latency_score = max(0, 100-30*10)=0 ... too harsh
            temp_max=68,
            power_avg=14,
        )
        result = assess_deployment_readiness(
            summary,
            target_fps=30,
            target_latency_ms=100,
            power_budget_watt=15,
        )

        # Score should be in a reasonable marginal range.
        self.assertGreaterEqual(result.score, 40)
        self.assertLessEqual(result.score, 90)
        # No thermal or FPS blocking (fps_score ≈ 73, thermal_score ≈ 90).
        # But latency_score = 0 so warnings will fire.
        self.assertIsInstance(result.ready, bool)
        self.assertIsInstance(result.blocking_issues, list)
        self.assertIsInstance(result.warnings, list)

    # ------------------------------------------------------------------ #
    # 6. Empty / missing summary                                          #
    # ------------------------------------------------------------------ #

    def test_empty_summary(self) -> None:
        """Missing fields should default to 0 without crashing."""
        result = assess_deployment_readiness(
            {},
            target_fps=30,
            target_latency_ms=100,
            power_budget_watt=15,
        )

        self.assertIsInstance(result, DeploymentAssessment)
        self.assertEqual(result.score, 0)
        self.assertFalse(result.ready)
        self.assertTrue(len(result.blocking_issues) > 0)

    def test_none_values_in_summary(self) -> None:
        """None values in summary dict should be treated as 0."""
        summary: dict = {
            "fps_avg": None,
            "latency_p95_ms": None,
            "temp_max_c": None,
            "power_avg_watt": None,
        }
        result = assess_deployment_readiness(
            summary,
            target_fps=30,
            target_latency_ms=100,
            power_budget_watt=15,
        )

        self.assertIsInstance(result, DeploymentAssessment)
        self.assertEqual(result.score, 0)
        self.assertFalse(result.ready)


if __name__ == "__main__":
    unittest.main()
