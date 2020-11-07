from __future__ import print_function

import time

import pytest
from squeak.core import CheckSqueak
from squeak.core.encryption import CEncryptedDecryptionKey

from proto import lnd_pb2 as ln
from proto import squeak_admin_pb2, squeak_server_pb2
from tests.util import (
    build_squeak_msg,
    generate_challenge_proof,
    generate_signing_key,
    get_address,
    get_challenge,
    get_hash,
    get_latest_block_info,
    make_squeak,
    squeak_from_msg,
    string_to_hex,
    open_channel,
    connect_peer,
)


def test_post_squeak(
    server_stub, admin_stub, lightning_client, following_signing_key
):
    # Post a squeak with a direct request to the server
    block_height, block_hash = get_latest_block_info(lightning_client)
    squeak = make_squeak(
        following_signing_key, "hello from itest!", block_hash, block_height
    )
    squeak_hash = get_hash(squeak)

    squeak_msg = build_squeak_msg(squeak)
    post_response = server_stub.PostSqueak(
        squeak_server_pb2.PostSqueakRequest(squeak=squeak_msg)
    )

    # Wait a few seconds for the squeak to be verified on the server.
    time.sleep(1)

    # Get the same squeak from the server
    get_response = server_stub.GetSqueak(
        squeak_server_pb2.GetSqueakRequest(hash=squeak_hash)
    )
    get_response_squeak = squeak_from_msg(get_response.squeak)
    CheckSqueak(get_response_squeak, skipDecryptionCheck=True)

    assert get_hash(get_response_squeak) == get_hash(squeak)


def test_post_squeak_not_following(
    server_stub, admin_stub, lightning_client, nonfollowing_signing_key
):
    # Post a squeak with a direct request to the server
    block_height, block_hash = get_latest_block_info(lightning_client)
    squeak = make_squeak(
        nonfollowing_signing_key, "hello from itest!", block_hash, block_height
    )
    squeak_hash = get_hash(squeak)

    squeak_msg = build_squeak_msg(squeak)
    with pytest.raises(Exception):
        server_stub.PostSqueak(squeak_server_pb2.PostSqueakRequest(squeak=squeak_msg))


def test_lookup_squeaks(server_stub, admin_stub, signing_profile_id, saved_squeak_hash):
    # Get the squeak profile
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=signing_profile_id,
        )
    )
    squeak_profile_address = get_squeak_profile_response.squeak_profile.address

    # Lookup squeaks for the given signing profile
    addresses = [squeak_profile_address]
    lookup_response = server_stub.LookupSqueaks(
        squeak_server_pb2.LookupSqueaksRequest(
            addresses=addresses,
            min_block=0,
            max_block=99999999,
        )
    )
    assert len(lookup_response.hashes) == 1
    assert saved_squeak_hash in set(lookup_response.hashes)


def test_lookup_squeaks_empty_result_addresses(server_stub, admin_stub):
    signing_key = generate_signing_key()
    address = get_address(signing_key)

    # Lookup squeaks for the given address
    addresses = [address]
    lookup_response = server_stub.LookupSqueaks(
        squeak_server_pb2.LookupSqueaksRequest(
            addresses=addresses,
            min_block=0,
            max_block=99999999,
        )
    )
    assert len(lookup_response.hashes) == 0


def test_lookup_squeaks_empty_result_block_ranges(
    server_stub, admin_stub, signing_profile_id
):
    # Get the squeak profile
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=signing_profile_id,
        )
    )
    squeak_profile_address = get_squeak_profile_response.squeak_profile.address

    # Lookup squeaks for the given signing profile
    addresses = [squeak_profile_address]
    lookup_response = server_stub.LookupSqueaks(
        squeak_server_pb2.LookupSqueaksRequest(
            addresses=addresses,
            min_block=99999999,
            max_block=99999999,
        )
    )
    assert len(lookup_response.hashes) == 0


