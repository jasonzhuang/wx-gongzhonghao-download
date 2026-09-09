import unittest
from unittest.mock import AsyncMock, patch

import httpx

from routes.login import _finish_qr_login, _web_json_succeeded


class FakeResponse:
    def __init__(self, body, status_code=200, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            raise httpx.HTTPStatusError("request failed", request=None, response=None)


class MpProbeTests(unittest.TestCase):
    def test_http_200_with_minus_2041_is_not_success(self):
        response = FakeResponse({"errCode": -2041, "errMsg": "WPA error"})
        self.assertFalse(_web_json_succeeded(response))

    def test_http_200_without_business_error_is_success(self):
        response = FakeResponse({"reviews": [], "clearAll": 1})
        self.assertTrue(_web_json_succeeded(response))


class QrRenewalHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_qr_tokens_are_not_sent_as_request_headers(self):
        class FakeLoginClient:
            def __init__(self):
                self.cookies = httpx.Cookies()
                self.renewal_headers = None

            async def get(self, url, headers=None):
                return FakeResponse({})

            async def post(self, url, content=None, headers=None, cookies=None):
                self.renewal_headers = dict(headers or {})
                return FakeResponse({"succ": 1}, headers={"x-wr-ticket": "fresh-ticket"})

        class VerifiedWereadClient:
            def __init__(self, credentials):
                self.credentials = credentials

            async def check_auth(self):
                return {"account_count": 1, "probe_article_count": 1}

        login_client = FakeLoginClient()
        session = {"client": login_client}
        result = {"webLoginVid": "123", "accessToken": "fresh-skey", "refreshToken": ""}
        with (
            patch("routes.login.WereadClient", VerifiedWereadClient),
            patch("routes.login.auth_manager.get_credentials", return_value=None),
            patch("routes.login.auth_manager.save_credentials", return_value=True),
            patch("routes.login.webhook.notify", AsyncMock()),
        ):
            check = await _finish_qr_login(session, result)

        self.assertEqual(check["account_count"], 1)
        self.assertNotIn("X-Vid", login_client.renewal_headers)
        self.assertNotIn("X-Skey", login_client.renewal_headers)

    async def test_same_account_article_ticket_is_reused_for_renewal(self):
        captured_credentials = {}

        class FakeLoginClient:
            def __init__(self):
                self.cookies = httpx.Cookies()
                self.renewal_headers = None

            async def get(self, url, headers=None):
                return FakeResponse({})

            async def post(self, url, content=None, headers=None, cookies=None):
                self.renewal_headers = dict(headers or {})
                return FakeResponse({"succ": 1}, headers={"x-wr-ticket": "renewed-ticket"})

        class VerifiedWereadClient:
            def __init__(self, credentials):
                self.credentials = credentials
                captured_credentials.update(credentials)

            async def check_auth(self):
                return {"account_count": 1, "probe_article_count": 1}

        login_client = FakeLoginClient()
        with (
            patch("routes.login.WereadClient", VerifiedWereadClient),
            patch("routes.login.auth_manager.get_credentials", return_value={
                "vid": "123", "ticket": "saved-ticket", "wrpa": "",
            }),
            patch("routes.login.auth_manager.save_credentials", return_value=True),
            patch("routes.login.webhook.notify", AsyncMock()),
        ):
            await _finish_qr_login(
                {"client": login_client},
                {"webLoginVid": "123", "accessToken": "fresh-skey", "refreshToken": ""},
            )

        self.assertEqual(login_client.renewal_headers["x-wr-ticket"], "saved-ticket")
        self.assertEqual(captured_credentials["ticket"], "renewed-ticket")
        self.assertNotIn("X-Vid", login_client.renewal_headers)
        self.assertNotIn("X-Skey", login_client.renewal_headers)

    async def test_renewal_business_error_is_not_treated_as_success(self):
        class FakeLoginClient:
            def __init__(self):
                self.cookies = httpx.Cookies()
                self.post_count = 0

            async def get(self, url, headers=None):
                return FakeResponse({})

            async def post(self, url, content=None, headers=None, cookies=None):
                self.post_count += 1
                return FakeResponse({"errCode": -2013, "errMsg": "鉴权失败"})

        login_client = FakeLoginClient()
        with (
            patch("routes.login.auth_manager.get_credentials", return_value=None),
            self.assertRaisesRegex(RuntimeError, "renewal 鉴权失败"),
        ):
            await _finish_qr_login(
                {"client": login_client},
                {"webLoginVid": "123", "accessToken": "fresh-skey", "refreshToken": ""},
            )
        self.assertEqual(login_client.post_count, 3)

    async def test_qr_without_article_ticket_fails_without_article_probe(self):
        class FakeLoginClient:
            def __init__(self):
                self.cookies = httpx.Cookies()
                self.get_urls = []

            async def get(self, url, headers=None):
                self.get_urls.append(url)
                return FakeResponse({})

            async def post(self, url, content=None, headers=None, cookies=None):
                return FakeResponse({"succ": 1})

        login_client = FakeLoginClient()
        with (
            patch("routes.login.logger.warning"),
            patch("routes.login.auth_manager.get_credentials", return_value=None),
            self.assertRaisesRegex(RuntimeError, "没有可验证的公众号文章列表票据"),
        ):
            await _finish_qr_login(
                {"client": login_client},
                {"webLoginVid": "123", "accessToken": "fresh-skey", "refreshToken": ""},
            )
        self.assertFalse(any("/web/mp/articles" in url for url in login_client.get_urls))
        self.assertFalse(any("/web/shelf/sync" in url for url in login_client.get_urls))


if __name__ == "__main__":
    unittest.main()
