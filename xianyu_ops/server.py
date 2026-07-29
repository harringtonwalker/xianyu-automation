from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import re
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .policy import PolicyError
from .service import OperationsService
from .store import StoreError


MAX_BODY = 5 * 1024 * 1024


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):  # type: ignore[no-untyped-def]
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream

    def doRollover(self) -> None:
        super().doRollover()
        for index in range(self.backupCount + 1):
            path = Path(self.baseFilename if index == 0 else f"{self.baseFilename}.{index}")
            if path.exists():
                os.chmod(path, 0o600)


class XianyuServer(ThreadingHTTPServer):
    request_logger: logging.Logger

    def server_close(self) -> None:
        super().server_close()
        for handler in list(self.request_logger.handlers):
            handler.close()
            self.request_logger.removeHandler(handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "XianyuOps/1.0"

    @property
    def service(self) -> OperationsService:
        return self.server.service  # type: ignore[attr-defined]

    @property
    def static_dir(self) -> Path:
        return self.server.static_dir  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        logger = getattr(self.server, "request_logger", None)
        message = f"{self.address_string()} {fmt % args}"
        if logger:
            logger.info(message)
        else:
            sys.stderr.write(f"[xianyu-ops] {message}\n")

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        request_path = urlparse(self.path).path
        allowed_origin = ""
        if origin == self.service.base_url:
            allowed_origin = origin
        elif origin.startswith("chrome-extension://") and (
            request_path.startswith("/api/extension/") or request_path.startswith("/api/assets/")
        ):
            allowed_origin = origin
        if allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Xianyu-Extension-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        self.send_header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._cors()
        self._security_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._json({"ok": False, "error": {"code": code, "message": message}}, status)

    def _body(self) -> bytes:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError:
            raise PolicyError("Content-Length 无效") from None
        if length < 0 or length > MAX_BODY:
            raise PolicyError("请求体过大")
        return self.rfile.read(length)

    def _json_body(self) -> dict[str, Any]:
        try:
            payload = json.loads(self._body() or b"{}")
        except json.JSONDecodeError as exc:
            raise PolicyError(f"JSON 无效：{exc}") from None
        if not isinstance(payload, dict):
            raise PolicyError("请求体必须是 JSON 对象")
        return payload

    def _extension_authorized(self) -> bool:
        provided = self.headers.get("X-Xianyu-Extension-Token", "")
        import secrets

        return bool(provided) and secrets.compare_digest(provided, self.service.extension_token)

    def _host_allowed(self) -> bool:
        port = self.server.server_address[1]
        host = self.headers.get("Host", "").lower()
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._host_allowed():
            self._error(421, "HOST_FORBIDDEN", "拒绝非本机 Host")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self._security_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_allowed():
            self._error(421, "HOST_FORBIDDEN", "拒绝非本机 Host")
            return
        try:
            self._handle_get()
        except FileNotFoundError:
            self._error(404, "NOT_FOUND", "资源不存在")
        except (PolicyError, StoreError, ValueError) as exc:
            self._error(400, "INVALID_REQUEST", str(exc))
        except Exception as exc:
            self.log_error("Unhandled GET error: %s", type(exc).__name__)
            self._error(500, "INTERNAL_ERROR", "本地服务内部错误，请查看服务日志")

    def _handle_get(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(self.service.health())
            return
        if path == "/api/jobs":
            self._json({"jobs": self.service.list_jobs()})
            return
        if path == "/api/settings":
            self._json({"settings": self.service.refresh_config()})
            return
        if path == "/api/pairing-token":
            self._json(self.service.pairing_token())
            return
        job_match = re.fullmatch(r"/api/jobs/([0-9a-f-]+)", path)
        if job_match:
            self._json(self.service.get_job(job_match.group(1)))
            return
        asset_match = re.fullmatch(r"/api/assets/([0-9a-f-]+)/([^/]+)", path)
        if asset_match:
            self._send_file(self.service.asset_path(asset_match.group(1), asset_match.group(2)))
            return
        if path == "/api/extension/ping":
            if not self._extension_authorized():
                self._error(401, "UNAUTHORIZED", "扩展配对令牌无效")
                return
            health = self.service.health()
            self._json(
                {
                    "ok": True,
                    "version": health["version"],
                    "publisher_enabled": health["publisher_enabled"],
                    "platform_contract": health["platform_contract"],
                }
            )
            return
        if path in {"/", "/index.html"}:
            self._send_file(self.static_dir / "index.html")
            return
        static_match = re.fullmatch(r"/static/([^/]+)", path)
        if static_match:
            self._send_file((self.static_dir / static_match.group(1)).resolve())
            return
        raise FileNotFoundError

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError
        body = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self._cors()
        self._security_headers()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_allowed():
            self._error(421, "HOST_FORBIDDEN", "拒绝非本机 Host")
            return
        try:
            self._handle_post()
        except FileNotFoundError:
            self._error(404, "NOT_FOUND", "接口不存在")
        except (PolicyError, StoreError, ValueError) as exc:
            self._error(400, "INVALID_REQUEST", str(exc))
        except Exception as exc:
            self.log_error("Unhandled POST error: %s", type(exc).__name__)
            self._error(500, "INTERNAL_ERROR", "本地服务内部错误，请查看服务日志")

    def _handle_post(self) -> None:
        path = urlparse(self.path).path
        origin = self.headers.get("Origin", "")
        origin_allowed = (
            not origin
            or origin == self.service.base_url
            or (origin.startswith("chrome-extension://") and path.startswith("/api/extension/"))
        )
        if not origin_allowed:
            self._error(403, "ORIGIN_FORBIDDEN", "拒绝非本地控制台或未配对扩展发起的写入")
            return
        if path == "/api/import/json":
            payload = self._json_body()
            records = payload.get("records")
            if not isinstance(records, list):
                records = [payload.get("record")] if isinstance(payload.get("record"), dict) else []
            self._json(self.service.import_records(records))
            return
        if path == "/api/import/csv":
            text = self._body().decode("utf-8")
            self._json(self.service.import_csv(text))
            return
        if path == "/api/extension/next":
            if not self._extension_authorized():
                self._error(401, "UNAUTHORIZED", "扩展配对令牌无效")
                return
            self._json(self.service.lease_next())
            return
        if path == "/api/generate-all":
            self._json(self.service.generate_all())
            return
        if path == "/api/jobs/approve":
            payload = self._json_body()
            job_ids = payload.get("job_ids")
            if not isinstance(job_ids, list):
                raise PolicyError("job_ids 必须是数组")
            self._json(self.service.approve([str(item) for item in job_ids], str(payload.get("acknowledgement") or "")))
            return
        if path == "/api/settings":
            payload = self._json_body()
            self._json({"settings": self.service.update_settings(payload)})
            return
        if path == "/api/publisher":
            payload = self._json_body()
            self._json(
                self.service.set_publisher(
                    bool(payload.get("enabled")),
                    str(payload.get("acknowledgement") or ""),
                )
            )
            return
        generate_match = re.fullmatch(r"/api/jobs/([0-9a-f-]+)/generate", path)
        if generate_match:
            self._json(self.service.generate_job(generate_match.group(1)))
            return
        review_match = re.fullmatch(r"/api/jobs/([0-9a-f-]+)/review", path)
        if review_match:
            payload = self._json_body()
            self._json(
                self.service.review(
                    review_match.group(1),
                    str(payload.get("acknowledgement") or ""),
                )
            )
            return
        retry_match = re.fullmatch(r"/api/jobs/([0-9a-f-]+)/retry", path)
        if retry_match:
            payload = self._json_body()
            self.service.store.retry(retry_match.group(1), str(payload.get("acknowledgement") or ""))
            self._json(self.service.get_job(retry_match.group(1)))
            return
        reconcile_match = re.fullmatch(r"/api/jobs/([0-9a-f-]+)/reconcile", path)
        if reconcile_match:
            payload = self._json_body()
            self._json(
                self.service.reconcile(
                    reconcile_match.group(1),
                    str(payload.get("decision") or ""),
                    str(payload.get("acknowledgement") or ""),
                    str(payload.get("receipt_url") or ""),
                    str(payload.get("item_id") or ""),
                )
            )
            return
        report_match = re.fullmatch(r"/api/extension/jobs/([0-9a-f-]+)/report", path)
        if report_match:
            if not self._extension_authorized():
                self._error(401, "UNAUTHORIZED", "扩展配对令牌无效")
                return
            payload = self._json_body()
            self._json(
                self.service.report(
                    report_match.group(1),
                    str(payload.get("lease_token") or ""),
                    str(payload.get("stage") or ""),
                    payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
                )
            )
            return
        source_match = path == "/api/extension/import"
        if source_match:
            if not self._extension_authorized():
                self._error(401, "UNAUTHORIZED", "扩展配对令牌无效")
                return
            payload = self._json_body()
            records = payload.get("records")
            if not isinstance(records, list):
                raise PolicyError("records 必须是数组")
            self._json(self.service.import_records(records))
            return
        raise FileNotFoundError


def build_server(host: str, port: int, data_dir: Path) -> XianyuServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("为保护本地令牌，服务只允许绑定 127.0.0.1 或 localhost")
    static_dir = Path(__file__).resolve().parent.parent / "static"
    resolved_data_dir = data_dir.resolve()
    log_dir = resolved_data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(resolved_data_dir, 0o700)
    os.chmod(log_dir, 0o700)
    log_path = log_dir / "http.log"
    request_logger = logging.getLogger(f"xianyu-ops.http.{resolved_data_dir}")
    request_logger.setLevel(logging.INFO)
    request_logger.propagate = False
    for existing in list(request_logger.handlers):
        existing.close()
        request_logger.removeHandler(existing)
    rotating = PrivateRotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    rotating.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    request_logger.addHandler(rotating)
    os.chmod(log_path, 0o600)

    server = XianyuServer((host, port), Handler)
    server.request_logger = request_logger
    actual_port = server.server_address[1]
    server.service = OperationsService(resolved_data_dir, f"http://{host}:{actual_port}")  # type: ignore[attr-defined]
    server.static_dir = static_dir  # type: ignore[attr-defined]
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Xianyu automation control plane")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    server = build_server(args.host, args.port, args.data_dir)
    print(f"Xianyu Ops running at http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
