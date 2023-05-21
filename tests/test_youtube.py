import unittest

from ncli.kit_youtube import extract_video_id


class TestYoutube(unittest.TestCase):
    def test_extract_video_id(self):
        video_id = "abcdeFGhIj0"
        url1 = f"https://www.youtube.com/watch?v={video_id}"
        url2 = f"https://youtu.be/{video_id}"
        url3 = f"https://www.youtube.com/embed/{video_id}"
        url4 = f"https://www.youtube.com/v/{video_id}"
        self.assertEqual(extract_video_id(url1), video_id)
        self.assertEqual(extract_video_id(url2), video_id)
        self.assertEqual(extract_video_id(url3), video_id)
        self.assertEqual(extract_video_id(url4), video_id)

if __name__ == '__main__':
    unittest.main()
