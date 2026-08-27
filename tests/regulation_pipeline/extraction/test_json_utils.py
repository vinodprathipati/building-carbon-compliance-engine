import pytest

from regulation_pipeline.extraction.json_utils import extract_json


def test_extract_json_direct():
    assert extract_json('{"matches": []}') == {"matches": []}


def test_extract_json_code_block():
    text = 'Here is the result:\n```json\n{"records": [{"a": 1}]}\n```\nDone.'
    assert extract_json(text) == {"records": [{"a": 1}]}


def test_extract_json_embedded_object_amid_prose():
    text = 'Sure, here you go: {"records": [{"a": 1}]} — let me know if you need more.'
    assert extract_json(text) == {"records": [{"a": 1}]}


def test_extract_json_embedded_array_amid_prose():
    text = "The list is: [1, 2, 3] as requested."
    assert extract_json(text) == [1, 2, 3]


def test_extract_json_raises_when_nothing_found():
    with pytest.raises(ValueError, match="No valid JSON found"):
        extract_json("I don't have an answer for that.")
