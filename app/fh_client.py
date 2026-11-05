import logging

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.models import Project, parse_project

BASE_URL = "https://api.freelancehunt.com/v2"

log = logging.getLogger(__name__)


class RateLimited(Exception):
    pass


class ServerError(Exception):
    pass


class FHError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class FreelancehuntClient:
    def __init__(self, token: str, session: aiohttp.ClientSession):
        self._session = session
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept-Language": "uk",
            "Accept": "application/json",
        }

    @retry(
        retry=retry_if_exception_type((aiohttp.ClientError, TimeoutError, ServerError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, max=30),
        reraise=True,
    )
    async def _get(self, url: str) -> dict:
        async with self._session.get(url, headers=self._headers) as resp:
            if resp.status == 429:
                raise RateLimited()
            if resp.status >= 500:
                raise ServerError(f"HTTP {resp.status} for {url}")
            if resp.status >= 400:
                text = await resp.text()
                raise FHError(f"HTTP {resp.status} for {url}: {text[:200]}", resp.status)
            return await resp.json(content_type=None)

    async def projects_page(self, url: str | None = None) -> tuple[list[Project], str | None]:
        data = await self._get(url or f"{BASE_URL}/projects")
        projects = []
        for item in data.get("data") or []:
            try:
                projects.append(parse_project(item))
            except (KeyError, TypeError, ValueError):
                log.exception("Cannot parse project %s", item.get("id"))
        next_url = (data.get("links") or {}).get("next")
        return projects, next_url