def test_sell_squeak(server_stub, admin_stub, lightning_client, saved_squeak_hash):
    # Check the server balance
    get_balance_response = admin_stub.LndWalletBalance(ln.WalletBalanceRequest())
    initial_server_balance = get_balance_response.total_balance

    # Get the squeak from the server
    get_response = server_stub.GetSqueak(
        squeak_server_pb2.GetSqueakRequest(hash=saved_squeak_hash)
    )
    get_response_squeak = squeak_from_msg(get_response.squeak)
    CheckSqueak(get_response_squeak, skipDecryptionCheck=True)

    # Generate a challenge to verify the offer
    expected_proof = generate_challenge_proof()
    encryption_key = get_response_squeak.GetEncryptionKey()
    challenge = get_challenge(encryption_key, expected_proof)

    # Buy the squeak data key
    buy_response = server_stub.GetOffer(
        squeak_server_pb2.GetOfferRequest(
            hash=saved_squeak_hash,
            challenge=challenge,
        )
    )
    assert buy_response.offer.payment_request.startswith("ln")

    # Check the offer challenge proof
    assert buy_response.offer.proof == expected_proof

    # Decode the payment request string
    decode_pay_req_response = lightning_client.decode_pay_req(
        buy_response.offer.payment_request
    )
    destination = decode_pay_req_response.destination

    with connect_peer(lightning_client, buy_response.offer.host, destination), \
         open_channel(lightning_client, destination, 1000000):
        # List peers
        list_peers_response = lightning_client.list_peers()

        # List channels
        list_channels_response = lightning_client.list_channels()

        # Pay the invoice
        payment = lightning_client.pay_invoice_sync(buy_response.offer.payment_request)
        preimage = payment.payment_preimage

        # Verify with the payment preimage and decryption key ciphertext
        decryption_key_cipher_bytes = buy_response.offer.key_cipher
        iv = buy_response.offer.iv
        encrypted_decryption_key = CEncryptedDecryptionKey.from_bytes(
            decryption_key_cipher_bytes
        )

        # Decrypt the decryption key
        decryption_key = encrypted_decryption_key.get_decryption_key(preimage, iv)
        serialized_decryption_key = decryption_key.get_bytes()

        get_response_squeak.SetDecryptionKey(serialized_decryption_key)
        CheckSqueak(get_response_squeak)

    # Check the server balance
    get_balance_response = admin_stub.LndWalletBalance(ln.WalletBalanceRequest())
    final_server_balance = get_balance_response.total_balance
    assert final_server_balance - initial_server_balance == 1000


def test_make_squeak(server_stub, admin_stub, signing_profile_id):
    # Create a new squeak using the new profile
    make_squeak_content = "Hello from the profile on the server!"
    make_squeak_response = admin_stub.MakeSqueak(
        squeak_admin_pb2.MakeSqueakRequest(
            profile_id=signing_profile_id,
            content=make_squeak_content,
        )
    )
    make_squeak_hash = make_squeak_response.squeak_hash
    assert len(make_squeak_hash) == 32 * 2

    # Get the new squeak from the server
    get_squeak_response = server_stub.GetSqueak(
        squeak_server_pb2.GetSqueakRequest(hash=make_squeak_hash)
    )
    get_squeak_response_squeak = squeak_from_msg(get_squeak_response.squeak)
    CheckSqueak(get_squeak_response_squeak, skipDecryptionCheck=True)
    assert get_hash(get_squeak_response_squeak) == make_squeak_hash

    # Get the squeak display item
    get_squeak_display_response = admin_stub.GetSqueakDisplay(
        squeak_admin_pb2.GetSqueakDisplayRequest(
            squeak_hash=make_squeak_hash,
        )
    )
    assert (
        get_squeak_display_response.squeak_display_entry.content_str
        == "Hello from the profile on the server!"
    )

    # Get the squeak profile
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=signing_profile_id,
        )
    )
    squeak_profile_address = get_squeak_profile_response.squeak_profile.address
    squeak_profile_name = get_squeak_profile_response.squeak_profile.profile_name

    # Get all squeak displays for the known address
    get_address_squeak_display_response = admin_stub.GetAddressSqueakDisplays(
        squeak_admin_pb2.GetAddressSqueakDisplaysRequest(address=squeak_profile_address)
    )
    assert len(get_address_squeak_display_response.squeak_display_entries) == 1
    for (
        squeak_display_entry
    ) in get_address_squeak_display_response.squeak_display_entries:
        assert squeak_display_entry.author_name == squeak_profile_name
        assert squeak_display_entry.author_address == squeak_profile_address


