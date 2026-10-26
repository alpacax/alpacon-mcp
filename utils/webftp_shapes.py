"""WebFTP response fields the tools read, shared so no tool module imports another."""

from typing import Required, TypedDict

from pydantic import TypeAdapter


class TransferRequest(TypedDict, total=False):  # a created upload or download
    id: Required[str]
    upload_url: str | None
    download_url: str | None
    command: str | None  # id of the command that runs the transfer on the host


class TransferState(TypedDict, total=False):  # success is null while in progress
    success: bool | None
    message: str | None
    download_url: str | None


TRANSFER_REQUEST = TypeAdapter(TransferRequest)
TRANSFER_STATE = TypeAdapter(TransferState)
