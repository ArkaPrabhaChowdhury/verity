import unittest

from score import exact_match, normalize, summarize, token_f1


class ScoreTests(unittest.TestCase):
    def test_normalization_matches_hotpot_style_answers(self):
        self.assertEqual(normalize("The Eiffel Tower."), "eiffel tower")
        self.assertEqual(exact_match("an answer", "Answer"), 1.0)

    def test_token_f1_rewards_partial_overlap(self):
        self.assertAlmostEqual(token_f1("Paris, France", "Paris"), 2 / 3)
        self.assertEqual(token_f1("London", "Paris"), 0.0)

    def test_failed_runs_stay_out_of_averages_but_count_in_denominator(self):
        result = summarize([
            {"answer": "Paris", "prediction": "Paris", "latency_seconds": 2, "estimated_cost_usd": 0.1, "source_count": 2, "critic_detected_contradiction": False, "trust_score": 90, "citation_validity_pct": 100, "numeric_claim_citation_pct": 100, "independent_domains": 2, "error": None},
            {"answer": "Rome", "prediction": "", "latency_seconds": 9, "estimated_cost_usd": 1, "source_count": 0, "error": "failed"},
        ])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["successful"], 1)
        self.assertEqual(result["exact_match_pct"], 100)
        self.assertEqual(result["avg_trust_score"], 90)
        self.assertEqual(result["citation_validity_pct"], 100)


if __name__ == "__main__":
    unittest.main()
