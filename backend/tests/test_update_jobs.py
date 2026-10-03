"""Tests for the one-command job refresh (pipeline and embedding are faked)."""
import unittest
from unittest import mock

from scripts import update_jobs


class TestUpdateJobs(unittest.TestCase):
    def run_main(self, argv, pipeline_code=0, embed_code=0):
        calls = []
        fake_run = mock.Mock(side_effect=lambda cmd, cwd: calls.append(cmd) or mock.Mock(returncode=pipeline_code))
        with mock.patch.object(update_jobs.subprocess, "run", fake_run), \
             mock.patch.object(update_jobs.embed_jobs, "main", return_value=embed_code) as embed:
            code = update_jobs.main(argv)
        return code, calls, embed

    def test_daily_run_collects_then_embeds(self):
        code, calls, embed = self.run_main([])
        self.assertEqual(code, 0)
        self.assertEqual(calls[0][1:], [str(update_jobs.PIPELINE), "--adzuna-mode", "recent", "--trigger", "manual"])
        embed.assert_called_once_with([])

    def test_weekly_full_mode(self):
        _, calls, _ = self.run_main(["--adzuna-mode", "full", "--trigger", "schedule"])
        self.assertIn("full", calls[0])
        self.assertIn("schedule", calls[0])

    def test_embeds_even_if_collecting_failed(self):
        code, _, embed = self.run_main([], pipeline_code=1)
        self.assertEqual(code, 1)                    # failure is still reported
        embed.assert_called_once_with([])            # but the jobs we have still get embedded

    def test_embed_only(self):
        code, calls, embed = self.run_main(["--embed-only"])
        self.assertEqual((code, calls), (0, []))
        embed.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
