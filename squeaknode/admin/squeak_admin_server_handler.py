import sys
import logging

from squeaknode.common.lnd_lightning_client import LNDLightningClient
from squeaknode.node.squeak_node import SqueakNode
from squeaknode.server.util import get_hash, get_replyto
from squeaknode.admin.util import squeak_entry_to_message
from squeaknode.admin.util import squeak_peer_to_message
from squeaknode.admin.util import squeak_profile_to_message
from squeaknode.admin.util import offer_entry_to_message
from squeaknode.admin.util import sent_payment_to_message
from squeaknode.admin.util import sync_result_to_message

from proto import squeak_admin_pb2, squeak_admin_pb2_grpc


logger = logging.getLogger(__name__)


class SqueakAdminServerHandler(object):
    """Handles admin server commands."""

    def __init__(
        self,
        lightning_client: LNDLightningClient,
        squeak_node: SqueakNode,
    ):
        self.lightning_client = lightning_client
        self.squeak_node = squeak_node

    def handle_lnd_get_info(self, request):
        logger.info("Handle lnd get info")
        return self.lightning_client.stub.GetInfo(request)

    def handle_lnd_wallet_balance(self, request):
        logger.info("Handle lnd wallet balance")
        return self.lightning_client.stub.WalletBalance(request)

    def handle_lnd_new_address(self, request):
        logger.info("Handle lnd new address: {}".format(request))
        return self.lightning_client.stub.NewAddress(request)

    def handle_lnd_list_channels(self, request):
        logger.info("Handle lnd list channels")
        return self.lightning_client.stub.ListChannels(request)

    def handle_lnd_pending_channels(self, request):
        logger.info("Handle lnd pending channels")
        return self.lightning_client.stub.PendingChannels(request)

    def handle_lnd_get_transactions(self, request):
        logger.info("Handle lnd get transactions")
        return self.lightning_client.stub.GetTransactions(request)

    def handle_lnd_list_peers(self, request):
        logger.info("Handle list peers")
        return self.lightning_client.stub.ListPeers(request)

    def handle_lnd_connect_peer(self, request):
        logger.info("Handle connect peer: {}".format(request))
        return self.lightning_client.stub.ConnectPeer(request)

    def handle_lnd_disconnect_peer(self, request):
        logger.info("Handle disconnect peer: {}".format(request))
        return self.lightning_client.stub.DisconnectPeer(request)

    def handle_lnd_open_channel_sync(self, request):
        logger.info("Handle open channel: {}".format(request))
        return self.lightning_client.stub.OpenChannelSync(request)

    def handle_lnd_close_channel(self, request):
        logger.info("Handle close channel: {}".format(request))
        return self.lightning_client.stub.CloseChannel(request)

    def handle_lnd_subscribe_channel_events(self, request):
        logger.info("Handle subscribe channel events")
        return self.lightning_client.stub.SubscribeChannelEvents(request)

    def handle_create_signing_profile(self, request):
        profile_name = request.profile_name
        logger.info("Handle create signing profile with name: {}".format(profile_name))
        profile_id = self.squeak_node.create_signing_profile(profile_name)
        logger.info("New profile_id: {}".format(profile_id))
        return squeak_admin_pb2.CreateSigningProfileReply(
            profile_id=profile_id,
        )

    def handle_create_contact_profile(self, request):
        profile_name = request.profile_name
        squeak_address = request.address
        logger.info("Handle create contact profile with name: {}, address: {}".format(
            profile_name,
            squeak_address,
        ))
        profile_id = self.squeak_node.create_contact_profile(
            profile_name, squeak_address
        )
        logger.info("New profile_id: {}".format(profile_id))
        return squeak_admin_pb2.CreateContactProfileReply(
            profile_id=profile_id,
        )

    def handle_get_signing_profiles(self, request):
        logger.info("Handle get signing profiles.")
        profiles = self.squeak_node.get_signing_profiles()
        logger.info("Got number of signing profiles: {}".format(len(profiles)))
        profile_msgs = [
            squeak_profile_to_message(profile) for profile in profiles
        ]
        return squeak_admin_pb2.GetSigningProfilesReply(squeak_profiles=profile_msgs)

    def handle_get_contact_profiles(self, request):
        logger.info("Handle get contact profiles.")
        profiles = self.squeak_node.get_contact_profiles()
        logger.info("Got number of contact profiles: {}".format(len(profiles)))
        profile_msgs = [
            squeak_profile_to_message(profile) for profile in profiles
        ]
        return squeak_admin_pb2.GetContactProfilesReply(squeak_profiles=profile_msgs)

    def handle_get_squeak_profile(self, request):
        profile_id = request.profile_id
        logger.info("Handle get squeak profile with id: {}".format(profile_id))
        squeak_profile = self.squeak_node.get_squeak_profile(profile_id)
        if squeak_profile is None:
            return None
        squeak_profile_msg = squeak_profile_to_message(squeak_profile)
        return squeak_admin_pb2.GetSqueakProfileReply(
            squeak_profile=squeak_profile_msg,
        )

    def handle_get_squeak_profile_by_address(self, request):
        address = request.address
        logger.info("Handle get squeak profile with address: {}".format(address))
        squeak_profile = self.squeak_node.get_squeak_profile_by_address(address)
        squeak_profile_msg = squeak_profile_to_message(squeak_profile)
        return squeak_admin_pb2.GetSqueakProfileReply(squeak_profile=squeak_profile_msg)

    def handle_set_squeak_profile_following(self, request):
        profile_id = request.profile_id
        following = request.following
        logger.info(
            "Handle set squeak profile following with profile id: {}, following: {}".format(
                profile_id,
                following,
            )
        )
        self.squeak_node.set_squeak_profile_following(profile_id, following)
        return squeak_admin_pb2.SetSqueakProfileFollowingReply()

    def handle_set_squeak_profile_sharing(self, request):
        profile_id = request.profile_id
        sharing = request.sharing
        logger.info(
            "Handle set squeak profile sharing with profile id: {}, sharing: {}".format(
                profile_id,
                sharing,
            )
        )
        self.squeak_node.set_squeak_profile_sharing(profile_id, sharing)
        return squeak_admin_pb2.SetSqueakProfileSharingReply()

    def handle_delete_squeak_profile(self, request):
        profile_id = request.profile_id
        logger.info("Handle delete squeak profile with id: {}".format(profile_id))
        self.squeak_node.delete_squeak_profile(profile_id)
        return squeak_admin_pb2.DeleteSqueakProfileReply()

    def handle_make_squeak(self, request):
        profile_id = request.profile_id
        content_str = request.content
        replyto_hash_str = request.replyto
        replyto_hash = bytes.fromhex(replyto_hash_str) if replyto_hash_str else None
        logger.info("Handle make squeak profile with id: {}".format(profile_id))
        inserted_squeak_hash = self.squeak_node.make_squeak(
            profile_id, content_str, replyto_hash
        )
        return squeak_admin_pb2.MakeSqueakReply(
            squeak_hash=inserted_squeak_hash,
        )

    def handle_get_squeak_display_entry(self, request):
        squeak_hash = request.squeak_hash
        logger.info("Handle get squeak display entry for hash: {}".format(squeak_hash))
        squeak_entry_with_profile = self.squeak_node.get_squeak_entry_with_profile(
            squeak_hash
        )
        display_message = squeak_entry_to_message(squeak_entry_with_profile)
        return squeak_admin_pb2.GetSqueakDisplayReply(
            squeak_display_entry=display_message
        )

    def handle_get_followed_squeak_display_entries(self, request):
        logger.info("Handle get followed squeak display entries.")
        squeak_entries_with_profile = (
            self.squeak_node.get_followed_squeak_entries_with_profile()
        )
        logger.info(
            "Got number of followed squeak entries: {}".format(
                len(squeak_entries_with_profile)
            )
        )
        squeak_display_msgs = [
            squeak_entry_to_message(entry)
            for entry in squeak_entries_with_profile
        ]
        return squeak_admin_pb2.GetFollowedSqueakDisplaysReply(
            squeak_display_entries=squeak_display_msgs
        )

    def handle_get_squeak_display_entries_for_address(self, request):
        address = request.address
        min_block = 0
        max_block = sys.maxsize
        logger.info("Handle get squeak display entries for address: {}".format(address))
        squeak_entries_with_profile = (
            self.squeak_node.get_squeak_entries_with_profile_for_address(
                address,
                min_block,
                max_block,
            )
        )
        logger.info(
            "Got number of squeak entries for address: {}".format(
                len(squeak_entries_with_profile)
            )
        )
        squeak_display_msgs = [
            squeak_entry_to_message(entry)
            for entry in squeak_entries_with_profile
        ]
        return squeak_admin_pb2.GetAddressSqueakDisplaysReply(
            squeak_display_entries=squeak_display_msgs
        )

    def handle_get_ancestor_squeak_display_entries(self, request):
        squeak_hash = request.squeak_hash
        logger.info(
            "Handle get ancestor squeak display entries for squeak hash: {}".format(
                squeak_hash
            )
        )
        squeak_entries_with_profile = (
            self.squeak_node.get_ancestor_squeak_entries_with_profile(
                squeak_hash,
            )
        )
        logger.info(
            "Got number of ancestor squeak entries: {}".format(
                len(squeak_entries_with_profile)
            )
        )
        squeak_display_msgs = [
            squeak_entry_to_message(entry)
            for entry in squeak_entries_with_profile
        ]
        return squeak_admin_pb2.GetAncestorSqueakDisplaysReply(
            squeak_display_entries=squeak_display_msgs
        )

    def handle_delete_squeak(self, request):
        squeak_hash = request.squeak_hash
        logger.info("Handle delete squeak with hash: {}".format(squeak_hash))
        self.squeak_node.delete_squeak(squeak_hash)
        logger.info("Deleted squeak entry with hash: {}".format(squeak_hash))
        return squeak_admin_pb2.DeleteSqueakReply()

    def handle_create_peer(self, request):
        peer_name = request.peer_name if request.peer_name else None
        host = request.host
        port = request.port
        logger.info(
            "Handle create peer with name: {}, host: {}, port: {}".format(
                peer_name,
                host,
                port,
            )
        )
        peer_id = self.squeak_node.create_peer(
            peer_name,
            host,
            port,
        )
        return squeak_admin_pb2.CreatePeerReply(
            peer_id=peer_id,
        )

    def handle_get_squeak_peer(self, request):
        peer_id = request.peer_id
        logger.info("Handle get squeak peer with id: {}".format(peer_id))
        squeak_peer = self.squeak_node.get_peer(peer_id)
        if squeak_peer is None:
            return None
        squeak_peer_msg = squeak_peer_to_message(squeak_peer)
        return squeak_admin_pb2.GetPeerReply(
            squeak_peer=squeak_peer_msg,
        )

    def handle_get_squeak_peers(self, request):
        logger.info("Handle get squeak peers")
        squeak_peers = self.squeak_node.get_peers()
        squeak_peer_msgs = [
            squeak_peer_to_message(squeak_peer)
            for squeak_peer in squeak_peers
        ]
        return squeak_admin_pb2.GetPeersReply(
            squeak_peers=squeak_peer_msgs,
        )

    def handle_set_squeak_peer_downloading(self, request):
        peer_id = request.peer_id
        downloading = request.downloading
        logger.info(
            "Handle set peer downloading with peer id: {}, downloading: {}".format(
                peer_id,
                downloading,
            )
        )
        self.squeak_node.set_peer_downloading(peer_id, downloading)
        return squeak_admin_pb2.SetPeerDownloadingReply()

    def handle_set_squeak_peer_uploading(self, request):
        peer_id = request.peer_id
        uploading = request.uploading
        logger.info(
            "Handle set peer uploading with peer id: {}, uploading: {}".format(
                peer_id,
                uploading,
            )
        )
        self.squeak_node.set_peer_uploading(peer_id, uploading)
        return squeak_admin_pb2.SetPeerUploadingReply()

    def handle_delete_squeak_peer(self, request):
        peer_id = request.peer_id
        logger.info("Handle delete squeak peer with id: {}".format(peer_id))
        self.squeak_node.delete_peer(peer_id)
        return squeak_admin_pb2.DeletePeerReply()

    def handle_get_buy_offers(self, request):
        squeak_hash = request.squeak_hash
        logger.info("Handle get buy offers for hash: {}".format(squeak_hash))
        offers = self.squeak_node.get_buy_offers_with_peer(squeak_hash)
        offer_msgs = [offer_entry_to_message(offer) for offer in offers]
        return squeak_admin_pb2.GetBuyOffersReply(
            offers=offer_msgs,
        )

    def handle_get_buy_offer(self, request):
        offer_id = request.offer_id
        logger.info("Handle get buy offer for hash: {}".format(offer_id))
        offer = self.squeak_node.get_buy_offer_with_peer(offer_id)
        offer_msg = offer_entry_to_message(offer)
        return squeak_admin_pb2.GetBuyOfferReply(
            offer=offer_msg,
        )

    def handle_sync_squeaks(self, request):
        logger.info("Handle sync squeaks")
        sync_result = self.squeak_node.sync_squeaks()
        sync_result_msg = sync_result_to_message(sync_result)
        return squeak_admin_pb2.SyncSqueaksReply(
            sync_result=sync_result_msg,
        )

    def handle_sync_squeak(self, request):
        squeak_hash = request.squeak_hash
        logger.info("Handle download squeak with hash: {}".format(squeak_hash))
        sync_result = self.squeak_node.sync_squeak(squeak_hash)
        sync_result_msg = sync_result_to_message(sync_result)
        return squeak_admin_pb2.SyncSqueakReply(
            sync_result=sync_result_msg,
        )

    def handle_pay_offer(self, request):
        offer_id = request.offer_id
        logger.info("Handle pay offer for offer id: {}".format(offer_id))
        sent_payment_id = self.squeak_node.pay_offer(offer_id)
        return squeak_admin_pb2.PayOfferReply(
            sent_payment_id=sent_payment_id,
        )

    def handle_get_sent_payments(self, request):
        logger.info("Handle get sent payments")
        sent_payments = self.squeak_node.get_sent_payments()
        sent_payment_msgs = [sent_payment_to_message(sent_payment) for sent_payment in sent_payments]
        return squeak_admin_pb2.GetSentPaymentsReply(
            sent_payments=sent_payment_msgs,
        )

    def handle_get_sent_payment(self, request):
        sent_payment_id = request.sent_payment_id
        logger.info("Handle get sent payment with id: {}".format(sent_payment_id))
        sent_payment = self.squeak_node.get_sent_payment(sent_payment_id)
        sent_payment_msg = sent_payment_to_message(sent_payment)
        return squeak_admin_pb2.GetSentPaymentReply(
            sent_payment=sent_payment_msg,
        )

    def handle_sign_data(self, request):
        profile_id = request.profile_id
        data = request.data
        logger.info("Handle sign data with profile id: {}".format(profile_id))
        signature = self.squeak_node.sign_data(profile_id, data)
        return squeak_admin_pb2.SignDataReply(
            signature=signature,
        )
