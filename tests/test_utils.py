import unittest

from ncli.utils import format_duration


class TestUtils(unittest.TestCase):
    def test_format_duration(self):
        # Test that durations less than an hour are formatted correctly
        self.assertEqual(format_duration(59.0), "0:59")
        self.assertEqual(format_duration(90.0), "1:30")
        self.assertEqual(format_duration(600.0), "10:00")

        # Test that durations greater than an hour are formatted correctly
        self.assertEqual(format_duration(3600.0), "1:00:00")
        self.assertEqual(format_duration(3661.0), "1:01:01")
        self.assertEqual(format_duration(4500.0), "1:15:00")


if __name__ == "__main__":
    unittest.main()