def test_make_reply_squeak(
    server_stub, admin_stub, saved_squeak_hash, signing_profile_id
):
    # Make another squeak as a reply
    reply_1_squeak_response = admin_stub.MakeSqueak(
        squeak_admin_pb2.MakeSqueakRequest(
            profile_id=signing_profile_id,
            content="Reply #1",
            replyto=saved_squeak_hash,
        )
    )
    reply_1_squeak_hash = reply_1_squeak_response.squeak_hash

    # Make a second squeak as a reply
    reply_2_squeak_response = admin_stub.MakeSqueak(
        squeak_admin_pb2.MakeSqueakRequest(
            profile_id=signing_profile_id,
            content="Reply #2",
            replyto=reply_1_squeak_hash,
        )
    )
    reply_2_squeak_hash = reply_2_squeak_response.squeak_hash

    # Get the squeak and check that the reply field is correct
    get_reply_squeak_display_response = admin_stub.GetSqueakDisplay(
        squeak_admin_pb2.GetSqueakDisplayRequest(
            squeak_hash=reply_2_squeak_hash,
        )
    )
    assert (
        get_reply_squeak_display_response.squeak_display_entry.squeak_hash
        == reply_2_squeak_hash
    )
    assert (
        get_reply_squeak_display_response.squeak_display_entry.reply_to
        == reply_1_squeak_hash
    )

    # Get the ancestors of the latest reply squeak
    get_ancestors_response = admin_stub.GetAncestorSqueakDisplays(
        squeak_admin_pb2.GetAncestorSqueakDisplaysRequest(
            squeak_hash=reply_2_squeak_hash,
        )
    )
    assert len(get_ancestors_response.squeak_display_entries) == 3


def test_post_squeak_rate_limit(server_stub, admin_stub, following_signing_key):
    # Make 10 squeak
    for i in range(10):
        try:
            block_height, block_hash = get_latest_block_info(lightning_client)
            squeak = make_squeak(
                nonfollowing_signing_key,
                "hello from itest!",
                block_hash,
                block_height,
            )
            squeak_msg = build_squeak_msg(squeak)
            server_stub.PostSqueak(
                squeak_server_pb2.PostSqueakRequest(squeak=squeak_msg)
            )
        except Exception as e:
            post_squeak_exception = e
    assert post_squeak_exception is not None


def test_make_signing_profile(server_stub, admin_stub):
    # Create a new signing profile
    profile_name = "test_signing_profile_name"
    create_signing_profile_response = admin_stub.CreateSigningProfile(
        squeak_admin_pb2.CreateSigningProfileRequest(
            profile_name=profile_name,
        )
    )
    profile_id = create_signing_profile_response.profile_id

    # Get the new squeak profile
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=profile_id,
        )
    )
    assert get_squeak_profile_response.squeak_profile.profile_name == profile_name
    squeak_profile_address = get_squeak_profile_response.squeak_profile.address

    # Get all signing profiles
    get_signing_profiles_response = admin_stub.GetSigningProfiles(
        squeak_admin_pb2.GetSigningProfilesRequest()
    )
    signing_profile_names = [
        profile.profile_name
        for profile in get_signing_profiles_response.squeak_profiles
    ]
    assert profile_name in signing_profile_names

    # Get squeak profile by address
    get_profile_by_address_response = admin_stub.GetSqueakProfileByAddress(
        squeak_admin_pb2.GetSqueakProfileByAddressRequest(
            address=squeak_profile_address
        )
    )
    assert get_profile_by_address_response.squeak_profile.profile_name == profile_name


def test_make_contact_profile(server_stub, admin_stub):
    # Create a new contact profile
    contact_name = "test_contact_profile_name"
    contact_signing_key = generate_signing_key()
    contact_address = get_address(contact_signing_key)
    create_contact_profile_response = admin_stub.CreateContactProfile(
        squeak_admin_pb2.CreateContactProfileRequest(
            profile_name=contact_name,
            address=contact_address,
        )
    )
    contact_profile_id = create_contact_profile_response.profile_id

    # Get all contact profiles
    get_contact_profiles_response = admin_stub.GetContactProfiles(
        squeak_admin_pb2.GetContactProfilesRequest()
    )
    contact_profile_names = [
        profile.profile_name
        for profile in get_contact_profiles_response.squeak_profiles
    ]
    assert contact_name in contact_profile_names


