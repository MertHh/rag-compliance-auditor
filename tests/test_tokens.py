from auditor.tokens import count_tokens


def test_counts_words_and_punctuation_separately():
    assert count_tokens("Hello, world.") == 4


def test_numbered_clause_prefix():
    assert count_tokens("8.2 The Supplier") == 5


def test_empty_and_whitespace():
    assert count_tokens("") == 0
    assert count_tokens("  \n\t ") == 0


def test_turkish_letters_stay_in_one_token():
    assert count_tokens("İşbu sözleşme") == 2
