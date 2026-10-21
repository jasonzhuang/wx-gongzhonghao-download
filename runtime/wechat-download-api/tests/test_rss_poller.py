import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from utils import rss_store
from utils.rss_poller import rss_poller


class SingleSubscriptionPollTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            rss_store,
            "DB_PATH",
            Path(self.temp_dir.name) / "rss.db",
        )
        self.db_patch.start()
        rss_store.init_db()
        rss_store.add_subscription("MP_WXS_ONE", "公众号一")
        rss_store.add_subscription("MP_WXS_TWO", "公众号二")

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    async def test_poll_subscription_only_fetches_requested_subscription(self):
        client = AsyncMock()
        client.list_articles.return_value = (
            [{"title": "单号文章", "link": "https://example.com/one", "publish_time": 100}],
            None,
        )

        with patch("utils.rss_poller.WereadClient", return_value=client), \
                patch("utils.rss_poller.FETCH_FULL_CONTENT", False):
            result = await rss_poller.poll_subscription("MP_WXS_ONE")

        self.assertEqual(result["ok"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["saved"], 1)
        client.list_articles.assert_awaited_once_with("MP_WXS_ONE", 0)
        self.assertEqual(rss_store.get_subscription("MP_WXS_ONE")["last_poll"] > 0, True)
        self.assertEqual(rss_store.get_subscription("MP_WXS_TWO")["last_poll"], 0)


if __name__ == "__main__":
    unittest.main()
