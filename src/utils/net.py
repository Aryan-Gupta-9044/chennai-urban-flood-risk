import time
from pathlib import Path
import requests

UA = {"User-Agent": "chennai-flood-risk/0.1 (academic project)"}


class DownloadError(Exception):
    pass


def download(url, dest, retries=2, timeout=(10, 120), log=None):
    """Download url -> dest. Never overwrites an existing non-empty file (raw data is kept)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        if log:
            log.info("cached: %s", dest.name)
        return dest
    tmp = dest.with_name(dest.name + ".part")
    last = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=timeout, headers=UA) as r:
                if r.status_code == 404:
                    raise DownloadError(f"404 not found: {url}")
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            tmp.replace(dest)
            if log:
                log.info("downloaded: %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
            return dest
        except DownloadError:
            raise
        except Exception as e:  # network, proxy, HTTP errors
            last = e
            if log:
                log.warning("attempt %d/%d failed for %s: %s", attempt, retries, url, str(e)[:160])
            time.sleep(1.5 * attempt)
    raise DownloadError(f"could not download {url}: {last}")


def get_json(url, retries=2, timeout=(10, 30)):
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout, headers=UA)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(1.5 * attempt)
    raise DownloadError(f"could not fetch {url}: {last}")
