from rentalscout.cli import main


def test_cli_rejects_unknown_command() -> None:
    try:
        main(["unknown"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("expected argparse to exit")
