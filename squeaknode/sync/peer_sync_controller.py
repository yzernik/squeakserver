import logging
from contextlib import contextmanager

from squeaknode.network.peer_client import PeerClient
from squeaknode.sync.util import parse_buy_offer

logger = logging.getLogger(__name__)


class PeerSyncController:

    def __init__(
        self,
        squeak_controller,
        peer,
        stopped,
    ):
        self.squeak_controller = squeak_controller
        self.peer = peer
        self.peer_client = PeerClient(
            self.peer.host,
            self.peer.port,
        )
        self.stopped = stopped

    @contextmanager
    def open_connection(self):
        with self.peer_client.open_stub():
            yield self

    def download(
        self,
        min_block,
        max_block,
    ):
        # Get list of followed addresses
        followed_addresses = self.squeak_controller.get_followed_addresses()
        # Get remote hashes
        lookup_result = self.peer_client.lookup_squeaks(
            followed_addresses,
            min_block,
            max_block,
        )
        remote_hashes = lookup_result.hashes
        logger.info("remote_hashes: {}".format(
            [hash.hex() for hash in remote_hashes]
        ))
        # Get local hashes of saved squeaks
        local_hashes = self.squeak_controller.lookup_squeaks_include_locked(
            followed_addresses,
            min_block,
            max_block,
        )
        logger.info("local_hashes: {}".format(
            [hash.hex() for hash in local_hashes]
        ))
        # Get hashes to download
        hashes_to_download = set(remote_hashes) - set(local_hashes)
        logger.info("hashes_to_download: {}".format(
            [hash.hex() for hash in hashes_to_download]
        ))
        # Download squeaks for the hashes
        # TODO: check if hash belongs to correct range after downloading.
        for hash in hashes_to_download:
            # if self.peer_connection.stopped():
            #     return
            self._download_squeak(hash)

        # Get local hashes of locked squeaks that don't have an offer from this peer.
        locked_hashes = self.squeak_controller.lookup_squeaks_needing_offer(
            followed_addresses,
            min_block,
            max_block,
            self.peer.peer_id,
        )
        # Get hashes to get offer
        hashes_to_get_offer = set(remote_hashes) & set(locked_hashes)
        # Download offers for the hashes
        # TODO: catch exception downloading individual squeak
        for hash in hashes_to_get_offer:
            # if self.peer_connection.stopped():
            #     return
            self._download_offer(hash)

    def upload(
        self,
        min_block,
        max_block,
    ):
        # Get list of sharing addresses.
        sharing_addresses = self.squeak_controller.get_sharing_addresses()
        # Get remote hashes
        lookup_result = self.peer_client.lookup_squeaks(
            sharing_addresses,
            min_block,
            max_block,
        )
        remote_hashes = lookup_result.hashes
        allowed_addresses = lookup_result.allowed_addresses
        peer_latest_block = lookup_result.latest_block_height
        max_block = min(max_block, peer_latest_block)
        if max_block < min_block:
            return
        # Get local hashes
        addresses_to_search = set(allowed_addresses) & set(sharing_addresses)
        local_hashes = self.squeak_controller.lookup_squeaks(
            addresses_to_search,
            min_block,
            max_block,
        )
        # Get hashes to upload
        hashes_to_upload = set(local_hashes) - set(remote_hashes)
        # Upload squeaks for the hashes
        # TODO: catch exception uploading individual squeak
        for hash in hashes_to_upload:
            # if self.peer_connection.stopped():
            #     return
            self._upload_squeak(hash)

    def download_single_squeak(self, squeak_hash: bytes):
        """Downloads a single squeak and the corresponding offer. """
        saved_squeak = self.squeak_controller.get_squeak(squeak_hash)
        if not saved_squeak:
            self._download_squeak(squeak_hash)
        saved_offer = self._get_saved_offer(squeak_hash)
        if not saved_offer:
            self._download_offer(squeak_hash)

    def upload_single_squeak(self, squeak_hash: bytes):
        """Uploads a single squeak. """
        local_squeak = self.squeak_controller.get_squeak(squeak_hash)
        if local_squeak and local_squeak.HasDecryptionKey():
            self._upload_squeak(squeak_hash)

    def _get_saved_offer(self, squeak_hash: bytes):
        offers = self.squeak_controller.get_buy_offers_with_peer(squeak_hash)
        for offer_with_peer in offers:
            if offer_with_peer.offer.peer_id == self.peer.peer_id:
                return offer_with_peer

    def _download_squeak(self, squeak_hash: bytes):
        squeak = self.peer_client.get_squeak(squeak_hash)
        self.squeak_controller.save_downloaded_squeak(squeak)
        logger.info("Downloaded squeak {} from peer {}".format(
            squeak_hash.hex(), self.peer
        ))

    def _download_offer(self, squeak_hash: bytes):
        squeak = self.squeak_controller.get_squeak(squeak_hash)
        offer_msg = self.peer_client.get_offer(squeak_hash)
        buy_offer = parse_buy_offer(offer_msg)
        decoded_offer = self.squeak_controller.get_offer(
            squeak, buy_offer, self.peer)
        self.squeak_controller.save_offer(decoded_offer)
        logger.info("Downloaded offer for squeak {} from peer {}".format(
            squeak_hash.hex(), self.peer
        ))

    def _upload_squeak(self, squeak_hash: bytes):
        squeak = self.squeak_controller.get_squeak(squeak_hash)
        self.peer_client.post_squeak(squeak)
        logger.info("Uploaded squeak {} to peer {}".format(
            squeak_hash.hex(), self.peer
        ))
