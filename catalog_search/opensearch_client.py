from __future__ import annotations

import contextlib

import botocore.session
from opensearchpy import AIOHttpConnection, AsyncOpenSearch, AWSV4SignerAsyncAuth
from opensearchpy.exceptions import NotFoundError

from exceptions import InvalidRequestError

BULK_CHUNK_DOCUMENTS = 100


class CatalogSearchOpenSearchClient:
    def __init__(
        self,
        *,
        endpoint: str,
        index_name: str,
        region: str,
        auth_mode: str,
        username: str,
        password: str,
        request_timeout: int = 120,
        max_retries: int = 3,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.index_name = index_name
        self.region = region
        self.auth_mode = auth_mode
        self.username = username
        self.password = password
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self._client: AsyncOpenSearch | None = None

    async def connect(self) -> None:
        http_auth: tuple[str, str] | AWSV4SignerAsyncAuth | None = None
        if self.auth_mode == "basic":
            http_auth = (self.username, self.password)
        elif self.auth_mode == "aws":
            http_auth = _aws_auth(self.region)
        elif self.auth_mode not in {"none", ""}:
            raise InvalidRequestError(f"Unsupported OpenSearch auth mode: {self.auth_mode}")

        self._client = AsyncOpenSearch(
            hosts=[self.endpoint],
            use_ssl=self.endpoint.startswith("https://"),
            verify_certs=True,
            connection_class=AIOHttpConnection,
            http_auth=http_auth,
            timeout=self.request_timeout,
            max_retries=self.max_retries,
            retry_on_timeout=True,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def index_exists(self) -> bool:
        return bool(await self._require_client().indices.exists(index=self.index_name))

    async def create_index(self, body: dict) -> None:
        await self._require_client().indices.create(index=self.index_name, body=body)

    async def delete_index(self) -> None:
        if await self.index_exists():
            await self._require_client().indices.delete(index=self.index_name)

    async def bulk_index(self, documents: list[dict], *, refresh: bool = True) -> None:
        if not documents:
            return

        for start in range(0, len(documents), BULK_CHUNK_DOCUMENTS):
            chunk = documents[start : start + BULK_CHUNK_DOCUMENTS]
            body: list[dict] = []
            for document in chunk:
                body.append({"index": {"_index": self.index_name, "_id": document["id"]}})
                body.append(document)

            response = await self._require_client().bulk(body=body, params={"refresh": "false"})
            if response.get("errors"):
                raise InvalidRequestError("OpenSearch catalog bulk indexing failed")

        if refresh:
            await self.refresh_index()

    async def delete_document(self, document_id: str, *, refresh: bool = True) -> None:
        with contextlib.suppress(NotFoundError):
            await self._require_client().delete(
                index=self.index_name,
                id=document_id,
                params={"refresh": str(refresh).lower()},
            )

    async def refresh_index(self) -> None:
        await self._require_client().indices.refresh(index=self.index_name)

    async def search(self, body: dict) -> dict:
        return await self._require_client().search(index=self.index_name, body=body)

    async def analyze(self, body: dict) -> dict:
        return await self._require_client().indices.analyze(index=self.index_name, body=body)

    def _require_client(self) -> AsyncOpenSearch:
        if self._client is None:
            raise InvalidRequestError("Catalog search client is not connected")
        return self._client


def _aws_auth(region: str) -> AWSV4SignerAsyncAuth:
    credentials = botocore.session.get_session().get_credentials()
    if credentials is None:
        raise InvalidRequestError("AWS credentials are required for OpenSearch SigV4 auth")
    return AWSV4SignerAsyncAuth(credentials, region, "es")
