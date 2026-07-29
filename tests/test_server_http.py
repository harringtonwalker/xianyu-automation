from __future__ import annotations

import http.client
import json
import stat
import tempfile
import threading
import unittest
from pathlib import Path

from xianyu_ops.server import build_server


class ServerHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.server = build_server("127.0.0.1", 0, Path(self.temp.name))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: str = "",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        final_headers = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        connection.request(method, path, body=body, headers=final_headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, payload, response_headers

    def test_health_and_private_settings(self) -> None:
        status, payload, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertFalse(payload["publisher_enabled"])
        status, settings, headers = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertNotIn("extension_token", settings["settings"])
        self.assertNotIn("approval_secret", settings["settings"])
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(headers.get("x-frame-options"), "DENY")
        self.assertIn("default-src 'self'", headers.get("content-security-policy", ""))
        status, _, cors_headers = self.request(
            "GET",
            "/api/health",
            headers={"Origin": self.server.service.base_url},  # type: ignore[attr-defined]
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            cors_headers.get("access-control-allow-origin"),
            self.server.service.base_url,  # type: ignore[attr-defined]
        )
        logger_handler = self.server.request_logger.handlers[0]  # type: ignore[attr-defined]
        self.assertEqual(logger_handler.maxBytes, 10 * 1024 * 1024)
        self.assertEqual(logger_handler.backupCount, 3)
        log_path = Path(self.temp.name) / "logs" / "http.log"
        self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)

    def test_forged_host_is_rejected(self) -> None:
        status, payload, _ = self.request(
            "GET",
            "/api/pairing-token",
            headers={"Host": f"attacker.example:{self.port}"},
        )
        self.assertEqual(status, 421)
        self.assertEqual(payload["error"]["code"], "HOST_FORBIDDEN")

    def test_malicious_origin_write_is_rejected(self) -> None:
        status, payload, headers = self.request(
            "POST",
            "/api/import/csv",
            body="title,price\nbad,1\n",
            headers={"Origin": "https://evil.example", "Content-Type": "text/csv"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "ORIGIN_FORBIDDEN")
        self.assertNotIn("access-control-allow-origin", headers)

    def test_extension_ping_is_read_only_and_token_protected(self) -> None:
        status, _, _ = self.request("GET", "/api/extension/ping")
        self.assertEqual(status, 401)
        token = self.server.service.extension_token  # type: ignore[attr-defined]
        status, payload, _ = self.request(
            "GET",
            "/api/extension/ping",
            headers={"X-Xianyu-Extension-Token": token},
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(self.server.service.store.list_jobs(), [])  # type: ignore[attr-defined]

    def test_non_object_records_return_structured_errors(self) -> None:
        status, payload, _ = self.request(
            "POST",
            "/api/import/json",
            body=json.dumps({"records": [42, "text", None]}),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["errors"]), 3)

    def test_rotated_http_logs_remain_private(self) -> None:
        handler = self.server.request_logger.handlers[0]  # type: ignore[attr-defined]
        handler.maxBytes = 256
        for index in range(100):
            self.server.request_logger.info("rotation-permission-check-%03d-%s", index, "x" * 80)  # type: ignore[attr-defined]
        handler.flush()
        log_files = list((Path(self.temp.name) / "logs").glob("http.log*"))
        self.assertGreaterEqual(len(log_files), 2)
        for path in log_files:
            with self.subTest(path=path):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
