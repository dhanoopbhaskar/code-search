import pytest

from src.engine.redactor import air_gap_enforcement, allow_downloads


@pytest.mark.integration
def test_download_exemption_under_air_gap() -> None:
    import socket

    with air_gap_enforcement(), allow_downloads():
        result = socket.socket().connect_ex(("127.0.0.1", 1))
        assert result != 0


@pytest.mark.integration
def test_air_gap_still_blocks_without_exemption() -> None:
    with air_gap_enforcement():
        import socket

        with pytest.raises(RuntimeError, match="Air-gap violation"):
            socket.socket().connect(("127.0.0.1", 1))


@pytest.mark.integration
def test_air_gap_restored_after_exit() -> None:
    import socket

    with air_gap_enforcement():
        with allow_downloads():
            pass
        with pytest.raises(RuntimeError, match="Air-gap violation"):
            socket.socket().connect(("127.0.0.1", 1))
