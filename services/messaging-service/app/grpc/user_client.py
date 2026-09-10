"""
gRPC client — calls user-service.
Used by messaging-service to verify JWT tokens.
"""

import os
import grpc
from app.grpc.generated import user_pb2, user_pb2_grpc

_USER_SERVICE_ADDR = os.getenv("USER_SERVICE_ADDR", "user-service:50051")


def get_stub() -> user_pb2_grpc.UserServiceStub:
    channel = grpc.insecure_channel(_USER_SERVICE_ADDR)
    return user_pb2_grpc.UserServiceStub(channel)


def verify_token(token: str) -> tuple[bool, str]:
    """Returns (is_valid, user_id)."""
    try:
        stub = get_stub()
        resp = stub.VerifyToken(user_pb2.VerifyTokenRequest(token=token))
        return resp.valid, resp.user_id
    except grpc.RpcError:
        return False, ""


def get_user(user_id: str):
    """Returns UserResponse or None."""
    try:
        stub = get_stub()
        return stub.GetUser(user_pb2.GetUserRequest(user_id=user_id))
    except grpc.RpcError:
        return None
