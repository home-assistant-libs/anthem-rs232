"""Serial connection failures at the public API boundary."""

from unittest.mock import AsyncMock, patch

import pytest
import serialx
from serialkit.testing import FakeLink

from anthem_rs232 import AnthemReceiver, Gen1Receiver


@pytest.mark.parametrize("receiver_class", [AnthemReceiver, Gen1Receiver])
async def test_connect_serial_exception_allows_retry(receiver_class) -> None:
    """Both generations report failed opens as retryable connection errors."""
    receiver = receiver_class("esphome://proxy.local/?port_name=RS232")
    error = serialx.SerialException("Serial proxy is unavailable")
    reader, writer = await FakeLink().connect()

    with (
        patch(
            "serialx.open_serial_connection",
            side_effect=[error, (reader, writer)],
        ) as open_connection,
        patch.object(receiver, "on_connect", new_callable=AsyncMock) as handshake,
    ):
        with pytest.raises(
            ConnectionError, match="Serial proxy is unavailable"
        ) as exc_info:
            await receiver.connect()

        assert exc_info.value.__cause__ is error
        assert not receiver.connected
        handshake.assert_not_awaited()

        try:
            await receiver.connect()
            assert receiver.connected
            assert open_connection.await_count == 2
            handshake.assert_awaited_once()
        finally:
            await receiver.disconnect()