def test_set_profile_following(server_stub, admin_stub, contact_profile_id):
    # Get the existing profile
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=contact_profile_id,
        )
    )
    assert get_squeak_profile_response.squeak_profile.following == False

    # Set the profile to be following
    admin_stub.SetSqueakProfileFollowing(
        squeak_admin_pb2.SetSqueakProfileFollowingRequest(
            profile_id=contact_profile_id,
            following=True,
        )
    )

    # Get the squeak profile again
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=contact_profile_id,
        )
    )
    assert get_squeak_profile_response.squeak_profile.following == True


def test_set_profile_sharing(server_stub, admin_stub, contact_profile_id):
    # Get the existing profile
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=contact_profile_id,
        )
    )
    assert get_squeak_profile_response.squeak_profile.sharing == False

    # Set the profile to be sharing
    admin_stub.SetSqueakProfileSharing(
        squeak_admin_pb2.SetSqueakProfileSharingRequest(
            profile_id=contact_profile_id,
            sharing=True,
        )
    )

    # Get the squeak profile again
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=contact_profile_id,
        )
    )
    assert get_squeak_profile_response.squeak_profile.sharing == True


def test_delete_profile(server_stub, admin_stub, contact_profile_id):
    # Delete the profile
    admin_stub.DeleteSqueakProfile(
        squeak_admin_pb2.DeleteSqueakProfileRequest(
            profile_id=contact_profile_id,
        )
    )

    # Try to get the profile and fail
    with pytest.raises(Exception) as excinfo:
        admin_stub.GetSqueakProfile(
            squeak_admin_pb2.GetSqueakProfileRequest(
                profile_id=contact_profile_id,
            )
        )
    assert "Profile not found." in str(excinfo.value)


def test_get_following_squeaks(
    server_stub, admin_stub, saved_squeak_hash, signing_profile_id
):
    # Set the profile to be following
    admin_stub.SetSqueakProfileFollowing(
        squeak_admin_pb2.SetSqueakProfileFollowingRequest(
            profile_id=signing_profile_id,
            following=True,
        )
    )

    # Get all squeak displays for the known address
    get_followed_squeak_display_response = admin_stub.GetFollowedSqueakDisplays(
        squeak_admin_pb2.GetFollowedSqueakDisplaysRequest()
    )
    assert len(get_followed_squeak_display_response.squeak_display_entries) >= 1
    for (
        squeak_display_entry
    ) in get_followed_squeak_display_response.squeak_display_entries:
        # TODO: check the profile id of the squeak display entry
        # assert squeak_display_entry.profile_id == signing_profile_id
        pass


def test_delete_squeak(server_stub, admin_stub, saved_squeak_hash):
    # Delete the squeak
    admin_stub.DeleteSqueak(
        squeak_admin_pb2.DeleteSqueakRequest(squeak_hash=saved_squeak_hash)
    )

    # Try to get the squeak and fail
    with pytest.raises(Exception) as excinfo:
        server_stub.GetSqueak(
            squeak_server_pb2.GetSqueakRequest(hash=saved_squeak_hash)
        )
    assert "Squeak not found." in str(excinfo.value)


def test_create_peer(server_stub, admin_stub):
    # Add a new peer
    create_peer_response = admin_stub.CreatePeer(
        squeak_admin_pb2.CreatePeerRequest(
            host="fake_host",
            port=1234,
        )
    )
    peer_id = create_peer_response.peer_id

    # Get the new peer
    get_peer_response = admin_stub.GetPeer(
        squeak_admin_pb2.GetPeerRequest(
            peer_id=peer_id,
        )
    )
    assert get_peer_response.squeak_peer.host == "fake_host"
    assert get_peer_response.squeak_peer.port == 1234

    # Get all peers
    get_peers_response = admin_stub.GetPeers(squeak_admin_pb2.GetPeersRequest())
    peer_hosts = [squeak_peer.host for squeak_peer in get_peers_response.squeak_peers]
    assert "fake_host" in peer_hosts


