# ruff: noqa: ANN001, ANN201, E501, S101
import pytest

from catalog_search.service import _index_body as catalog_index_body
from config import settings
from content_search.service import _build_chunk_documents, _index_body as content_index_body
from identifier import generate_id
from main import create_app
from models.annotation import SegmentWithContextOutput, Span
from models.base import LocalizedString
from models.contribution import PersonContributionInput
from models.enums import ContributorRole, EditionType
from models.person import PersonInput
from models.text import TextInput


@pytest.mark.asyncio(loop_scope="session")
async def test_non_testing_startup_requires_opensearch_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(settings, "opensearch_endpoint", "")
    app = create_app(testing=False)

    with pytest.raises(RuntimeError, match="OPENSEARCH_ENDPOINT is required"):
        async with app.router.lifespan_context(app):
            pass


def test_search_indexes_use_one_primary_shard() -> None:
    assert content_index_body()["settings"]["number_of_shards"] == 1
    assert catalog_index_body()["settings"]["number_of_shards"] == 1


async def _create_person(db) -> str:
    return await db.person.create(PersonInput(name=LocalizedString({"en": "Search Author"}), bdrc="P" + generate_id()[:8]))


async def _create_text(db, person_id: str, title: str = "Search Text", language: str = "bo") -> str:
    return await db.text.create(
        TextInput(
            category_id="category",
            title=LocalizedString({language: title}),
            language=language,
            contributions=[PersonContributionInput(type="person", id=person_id, role=ContributorRole.AUTHOR)],
        )
    )


