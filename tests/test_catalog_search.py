# ruff: noqa: ANN001, ANN201, S101
import pytest

from models.base import LocalizedString
from models.contribution import PersonContributionInput
from models.enums import ContributorRole
from models.person import PersonInput
from models.text import TextInput


async def _create_person(
    test_database,
    *,
    name: dict[str, str],
    alt_names: list[dict[str, str]] | None = None,
) -> str:
    return await test_database.person.create(
        PersonInput(
            name=LocalizedString(name),
            alt_names=[LocalizedString(alt) for alt in alt_names] if alt_names else None,
        )
    )


async def _create_text(
    test_database,
    *,
    person_id: str,
    title: dict[str, str],
    language: str = "sa",
    alt_titles: list[dict[str, str]] | None = None,
) -> str:
    return await test_database.text.create(
        TextInput(
            category_id="category",
            title=LocalizedString(title),
            alt_titles=[LocalizedString(alt) for alt in alt_titles] if alt_titles else None,
            language=language,
            contributions=[PersonContributionInput(type="person", id=person_id, role=ContributorRole.AUTHOR)],
        )
    )


@pytest.mark.asyncio(loop_scope="session")
class TestCatalogSearch:
    async def test_person_sanskrit_lenient_search_returns_canonical_record(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"sa-x-iast": "Śāntideva"})
        await catalog_search.index_person(person_id, test_database)

        response = await catalog_client.get("/v2/persons", params={"name": "Shantideva"})

        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["id"] == person_id
        assert response.json()["items"][0]["name"]["sa-x-iast"] == "Śāntideva"

    async def test_person_diacritic_free_search_returns_canonical_record(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"sa-x-iast": "Śāntideva"})
        await catalog_search.index_person(person_id, test_database)

        response = await catalog_client.get("/v2/persons", params={"name": "Santideva"})

        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["id"] == person_id
        assert response.json()["items"][0]["name"]["sa-x-iast"] == "Śāntideva"

    async def test_person_alternative_name_lenient_search_returns_canonical_record(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(
            test_database,
            name={"en": "Peace Deity"},
            alt_names=[{"sa-x-iast": "Śāntideva"}],
        )
        await catalog_search.index_person(person_id, test_database)

        response = await catalog_client.get("/v2/persons", params={"name": "Shantideva"})

        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["id"] == person_id
        assert response.json()["items"][0]["alt_names"][0]["sa-x-iast"] == "Śāntideva"

    async def test_text_title_sanskrit_lenient_search_returns_canonical_record(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"en": "Search Author"})
        text_id = await _create_text(test_database, person_id=person_id, title={"sa-x-iast": "Nāgārjuna"})
        await catalog_search.index_text(text_id, test_database)

        response = await catalog_client.get("/v2/texts", params={"title": "Nagarjuna"})

        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["id"] == text_id
        assert response.json()["items"][0]["title"]["sa-x-iast"] == "Nāgārjuna"

    async def test_text_alternative_title_lenient_search_returns_canonical_record(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"en": "Search Author"})
        text_id = await _create_text(
            test_database,
            person_id=person_id,
            title={"en": "Fundamental Verses"},
            language="en",
            alt_titles=[{"sa-x-iast": "Nāgārjuna"}],
        )
        await catalog_search.index_text(text_id, test_database)

        response = await catalog_client.get("/v2/texts", params={"title": "Nagarjuna"})

        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["id"] == text_id
        assert response.json()["items"][0]["alt_titles"][0]["sa-x-iast"] == "Nāgārjuna"

    @pytest.mark.parametrize(
        "query",
        [
            "How to see yourself as you really are",
            "How to see yourself as you truly are",
            "How to see you as you really are",
        ],
    )
    async def test_text_english_title_tolerates_word_variations(
        self,
        catalog_client,
        catalog_search,
        test_database,
        query,
    ):
        person_id = await _create_person(test_database, name={"en": "Search Author"})
        text_id = await _create_text(
            test_database,
            person_id=person_id,
            title={"en": "How to See Yourself as You Really Are"},
            language="en",
        )
        await catalog_search.index_text(text_id, test_database)

        response = await catalog_client.get("/v2/texts", params={"title": query})

        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["id"] == text_id

    async def test_person_tibetan_phonetic_search_returns_tibetan_record(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"bo": "ཞི་བ་ལྷ་"})
        await catalog_search.index_person(person_id, test_database)

        response = await catalog_client.get("/v2/persons", params={"name": "zhi ba lha"})

        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["id"] == person_id

    async def test_text_title_search_filters_before_pagination(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"en": "Search Author"})
        sanskrit_text_id = await _create_text(
            test_database,
            person_id=person_id,
            title={"sa-x-iast": "Bodhicaryāvatāra"},
            language="sa",
        )
        english_text_id = await _create_text(
            test_database,
            person_id=person_id,
            title={"en": "Bodhicaryavatara"},
            language="en",
        )
        await catalog_search.index_text(sanskrit_text_id, test_database)
        await catalog_search.index_text(english_text_id, test_database)

        response = await catalog_client.get(
            "/v2/texts",
            params={"title": "Bodhicaryavatara", "language": "sa", "limit": 1},
        )

        assert response.status_code == 200, response.json()
        body = response.json()
        assert [item["id"] for item in body["items"]] == [sanskrit_text_id]
        assert body["has_more"] is False

    async def test_person_search_excludes_syllable_neighbors_and_anagrams(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        target_id = await _create_person(test_database, name={"sa-x-iast": "Śāntideva"})
        neighbor_id = await _create_person(test_database, name={"sa-x-iast": "Śāntigarbha"})
        anagram_id = await _create_person(test_database, name={"sa-x-iast": "Devaśānti"})
        unrelated_id = await _create_person(test_database, name={"sa-x-iast": "Nāgārjuna"})
        await catalog_search.index_person(target_id, test_database)
        await catalog_search.index_person(neighbor_id, test_database)
        await catalog_search.index_person(anagram_id, test_database)
        await catalog_search.index_person(unrelated_id, test_database)

        response = await catalog_client.get("/v2/persons", params={"name": "Shantideva"})

        assert response.status_code == 200, response.json()
        returned_ids = [item["id"] for item in response.json()["items"]]
        assert returned_ids == [target_id]
        assert neighbor_id not in returned_ids
        assert anagram_id not in returned_ids
        assert unrelated_id not in returned_ids

    async def test_text_exact_title_ranks_above_superset_title(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"en": "Search Author"})
        exact_id = await _create_text(
            test_database,
            person_id=person_id,
            title={"en": "Emptiness"},
            language="en",
        )
        superset_id = await _create_text(
            test_database,
            person_id=person_id,
            title={"en": "Emptiness Meditation"},
            language="en",
        )
        await catalog_search.index_text(exact_id, test_database)
        await catalog_search.index_text(superset_id, test_database)

        response = await catalog_client.get("/v2/texts", params={"title": "Emptiness"})

        assert response.status_code == 200, response.json()
        returned_ids = [item["id"] for item in response.json()["items"]]
        assert returned_ids[0] == exact_id
        assert set(returned_ids) == {exact_id, superset_id}

    async def test_text_author_filter_narrows_results(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        author_a = await _create_person(test_database, name={"en": "Author Alpha"})
        author_b = await _create_person(test_database, name={"en": "Author Beta"})
        text_a = await _create_text(
            test_database,
            person_id=author_a,
            title={"en": "Collected Works Alpha"},
            language="en",
        )
        text_b = await _create_text(
            test_database,
            person_id=author_b,
            title={"en": "Collected Works Beta"},
            language="en",
        )
        await catalog_search.index_text(text_a, test_database)
        await catalog_search.index_text(text_b, test_database)

        response = await catalog_client.get(
            "/v2/texts",
            params={"title": "Collected Works", "author_id": author_a},
        )

        assert response.status_code == 200, response.json()
        returned_ids = [item["id"] for item in response.json()["items"]]
        assert returned_ids == [text_a]
        assert text_b not in returned_ids

    async def test_text_sanskrit_devanagari_search_returns_record(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"en": "Search Author"})
        text_id = await _create_text(
            test_database,
            person_id=person_id,
            title={"sa-Deva": "नागार्जुन"},
            language="sa",
        )
        await catalog_search.index_text(text_id, test_database)

        response = await catalog_client.get("/v2/texts", params={"title": "नागार्जुन"})

        assert response.status_code == 200, response.json()
        assert response.json()["items"][0]["id"] == text_id

    async def test_deleting_person_removes_it_from_search(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"sa-x-iast": "Śāntideva"})
        await catalog_search.index_person(person_id, test_database)

        found = await catalog_client.get("/v2/persons", params={"name": "Shantideva"})
        assert [item["id"] for item in found.json()["items"]] == [person_id]

        await catalog_search.delete_person(person_id)

        after_delete = await catalog_client.get("/v2/persons", params={"name": "Shantideva"})
        assert after_delete.status_code == 200, after_delete.json()
        assert after_delete.json()["items"] == []

    async def test_search_with_no_matches_returns_empty_results(
        self,
        catalog_client,
        catalog_search,
        test_database,
    ):
        person_id = await _create_person(test_database, name={"sa-x-iast": "Śāntideva"})
        await catalog_search.index_person(person_id, test_database)

        response = await catalog_client.get("/v2/persons", params={"name": "Zzzq Nonexistent"})

        assert response.status_code == 200, response.json()
        assert response.json()["items"] == []