def test_set_peer_downloading(server_stub, admin_stub, peer_id):
    # Get the peer
    get_peer_response = admin_stub.GetPeer(
        squeak_admin_pb2.GetPeerRequest(
            peer_id=peer_id,
        )
    )
    assert get_peer_response.squeak_peer.downloading == False

    # Set the peer to be downloading
    admin_stub.SetPeerDownloading(
        squeak_admin_pb2.SetPeerDownloadingRequest(
            peer_id=peer_id,
            downloading=True,
        )
    )

    # Get the peer again
    get_peer_response = admin_stub.GetPeer(
        squeak_admin_pb2.GetPeerRequest(
            peer_id=peer_id,
        )
    )
    assert get_peer_response.squeak_peer.downloading == True


def test_set_peer_uploading(server_stub, admin_stub, peer_id):
    # Get the peer
    get_peer_response = admin_stub.GetPeer(
        squeak_admin_pb2.GetPeerRequest(
            peer_id=peer_id,
        )
    )
    assert get_peer_response.squeak_peer.uploading == False

    # Set the peer to be uploading
    admin_stub.SetPeerUploading(
        squeak_admin_pb2.SetPeerUploadingRequest(
            peer_id=peer_id,
            uploading=True,
        )
    )

    # Get the peer again
    get_peer_response = admin_stub.GetPeer(
        squeak_admin_pb2.GetPeerRequest(
            peer_id=peer_id,
        )
    )
    assert get_peer_response.squeak_peer.uploading == True


def test_delete_peer(server_stub, admin_stub, peer_id):
    # Delete the peer
    admin_stub.DeletePeer(
        squeak_admin_pb2.DeletePeerRequest(
            peer_id=peer_id,
        )
    )

    # Try to get the peer and fail
    with pytest.raises(Exception) as excinfo:
        admin_stub.GetPeer(
            squeak_admin_pb2.GetPeerRequest(
                peer_id=peer_id,
            )
        )
    assert "Peer not found." in str(excinfo.value)


def test_list_channels(server_stub, admin_stub, lightning_client, saved_squeak_hash):
    # Get the squeak from the server
    get_response = server_stub.GetSqueak(
        squeak_server_pb2.GetSqueakRequest(hash=saved_squeak_hash)
    )
    get_response_squeak = squeak_from_msg(get_response.squeak)
    CheckSqueak(get_response_squeak, skipDecryptionCheck=True)

    # Generate a challenge to verify the offer
    expected_proof = generate_challenge_proof()
    encryption_key = get_response_squeak.GetEncryptionKey()
    challenge = get_challenge(encryption_key, expected_proof)

    # Buy the squeak data key
    buy_response = server_stub.GetOffer(
        squeak_server_pb2.GetOfferRequest(
            hash=saved_squeak_hash,
            challenge=challenge,
        )
    )
    assert buy_response.offer.payment_request.startswith("ln")

    # Decode the payment request string
    decode_pay_req_response = lightning_client.decode_pay_req(
        buy_response.offer.payment_request
    )
    destination = decode_pay_req_response.destination

    with connect_peer(lightning_client, buy_response.offer.host, destination), \
         open_channel(lightning_client, destination, 1000000):
        # List channels
        get_info_response = lightning_client.get_info()
        list_channels_response = admin_stub.LndListChannels(ln.ListChannelsRequest())

        assert len(list_channels_response.channels) > 0
        assert any([
            channel.remote_pubkey == get_info_response.identity_pubkey
            for channel in list_channels_response.channels
        ])

    list_channels_response = admin_stub.LndListChannels(ln.ListChannelsRequest())
    assert len(list_channels_response.channels) == 0


def test_send_coins(server_stub, admin_stub, lightning_client):
    new_address_response = admin_stub.LndNewAddress(ln.NewAddressRequest())
    send_coins_response = lightning_client.send_coins(new_address_response.address, 55555555)
    time.sleep(10)
    get_transactions_response = admin_stub.LndGetTransactions(ln.GetTransactionsRequest())

    assert any([
        transaction.tx_hash == send_coins_response.txid
        for transaction in get_transactions_response.transactions
    ])

