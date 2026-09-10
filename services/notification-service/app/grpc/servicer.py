"""
NotificationService gRPC server.
Other services can call this directly to send notifications
without going through Redis Pub/Sub.
"""

import structlog
from app.grpc.generated import notification_pb2, notification_pb2_grpc
from app.handlers.email_handler import send_contact_email

log = structlog.get_logger()


class NotificationServicer(notification_pb2_grpc.NotificationServiceServicer):

    def SendMessageNotification(self, request, context):
        log.info("grpc_send_message_notification",
                 buyer=request.buyer_id, seller=request.seller_id, item=request.item_id)
        success = send_contact_email(
            seller_id=request.seller_id,
            buyer_id=request.buyer_id,
            item_id=request.item_id,
            subject=request.subject,
            message=request.message,
        )
        return notification_pb2.Ack(
            success=success,
            message="Email sent" if success else "Email failed",
        )

    def SendItemAlert(self, request, context):
        log.info("grpc_send_item_alert",
                 seller=request.seller_id, item=request.item_id, category=request.category)
        return notification_pb2.Ack(success=True, message="Alert queued")
