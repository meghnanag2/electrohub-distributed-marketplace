"""
UserService gRPC server — answers inter-service calls.

Called by:
  listing-service  → VerifyToken (check JWT before creating listing)
  messaging-service → GetUser (fetch seller email for contact form)
"""

import structlog
import grpc

from app.grpc.generated import user_pb2, user_pb2_grpc
from app.core.database import SessionLocal
from app.models.user import User
from app.core.security import decode_access_token

log = structlog.get_logger()


class UserServicer(user_pb2_grpc.UserServiceServicer):

    def GetUser(self, request, context):
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.user_id == request.user_id).first()
            if not user:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"User {request.user_id} not found")
                return user_pb2.UserResponse()
            log.info("grpc_get_user", user_id=request.user_id)
            return user_pb2.UserResponse(
                user_id=user.user_id,
                email=user.email,
                name=user.name,
                is_active=user.is_active,
            )
        finally:
            db.close()

    def VerifyToken(self, request, context):
        user_id = decode_access_token(request.token)
        if not user_id:
            return user_pb2.VerifyTokenResponse(valid=False, user_id="")
        log.info("grpc_verify_token", user_id=user_id)
        return user_pb2.VerifyTokenResponse(valid=True, user_id=user_id)
