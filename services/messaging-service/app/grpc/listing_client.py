"""
gRPC client — calls listing-service.
Used by messaging-service to verify item is active and get seller info.
"""

import os
import grpc
from app.grpc.generated import listing_pb2, listing_pb2_grpc

_LISTING_SERVICE_ADDR = os.getenv("LISTING_SERVICE_ADDR", "listing-service:50052")


def get_stub() -> listing_pb2_grpc.ListingServiceStub:
    channel = grpc.insecure_channel(_LISTING_SERVICE_ADDR)
    return listing_pb2_grpc.ListingServiceStub(channel)


def get_seller_info(item_id: int):
    """Returns SellerInfoResponse or None."""
    try:
        stub = get_stub()
        return stub.GetSellerInfo(listing_pb2.GetSellerInfoRequest(item_id=item_id))
    except grpc.RpcError:
        return None


def get_listing(item_id: int):
    """Returns ListingResponse or None."""
    try:
        stub = get_stub()
        return stub.GetListing(listing_pb2.GetListingRequest(item_id=item_id))
    except grpc.RpcError:
        return None
