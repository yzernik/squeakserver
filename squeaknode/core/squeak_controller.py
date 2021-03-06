import logging
import threading
import time
from typing import List

from squeak.core import CheckSqueak
from squeak.core import CSqueak
from squeak.core.signing import CSigningKey
from squeak.core.signing import CSqueakAddress

from squeaknode.core.offer import Offer
from squeaknode.core.received_offer import ReceivedOffer
from squeaknode.core.received_payment_summary import ReceivedPaymentSummary
from squeaknode.core.sent_offer import SentOffer
from squeaknode.core.sent_payment_summary import SentPaymentSummary
from squeaknode.core.squeak_peer import SqueakPeer
from squeaknode.core.squeak_profile import SqueakProfile
from squeaknode.core.util import get_hash
from squeaknode.core.util import is_address_valid
from squeaknode.node.received_payments_subscription_client import (
    OpenReceivedPaymentsSubscriptionClient,
)


logger = logging.getLogger(__name__)


class SqueakController:
    def __init__(
        self,
        squeak_db,
        squeak_core,
        squeak_whitelist,
        squeak_rate_limiter,
        config,
    ):
        self.squeak_db = squeak_db
        self.squeak_core = squeak_core
        self.squeak_whitelist = squeak_whitelist
        self.squeak_rate_limiter = squeak_rate_limiter
        self.config = config
        self.create_offer_lock = threading.Lock()

    def save_uploaded_squeak(self, squeak: CSqueak) -> bytes:
        if not self.squeak_whitelist.should_allow_squeak(squeak):
            raise Exception("Squeak upload not allowed by whitelist.")
        if not self.squeak_rate_limiter.should_rate_limit_allow(squeak):
            raise Exception(
                "Excedeed allowed number of squeaks per block.")
        # Only allow uploaded squeak if decryption key included.
        if not squeak.HasDecryptionKey():
            raise Exception(
                "Uploaded squeak must contain decryption key.")
        decryption_key = squeak.GetDecryptionKey()
        squeak_entry = self.squeak_core.validate_squeak(squeak)
        logger.info("Saving uploaded squeak: {}".format(
            get_hash(squeak).hex()
        ))
        inserted_squeak_hash = self.squeak_db.insert_squeak(
            squeak, squeak_entry.block_header)
        logger.info("Unlocking uploaded squeak: {}".format(
            get_hash(squeak).hex()
        ))
        self.squeak_db.set_squeak_decryption_key(
            inserted_squeak_hash, decryption_key
        )
        return inserted_squeak_hash

    def save_downloaded_squeak(self, squeak: CSqueak) -> bytes:
        if not self.squeak_rate_limiter.should_rate_limit_allow(squeak):
            raise Exception(
                "Excedeed allowed number of squeaks per block.")
        squeak_entry = self.squeak_core.validate_squeak(squeak)
        inserted_squeak_hash = self.squeak_db.insert_squeak(
            squeak, squeak_entry.block_header)
        return inserted_squeak_hash

    def get_squeak(self, squeak_hash: bytes, clear_decryption_key: bool = False):
        squeak_entry = self.squeak_db.get_squeak_entry(squeak_hash)
        if squeak_entry is None:
            return None
        squeak = squeak_entry.squeak
        if clear_decryption_key:
            squeak.ClearDecryptionKey()
        return squeak

    def get_public_squeak(self, squeak_hash: bytes):
        return self.get_squeak(squeak_hash, clear_decryption_key=True)

    def lookup_allowed_addresses(self, addresses: List[str]):
        return self.squeak_whitelist.get_allowed_addresses(addresses)

    def get_buy_offer(self, squeak_hash: bytes, client_addr: str):
        # Check if there is an existing offer for the hash/client_addr combination
        sent_offer = self.get_saved_sent_offer(squeak_hash, client_addr)
        return self.squeak_core.package_offer(
            sent_offer,
            self.config.lnd.external_host,
            self.config.lnd.port,
        )

    def get_saved_sent_offer(self, squeak_hash: bytes, client_addr: str):
        with self.create_offer_lock:
            # Check if there is an existing offer for the hash/client_addr combination
            sent_offer = self.squeak_db.get_sent_offer_by_squeak_hash_and_client_addr(
                squeak_hash,
                client_addr,
            )
            if sent_offer:
                return sent_offer
            squeak = self.get_squeak(squeak_hash)
            # sent_offer = self.create_offer(
            #     squeak, client_addr, self.config.core.price_msat)
            sent_offer = self.squeak_core.create_offer(
                squeak,
                client_addr,
                self.config.core.price_msat,
            )
            self.squeak_db.insert_sent_offer(sent_offer)
            return sent_offer

    def create_signing_profile(self, profile_name: str):
        if len(profile_name) == 0:
            raise Exception(
                "Profile name cannot be empty.",
            )
        signing_key = CSigningKey.generate()
        verifying_key = signing_key.get_verifying_key()
        address = CSqueakAddress.from_verifying_key(verifying_key)
        signing_key_str = str(signing_key)
        signing_key_bytes = signing_key_str.encode()
        squeak_profile = SqueakProfile(
            profile_id=None,
            profile_name=profile_name,
            private_key=signing_key_bytes,
            address=str(address),
            sharing=True,
            following=True,
            profile_image=None,
        )
        return self.squeak_db.insert_profile(squeak_profile)

    def import_signing_profile(self, profile_name: str, private_key: str):
        signing_key = CSigningKey(private_key)
        verifying_key = signing_key.get_verifying_key()
        address = CSqueakAddress.from_verifying_key(verifying_key)
        signing_key_str = str(signing_key)
        signing_key_bytes = signing_key_str.encode()
        squeak_profile = SqueakProfile(
            profile_id=None,
            profile_name=profile_name,
            private_key=signing_key_bytes,
            address=str(address),
            sharing=False,
            following=False,
            profile_image=None,
        )
        return self.squeak_db.insert_profile(squeak_profile)

    def create_contact_profile(self, profile_name: str, squeak_address: str):
        if len(profile_name) == 0:
            raise Exception(
                "Profile name cannot be empty.",
            )
        if not is_address_valid(squeak_address):
            raise Exception(
                "Invalid squeak address: {}".format(
                    squeak_address
                ),
            )
        squeak_profile = SqueakProfile(
            profile_id=None,
            profile_name=profile_name,
            private_key=None,
            address=squeak_address,
            sharing=False,
            following=True,
            profile_image=None,
        )
        return self.squeak_db.insert_profile(squeak_profile)

    def get_signing_profiles(self):
        return self.squeak_db.get_signing_profiles()

    def get_contact_profiles(self):
        return self.squeak_db.get_contact_profiles()

    def get_squeak_profile(self, profile_id: int):
        return self.squeak_db.get_profile(profile_id)

    def get_squeak_profile_by_address(self, address: str):
        return self.squeak_db.get_profile_by_address(address)

    def get_squeak_profile_by_name(self, name: str):
        return self.squeak_db.get_profile_by_name(name)

    def set_squeak_profile_following(self, profile_id: int, following: bool):
        self.squeak_db.set_profile_following(profile_id, following)
        self.squeak_whitelist.refresh()

    def set_squeak_profile_sharing(self, profile_id: int, sharing: bool):
        self.squeak_db.set_profile_sharing(profile_id, sharing)

    def rename_squeak_profile(self, profile_id: int, profile_name: str):
        self.squeak_db.set_profile_name(profile_id, profile_name)

    def delete_squeak_profile(self, profile_id: int):
        self.squeak_db.delete_profile(profile_id)

    def set_squeak_profile_image(self, profile_id: int, profile_image: bytes):
        self.squeak_db.set_profile_image(profile_id, profile_image)

    def clear_squeak_profile_image(self, profile_id: int):
        self.squeak_db.set_profile_image(profile_id, None)

    def get_squeak_profile_private_key(self, profile_id: int):
        profile = self.get_squeak_profile(profile_id)
        if profile.private_key is None:
            raise Exception("Profile with id: {} does not have a private key.".format(
                profile_id
            ))
        return profile.private_key

    def make_squeak(self, profile_id: int, content_str: str, replyto_hash: bytes):
        squeak_profile = self.squeak_db.get_profile(profile_id)
        squeak_entry = self.squeak_core.make_squeak(
            squeak_profile, content_str, replyto_hash)
        # return self.save_created_squeak(squeak_entry.squeak)
        inserted_squeak_hash = self.squeak_db.insert_squeak(
            squeak_entry.squeak, squeak_entry.block_header)
        return inserted_squeak_hash

    def delete_squeak(self, squeak_hash: bytes):
        num_deleted_offers = self.squeak_db.delete_offers_for_squeak(
            squeak_hash)
        logger.info("Deleted number of offers : {}".format(num_deleted_offers))
        return self.squeak_db.delete_squeak(squeak_hash)

    def create_peer(self, peer_name: str, host: str, port: int):
        if len(peer_name) == 0:
            raise Exception(
                "Peer name cannot be empty.",
            )
        port = port or self.config.core.default_peer_rpc_port
        squeak_peer = SqueakPeer(
            peer_id=None,
            peer_name=peer_name,
            host=host,
            port=port,
            uploading=False,
            downloading=False,
        )
        return self.squeak_db.insert_peer(squeak_peer)

    def get_peer(self, peer_id: int):
        return self.squeak_db.get_peer(peer_id)

    def get_peers(self):
        return self.squeak_db.get_peers()

    def get_downloading_peers(self):
        return self.squeak_db.get_downloading_peers()

    def get_uploading_peers(self):
        return self.squeak_db.get_uploading_peers()

    def set_peer_downloading(self, peer_id: int, downloading: bool):
        self.squeak_db.set_peer_downloading(peer_id, downloading)

    def set_peer_uploading(self, peer_id: int, uploading: bool):
        self.squeak_db.set_peer_uploading(peer_id, uploading)

    def rename_peer(self, peer_id: int, peer_name: str):
        self.squeak_db.set_peer_name(peer_id, peer_name)

    def delete_peer(self, peer_id: int):
        self.squeak_db.delete_peer(peer_id)

    def get_buy_offers_with_peer(self, squeak_hash: bytes):
        return self.squeak_db.get_offers_with_peer(squeak_hash)

    def get_buy_offer_with_peer(self, offer_id: int):
        return self.squeak_db.get_offer_with_peer(offer_id)

    def pay_offer(self, received_offer_id: int) -> int:
        # Get the offer from the database
        received_offer_with_peer = self.squeak_db.get_offer_with_peer(
            received_offer_id)
        if received_offer_with_peer is None:
            raise Exception("Received offer with id {} not found.".format(
                received_offer_id,
            ))
        received_offer = received_offer_with_peer.received_offer
        logger.info("Paying received offer: {}".format(received_offer))
        sent_payment = self.squeak_core.pay_offer(received_offer)
        sent_payment_id = self.squeak_db.insert_sent_payment(sent_payment)
        # Delete the received offer
        self.squeak_db.delete_offer(sent_payment.payment_hash)
        secret_key = sent_payment.secret_key
        squeak_entry = self.squeak_db.get_squeak_entry(
            received_offer.squeak_hash)
        squeak = squeak_entry.squeak
        # Check the decryption key
        squeak.SetDecryptionKey(secret_key)
        CheckSqueak(squeak)
        # Set the decryption key in the database
        self.unlock_squeak(
            received_offer.squeak_hash,
            secret_key,
        )
        return sent_payment_id

    def unlock_squeak(self, squeak_hash: bytes, secret_key: bytes):
        self.squeak_db.set_squeak_decryption_key(
            squeak_hash,
            secret_key,
        )

    def get_sent_payments(self):
        return self.squeak_db.get_sent_payments()

    def get_sent_payment(self, sent_payment_id: int):
        return self.squeak_db.get_sent_payment(sent_payment_id)

    def get_sent_offers(self):
        return self.squeak_db.get_sent_offers()

    def get_received_payments(self):
        return self.squeak_db.get_received_payments()

    def delete_all_expired_offers(self):
        logger.debug("Deleting expired offers.")
        num_expired_offers = self.squeak_db.delete_expired_offers()
        if num_expired_offers > 0:
            logger.info("Deleted number of expired offers: {}".format(
                num_expired_offers))

    def delete_all_expired_sent_offers(self):
        logger.debug("Deleting expired sent offers.")
        num_expired_sent_offers = self.squeak_db.delete_expired_sent_offers()
        if num_expired_sent_offers > 0:
            logger.info(
                "Deleted number of expired sent offers: {}".format(
                    num_expired_sent_offers)
            )

    def process_subscribed_invoices(self, retry_s: int = 10):
        def get_sent_offer_for_payment_hash(payment_hash: bytes) -> SentOffer:
            return self.squeak_db.get_sent_offer_by_payment_hash(
                payment_hash
            )
        while True:
            try:
                latest_settle_index = self.squeak_db.get_latest_settle_index() or 0
                for received_payment in self.squeak_core.get_received_payments(
                        get_sent_offer_for_payment_hash,
                        latest_settle_index,
                ):
                    logger.info(
                        "Got received payment: {}".format(received_payment))
                    self.squeak_db.insert_received_payment(received_payment)
                    self.squeak_db.delete_sent_offer(
                        received_payment.payment_hash)
            except Exception:
                logger.info(
                    "Unable to subscribe invoices from lnd. Retrying in "
                    "{} seconds.".format(retry_s),
                )
                time.sleep(retry_s)

    def subscribe_received_payments(self, initial_index: int):
        with OpenReceivedPaymentsSubscriptionClient(
            self.squeak_db,
            initial_index,
        ) as client:
            for payment in client.get_received_payments():
                yield payment

    def get_best_block_height(self):
        return self.squeak_core.get_best_block_height()

    def get_block_range(self):
        return self.config.sync.block_range

    def get_network(self):
        return self.config.core.network

    def get_offer(self, squeak: CSqueak, offer: Offer, peer: SqueakPeer) -> ReceivedOffer:
        return self.squeak_core.unpack_offer(squeak, offer, peer)

    def get_squeak_entry_with_profile(self, squeak_hash: bytes):
        return self.squeak_db.get_squeak_entry_with_profile(squeak_hash)

    def get_timeline_squeak_entries_with_profile(self):
        return self.squeak_db.get_timeline_squeak_entries_with_profile()

    def get_squeak_entries_with_profile_for_address(
        self, address: str, min_block: int, max_block: int
    ):
        return self.squeak_db.get_squeak_entries_with_profile_for_address(
            address,
            min_block,
            max_block,
        )

    def get_ancestor_squeak_entries_with_profile(self, squeak_hash: bytes):
        return self.squeak_db.get_thread_ancestor_squeak_entries_with_profile(
            squeak_hash,
        )

    def get_reply_squeak_entries_with_profile(self, squeak_hash: bytes):
        return self.squeak_db.get_thread_reply_squeak_entries_with_profile(
            squeak_hash,
        )

    def lookup_squeaks(self, addresses: List[str], min_block: int, max_block: int):
        return self.squeak_db.lookup_squeaks(
            addresses,
            min_block,
            max_block,
        )

    def lookup_squeaks_include_locked(self, addresses: List[str], min_block: int, max_block: int):
        return self.squeak_db.lookup_squeaks(
            addresses,
            min_block,
            max_block,
            include_locked=True,
        )

    def lookup_squeaks_needing_offer(self, addresses: List[str], min_block, max_block, peer_id):
        return self.squeak_db.lookup_squeaks_needing_offer(
            addresses,
            min_block,
            max_block,
            peer_id,
        )

    def save_offer(self, received_offer: ReceivedOffer):
        logger.info("Saving received offer: {}".format(received_offer))
        self.squeak_db.insert_received_offer(received_offer)

    def get_followed_addresses(self):
        followed_profiles = self.squeak_db.get_following_profiles()
        return [profile.address for profile in followed_profiles]

    def get_sharing_addresses(self):
        sharing_profiles = self.squeak_db.get_sharing_profiles()
        return [profile.address for profile in sharing_profiles]

    def get_received_payment_summary(self) -> ReceivedPaymentSummary:
        return self.squeak_db.get_received_payment_summary()

    def get_sent_payment_summary(self) -> SentPaymentSummary:
        return self.squeak_db.get_sent_payment_summary()