def test_list_peers(server_stub, admin_stub, lightning_client, saved_squeak_hash):
    # Get the squeak from the server
    get_response = server_stub.GetSqueak(
        squeak_server_pb2.GetSqueakRequest(hash=saved_squeak_hash)
    )
    get_response_squeak = squeak_from_msg(get_response.squeak)
    CheckSqueak(get_response_squeak, skipDecryptionCheck=True)

    # Generate a challenge to verify the offer
    expected_proof = generate_challenge_proof()
    encryption_key = get_response_squeak.GetEncryptionKey()
    challenge = get_challenge(encryption_key, expected_proof)

    # Buy the squeak data key
    buy_response = server_stub.GetOffer(
        squeak_server_pb2.GetOfferRequest(
            hash=saved_squeak_hash,
            challenge=challenge,
        )
    )
    assert buy_response.offer.payment_request.startswith("ln")

    # Decode the payment request string
    decode_pay_req_response = lightning_client.decode_pay_req(
        buy_response.offer.payment_request
    )
    destination = decode_pay_req_response.destination

    get_info_response = lightning_client.get_info()

    admin_stub.LndConnectPeer(ln.ConnectPeerRequest(
        addr=ln.LightningAddress(
            pubkey=get_info_response.identity_pubkey,
            host="lnd_client",
        ),
    ))

    list_peers_response = admin_stub.LndListPeers(ln.ListPeersRequest())
    assert any([
        peer.pub_key == get_info_response.identity_pubkey
        for peer in list_peers_response.peers
    ])

    # Disconnect the peer
    admin_stub.LndDisconnectPeer(ln.DisconnectPeerRequest(
        pub_key=get_info_response.identity_pubkey,
    ))

    list_peers_response = admin_stub.LndListPeers(ln.ListPeersRequest())
    assert not any([
        peer.pub_key == get_info_response.identity_pubkey
        for peer in list_peers_response.peers
    ])

def test_open_channel(server_stub, admin_stub, lightning_client, saved_squeak_hash):
    # Get the squeak from the server
    get_response = server_stub.GetSqueak(
        squeak_server_pb2.GetSqueakRequest(hash=saved_squeak_hash)
    )
    get_response_squeak = squeak_from_msg(get_response.squeak)
    CheckSqueak(get_response_squeak, skipDecryptionCheck=True)

    # Generate a challenge to verify the offer
    expected_proof = generate_challenge_proof()
    encryption_key = get_response_squeak.GetEncryptionKey()
    challenge = get_challenge(encryption_key, expected_proof)

    # Buy the squeak data key
    buy_response = server_stub.GetOffer(
        squeak_server_pb2.GetOfferRequest(
            hash=saved_squeak_hash,
            challenge=challenge,
        )
    )
    assert buy_response.offer.payment_request.startswith("ln")

    # Decode the payment request string
    decode_pay_req_response = lightning_client.decode_pay_req(
        buy_response.offer.payment_request
    )
    destination = decode_pay_req_response.destination

    with connect_peer(lightning_client, buy_response.offer.host, destination):
        # List pending channels
        get_info_response = lightning_client.get_info()
        pending_channels_response = admin_stub.LndPendingChannels(ln.PendingChannelsRequest())
        assert len(pending_channels_response.pending_open_channels) == 0

        # Open the new channel
        open_channel_response = admin_stub.LndOpenChannelSync(ln.OpenChannelRequest(
            node_pubkey_string=get_info_response.identity_pubkey,
            local_funding_amount=1000000,
        ))

        pending_channels_response = admin_stub.LndPendingChannels(ln.PendingChannelsRequest())
        assert len(pending_channels_response.pending_open_channels) == 1

        subscribe_channel_events_response = admin_stub.LndSubscribeChannelEvents(ln.ChannelEventSubscription())
        for update in subscribe_channel_events_response:
            if update.HasField("active_channel"):
                channel_point = update.active_channel
                print("Channel now open: " + str(channel_point))
                break

        list_channels_response = admin_stub.LndListChannels(ln.ListChannelsRequest())
        assert len(list_channels_response.channels) == 1

        # Close the channel
        close_channel_response = admin_stub.LndCloseChannel(ln.CloseChannelRequest(
            channel_point=channel_point,
        ))
        for update in close_channel_response:
            if update.HasField("chan_close"):
                print("Channel now closed.")
                break

        list_channels_response = admin_stub.LndListChannels(ln.ListChannelsRequest())
        assert len(list_channels_response.channels) == 0


