# pylint: disable=redefined-outer-name
"""
Integration tests for recording endpoints using a real Neo4j test instance.

Tests endpoints:
- GET /v2/editions/{edition_id}/recordings
- POST /v2/editions/{edition_id}/recordings
- GET /v2/recordings/{recording_id}
- GET /v2/recordings/{recording_id}/audio
- PATCH /v2/recordings/{recording_id}
- DELETE /v2/recordings/{recording_id}
"""

import json
import logging

import pytest
from identifier import generate_id
from models.base import LocalizedString
from models.contribution import PersonContributionInput
from models.edition import EditionType
from models.enums import ContributorRole
from models.person import PersonInput
from models.text import TextInput

logger = logging.getLogger(__name__)

AUDIO_BYTES = b"ID3\x04\x00\x00\x00\x00\x00\x00fake mp3 payload"


@pytest.mark.asyncio(loop_scope="session")
class TestRecordingsEndpoints:
    """Integration tests for recordings under an edition."""

    async def _create_person(self, db, name: str = "Test Narrator", bdrc: str | None = None) -> str:
        return await db.person.create(
            PersonInput(
                name=LocalizedString({"en": name, "bo": "སྒྲ་སྒྲོག་མཁན།"}),
                bdrc=bdrc or f"P{generate_id()[:8]}",
            )
        )

    async def _create_text(self, db, person_id: str) -> str:
        return await db.text.create(
            TextInput(
                category_id="category",
                title=LocalizedString({"en": f"Recording host text {generate_id()[:6]}", "bo": "བརྟག་དཔྱད།"}),
                language="bo",
                contributions=[PersonContributionInput(type="person", id=person_id, role=ContributorRole.AUTHOR)],
            )
        )

    async def _create_edition(self, client, text_id: str, content: str = "Sample text content") -> str:
        response = await client.post(
            f"/v2/texts/{text_id}/editions",
            json={
                "content": content,
                "metadata": {
                    "type": EditionType.DIPLOMATIC.value,
                    "bdrc": f"W{generate_id()[:8]}",
                    "source": "Test Source",
                },
                "pagination": {
                    "volumes": [{"pages": [{"reference": "1a", "lines": [{"start": 0, "end": len(content)}]}]}]
                },
            },
        )
        assert response.status_code == 201, f"Failed to create edition: {response.json()}"
        return response.json()["id"]

    async def _setup_edition(self, client, test_database) -> tuple[str, str]:
        """Create a person and an edition to hang recordings off, returning both IDs."""
        person_id = await self._create_person(test_database)
        text_id = await self._create_text(test_database, person_id)
        edition_id = await self._create_edition(client, text_id)
        return person_id, edition_id

    @staticmethod
    def _upload(metadata: dict, content_type: str = "audio/mpeg", audio: bytes = AUDIO_BYTES) -> dict:
        return {
            "data": {"metadata": json.dumps(metadata)},
            "files": {"audio": ("reading.mp3", audio, content_type)},
        }

    async def _post_recording(self, client, edition_id: str, metadata: dict, **kwargs):
        return await client.post(f"/v2/editions/{edition_id}/recordings", **self._upload(metadata, **kwargs))

    async def test_create_recording(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)

        response = await self._post_recording(
            client,
            edition_id,
            {
                "title": {"en": "Chapter one, read aloud"},
                "language": "bo",
                "license": "cc-by",
                "date": "2024",
                "duration_ms": 754000,
                "contributions": [{"type": "person", "id": person_id, "role": "narrator"}],
            },
        )

        assert response.status_code == 201, response.json()
        recording_id = response.json()["id"]

        recording = (await client.get(f"/v2/recordings/{recording_id}")).json()
        assert recording["id"] == recording_id
        assert recording["edition_id"] == edition_id
        assert recording["title"] == {"en": "Chapter one, read aloud"}
        assert recording["language"] == "bo"
        assert recording["license"] == "cc-by"
        assert recording["date"] == "2024"
        assert recording["duration_ms"] == 754000
        assert recording["format"] == "mp3"
        assert recording["size_bytes"] == len(AUDIO_BYTES)
        assert len(recording["contributions"]) == 1
        contribution = recording["contributions"][0]
        assert contribution["type"] == "person"
        assert contribution["id"] == person_id
        assert contribution["role"] == "narrator"
        assert contribution["name"] == {"en": "Test Narrator", "bo": "སྒྲ་སྒྲོག་མཁན།"}

    async def test_create_recording_minimal_metadata(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)

        response = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
        )

        assert response.status_code == 201, response.json()
        recording = (await client.get(f"/v2/recordings/{response.json()['id']}")).json()
        assert recording["license"] == "public"

    async def test_create_recording_with_ai_narrator(self, client, test_database):
        _, edition_id = await self._setup_edition(client, test_database)

        response = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "ai", "id": "tts-model-v1", "role": "narrator"}]},
        )

        assert response.status_code == 201, response.json()
        recording = (await client.get(f"/v2/recordings/{response.json()['id']}")).json()
        assert recording["contributions"] == [{"type": "ai", "id": "tts-model-v1", "role": "narrator"}]

    @pytest.mark.parametrize("role", ["translator", "author", "reviser"])
    async def test_create_recording_rejects_non_narrator_role(self, client, test_database, role):
        person_id, edition_id = await self._setup_edition(client, test_database)

        response = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": role}]},
        )

        assert response.status_code == 422
        assert "must have role 'narrator'" in response.text

    async def test_create_recording_requires_a_contribution(self, client, test_database):
        _, edition_id = await self._setup_edition(client, test_database)

        response = await self._post_recording(client, edition_id, {"contributions": []})

        assert response.status_code == 422

    async def test_create_recording_rejects_unsupported_content_type(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)

        response = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
            content_type="application/pdf",
        )

        assert response.status_code == 422
        assert "Unsupported audio content type" in response.json()["error"]

    async def test_create_recording_rejects_empty_audio(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)

        response = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
            audio=b"",
        )

        assert response.status_code == 422
        assert "empty" in response.json()["error"]

    async def test_create_recording_rejects_unknown_person(self, client, test_database):
        _, edition_id = await self._setup_edition(client, test_database)

        response = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": "does-not-exist", "role": "narrator"}]},
        )

        assert response.status_code == 422
        assert "do not exist" in response.json()["error"]

    async def test_create_recording_when_narrator_role_is_missing(self, client, test_database):
        """Production may predate the recordings feature and lack RoleType {name: 'narrator'}."""
        person_id, edition_id = await self._setup_edition(client, test_database)
        async with test_database.get_session() as session:
            await session.run("MATCH (rt:RoleType {name: 'narrator'}) DETACH DELETE rt")

        response = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
        )

        assert response.status_code == 201, response.text
        recording = (await client.get(f"/v2/recordings/{response.json()['id']}")).json()
        assert recording["contributions"][0]["role"] == "narrator"

    async def test_create_recording_on_missing_edition(self, client, test_database):
        person_id = await self._create_person(test_database)

        response = await self._post_recording(
            client,
            "missing-edition",
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
        )

        assert response.status_code == 404

    async def test_list_recordings_for_edition(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)

        for index in range(2):
            response = await self._post_recording(
                client,
                edition_id,
                {
                    "title": {"en": f"Take {index + 1}"},
                    "contributions": [{"type": "person", "id": person_id, "role": "narrator"}],
                },
            )
            assert response.status_code == 201, response.json()

        response = await client.get(f"/v2/editions/{edition_id}/recordings")

        assert response.status_code == 200
        recordings = response.json()
        assert len(recordings) == 2
        assert {r["title"]["en"] for r in recordings} == {"Take 1", "Take 2"}
        assert all(r["edition_id"] == edition_id for r in recordings)

    async def test_list_recordings_empty(self, client, test_database):
        _, edition_id = await self._setup_edition(client, test_database)

        response = await client.get(f"/v2/editions/{edition_id}/recordings")

        assert response.status_code == 200
        assert response.json() == []

    async def test_list_recordings_for_missing_edition(self, client):
        response = await client.get("/v2/editions/missing-edition/recordings")

        assert response.status_code == 404

    async def test_get_missing_recording(self, client):
        response = await client.get(f"/v2/recordings/{generate_id()}")

        assert response.status_code == 404

    async def test_get_recording_audio_redirects(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)
        create = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
        )
        recording_id = create.json()["id"]

        response = await client.get(f"/v2/recordings/{recording_id}/audio", follow_redirects=False)

        assert response.status_code == 307
        assert response.headers["location"] == (
            f"https://mock-s3.example.com/recordings/{edition_id}/{recording_id}.mp3?signed=1&expires_in=3600"
        )

    async def test_get_audio_for_missing_recording(self, client):
        response = await client.get(f"/v2/recordings/{generate_id()}/audio", follow_redirects=False)

        assert response.status_code == 404

    async def test_patch_recording_metadata(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)
        create = await self._post_recording(
            client,
            edition_id,
            {
                "title": {"en": "First pass"},
                "license": "public",
                "contributions": [{"type": "person", "id": person_id, "role": "narrator"}],
            },
        )
        recording_id = create.json()["id"]

        response = await client.patch(
            f"/v2/recordings/{recording_id}",
            json={"title": {"en": "Final cut"}, "license": "cc-by-sa", "duration_ms": 1200, "date": "2025"},
        )

        assert response.status_code == 200, response.json()
        recording = response.json()
        assert recording["title"] == {"en": "Final cut"}
        assert recording["license"] == "cc-by-sa"
        assert recording["duration_ms"] == 1200
        assert recording["date"] == "2025"
        assert recording["format"] == "mp3"

    async def test_patch_recording_contributions(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)
        replacement_id = await self._create_person(test_database, name="Second Narrator")
        create = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
        )
        recording_id = create.json()["id"]

        response = await client.patch(
            f"/v2/recordings/{recording_id}",
            json={"contributions": [{"type": "person", "id": replacement_id, "role": "narrator"}]},
        )

        assert response.status_code == 200, response.json()
        contributions = response.json()["contributions"]
        assert len(contributions) == 1
        assert contributions[0]["id"] == replacement_id

    async def test_patch_recording_rejects_non_narrator_role(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)
        create = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
        )

        response = await client.patch(
            f"/v2/recordings/{create.json()['id']}",
            json={"contributions": [{"type": "person", "id": person_id, "role": "translator"}]},
        )

        assert response.status_code == 422
        assert "must have role 'narrator'" in response.text

    async def test_patch_missing_recording(self, client):
        response = await client.patch(f"/v2/recordings/{generate_id()}", json={"date": "2025"})

        assert response.status_code == 404

    async def test_delete_recording(self, client, test_database, mock_storage):
        person_id, edition_id = await self._setup_edition(client, test_database)
        create = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
        )
        recording_id = create.json()["id"]
        storage_key = f"recordings/{edition_id}/{recording_id}.mp3"
        assert storage_key in mock_storage._storage

        response = await client.delete(f"/v2/recordings/{recording_id}")

        assert response.status_code == 204
        assert (await client.get(f"/v2/recordings/{recording_id}")).status_code == 404
        assert storage_key not in mock_storage._storage

    async def test_delete_missing_recording(self, client):
        response = await client.delete(f"/v2/recordings/{generate_id()}")

        assert response.status_code == 404

    async def test_delete_recording_leaves_person_and_edition(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)
        create = await self._post_recording(
            client,
            edition_id,
            {"contributions": [{"type": "person", "id": person_id, "role": "narrator"}]},
        )

        assert (await client.delete(f"/v2/recordings/{create.json()['id']}")).status_code == 204
        assert (await client.get(f"/v2/editions/{edition_id}")).status_code == 200
        assert (await client.get(f"/v2/persons/{person_id}")).status_code == 200

    async def test_deleting_edition_cascades_to_recordings(self, client, test_database):
        person_id, edition_id = await self._setup_edition(client, test_database)
        create = await self._post_recording(
            client,
            edition_id,
            {
                "title": {"en": "Cascade check"},
                "contributions": [{"type": "person", "id": person_id, "role": "narrator"}],
            },
        )
        recording_id = create.json()["id"]

        assert (await client.delete(f"/v2/editions/{edition_id}")).status_code == 204

        assert (await client.get(f"/v2/recordings/{recording_id}")).status_code == 404
        async with test_database.get_session() as session:
            result = await session.run("MATCH (r:Recording) RETURN count(r) AS count")
            assert (await result.single())["count"] == 0
            result = await session.run(
                "MATCH (c:Contribution)-[:BY]->(:Person {id: $person_id}) RETURN count(c) AS count",
                person_id=person_id,
            )
            # The text's author contribution survives; only the recording's narrator credit is removed.
            assert (await result.single())["count"] == 1
