from rentalscout.parsers.common import split_district_community


def test_splits_district_and_community() -> None:
    assert split_district_community("浦东 华泰金融大厦") == ("浦东", "华泰金融大厦")


def test_single_part_returns_district_only() -> None:
    assert split_district_community("浦东") == ("浦东", None)


def test_empty_returns_pair_of_none() -> None:
    assert split_district_community("") == (None, None)
    assert split_district_community(None) == (None, None)