def test_connect_other_node(server_stub, admin_stub, other_server_stub, other_admin_stub, lightning_client, signing_profile_id, saved_squeak_hash):
    # Get all squeak displays
    get_followed_squeak_display_response = other_admin_stub.GetFollowedSqueakDisplays(
        squeak_admin_pb2.GetFollowedSqueakDisplaysRequest()
    )
    assert len(get_followed_squeak_display_response.squeak_display_entries) == 0

    # Add the main node as a peer
    create_peer_response = other_admin_stub.CreatePeer(
        squeak_admin_pb2.CreatePeerRequest(
            host="squeaknode",
            port=8774,
        )
    )
    peer_id = create_peer_response.peer_id

    # Set the peer to be downloading
    other_admin_stub.SetPeerDownloading(
        squeak_admin_pb2.SetPeerDownloadingRequest(
            peer_id=peer_id,
            downloading=True,
        )
    )

    # Get the squeak profile
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=signing_profile_id,
        )
    )
    squeak_profile_address = get_squeak_profile_response.squeak_profile.address
    squeak_profile_name = get_squeak_profile_response.squeak_profile.profile_name
    print("Got squeak profile: {} with address: {}".format(squeak_profile_name, squeak_profile_address))


    # Set the signing profile to be sharing on the main server
    admin_stub.SetSqueakProfileSharing(
        squeak_admin_pb2.SetSqueakProfileSharingRequest(
            profile_id=signing_profile_id,
            sharing=True,
        )
    )

    # Add the contact profile to the other server and set the profile to be following
    create_contact_profile_response = other_admin_stub.CreateContactProfile(
        squeak_admin_pb2.CreateContactProfileRequest(
            profile_name=squeak_profile_name,
            address=squeak_profile_address,
        )
    )
    contact_profile_id = create_contact_profile_response.profile_id
    other_admin_stub.SetSqueakProfileFollowing(
        squeak_admin_pb2.SetSqueakProfileFollowingRequest(
            profile_id=contact_profile_id,
            following=True,
        )
    )

    # Sync squeaks
    sync_squeaks_response = other_admin_stub.SyncSqueaks(
        squeak_admin_pb2.SyncSqueaksRequest(),
    )
    #time.sleep(10)
    print(sync_squeaks_response)
    assert peer_id in sync_squeaks_response.sync_result.completed_peer_ids

    # Get the buy offer
    get_buy_offers_response = other_admin_stub.GetBuyOffers(
        squeak_admin_pb2.GetBuyOffersRequest(
            squeak_hash=saved_squeak_hash,
        )
    )
    print(get_buy_offers_response)
    assert len(get_buy_offers_response.offers) > 0

    offer = get_buy_offers_response.offers[0]

    with connect_peer(lightning_client, offer.node_host, offer.node_pubkey), \
         open_channel(lightning_client, offer.node_pubkey, 1000000):

        list_channels_response = lightning_client.list_channels()
        print(list_channels_response)

        # Pay the offer
        pay_offer_response = other_admin_stub.PayOffer(
            squeak_admin_pb2.PayOfferRequest(
                offer_id=offer.offer_id,
            )
        )
        print(pay_offer_response)
        assert pay_offer_response.sent_payment_id > 0

        # Get the squeak display item
        get_squeak_display_response = other_admin_stub.GetSqueakDisplay(
            squeak_admin_pb2.GetSqueakDisplayRequest(
                squeak_hash=saved_squeak_hash,
            )
        )
        assert (
            get_squeak_display_response.squeak_display_entry.content_str
            == "Hello from the profile on the server!"
        )

        # Get all sent payments
        get_sent_payments_response = other_admin_stub.GetSentPayments(
            squeak_admin_pb2.GetSentPaymentsRequest(),
        )
        squeak_hashes = [sent_payment.squeak_hash for sent_payment in get_sent_payments_response.sent_payments]
        assert saved_squeak_hash in squeak_hashes

        # Get the single sent payment
        for sent_payment in get_sent_payments_response.sent_payments:
            if sent_payment.squeak_hash == saved_squeak_hash:
                sent_payment_id = sent_payment.sent_payment_id
        get_sent_payment_response = other_admin_stub.GetSentPayment(
            squeak_admin_pb2.GetSentPaymentRequest(
                sent_payment_id=sent_payment_id,
            ),
        )
        assert saved_squeak_hash == get_sent_payment_response.sent_payment.squeak_hash


