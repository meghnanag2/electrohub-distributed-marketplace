"""
ListingService gRPC server — answers inter-service calls.

Called by:
  messaging-service → GetListing (verify item is active before contact)
  messaging-service → GetSellerInfo (fetch seller email + item title)
"""

import structlog
import grpc

from app.grpc.generated import listing_pb2, listing_pb2_grpc
from app.core.database import SessionLocal
from sqlalchemy import text

log = structlog.get_logger()


class ListingServicer(listing_pb2_grpc.ListingServiceServicer):

    def GetListing(self, request, context):
        db = SessionLocal()
        try:
            row = db.execute(
                text("SELECT item_id, title, seller_id, is_active, price FROM marketplace_items WHERE item_id = :id"),
                {"id": request.item_id}
            ).first()
            if not row:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"Item {request.item_id} not found")
                return listing_pb2.ListingResponse()
            return listing_pb2.ListingResponse(
                item_id=row[0], title=row[1], seller_id=row[2],
                is_active=row[3], price=float(row[4]),
            )
        finally:
            db.close()

    def GetSellerInfo(self, request, context):
        db = SessionLocal()
        try:
            row = db.execute(text("""
                SELECT m.seller_id, u.email, u.name, m.title
                FROM marketplace_items m
                JOIN user_accounts u ON m.seller_id = u.user_id
                WHERE m.item_id = :id AND m.is_active = true
            """), {"id": request.item_id}).first()
            if not row:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"Listing {request.item_id} not found or inactive")
                return listing_pb2.SellerInfoResponse()
            log.info("grpc_get_seller_info", item_id=request.item_id)
            return listing_pb2.SellerInfoResponse(
                seller_id=row[0], seller_email=row[1],
                seller_name=row[2], item_title=row[3],
            )
        finally:
            db.close()
