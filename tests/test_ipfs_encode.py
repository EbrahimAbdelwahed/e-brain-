from e_brain.curation.discovery.ipfs import encode_doi_for_path


def test_encode_doi_for_path_basic():
    assert encode_doi_for_path("10.1038/NN.12345") == "10.1038%2Fnn.12345"


def test_encode_doi_for_path_spaces():
    assert encode_doi_for_path("10.1000/ABC 123") == "10.1000%2Fabc%20123"


def test_encode_doi_for_path_idempotent_lower():
    assert encode_doi_for_path(" 10.5555/XYZ / Q ") == "10.5555%2Fxyz%20%2F%20q"