def test_download_single_squeak(server_stub, admin_stub, other_server_stub, other_admin_stub, lightning_client, signing_profile_id, saved_squeak_hash):

    # Add the main node as a peer
    create_peer_response = other_admin_stub.CreatePeer(
        squeak_admin_pb2.CreatePeerRequest(
            host="squeaknode",
            port=8774,
        )
    )
    peer_id = create_peer_response.peer_id

    # Set the peer to be downloading
    other_admin_stub.SetPeerDownloading(
        squeak_admin_pb2.SetPeerDownloadingRequest(
            peer_id=peer_id,
            downloading=True,
        )
    )

    # Get the squeak profile
    get_squeak_profile_response = admin_stub.GetSqueakProfile(
        squeak_admin_pb2.GetSqueakProfileRequest(
            profile_id=signing_profile_id,
        )
    )
    squeak_profile_address = get_squeak_profile_response.squeak_profile.address
    squeak_profile_name = get_squeak_profile_response.squeak_profile.profile_name
    print("Got squeak profile: {} with address: {}".format(squeak_profile_name, squeak_profile_address))


    # Set the signing profile to be sharing on the main server
    admin_stub.SetSqueakProfileSharing(
        squeak_admin_pb2.SetSqueakProfileSharingRequest(
            profile_id=signing_profile_id,
            sharing=True,
        )
    )

    # Add the contact profile to the other server and set the profile to be following
    create_contact_profile_response = other_admin_stub.CreateContactProfile(
        squeak_admin_pb2.CreateContactProfileRequest(
            profile_name=squeak_profile_name,
            address=squeak_profile_address,
        )
    )
    contact_profile_id = create_contact_profile_response.profile_id
    other_admin_stub.SetSqueakProfileFollowing(
        squeak_admin_pb2.SetSqueakProfileFollowingRequest(
            profile_id=contact_profile_id,
            following=True,
        )
    )


    # Get the squeak display item (should be empty)
    get_squeak_display_response = other_admin_stub.GetSqueakDisplay(
        squeak_admin_pb2.GetSqueakDisplayRequest(
            squeak_hash=saved_squeak_hash,
        )
    )
    assert get_squeak_display_response.squeak_display_entry.squeak_hash == ""
    # Get the buy offer (should be empty)
    get_buy_offers_response = other_admin_stub.GetBuyOffers(
        squeak_admin_pb2.GetBuyOffersRequest(
            squeak_hash=saved_squeak_hash,
        )
    )
    print(get_buy_offers_response)
    assert len(get_buy_offers_response.offers) == 0

    # Download squeak
    sync_squeak_response = other_admin_stub.SyncSqueak(
        squeak_admin_pb2.SyncSqueakRequest(
            squeak_hash=saved_squeak_hash,
        ),
    )
    # time.sleep(10)
    print(sync_squeak_response)
    assert peer_id in sync_squeak_response.sync_result.completed_peer_ids

    # Get the squeak display item
    get_squeak_display_response = other_admin_stub.GetSqueakDisplay(
        squeak_admin_pb2.GetSqueakDisplayRequest(
            squeak_hash=saved_squeak_hash,
        )
    )
    assert get_squeak_display_response.squeak_display_entry != None
    # Get the buy offer
    get_buy_offers_response = other_admin_stub.GetBuyOffers(
        squeak_admin_pb2.GetBuyOffersRequest(
            squeak_hash=saved_squeak_hash,
        )
    )
    print(get_buy_offers_response)
    assert len(get_buy_offers_response.offers) > 0


def test_sign_data(server_stub, admin_stub, signing_profile_id):
    # Create a new squeak using the new profile
    data_to_sign = generate_challenge_proof()
    sign_data_response = admin_stub.SignData(
        squeak_admin_pb2.SignDataRequest(
            profile_id=signing_profile_id,
            data=data_to_sign,
        )
    )
    signature = sign_data_response.signature
    print("signature: {}".format(signature.hex()))
    assert len(signature) > 0
