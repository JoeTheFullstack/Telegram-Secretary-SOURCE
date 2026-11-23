import unittest

from app.adapters.telegram import parse_update


class TelegramMediaParsingTests(unittest.TestCase):
    def base(self, message):
        return {"update_id": 10, "message": {
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 200, "first_name": "Test"},
            **message,
        }}

    def test_photo_uses_largest_variant_and_keeps_album_id_and_caption(self):
        inc = parse_update(self.base({
            "photo": [
                {"file_id": "small", "file_unique_id": "us", "width": 90, "height": 90, "file_size": 100},
                {"file_id": "large", "file_unique_id": "ul", "width": 800, "height": 800, "file_size": 1000},
            ],
            "media_group_id": "album-1", "caption": "نمای بیرونی",
        }))
        self.assertEqual(inc.text, "نمای بیرونی")
        self.assertEqual(inc.media, {
            "kind": "photo", "file_id": "large", "file_unique_id": "ul",
            "media_group_id": "album-1", "caption": "نمای بیرونی",
        })

    def test_video_is_normalized(self):
        inc = parse_update(self.base({"video": {"file_id": "vid", "file_unique_id": "uv"}}))
        self.assertEqual(inc.media["kind"], "video")
        self.assertEqual(inc.media["file_id"], "vid")

    def test_text_message_has_no_media(self):
        inc = parse_update(self.base({"text": "سلام"}))
        self.assertEqual(inc.text, "سلام")
        self.assertIsNone(inc.media)


if __name__ == "__main__":
    unittest.main()
