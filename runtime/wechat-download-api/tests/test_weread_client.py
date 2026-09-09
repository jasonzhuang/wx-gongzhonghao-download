import base64
import sys
import types
import unittest
from unittest.mock import patch


try:
    import httpx  # noqa: F401
except ImportError:
    # 纯解析测试不发网络请求；允许在未安装依赖的打包环境中运行。
    sys.modules["httpx"] = types.ModuleType("httpx")

from utils.weread_client import (
    WereadAuthError,
    _check_json,
    normalize_book_id,
    parse_mp_accounts,
    parse_mp_articles,
    parse_curl_credentials,
)


class WereadClientContractTests(unittest.TestCase):
    def test_normalize_book_id_supports_new_numeric_and_legacy_fakeid(self):
        encoded = base64.b64encode(b"1234567890").decode("ascii")
        self.assertEqual(normalize_book_id("MP_WXS_1234567890"), "MP_WXS_1234567890")
        self.assertEqual(normalize_book_id("1234567890"), "MP_WXS_1234567890")
        self.assertEqual(normalize_book_id(encoded), "MP_WXS_1234567890")

    def test_shelf_parser_accepts_direct_and_nested_book_info(self):
        accounts = parse_mp_accounts({
            "books": [
                {"bookId": "MP_WXS_1", "title": "直接结构", "cover": "a"},
                {"bookInfo": {"bookId": "MP_WXS_2", "title": "嵌套结构"}},
                {"bookId": "123", "title": "普通书籍"},
            ]
        })
        self.assertEqual([item["fakeid"] for item in accounts], ["MP_WXS_1", "MP_WXS_2"])

    def test_articles_parser_flattens_subreviews_and_returns_group_offset(self):
        articles, cursor = parse_mp_articles({
            "reviews": [
                {
                    "createTime": 200,
                    "subReviews": [{"review": {
                        "reviewId": "MP_WXS_1_token_a",
                        "mpInfo": {
                            "title": "标题 &amp; 一",
                            "content": "摘要",
                            "originalId": "token_a",
                            "time": 201,
                            "mp_name": "测试号",
                        },
                    }}],
                },
                {
                    "createTime": 100,
                    "subReviews": [{"review": {
                        "reviewId": "MP_WXS_1_token_b",
                        "mpInfo": {"title": "标题二", "originalId": "token_b"},
                    }}],
                },
            ]
        }, "MP_WXS_1")
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0]["title"], "标题 & 一")
        self.assertEqual(articles[0]["link"], "https://mp.weixin.qq.com/s/token_a")
        self.assertEqual(cursor, 2)

    def test_clear_all_does_not_stop_pagination(self):
        _, cursor = parse_mp_articles({"reviews": [{"createTime": 100}], "clearAll": 1}, "MP_WXS_1")
        self.assertEqual(cursor, 1)

    def test_synckey_is_not_used_as_pagination_offset(self):
        _, cursor = parse_mp_articles({
            "reviews": [{"createTime": 100}], "clearAll": 1, "synckey": 999999
        }, "MP_WXS_1")
        self.assertEqual(cursor, 1)

    def test_minus_2041_is_not_treated_as_empty_list(self):
        with self.assertRaises(WereadAuthError) as caught:
            _check_json({"errCode": -2041, "errMsg": "WPA error"}, "读取文章列表")
        self.assertIn("刷新文章列表凭证", str(caught.exception))

    def test_wrpa_is_sent_when_ticket_is_unavailable(self):
        from utils.weread_client import WereadClient

        client = WereadClient({"cookie": "wr_vid=1", "ticket": "", "wrpa": "wpa-value"})
        headers = client._headers()
        self.assertNotIn("x-wr-ticket", headers)
        self.assertEqual(headers["x-wrpa-0"], "wpa-value")

    def test_parse_curl_extracts_cookie_and_wpa_without_logging_input(self):
        credentials = parse_curl_credentials(
            "curl 'https://weread.qq.com/web/mp/articles' "
            "-H 'Cookie: wr_vid=1; wr_skey=s' "
            "-H 'x-wr-ticket: ticket-value'"
        )
        self.assertEqual(credentials["cookie"], "wr_vid=1; wr_skey=s")
        self.assertEqual(credentials["ticket"], "ticket-value")


class WereadRenewalTests(unittest.IsolatedAsyncioTestCase):
    async def test_renewal_captures_ticket_and_updated_cookie(self):
        from utils.weread_client import WereadClient

        class FakeResponse:
            headers = {"x-wr-ticket": "fresh-ticket"}
            cookies = {"wr_skey": "new-skey"}

            def raise_for_status(self):
                return None

            def json(self):
                return {"succ": 1}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def post(self, *args, **kwargs):
                self.last_body = kwargs.get("content", "")
                return FakeResponse()

        client = WereadClient({"cookie": "wr_vid=1; wr_skey=old", "ticket": "", "wrpa": ""})
        with patch("utils.weread_client.httpx.AsyncClient", FakeAsyncClient):
            credentials = await client.renew_mp_auth()
        self.assertEqual(credentials["ticket"], "fresh-ticket")
        self.assertIn("wr_skey=new-skey", credentials["cookie"])

    async def test_article_list_uses_review_group_offset_not_synckey(self):
        from unittest.mock import AsyncMock
        from utils.weread_client import WereadClient

        client = WereadClient({"cookie": "wr_vid=1"})
        client._get_json = AsyncMock(return_value={
            "reviews": [{"createTime": 100}, {"createTime": 90}],
            "clearAll": 1,
            "synckey": 999999,
        })
        _, next_offset = await client.list_articles("MP_WXS_1", 20)
        self.assertEqual(next_offset, 22)


if __name__ == "__main__":
    unittest.main()
