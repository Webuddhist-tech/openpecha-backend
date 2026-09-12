# pylint: disable=redefined-outer-name
"""Integration tests for direct edition-pair alignment endpoints."""

import pytest

from identifier import generate_id
from models.base import LocalizedString
from models.contribution import PersonContributionInput
from models.enums import ContributorRole
from models.person import PersonInput
from models.text import TextInput


async def _create_person(db) -> str:
    return await db.person.create(
        PersonInput(
            name=LocalizedString({"en": f"Alignment Person {generate_id()}"}),
            bdrc="P" + generate_id()[:8],
        )
    )


async def _create_text(db, person_id: str, title: str) -> str:
    return await db.text.create(
        TextInput(
            category_id="category",
            title=LocalizedString({"en": title}),
            language="en",
            contributions=[PersonContributionInput(type="person", id=person_id, role=ContributorRole.AUTHOR)],
        )
    )


async def _create_edition(client, text_id: str, content: str) -> str:
    response = await client.post(
        f"/v2/texts/{text_id}/editions",
        json={
            "content": content,
            "metadata": {
                "type": "diplomatic",
                "bdrc": "W" + generate_id()[:8],
                "source": "Alignment Test Source",
            },
            "pagination": {
                "volumes": [{"pages": [{"reference": "1a", "lines": [{"start": 0, "end": len(content)}]}]}]
            },
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


async def _create_segmentation(
    client,
    edition_id: str,
    spans: list[tuple[int, int]],
    types: list[str] | None = None,
) -> tuple[str, list[str], list[str]]:
    references = [f"{index + 1}" for index in range(len(spans))]
    response = await client.post(
        f"/v2/editions/{edition_id}/segmentation",
        json={
            "segments": [
                {
                    "reference": references[index],
                    "lines": [{"start": start, "end": end}],
                    **({"type": types[index]} if types is not None else {}),
                }
                for index, (start, end) in enumerate(spans)
            ]
        },
    )
    assert response.status_code == 201, response.json()
    segmentation_id = response.json()["id"]
    segments_response = await client.get(f"/v2/editions/{edition_id}/segmentation/segments")
    assert segments_response.status_code == 200, segments_response.json()
    return segmentation_id, references, [segment["id"] for segment in segments_response.json()["items"]]


@pytest.mark.asyncio(loop_scope="session")
class TestEditionPairAlignments:
    async def test_replace_get_and_delete_edition_pair_alignments(self, client, test_database):
        person_id = await _create_person(test_database)
        source_text_id = await _create_text(test_database, person_id, "Alignment Source")
        target_text_id = await _create_text(test_database, person_id, "Alignment Target")
        source_edition_id = await _create_edition(client, source_text_id, "0123456789")
        target_edition_id = await _create_edition(client, target_text_id, "ABCDEFGHIJ")
        source_segmentation_id, source_segment_refs, source_segment_ids = await _create_segmentation(
            client, source_edition_id, [(0, 5), (5, 10)], types=["top_segment", "verse"]
        )
        _, target_segment_refs, target_segment_ids = await _create_segmentation(
            client, target_edition_id, [(0, 5), (5, 10)], types=["title", "paragraph"]
        )

        response = await client.put(
            f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}",
            json={
                "alignments": [
                    {
                        "source_segment_reference": source_segment_refs[0],
                        "target_segment_reference": target_segment_refs[0],
                    },
                    {
                        "source_segment_reference": source_segment_refs[1],
                        "target_segment_reference": target_segment_refs[1],
                    },
                ]
            },
        )
        assert response.status_code == 204

        first_page = await client.get(f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}?limit=1")
        assert first_page.status_code == 200
        first_body = first_page.json()
        assert first_body["has_more"] is True
        assert first_body["offset"] == 0
        assert first_body["limit"] == 1
        assert first_body["items"][0]["source_segment"]["id"] == source_segment_ids[0]
        assert first_body["items"][0]["source_segment"]["type"] == "top_segment"
        assert first_body["items"][0]["source_segment"]["reference"] == source_segment_refs[0]
        assert first_body["items"][0]["source_segment"]["segmentation_id"] == source_segmentation_id
        assert first_body["items"][0]["source_segment"]["edition_id"] == source_edition_id
        assert first_body["items"][0]["source_segment"]["text_id"] == source_text_id
        assert first_body["items"][0]["target_segment"]["id"] == target_segment_ids[0]
        assert first_body["items"][0]["target_segment"]["type"] == "title"
        assert first_body["items"][0]["target_segment"]["reference"] == target_segment_refs[0]
        assert first_body["items"][0]["target_segment"]["edition_id"] == target_edition_id
        assert first_body["items"][0]["target_segment"]["text_id"] == target_text_id

        second_page = await client.get(
            f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}?limit=1&offset=1"
        )
        assert second_page.status_code == 200
        assert second_page.json()["has_more"] is False
        assert second_page.json()["items"][0]["source_segment"]["id"] == source_segment_ids[1]
        assert second_page.json()["items"][0]["source_segment"]["type"] == "verse"
        assert second_page.json()["items"][0]["target_segment"]["type"] == "paragraph"

        response = await client.delete(f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}")
        assert response.status_code == 204
        empty_response = await client.get(f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}")
        assert empty_response.status_code == 200
        assert empty_response.json()["items"] == []

    async def test_get_edition_pair_alignments_preserves_segment_types(self, client, test_database):
        person_id = await _create_person(test_database)
        source_text_id = await _create_text(test_database, person_id, "Type Source")
        target_text_id = await _create_text(test_database, person_id, "Type Target")
        source_edition_id = await _create_edition(client, source_text_id, "0123456789")
        target_edition_id = await _create_edition(client, target_text_id, "ABCDEFGHIJ")
        _, source_segment_refs, source_segment_ids = await _create_segmentation(
            client, source_edition_id, [(0, 10)], types=["top_segment"]
        )
        _, target_segment_refs, target_segment_ids = await _create_segmentation(
            client, target_edition_id, [(0, 10)], types=["verse"]
        )

        response = await client.put(
            f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}",
            json={"alignments": [{
                "source_segment_reference": source_segment_refs[0],
                "target_segment_reference": target_segment_refs[0],
            }]},
        )
        assert response.status_code == 204

        source_segment_response = await client.get(f"/v2/segments/{source_segment_ids[0]}")
        target_segment_response = await client.get(f"/v2/segments/{target_segment_ids[0]}")
        assert source_segment_response.status_code == 200
        assert target_segment_response.status_code == 200
        source_segment = source_segment_response.json()
        target_segment = target_segment_response.json()
        assert source_segment["type"] == "top_segment"
        assert target_segment["type"] == "verse"

        alignments_response = await client.get(
            f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}"
        )
        assert alignments_response.status_code == 200
        items = alignments_response.json()["items"]
        assert len(items) == 1
        assert items[0]["source_segment"]["type"] == source_segment["type"]
        assert items[0]["target_segment"]["type"] == target_segment["type"]

    async def test_put_replaces_existing_edition_pair_alignments(self, client, test_database):
        person_id = await _create_person(test_database)
        source_text_id = await _create_text(test_database, person_id, "Replace Source")
        target_text_id = await _create_text(test_database, person_id, "Replace Target")
        source_edition_id = await _create_edition(client, source_text_id, "0123456789")
        target_edition_id = await _create_edition(client, target_text_id, "ABCDEFGHIJ")
        _, source_segment_refs, source_segment_ids = await _create_segmentation(
            client, source_edition_id, [(0, 5), (5, 10)]
        )
        _, target_segment_refs, target_segment_ids = await _create_segmentation(
            client, target_edition_id, [(0, 5), (5, 10)]
        )

        path = f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}"
        assert (
            await client.put(
                path,
                json={"alignments": [{
                    "source_segment_reference": source_segment_refs[0],
                    "target_segment_reference": target_segment_refs[0],
                }]},
            )
        ).status_code == 204
        assert (
            await client.put(
                path,
                json={"alignments": [{
                    "source_segment_reference": source_segment_refs[1],
                    "target_segment_reference": target_segment_refs[1],
                }]},
            )
        ).status_code == 204

        response = await client.get(path)
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["source_segment"]["id"] == source_segment_ids[1]
        assert items[0]["target_segment"]["id"] == target_segment_ids[1]

    async def test_put_rejects_missing_segment_reference_without_replacing_existing_alignments(
        self, client, test_database
    ):
        person_id = await _create_person(test_database)
        source_text_id = await _create_text(test_database, person_id, "Validation Source")
        target_text_id = await _create_text(test_database, person_id, "Validation Target")
        source_edition_id = await _create_edition(client, source_text_id, "0123456789")
        target_edition_id = await _create_edition(client, target_text_id, "ABCDEFGHIJ")
        _, source_segment_refs, _ = await _create_segmentation(client, source_edition_id, [(0, 5), (5, 10)])
        _, target_segment_refs, target_segment_ids = await _create_segmentation(
            client, target_edition_id, [(0, 5), (5, 10)]
        )

        path = f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}"
        response = await client.put(
            path,
            json={"alignments": [{
                "source_segment_reference": source_segment_refs[0],
                "target_segment_reference": target_segment_refs[0],
            }]},
        )
        assert response.status_code == 204

        response = await client.put(
            path,
            json={"alignments": [{
                "source_segment_reference": source_segment_refs[1],
                "target_segment_reference": "missing-target-reference",
            }]},
        )

        assert response.status_code == 400
        assert "target segment references" in response.json()["error"]

        get_response = await client.get(path)
        assert get_response.status_code == 200
        items = get_response.json()["items"]
        assert len(items) == 1
        assert items[0]["target_segment"]["id"] == target_segment_ids[0]

    async def test_get_edition_alignments_returns_directional_segmentation_context(self, client, test_database):
        person_id = await _create_person(test_database)
        source_text_id = await _create_text(test_database, person_id, "Edition Summary Source")
        target_text_id = await _create_text(test_database, person_id, "Edition Summary Target")
        source_edition_id = await _create_edition(client, source_text_id, "0123456789")
        target_edition_id = await _create_edition(client, target_text_id, "ABCDEFGHIJ")
        _, source_segment_refs, _ = await _create_segmentation(client, source_edition_id, [(0, 5), (5, 10)])
        _, target_segment_refs, _ = await _create_segmentation(
            client, target_edition_id, [(0, 5), (5, 10)]
        )

        response = await client.put(
            f"/v2/editions/{source_edition_id}/alignments/{target_edition_id}",
            json={
                "alignments": [
                    {
                        "source_segment_reference": source_segment_refs[0],
                        "target_segment_reference": target_segment_refs[0],
                    },
                    {
                        "source_segment_reference": source_segment_refs[1],
                        "target_segment_reference": target_segment_refs[1],
                    },
                ]
            },
        )
        assert response.status_code == 204

        expected_row = {
            "aligned_edition_id": source_edition_id,
            "aligned_text_id": source_text_id,
            "target_edition_id": target_edition_id,
            "target_text_id": target_text_id,
        }

        source_response = await client.get(f"/v2/editions/{source_edition_id}/alignments")
        assert source_response.status_code == 200
        assert source_response.json() == [expected_row]

        target_response = await client.get(f"/v2/editions/{target_edition_id}/alignments")
        assert target_response.status_code == 200
        assert target_response.json() == [expected_row]
