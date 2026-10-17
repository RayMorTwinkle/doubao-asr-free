from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FrameState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FRAME_STATE_UNSPECIFIED: _ClassVar[FrameState]
    FRAME_STATE_FIRST: _ClassVar[FrameState]
    FRAME_STATE_MIDDLE: _ClassVar[FrameState]
    FRAME_STATE_LAST: _ClassVar[FrameState]
FRAME_STATE_UNSPECIFIED: FrameState
FRAME_STATE_FIRST: FrameState
FRAME_STATE_MIDDLE: FrameState
FRAME_STATE_LAST: FrameState

class AsrRequest(_message.Message):
    __slots__ = ("token", "service_name", "method_name", "payload", "audio_data", "request_id", "frame_state")
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    METHOD_NAME_FIELD_NUMBER: _ClassVar[int]
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    AUDIO_DATA_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    FRAME_STATE_FIELD_NUMBER: _ClassVar[int]
    token: str
    service_name: str
    method_name: str
    payload: str
    audio_data: bytes
    request_id: str
    frame_state: FrameState
    def __init__(self, token: _Optional[str] = ..., service_name: _Optional[str] = ..., method_name: _Optional[str] = ..., payload: _Optional[str] = ..., audio_data: _Optional[bytes] = ..., request_id: _Optional[str] = ..., frame_state: _Optional[_Union[FrameState, str]] = ...) -> None: ...

class AsrResponse(_message.Message):
    __slots__ = ("request_id", "task_id", "service_name", "message_type", "status_code", "status_message", "result_json", "unknown_field_9")
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    TASK_ID_FIELD_NUMBER: _ClassVar[int]
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_TYPE_FIELD_NUMBER: _ClassVar[int]
    STATUS_CODE_FIELD_NUMBER: _ClassVar[int]
    STATUS_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    RESULT_JSON_FIELD_NUMBER: _ClassVar[int]
    UNKNOWN_FIELD_9_FIELD_NUMBER: _ClassVar[int]
    request_id: str
    task_id: str
    service_name: str
    message_type: str
    status_code: int
    status_message: str
    result_json: str
    unknown_field_9: int
    def __init__(self, request_id: _Optional[str] = ..., task_id: _Optional[str] = ..., service_name: _Optional[str] = ..., message_type: _Optional[str] = ..., status_code: _Optional[int] = ..., status_message: _Optional[str] = ..., result_json: _Optional[str] = ..., unknown_field_9: _Optional[int] = ...) -> None: ...
