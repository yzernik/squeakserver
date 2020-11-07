import logging
import sys
from concurrent import futures

import grpc

from proto import squeak_admin_pb2, squeak_admin_pb2_grpc
from squeaknode.server.util import get_hash, get_replyto

logger = logging.getLogger(__name__)


class SqueakAdminServerServicer(squeak_admin_pb2_grpc.SqueakAdminServicer):
    """Provides methods that implement functionality of squeak admin server."""

    def __init__(self, host, port, handler):
        self.host = host
        self.port = port
        self.handler = handler

    def LndGetInfo(self, request, context):
        return self.handler.handle_lnd_get_info(request)

    def LndWalletBalance(self, request, context):
        return self.handler.handle_lnd_wallet_balance(request)

    def LndNewAddress(self, request, context):
        return self.handler.handle_lnd_new_address(request)

    def LndListChannels(self, request, context):
        return self.handler.handle_lnd_list_channels(request)

    def LndPendingChannels(self, request, context):
        return self.handler.handle_lnd_pending_channels(request)

    def LndGetTransactions(self, request, context):
        return self.handler.handle_lnd_get_transactions(request)

    def LndListPeers(self, request, context):
        return self.handler.handle_lnd_list_peers(request)

    def LndConnectPeer(self, request, context):
        return self.handler.handle_lnd_connect_peer(request)

    def LndDisconnectPeer(self, request, context):
        return self.handler.handle_lnd_disconnect_peer(request)

    def LndOpenChannelSync(self, request, context):
        return self.handler.handle_lnd_open_channel_sync(request)

    def LndCloseChannel(self, request, context):
        return self.handler.handle_lnd_close_channel(request)

    def LndSubscribeChannelEvents(self, request, context):
        return self.handler.handle_lnd_subscribe_channel_events(request)

    def CreateSigningProfile(self, request, context):
        return self.handler.handle_create_signing_profile(request)

    def CreateContactProfile(self, request, context):
        return self.handler.handle_create_contact_profile(request)

    def GetSigningProfiles(self, request, context):
        return self.handler.handle_get_signing_profiles(request)

    def GetContactProfiles(self, request, context):
        return self.handler.handle_get_contact_profiles(request)

    def GetSqueakProfile(self, request, context):
        reply = self.handler.handle_get_squeak_profile(request)
        if reply is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Profile not found.")
            return squeak_admin_pb2.GetSqueakProfileReply()
        return reply

    def GetSqueakProfileByAddress(self, request, context):
        return self.handler.handle_get_squeak_profile_by_address(request)

    def SetSqueakProfileFollowing(self, request, context):
        return self.handler.handle_set_squeak_profile_following(request)

    def SetSqueakProfileSharing(self, request, context):
        return self.handler.handle_set_squeak_profile_sharing(request)

    def DeleteSqueakProfile(self, request, context):
        return self.handler.handle_delete_squeak_profile(request)

    def MakeSqueak(self, request, context):
        return self.handler.handle_make_squeak(request)

    def GetSqueakDisplay(self, request, context):
        return self.handler.handle_get_squeak_display_entry(request)

    def GetFollowedSqueakDisplays(self, request, context):
        return self.handler.handle_get_followed_squeak_display_entries(request)

    def GetAddressSqueakDisplays(self, request, context):
        return self.handler.handle_get_squeak_display_entries_for_address(request)

    def GetAncestorSqueakDisplays(self, request, context):
        return self.handler.handle_get_ancestor_squeak_display_entries(request)

    def DeleteSqueak(self, request, context):
        return self.handler.handle_delete_squeak(request)

    def CreatePeer(self, request, context):
        return self.handler.handle_create_peer(request)

    def GetPeer(self, request, context):
        reply = self.handler.handle_get_squeak_peer(request)
        if reply is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details("Peer not found.")
            return squeak_admin_pb2.GetPeerReply()
        return reply

    def GetPeers(self, request, context):
        return self.handler.handle_get_squeak_peers(request)

    def SetPeerDownloading(self, request, context):
        return self.handler.handle_set_squeak_peer_downloading(request)

    def SetPeerUploading(self, request, context):
        return self.handler.handle_set_squeak_peer_uploading(request)

    def DeletePeer(self, request, context):
        return self.handler.handle_delete_squeak_peer(request)

    def GetBuyOffers(self, request, context):
        return self.handler.handle_get_buy_offers(request)

    def GetBuyOffer(self, request, context):
        return self.handler.handle_get_buy_offer(request)

    def SyncSqueaks(self, request, context):
        return self.handler.handle_sync_squeaks(request)

    def SyncSqueak(self, request, context):
        return self.handler.handle_sync_squeak(request)

    def PayOffer(self, request, context):
        return self.handler.handle_pay_offer(request)

    def GetSentPayments(self, request, context):
        return self.handler.handle_get_sent_payments(request)

    def GetSentPayment(self, request, context):
        return self.handler.handle_get_sent_payment(request)

    def SignData(self, request, context):
        return self.handler.handle_sign_data(request)

    def serve(self):
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        squeak_admin_pb2_grpc.add_SqueakAdminServicer_to_server(self, server)
        server.add_insecure_port("{}:{}".format(self.host, self.port))
        server.start()
        server.wait_for_termination()
