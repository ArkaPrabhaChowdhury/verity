import unittest

from run_agent_eval import citation_health


class CitationHealthTests(unittest.TestCase):
    def test_counts_valid_citations_and_numeric_coverage(self):
        report = "Growth was 25% [1].\n\n## References\n[1] https://example.com"
        findings = [{"sources": [{"url": "https://example.com"}]}]
        result = citation_health(report, findings)
        self.assertEqual(result["citation_validity_pct"], 100)
        self.assertEqual(result["numeric_claim_citation_pct"], 100)


if __name__ == "__main__":
    unittest.main()
