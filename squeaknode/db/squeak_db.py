import logging
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import List
from typing import Optional

import sqlalchemy
from sqlalchemy import func
from sqlalchemy import literal
from sqlalchemy.sql import and_
from sqlalchemy.sql import or_
from sqlalchemy.sql import select
from squeak.core import CSqueak

from squeaknode.bitcoin.util import parse_block_header
from squeaknode.core.received_offer import ReceivedOffer
from squeaknode.core.received_offer_with_peer import ReceivedOfferWithPeer
from squeaknode.core.received_payment import ReceivedPayment
from squeaknode.core.sent_offer import SentOffer
from squeaknode.core.sent_payment import SentPayment
from squeaknode.core.sent_payment_with_peer import SentPaymentWithPeer
from squeaknode.core.squeak_entry import SqueakEntry
from squeaknode.core.squeak_entry_with_profile import SqueakEntryWithProfile
from squeaknode.core.squeak_peer import SqueakPeer
from squeaknode.core.squeak_profile import SqueakProfile
from squeaknode.core.util import get_hash
from squeaknode.db.migrations import run_migrations
from squeaknode.db.models import Models

logger = logging.getLogger(__name__)


class SqueakDb:
    def __init__(self, engine, schema=None):
        self.engine = engine
        self.schema = schema
        self.models = Models(schema=schema)

    @contextmanager
    def get_connection(self):
        with self.engine.connect() as connection:
            yield connection

    def init(self):
        """ Create the tables and indices in the database. """
        logger.debug("SqlAlchemy version: {}".format(sqlalchemy.__version__))
        run_migrations(self.engine)

    @property
    def squeaks(self):
        return self.models.squeaks

    @property
    def profiles(self):
        return self.models.profiles

    @property
    def peers(self):
        return self.models.peers

    @property
    def received_offers(self):
        return self.models.received_offers

    @property
    def sent_payments(self):
        return self.models.sent_payments

    @property
    def received_payments(self):
        return self.models.received_payments

    @property
    def sent_offers(self):
        return self.models.sent_offers

    def insert_squeak(self, squeak, block_header_bytes) -> bytes:
        """ Insert a new squeak.

        Return the hash (bytes) of the inserted squeak.
        """
        secret_key_hex = (
            squeak.GetDecryptionKey().hex() if squeak.HasDecryptionKey() else None
        )
        squeak.ClearDecryptionKey()
        ins = self.squeaks.insert().values(
            hash=get_hash(squeak).hex(),
            squeak=squeak.serialize(),
            hash_reply_sqk=squeak.hashReplySqk.hex(),
            hash_block=squeak.hashBlock.hex(),
            n_block_height=squeak.nBlockHeight,
            n_time=squeak.nTime,
            author_address=str(squeak.GetAddress()),
            secret_key=secret_key_hex,
            block_header=block_header_bytes,
        )
        with self.get_connection() as connection:
            try:
                connection.execute(ins)
                # inserted_squeak_hash = res.inserted_primary_key[0]
            except sqlalchemy.exc.IntegrityError:
                pass
            return get_hash(squeak)

    def get_squeak_entry(self, squeak_hash: bytes) -> Optional[SqueakEntry]:
        """ Get a squeak. """
        s = select([self.squeaks]).where(
            self.squeaks.c.hash == squeak_hash.hex())
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            if row is None:
                return None
            return self._parse_squeak_entry(row)

    def get_squeak_entry_with_profile(self, squeak_hash: bytes) -> Optional[SqueakEntryWithProfile]:
        """ Get a squeak with the author profile. """
        s = (
            select([self.squeaks, self.profiles])
            .select_from(
                self.squeaks.outerjoin(
                    self.profiles,
                    self.profiles.c.address == self.squeaks.c.author_address,
                )
            )
            .where(self.squeaks.c.hash == squeak_hash.hex())
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            if row is None:
                return None
            return self._parse_squeak_entry_with_profile(row)

    def get_timeline_squeak_entries_with_profile(self) -> List[SqueakEntryWithProfile]:
        """ Get all followed squeaks. """
        s = (
            select([self.squeaks, self.profiles])
            .select_from(
                self.squeaks.outerjoin(
                    self.profiles,
                    self.profiles.c.address == self.squeaks.c.author_address,
                )
            )
            .where(self.squeaks.c.block_header != None)  # noqa: E711
            .order_by(
                self.squeaks.c.n_block_height.desc(),
                self.squeaks.c.n_time.desc(),
            )
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            return [self._parse_squeak_entry_with_profile(row) for row in rows]

    def get_squeak_entries_with_profile_for_address(
        self, address, min_block, max_block
    ) -> List[SqueakEntryWithProfile]:
        """ Get a squeak. """
        s = (
            select([self.squeaks, self.profiles])
            .select_from(
                self.squeaks.outerjoin(
                    self.profiles,
                    self.profiles.c.address == self.squeaks.c.author_address,
                )
            )
            .where(self.squeaks.c.block_header != None)  # noqa: E711
            .where(self.squeaks.c.author_address == address)
            .where(self.squeaks.c.n_block_height >= min_block)
            .where(self.squeaks.c.n_block_height <= max_block)
            .order_by(
                self.squeaks.c.n_block_height.desc(),
                self.squeaks.c.n_time.desc(),
            )
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            return [self._parse_squeak_entry_with_profile(row) for row in rows]

    def get_thread_ancestor_squeak_entries_with_profile(self, squeak_hash: bytes) -> List[SqueakEntryWithProfile]:
        """ Get all reply ancestors of squeak hash. """
        ancestors = (
            select(
                [
                    self.squeaks.c.hash.label("hash"),
                    literal(0).label("depth"),
                ]
            )
            .where(self.squeaks.c.hash == squeak_hash.hex())
            .cte(recursive=True)
        )

        ancestors_alias = ancestors.alias()
        squeaks_alias = self.squeaks.alias()

        ancestors = ancestors.union_all(
            select(
                [
                    squeaks_alias.c.hash_reply_sqk.label("hash"),
                    (ancestors_alias.c.depth + 1).label("depth"),
                ]
            ).where(squeaks_alias.c.hash == ancestors_alias.c.hash)
        )

        s = (
            select([self.squeaks, self.profiles])
            .select_from(
                self.squeaks.join(
                    ancestors,
                    ancestors.c.hash == self.squeaks.c.hash,
                ).outerjoin(
                    self.profiles,
                    self.profiles.c.address == self.squeaks.c.author_address,
                )
            )
            .where(self.squeaks.c.block_header != None)  # noqa: E711
            .order_by(
                ancestors.c.depth.desc(),
            )
        )

        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            return [self._parse_squeak_entry_with_profile(row) for row in rows]

        # sql = """
        # WITH RECURSIVE is_thread_ancestor(hash, depth) AS (
        #     VALUES(%s, 1)
        #   UNION\n
        #     SELECT squeak.hash_reply_sqk AS hash, is_thread_ancestor.depth + 1 AS depth FROM squeak, is_thread_ancestor
        #     WHERE squeak.hash=is_thread_ancestor.hash
        #   )
        #   SELECT * FROM squeak
        #   JOIN is_thread_ancestor
        #     ON squeak.hash=is_thread_ancestor.hash
        #   LEFT JOIN profile
        #     ON squeak.author_address=profile.address
        #   WHERE squeak.block_header IS NOT NULL
        #   ORDER BY is_thread_ancestor.depth DESC;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (squeak_hash_str,))
        #     rows = curs.fetchall()
        #     return [self._parse_squeak_entry_with_profile(row) for row in rows]

    def get_thread_reply_squeak_entries_with_profile(self, squeak_hash: bytes) -> List[SqueakEntryWithProfile]:
        """ Get all replies for a squeak hash. """
        s = (
            select([self.squeaks, self.profiles])
            .select_from(
                self.squeaks.outerjoin(
                    self.profiles,
                    self.profiles.c.address == self.squeaks.c.author_address,
                )
            )
            .where(self.squeaks.c.block_header != None)  # noqa: E711
            .where(self.squeaks.c.hash_reply_sqk == squeak_hash.hex())
            .order_by(
                self.squeaks.c.n_block_height.desc(),
                self.squeaks.c.n_time.desc(),
            )
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            return [self._parse_squeak_entry_with_profile(row) for row in rows]

    def lookup_squeaks(
        self,
        addresses,
        min_block,
        max_block,
        include_unverified=False,
        include_locked=False,
    ):
        """ Lookup squeaks. """
        if not addresses:
            return []

        s = (
            select([self.squeaks.c.hash])
            .where(self.squeaks.c.author_address.in_(addresses))
            .where(self.squeaks.c.n_block_height >= min_block)
            .where(self.squeaks.c.n_block_height <= max_block)
            .where(
                or_(
                    self.squeaks.c.secret_key != None,  # noqa: E711
                    include_locked,
                )
            )
            .where(
                or_(
                    self.squeaks.c.block_header != None,  # noqa: E711
                    include_unverified,
                )
            )
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            hashes = [bytes.fromhex(row["hash"]) for row in rows]
            return hashes

        # sql = """
        # SELECT hash FROM squeak
        # WHERE author_address IN %s
        # AND n_block_height >= %s
        # AND n_block_height <= %s
        # AND (secret_key IS NOT NULL) OR %s
        # AND ((block_header IS NOT NULL) OR %s);
        # """
        # addresses_tuple = tuple(addresses)

        # if not addresses:
        #     return []

        # with self.get_cursor() as curs:
        #     # mogrify to debug.
        #     # logger.info(curs.mogrify(sql, (addresses_tuple, min_block, max_block)))
        #     curs.execute(
        #         sql, (addresses_tuple, min_block, max_block, include_locked, include_unverified)
        #     )
        #     rows = curs.fetchall()
        #     hashes = [bytes.fromhex(row["hash"]) for row in rows]
        #     return hashes

    def lookup_squeaks_by_time(
        self,
        addresses,
        interval_seconds,
        include_unverified=False,
        include_locked=False,
    ) -> List[bytes]:
        """ Lookup squeaks. """
        if not addresses:
            return []

        s = (
            select([self.squeaks.c.hash])
            .where(self.squeaks.c.author_address.in_(addresses))
            .where(
                self.squeaks.c.created > datetime.now(
                    timezone.utc) - timedelta(seconds=interval_seconds)
            )
            .where(
                or_(
                    self.squeaks.c.secret_key != None,  # noqa: E711
                    include_locked,
                )
            )
            .where(
                or_(
                    self.squeaks.c.block_header != None,  # noqa: E711
                    include_unverified,
                )
            )
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            hashes = [bytes.fromhex(row["hash"]) for row in rows]
            return hashes

        # sql = """
        # SELECT hash FROM squeak
        # WHERE author_address IN %s
        # AND created > now() - interval '%s seconds'
        # AND secret_key IS NOT NULL
        # AND ((block_header IS NOT NULL) OR %s);
        # """
        # addresses_tuple = tuple(addresses)

        # if not addresses:
        #     return []

        # with self.get_cursor() as curs:
        #     # mogrify to debug.
        #     # logger.info(curs.mogrify(sql, (addresses_tuple, min_block, max_block)))
        #     curs.execute(sql, (addresses_tuple, interval_seconds, include_unverified))
        #     rows = curs.fetchall()
        #     hashes = [bytes.fromhex(row["hash"]) for row in rows]
        #     return hashes

    def lookup_squeaks_needing_offer(
        self, addresses, min_block, max_block, peer_id, include_unverified=False
    ) -> List[bytes]:
        """ Lookup squeaks that are locked and don't have an offer. """
        if not addresses:
            return []

        s = (
            select([self.squeaks.c.hash])
            .select_from(
                self.squeaks.outerjoin(
                    self.received_offers,
                    and_(
                        self.received_offers.c.squeak_hash == self.squeaks.c.hash,
                        self.received_offers.c.peer_id == peer_id,
                    ),
                )
            )
            .where(self.squeaks.c.author_address.in_(addresses))
            .where(self.squeaks.c.n_block_height >= min_block)
            .where(self.squeaks.c.n_block_height <= max_block)
            .where(self.squeaks.c.secret_key == None)  # noqa: E711
            .where(
                or_(
                    self.squeaks.c.block_header != None,  # noqa: E711
                    include_unverified,
                )
            )
            .where(self.received_offers.c.squeak_hash == None)  # noqa: E711
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            hashes = [bytes.fromhex(row["hash"]) for row in rows]
            return hashes

        # sql = """
        # SELECT hash FROM squeak
        # LEFT JOIN offer
        # ON squeak.hash=offer.squeak_hash
        # AND offer.peer_id=%s
        # WHERE author_address IN %s
        # AND n_block_height >= %s
        # AND n_block_height <= %s
        # AND secret_key IS NULL
        # AND ((block_header IS NOT NULL) OR %s)
        # AND offer.squeak_hash IS NULL
        # """
        # addresses_tuple = tuple(addresses)

        # if not addresses:
        #     return []

        # with self.get_cursor() as curs:
        #     # mogrify to debug.
        #     # logger.info(curs.mogrify(sql, (addresses_tuple, min_block, max_block)))
        #     curs.execute(
        #         sql, (peer_id, addresses_tuple, min_block, max_block, include_unverified)
        #     )
        #     rows = curs.fetchall()
        #     hashes = [bytes.fromhex(row["hash"]) for row in rows]
        #     return hashes

    def insert_profile(self, squeak_profile) -> int:
        """ Insert a new squeak profile. """
        ins = self.profiles.insert().values(
            profile_name=squeak_profile.profile_name,
            private_key=squeak_profile.private_key,
            address=squeak_profile.address,
            sharing=squeak_profile.sharing,
            following=squeak_profile.following,
        )
        with self.get_connection() as connection:
            res = connection.execute(ins)
            profile_id = res.inserted_primary_key[0]
            return profile_id

    def get_signing_profiles(self):
        """ Get all signing profiles. """
        s = select([self.profiles]).where(self.profiles.c.private_key != None)  # noqa: E711
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            profiles = [self._parse_squeak_profile(row) for row in rows]
            return profiles

        # sql = """
        # SELECT * FROM profile
        # WHERE private_key IS NOT NULL;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql)
        #     rows = curs.fetchall()
        #     profiles = [self._parse_squeak_profile(row) for row in rows]
        #     return profiles

    def get_contact_profiles(self):
        """ Get all contact profiles. """
        s = select([self.profiles]).where(self.profiles.c.private_key == None)  # noqa: E711
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            profiles = [self._parse_squeak_profile(row) for row in rows]
            return profiles

        # sql = """
        # SELECT * FROM profile
        # WHERE private_key IS NULL;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql)
        #     rows = curs.fetchall()
        #     profiles = [self._parse_squeak_profile(row) for row in rows]
        #     return profiles

    def get_following_profiles(self):
        """ Get all following profiles. """
        s = select([self.profiles]).where(self.profiles.c.following)
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            profiles = [self._parse_squeak_profile(row) for row in rows]
            return profiles

    def get_following_profiles_from_addreses(self, addresses):
        """ Get all following profiles. """
        s = (
            select([self.profiles])
            .where(self.profiles.c.following)
            .where(self.profiles.c.address.in_(addresses))
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            profiles = [self._parse_squeak_profile(row) for row in rows]
            return profiles

    def get_sharing_profiles(self):
        """ Get all sharing profiles. """
        s = select([self.profiles]).where(self.profiles.c.sharing)
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            profiles = [self._parse_squeak_profile(row) for row in rows]
            return profiles

        # sql = """
        # SELECT * FROM profile
        # WHERE sharing;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql)
        #     rows = curs.fetchall()
        #     profiles = [self._parse_squeak_profile(row) for row in rows]
        #     return profiles

    def get_profile(self, profile_id):
        """ Get a profile. """
        s = select([self.profiles]).where(
            self.profiles.c.profile_id == profile_id)
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            return self._parse_squeak_profile(row)

        # sql = """
        # SELECT * FROM profile WHERE profile_id=%s"""
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (profile_id,))
        #     row = curs.fetchone()
        #     return self._parse_squeak_profile(row)

    def get_profile_by_address(self, address):
        """ Get a profile by address. """
        s = select([self.profiles]).where(self.profiles.c.address == address)
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            return self._parse_squeak_profile(row)

        # sql = """
        # SELECT * FROM profile
        # WHERE address=%s;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (address,))
        #     row = curs.fetchone()
        #     return self._parse_squeak_profile(row)

    def get_profile_by_name(self, name):
        """ Get a profile by name. """
        s = select([self.profiles]).where(self.profiles.c.profile_name == name)
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            return self._parse_squeak_profile(row)

    def set_profile_following(self, profile_id, following):
        """ Set a profile is following. """
        stmt = (
            self.profiles.update()
            .where(self.profiles.c.profile_id == profile_id)
            .values(following=following)
        )
        with self.get_connection() as connection:
            connection.execute(stmt)

        # sql = """
        # UPDATE profile
        # SET following=%s
        # WHERE profile_id=%s;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (following, profile_id,))

    def set_profile_sharing(self, profile_id, sharing):
        """ Set a profile is sharing. """
        stmt = (
            self.profiles.update()
            .where(self.profiles.c.profile_id == profile_id)
            .values(sharing=sharing)
        )
        with self.get_connection() as connection:
            connection.execute(stmt)

        # sql = """
        # UPDATE profile
        # SET sharing=%s
        # WHERE profile_id=%s;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (sharing, profile_id,))

    def delete_profile(self, profile_id):
        """ Delete a profile. """
        delete_profile_stmt = self.profiles.delete().where(
            self.profiles.c.profile_id == profile_id
        )
        with self.get_connection() as connection:
            connection.execute(delete_profile_stmt)

        # sql = """
        # DELETE FROM profile
        # WHERE profile_id=%s;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (profile_id,))

    def get_unverified_block_squeaks(self):
        """ Get all squeaks without block header. """
        s = select([self.squeaks.c.hash]).where(self.squeaks.c.block_header == None)  # noqa: E711
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            hashes = [bytes.fromhex(row["hash"]) for row in rows]
            return hashes

        # sql = """
        # SELECT hash FROM squeak
        # WHERE block_header IS NULL;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql)
        #     rows = curs.fetchall()
        #     hashes = [bytes.fromhex(row["hash"]) for row in rows]
        #     return hashes

    def mark_squeak_block_valid(self, squeak_hash: bytes, block_header):
        """ Add the block header to a squeak. """
        stmt = (
            self.squeaks.update()
            .where(self.squeaks.c.hash == squeak_hash.hex())
            .values(block_header=block_header)
        )
        with self.get_connection() as connection:
            connection.execute(stmt)

        # sql = """
        # UPDATE squeak
        # SET block_header=%s
        # WHERE hash=%s;
        # """
        # squeak_hash_str = squeak_hash.hex()
        # with self.get_cursor() as curs:
        #     # execute the UPDATE statement
        #     curs.execute(sql, (block_header, squeak_hash_str,))

    def set_squeak_decryption_key(self, squeak_hash: bytes, secret_key: bytes):
        """ Set the decryption key of a squeak. """
        stmt = (
            self.squeaks.update()
            .where(self.squeaks.c.hash == squeak_hash.hex())
            .values(secret_key=secret_key.hex())
        )
        with self.get_connection() as connection:
            connection.execute(stmt)

    def delete_squeak(self, squeak_hash: bytes):
        """ Delete a squeak. """
        delete_squeak_stmt = self.squeaks.delete().where(
            self.squeaks.c.hash == squeak_hash.hex()
        )
        with self.get_connection() as connection:
            connection.execute(delete_squeak_stmt)

        # sql = """
        # DELETE FROM squeak
        # WHERE squeak.hash=%s
        # """
        # squeak_hash_str = squeak_hash.hex()
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (squeak_hash_str,))

    def insert_peer(self, squeak_peer: SqueakPeer):
        """ Insert a new squeak peer. """
        ins = self.peers.insert().values(
            peer_name=squeak_peer.peer_name,
            server_host=squeak_peer.host,
            server_port=squeak_peer.port,
            uploading=squeak_peer.uploading,
            downloading=squeak_peer.downloading,
        )
        with self.get_connection() as connection:
            res = connection.execute(ins)
            id = res.inserted_primary_key[0]
            return id

    def get_peer(self, peer_id):
        """ Get a peer. """
        s = select([self.peers]).where(self.peers.c.peer_id == peer_id)
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            return self._parse_squeak_peer(row)

    def get_peers(self):
        """ Get all peers. """
        s = select([self.peers])
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            peers = [self._parse_squeak_peer(row) for row in rows]
            return peers

    def get_downloading_peers(self):
        """ Get peers that are set to be downloading. """
        s = select([self.peers]).where(self.peers.c.downloading)
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            peers = [self._parse_squeak_peer(row) for row in rows]
            return peers

    def get_uploading_peers(self):
        """ Get peers that are set to be uploading. """
        s = select([self.peers]).where(self.peers.c.uploading)
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            peers = [self._parse_squeak_peer(row) for row in rows]
            return peers

    def set_peer_downloading(self, peer_id, downloading):
        """ Set a peer is downloading. """
        stmt = (
            self.peers.update()
            .where(self.peers.c.peer_id == peer_id)
            .values(downloading=downloading)
        )
        with self.get_connection() as connection:
            connection.execute(stmt)

    def set_peer_uploading(self, peer_id, uploading):
        """ Set a peer is uploading. """
        stmt = (
            self.peers.update()
            .where(self.peers.c.peer_id == peer_id)
            .values(uploading=uploading)
        )
        with self.get_connection() as connection:
            connection.execute(stmt)

    def delete_peer(self, peer_id):
        """ Delete a peer. """
        delete_peer_stmt = self.peers.delete().where(self.peers.c.peer_id == peer_id)
        with self.get_connection() as connection:
            connection.execute(delete_peer_stmt)

    def insert_offer(self, offer):
        """ Insert a new offer. """
        ins = self.received_offers.insert().values(
            squeak_hash=offer.squeak_hash.hex(),
            payment_hash=offer.payment_hash.hex(),
            nonce=offer.nonce.hex(),
            payment_point=offer.payment_point.hex(),
            invoice_timestamp=offer.invoice_timestamp,
            invoice_expiry=offer.invoice_expiry,
            price_msat=offer.price_msat,
            payment_request=offer.payment_request,
            destination=offer.destination,
            node_host=offer.node_host,
            node_port=offer.node_port,
            peer_id=offer.peer_id,
        )
        with self.get_connection() as connection:
            res = connection.execute(ins)
            received_offer_id = res.inserted_primary_key[0]
            return received_offer_id

        # sql = """
        # INSERT INTO offer(squeak_hash, key_cipher, iv, price_msat, payment_hash, invoice_timestamp, invoice_expiry, payment_request, destination, node_host, node_port, peer_id)
        # VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        # RETURNING offer_id;
        # """
        # with self.get_cursor() as curs:
        #     # execute the INSERT statement
        #     curs.execute(
        #         sql,
        #         (
        #             offer.squeak_hash.hex(),
        #             offer.key_cipher,
        #             offer.iv,
        #             offer.price_msat,
        #             offer.payment_hash.hex(),
        #             offer.invoice_timestamp,
        #             offer.invoice_expiry,
        #             offer.payment_request,
        #             offer.destination,
        #             offer.node_host,
        #             offer.node_port,
        #             offer.peer_id,
        #         ),
        #     )
        #     # get the new offer id back
        #     row = curs.fetchone()
        #     return row["offer_id"]

    def get_offers(self, squeak_hash: bytes):
        """ Get offers for a squeak hash. """
        s = select([self.received_offers]).where(
            self.received_offers.c.squeak_hash == squeak_hash.hex())
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            offers = [self._parse_offer(row) for row in rows]
            return offers

        # sql = """
        # SELECT * FROM offer
        # WHERE squeak_hash=%s;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (squeak_hash,))
        #     rows = curs.fetchall()
        #     offers = [self._parse_offer(row) for row in rows]
        #     return offers

    def get_offers_with_peer(self, squeak_hash: bytes):
        """ Get offers with peer for a squeak hash. """
        s = (
            select([self.received_offers, self.peers])
            .select_from(
                self.received_offers.outerjoin(
                    self.peers,
                    self.peers.c.peer_id == self.received_offers.c.peer_id,
                )
            )
            .where(self.received_offers.c.squeak_hash == squeak_hash.hex())
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            offers_with_peer = [
                self._parse_offer_with_peer(row) for row in rows]
            return offers_with_peer

        # sql = """
        # SELECT * FROM offer
        # LEFT JOIN peer
        # ON offer.peer_id=peer.peer_id
        # WHERE squeak_hash=%s;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql, (squeak_hash,))
        #     rows = curs.fetchall()
        #     offers_with_peer = [self._parse_offer_with_peer(row) for row in rows]
        #     return offers_with_peer

    def get_offer_with_peer(self, received_offer_id):
        """ Get offer with peer for an offer id. """
        s = (
            select([self.received_offers, self.peers])
            .select_from(
                self.received_offers.outerjoin(
                    self.peers,
                    self.peers.c.peer_id == self.received_offers.c.peer_id,
                )
            )
            .where(self.received_offers.c.received_offer_id == received_offer_id)
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            offer_with_peer = self._parse_offer_with_peer(row)
            return offer_with_peer

    def delete_expired_offers(self):
        """ Delete all expired offers. """
        s = self.received_offers.delete().where(
            datetime.now(timezone.utc).timestamp(
            ) > self.received_offers.c.invoice_timestamp + self.received_offers.c.invoice_expiry
        )
        with self.get_connection() as connection:
            res = connection.execute(s)
            deleted_offers = res.rowcount
            return deleted_offers

        # sql = """
        # DELETE FROM offer
        # WHERE now() > to_timestamp(invoice_timestamp + invoice_expiry)
        # RETURNING *;
        # """
        # with self.get_cursor() as curs:
        #     curs.execute(sql)
        #     rows = curs.fetchall()
        #     return len(rows)

    def delete_offers_for_squeak(self, squeak_hash: bytes):
        """ Delete all offers for a squeak hash. """
        s = self.received_offers.delete().where(
            self.received_offers.c.squeak_hash == squeak_hash.hex())
        with self.get_connection() as connection:
            res = connection.execute(s)
            deleted_offers = res.rowcount
            return deleted_offers

    def delete_offer(self, payment_hash: bytes):
        """ Delete a received offer by payment hash. """
        s = self.received_offers.delete().where(
            self.received_offers.c.payment_hash == payment_hash.hex()
        )
        with self.get_connection() as connection:
            connection.execute(s)

    def insert_sent_payment(self, sent_payment):
        """ Insert a new sent payment. """
        ins = self.sent_payments.insert().values(
            peer_id=sent_payment.peer_id,
            squeak_hash=sent_payment.squeak_hash.hex(),
            payment_hash=sent_payment.payment_hash.hex(),
            secret_key=sent_payment.secret_key.hex(),
            price_msat=sent_payment.price_msat,
            node_pubkey=sent_payment.node_pubkey,
            valid=sent_payment.valid,
        )
        with self.get_connection() as connection:
            res = connection.execute(ins)
            sent_payment_id = res.inserted_primary_key[0]
            return sent_payment_id

    def get_sent_payments(self):
        """ Get all sent payments. """
        s = (
            select([self.sent_payments, self.peers])
            .select_from(
                self.sent_payments.outerjoin(
                    self.peers,
                    self.peers.c.peer_id == self.sent_payments.c.peer_id,
                )
            )
            .order_by(
                self.sent_payments.c.created.desc(),
            )
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            sent_payments = [
                self._parse_sent_payment_with_peer(row) for row in rows]
            return sent_payments

    def get_sent_payment(self, sent_payment_id):
        """ Get sent payment by id. """
        s = (
            select([self.sent_payments, self.peers])
            .select_from(
                self.sent_payments.outerjoin(
                    self.peers,
                    self.peers.c.peer_id == self.sent_payments.c.peer_id,
                )
            )
            .where(self.sent_payments.c.sent_payment_id == sent_payment_id)
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            return self._parse_sent_payment_with_peer(row)

    def insert_sent_offer(self, sent_offer):
        """ Insert a new sent offer. """
        ins = self.sent_offers.insert().values(
            squeak_hash=sent_offer.squeak_hash.hex(),
            payment_hash=sent_offer.payment_hash.hex(),
            secret_key=sent_offer.secret_key.hex(),
            nonce=sent_offer.nonce.hex(),
            price_msat=sent_offer.price_msat,
            payment_request=sent_offer.payment_request,
            invoice_timestamp=sent_offer.invoice_time,
            invoice_expiry=sent_offer.invoice_expiry,
            client_addr=sent_offer.client_addr,
        )
        with self.get_connection() as connection:
            res = connection.execute(ins)
            sent_offer_id = res.inserted_primary_key[0]
            return sent_offer_id

    def get_sent_offers(self):
        """ Get all received payments. """
        s = select([self.sent_offers]).order_by(
            self.sent_offers.c.created.desc(),
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            sent_offers = [self._parse_sent_offer(row) for row in rows]
            return sent_offers

    def get_sent_offer_by_payment_hash(self, payment_hash: bytes):
        """ Get a sent offer by preimage hash. """
        s = select([self.sent_offers]).where(
            self.sent_offers.c.payment_hash == payment_hash.hex()
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            if row is None:
                return None
            sent_offer = self._parse_sent_offer(row)
            return sent_offer

    def get_sent_offer_by_squeak_hash_and_client_addr(self, squeak_hash: bytes, client_addr):
        """ Get a sent offer by squeak hash and client addr. """
        s = (
            select([self.sent_offers])
            .where(self.sent_offers.c.squeak_hash == squeak_hash.hex())
            .where(self.sent_offers.c.client_addr == client_addr)
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            if row is None:
                return None
            sent_offer = self._parse_sent_offer(row)
            return sent_offer

    def delete_sent_offer(self, payment_hash: bytes):
        """ Delete a sent offer by payment hash. """
        s = self.sent_offers.delete().where(
            self.sent_offers.c.payment_hash == payment_hash.hex()
        )
        with self.get_connection() as connection:
            connection.execute(s)

    def delete_expired_sent_offers(self):
        """ Delete all expired sent offers. """
        s = self.sent_offers.delete().where(
            datetime.now(timezone.utc).timestamp(
            ) > self.sent_offers.c.invoice_timestamp + self.sent_offers.c.invoice_expiry
        )
        with self.get_connection() as connection:
            res = connection.execute(s)
            deleted_sent_offers = res.rowcount
            return deleted_sent_offers

    def get_latest_settle_index(self):
        """ Get the lnd settled index of the most recent received payment. """
        s = select(
            [func.max(self.received_payments.c.settle_index)],
        ).select_from(self.received_payments)
        with self.get_connection() as connection:
            result = connection.execute(s)
            row = result.fetchone()
            logger.info("Row for get_latest_settle_index: {}".format(row))
            latest_index = row[0]
            return latest_index

    def insert_received_payment(self, received_payment):
        """ Insert a new received payment. """
        ins = self.received_payments.insert().values(
            squeak_hash=received_payment.squeak_hash.hex(),
            payment_hash=received_payment.payment_hash.hex(),
            price_msat=received_payment.price_msat,
            settle_index=received_payment.settle_index,
            client_addr=received_payment.client_addr,
        )
        with self.get_connection() as connection:
            res = connection.execute(ins)
            received_payment_id = res.inserted_primary_key[0]
            return received_payment_id

    def get_received_payments(self):
        """ Get all received payments. """
        s = select([self.received_payments]).order_by(
            self.received_payments.c.created.desc(),
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            rows = result.fetchall()
            received_payments = [
                self._parse_received_payment(row) for row in rows]
            return received_payments

    def yield_received_payments_from_index(self, start_index=0):
        """ Get all received payments. """
        s = (
            select([self.received_payments])
            .order_by(
                self.received_payments.c.received_payment_id.asc(),
            )
            .where(self.received_payments.c.received_payment_id > start_index)
        )
        with self.get_connection() as connection:
            result = connection.execute(s)
            for row in result:
                received_payment = self._parse_received_payment(row)
                yield received_payment

    def _parse_squeak_entry(self, row) -> SqueakEntry:
        secret_key_column = row["secret_key"]
        secret_key = bytes.fromhex(
            secret_key_column) if secret_key_column else b""
        squeak = CSqueak.deserialize(row["squeak"])
        if secret_key:
            squeak.SetDecryptionKey(secret_key)
        block_header_column = row["block_header"]
        block_header_bytes = bytes(
            block_header_column) if block_header_column else None
        block_header = (
            parse_block_header(
                block_header_bytes) if block_header_bytes else None
        )
        return SqueakEntry(squeak=squeak, block_header=block_header)

    def _parse_squeak_profile(self, row):
        if row is None:
            return None
        if row["profile_id"] is None:
            return None
        private_key_column = row["private_key"]
        private_key = bytes(private_key_column) if private_key_column else None
        return SqueakProfile(
            profile_id=row["profile_id"],
            profile_name=row["profile_name"],
            private_key=private_key,
            address=row["address"],
            sharing=row["sharing"],
            following=row["following"],
        )

    def _parse_squeak_entry_with_profile(self, row) -> SqueakEntryWithProfile:
        squeak_entry = self._parse_squeak_entry(row)
        squeak_profile = self._parse_squeak_profile(row)
        return SqueakEntryWithProfile(
            squeak_entry=squeak_entry,
            squeak_profile=squeak_profile,
        )

    def _parse_squeak_peer(self, row):
        if row is None:
            return None
        return SqueakPeer(
            peer_id=row[self.peers.c.peer_id],
            peer_name=row["peer_name"],
            host=row["server_host"],
            port=row["server_port"],
            uploading=row["uploading"],
            downloading=row["downloading"],
        )

    def _parse_offer(self, row):
        if row is None:
            return None
        return ReceivedOffer(
            received_offer_id=row["received_offer_id"],
            squeak_hash=bytes.fromhex(row["squeak_hash"]),
            payment_hash=bytes.fromhex(row["payment_hash"]),
            nonce=bytes.fromhex(row["nonce"]),
            payment_point=bytes.fromhex(row["payment_point"]),
            invoice_timestamp=row["invoice_timestamp"],
            invoice_expiry=row["invoice_expiry"],
            price_msat=row["price_msat"],
            payment_request=row["payment_request"],
            destination=row["destination"],
            node_host=row["node_host"],
            node_port=row["node_port"],
            peer_id=row[self.peers.c.peer_id],
        )

    def _parse_offer_with_peer(self, row):
        if row is None:
            return None
        offer = self._parse_offer(row)
        peer = self._parse_squeak_peer(row)
        return ReceivedOfferWithPeer(
            received_offer=offer,
            peer=peer,
        )

    def _parse_sent_payment(self, row):
        if row is None:
            return None
        return SentPayment(
            sent_payment_id=row["sent_payment_id"],
            created=row[self.sent_payments.c.created],
            peer_id=row[self.sent_payments.c.peer_id],
            squeak_hash=bytes.fromhex(row["squeak_hash"]),
            payment_hash=bytes.fromhex(row["payment_hash"]),
            secret_key=bytes.fromhex(row["secret_key"]),
            price_msat=row["price_msat"],
            node_pubkey=row["node_pubkey"],
            valid=row["valid"],
        )

    def _parse_sent_payment_with_peer(self, row):
        if row is None:
            return None
        sent_payment = self._parse_sent_payment(row)
        peer = self._parse_squeak_peer(row)
        return SentPaymentWithPeer(
            sent_payment=sent_payment,
            peer=peer,
        )

    def _parse_sent_offer(self, row) -> SentOffer:
        return SentOffer(
            sent_offer_id=row["sent_offer_id"],
            squeak_hash=bytes.fromhex(row["squeak_hash"]),
            payment_hash=bytes.fromhex(row["payment_hash"]),
            secret_key=bytes.fromhex(row["secret_key"]),
            nonce=bytes.fromhex(row["nonce"]),
            price_msat=row["price_msat"],
            payment_request=row["payment_request"],
            invoice_time=row["invoice_timestamp"],
            invoice_expiry=row["invoice_expiry"],
            client_addr=row["client_addr"],
        )

    def _parse_received_payment(self, row) -> ReceivedPayment:
        return ReceivedPayment(
            received_payment_id=row["received_payment_id"],
            created=row["created"],
            squeak_hash=bytes.fromhex(row["squeak_hash"]),
            payment_hash=bytes.fromhex(row["payment_hash"]),
            price_msat=row["price_msat"],
            settle_index=row["settle_index"],
            client_addr=row["client_addr"],
        )