async def _create_critical_edition(search_client, text_id: str, content: str, segments: list[tuple[int, int]]) -> str:
    response = await search_client.post(
        f"/v2/texts/{text_id}/editions",
        json={
            "content": content,
            "metadata": {"type": EditionType.CRITICAL.value, "source": "Search Source"},
            "segmentation": {"segments": [{"lines": [{"start": start, "end": end}]} for start, end in segments]},
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def _segment(segment_id: str, start: int, end: int) -> SegmentWithContextOutput:
    return SegmentWithContextOutput(
        id=segment_id,
        segmentation_id="segmentation",
        edition_id="edition",
        text_id="text",
        lines=[Span(start=start, end=end)],
    )


def test_overlapping_chunks_cover_boundary_matches():
    documents = _build_chunk_documents(
        text_id="text",
        edition_id="edition",
        edition_type=EditionType.CRITICAL.value,
        language="bo",
        title={"bo": "Title"},
        source=None,
        content="0123456789",
        segments=[_segment("s1", 0, 4), _segment("s2", 4, 8), _segment("s3", 8, 10)],
        chunk_chars=6,
        chunk_overlap_chars=3,
    )

    boundary_document = next(document for document in documents if "4567" in document["content"])
    assert boundary_document["context_span_start"] == 3
    assert boundary_document["context_span_end"] == 9
    assert {segment["id"] for segment in boundary_document["segments"]} == {"s1", "s2", "s3"}


@pytest.mark.asyncio(loop_scope="session")
class TestContentSearch:
    async def test_exact_search_returns_match_span_and_all_overlapping_segments(
        self,
        search_client,
        test_database,
    ):
        person_id = await _create_person(test_database)
        text_id = await _create_text(test_database, person_id)
        content = "ab cd ef gh"
        edition_id = await _create_critical_edition(
            search_client,
            text_id,
            content=content,
            segments=[(0, 5), (5, 11)],
        )

        response = await search_client.get("/v2/content-search", params={"query": "cd ef", "search_type": "exact"})

        assert response.status_code == 200, response.json()
        results = response.json()
        assert len(results) == 1
        result = results[0]
        assert result["text_id"] == text_id
        assert result["edition_id"] == edition_id
        assert result["match_span"] == {"start": 3, "end": 8}
        assert result["context"] == content[result["context_span"]["start"] : result["context_span"]["end"]]
        assert len(result["segment_ids"]) == 2

    async def test_tibetan_exact_search_returns_unicode_match_span(self, search_client, test_database):
        person_id = await _create_person(test_database)
        text_id = await _create_text(test_database, person_id, title="བོད་ཡིག་ཚོལ་བ།")
        first_segment = "བཀྲ་ཤིས་"
        second_segment = "བདེ་ལེགས།"
        content = first_segment + second_segment
        query = "ཤིས་བདེ"
        expected_start = content.index(query)
        expected_end = expected_start + len(query)
        edition_id = await _create_critical_edition(
            search_client,
            text_id,
            content=content,
            segments=[(0, len(first_segment)), (len(first_segment), len(content))],
        )

        response = await search_client.get("/v2/content-search", params={"query": query, "search_type": "exact"})

        assert response.status_code == 200, response.json()
        results = response.json()
        assert len(results) == 1
        result = results[0]
        assert result["text_id"] == text_id
        assert result["edition_id"] == edition_id
        assert result["match_span"] == {"start": expected_start, "end": expected_end}
        assert result["context"] == content[result["context_span"]["start"] : result["context_span"]["end"]]
        assert len(result["segment_ids"]) == 2

    async def test_tibetan_similar_search_uses_icu_analyzer(self, search_client, test_database):
        person_id = await _create_person(test_database)
        text_id = await _create_text(test_database, person_id, title="བོད་ཡིག་འདྲ་མཚུངས།")
        content = "འདི་ནི་བོད་ཡིག་གི་བདེ་ལེགས་ཞེས་པའི་ཚིག་ཡིན།"
        await _create_critical_edition(
            search_client,
            text_id,
            content=content,
            segments=[(0, len(content))],
        )

        response = await search_client.get("/v2/content-search", params={"query": "བདེ་ལེགས", "search_type": "similar"})

        assert response.status_code == 200, response.json()
        results = response.json()
        assert len(results) == 1
        result = results[0]
        assert result["text_id"] == text_id
        assert result["match_span"] is None
        assert result["context_span"] == {"start": 0, "end": len(content)}
        assert result["context"] == content
        assert result["segment_ids"]

    async def test_similar_search_returns_context_without_match_span(self, search_client, test_database):
        person_id = await _create_person(test_database)
        text_id = await _create_text(test_database, person_id)
        content = "བཀྲ་ཤིས་ search བདེ་ལེགས།"
        await _create_critical_edition(
            search_client,
            text_id,
            content=content,
            segments=[(0, len(content))],
        )

        response = await search_client.get("/v2/content-search", params={"query": "SEARCH", "search_type": "similar"})

        assert response.status_code == 200, response.json()
        result = response.json()[0]
        assert result["match_span"] is None
        assert result["context_span"]["start"] == 0
        assert result["segment_ids"]
        assert result["context"] == content[result["context_span"]["start"] : result["context_span"]["end"]]
        assert "<em>" not in result["context"]

    async def test_similar_search_requires_meaningful_overlap_for_long_queries(self, search_client, test_database):
        person_id = await _create_person(test_database)
        weak_text_id = await _create_text(test_database, person_id, "Weak Match", language="en")
        strong_text_id = await _create_text(test_database, person_id, "Strong Match", language="en")
        await _create_critical_edition(search_client, weak_text_id, "alpha unrelated filler", [(0, 22)])
        await _create_critical_edition(search_client, strong_text_id, "alpha beta gamma delta epsilon", [(0, 30)])

        response = await search_client.get(
            "/v2/content-search",
            params={"query": "alpha beta gamma delta epsilon", "search_type": "similar", "limit": 10},
        )

        assert response.status_code == 200, response.json()
        assert {result["text_id"] for result in response.json()} == {strong_text_id}

    async def test_search_filters_by_text_and_edition(self, search_client, test_database):
        person_id = await _create_person(test_database)
        first_text_id = await _create_text(test_database, person_id, "First")
        second_text_id = await _create_text(test_database, person_id, "Second")
        first_edition_id = await _create_critical_edition(search_client, first_text_id, "shared phrase one", [(0, 17)])
        await _create_critical_edition(search_client, second_text_id, "shared phrase two", [(0, 17)])

        text_response = await search_client.get(
            "/v2/content-search",
            params={"query": "shared", "search_type": "exact", "text_id": first_text_id},
        )
        edition_response = await search_client.get(
            "/v2/content-search",
            params={"query": "shared", "search_type": "exact", "edition_id": first_edition_id},
        )

        assert text_response.status_code == 200, text_response.json()
        assert {result["text_id"] for result in text_response.json()} == {first_text_id}
        assert edition_response.status_code == 200, edition_response.json()
        assert {result["edition_id"] for result in edition_response.json()} == {first_edition_id}

    async def test_patch_reindexes_content(self, search_client, test_database):
        person_id = await _create_person(test_database)
        text_id = await _create_text(test_database, person_id)
        edition_id = await _create_critical_edition(search_client, text_id, "hello world", [(0, 11)])

        response_before = await search_client.get("/v2/content-search", params={"query": "planet", "search_type": "exact"})
        assert response_before.json() == []

        patch_response = await search_client.patch(
            f"/v2/editions/{edition_id}/content",
            json={"type": "replace", "start": 6, "end": 11, "text": "planet"},
        )
        assert patch_response.status_code == 204

        response_after = await search_client.get("/v2/content-search", params={"query": "planet", "search_type": "exact"})
        assert response_after.status_code == 200
        assert len(response_after.json()) == 1

    async def test_delete_removes_indexed_documents(self, search_client, test_database):
        person_id = await _create_person(test_database)
        text_id = await _create_text(test_database, person_id)
        edition_id = await _create_critical_edition(search_client, text_id, "delete me", [(0, 9)])

        assert len((await search_client.get("/v2/content-search", params={"query": "delete", "search_type": "exact"})).json()) == 1

        delete_response = await search_client.delete(f"/v2/editions/{edition_id}")
        assert delete_response.status_code == 204

        assert (await search_client.get("/v2/content-search", params={"query": "delete", "search_type": "exact"})).json() == []

    async def test_delete_all_documents_clears_stale_index_data(
        self,
        search_client,
        test_database,
        content_search,
    ):
        person_id = await _create_person(test_database)
        text_id = await _create_text(test_database, person_id)
        await _create_critical_edition(search_client, text_id, "clearable phrase", [(0, 16)])

        assert (await search_client.get("/v2/content-search", params={"query": "clearable"})).json()

        await content_search.delete_all_documents()

        assert (await search_client.get("/v2/content-search", params={"query": "clearable"})).json() == []

    async def test_segmentation_changes_reindex_edition_content(self, search_client, test_database):
        person_id = await _create_person(test_database)
        text_id = await _create_text(test_database, person_id)
        content = "segmentation lifecycle"
        edition_response = await search_client.post(
            f"/v2/texts/{text_id}/editions",
            json={
                "content": content,
                "metadata": {
                    "type": EditionType.DIPLOMATIC.value,
                    "bdrc": "W1SEARCH",
                    "source": "Search Source",
                },
                "pagination": {
                    "volumes": [
                        {
                            "pages": [
                                {
                                    "reference": "1a",
                                    "lines": [{"start": 0, "end": len(content)}],
                                }
                            ]
                        }
                    ]
                },
            },
        )
        assert edition_response.status_code == 201, edition_response.json()
        edition_id = edition_response.json()["id"]
        assert (await search_client.get("/v2/content-search", params={"query": "lifecycle"})).json() == []

        segmentation_response = await search_client.post(
            f"/v2/editions/{edition_id}/segmentation",
            json={"segments": [{"lines": [{"start": 0, "end": len(content)}]}]},
        )
        assert segmentation_response.status_code == 201, segmentation_response.json()
        assert (await search_client.get("/v2/content-search", params={"query": "lifecycle"})).json()

        delete_response = await search_client.delete(f"/v2/editions/{edition_id}/segmentation")
        assert delete_response.status_code == 204
        assert (await search_client.get("/v2/content-search", params={"query": "lifecycle"})).json() == []
