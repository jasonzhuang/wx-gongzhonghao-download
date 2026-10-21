import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import rss_store


class FeedArticleOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            rss_store,
            "DB_PATH",
            Path(self.temp_dir.name) / "rss.db",
        )
        self.db_patch.start()
        rss_store.init_db()
        rss_store.add_subscription("MP_WXS_TEST", "测试号")
        rss_store.save_articles(
            "MP_WXS_TEST",
            [
                {"title": "较早", "link": "https://example.com/1", "publish_time": 100},
                {"title": "最新", "link": "https://example.com/3", "publish_time": 300},
                {"title": "居中", "link": "https://example.com/2", "publish_time": 200},
            ],
        )

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_default_order_remains_ascending_for_incremental_sync(self):
        rows = rss_store.get_feed_articles(fakeid="MP_WXS_TEST", limit=3)
        self.assertEqual([row["publish_time"] for row in rows], [100, 200, 300])

    def test_descending_order_returns_latest_articles_first(self):
        rows = rss_store.get_feed_articles(
            fakeid="MP_WXS_TEST",
            limit=3,
            descending=True,
        )
        self.assertEqual([row["publish_time"] for row in rows], [300, 200, 100])


if __name__ == "__main__":
    unittest.main()
