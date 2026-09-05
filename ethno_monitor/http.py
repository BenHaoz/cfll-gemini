"""HTTP 抓取工具：统一 UA、重试、编码识别、调试快照。"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import requests

from .config import DEBUG_DIR

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(HEADERS)
        _session = s
    return _session


def fix_encoding(resp: requests.Response) -> str:
    """中文站点常见 gb2312/gbk 或未声明编码，做一次稳妥推断。"""
    enc = (resp.encoding or "").lower()
    ctype = resp.headers.get("content-type", "").lower()
    if not enc or enc in ("iso-8859-1", "latin-1") or ("charset" not in ctype and enc == "utf-8"):
        guess = (resp.apparent_encoding or "utf-8").lower()
        enc = guess
    if enc in ("gb2312", "gbk"):
        enc = "gb18030"
    try:
        return resp.content.decode(enc, errors="replace")
    except LookupError:
        return resp.content.decode("utf-8", errors="replace")


def fetch(url: str, *, params: dict[str, Any] | None = None, method: str = "GET",
          data: Any = None, json: Any = None, timeout: int = 25, retries: int = 2,
          headers: dict[str, str] | None = None, snapshot: str | None = None) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = session().request(method, url, params=params, data=data, json=json,
                                     timeout=timeout, headers=headers, allow_redirects=True)
            if snapshot:
                save_snapshot(snapshot, resp)
            if resp.status_code >= 500 and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:  # noqa: PERF203
            last_exc = exc
            log.warning("fetch %s failed (%d/%d): %s", url, attempt + 1, retries + 1, exc)
            time.sleep(1.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def fetch_text(url: str, **kw: Any) -> str:
    return fix_encoding(fetch(url, **kw))


def save_snapshot(name: str, resp: requests.Response) -> None:
    """保存原始响应到 debug/ 供排查选择器（GitHub Actions 会作为 artifact 上传）。"""
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:80]
        path: Path = DEBUG_DIR / f"{safe}.html"
        path.write_bytes(resp.content[:2_000_000])
    except OSError:
        pass
