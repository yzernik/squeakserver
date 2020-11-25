import uuid

import grpc
import pytest
from squeak.params import SelectParams

from proto import squeak_admin_pb2, squeak_admin_pb2_grpc, squeak_server_pb2_grpc
from tests.util import generate_signing_key, get_address, load_lightning_client


@pytest.fixture(autouse=True)
def select_mainnet_params():
    # Set the network to simnet
    SelectParams("simnet")


@pytest.fixture
def server_stub():
    with grpc.insecure_channel("squeaknode:8774") as server_channel:
        yield squeak_server_pb2_grpc.SqueakServerStub(server_channel)


@pytest.fixture
def other_server_stub():
    with grpc.insecure_channel("squeaknode_other:8774") as server_channel:
        yield squeak_server_pb2_grpc.SqueakServerStub(server_channel)


@pytest.fixture
def admin_stub():
    with open('/squeaknode-certs/service.pem', 'rb') as f:
        creds = grpc.ssl_channel_credentials(f.read())
    options = (
        ('grpc.ssl_target_name_override', 'localhost'),
        ('grpc.default_authority', 'localhost'),
    )
    #with grpc.insecure_channel("squeaknode:8994") as admin_channel:
    with grpc.secure_channel("squeaknode:8994", creds, options) as admin_channel:
        yield squeak_admin_pb2_grpc.SqueakAdminStub(admin_channel)


@pytest.fixture
def other_admin_stub():
    with open('/squeaknode-certs_other/service.pem', 'rb') as f:
        creds = grpc.ssl_channel_credentials(f.read())
    options = (
        ('grpc.ssl_target_name_override', 'localhost'),
        ('grpc.default_authority', 'localhost'),
    )
    #with grpc.insecure_channel("squeaknode_other:8994") as admin_channel:
    with grpc.secure_channel("squeaknode_other:8994", creds, options) as admin_channel:
        yield squeak_admin_pb2_grpc.SqueakAdminStub(admin_channel)


@pytest.fixture
def lightning_client():
    return load_lightning_client()


@pytest.fixture
def following_signing_key(server_stub, admin_stub):
    # Create a signing key
    signing_key = generate_signing_key()

    # Create a new contact profile
    profile_name = "following_contact_{}".format(uuid.uuid1())
    profile_address = get_address(signing_key)
    create_contact_profile_response = admin_stub.CreateContactProfile(
        squeak_admin_pb2.CreateContactProfileRequest(
            profile_name=profile_name,
            address=profile_address,
        )
    )
    contact_profile_id = create_contact_profile_response.profile_id

    # Set the profile to be following
    admin_stub.SetSqueakProfileFollowing(
        squeak_admin_pb2.SetSqueakProfileFollowingRequest(
            profile_id=contact_profile_id,
            following=True,
        )
    )

    # Yield the signing key
    yield signing_key


@pytest.fixture
def nonfollowing_signing_key(server_stub, admin_stub):
    # Create a signing key
    signing_key = generate_signing_key()

    # Yield the signing key
    yield signing_key


@pytest.fixture
def signing_profile_id(server_stub, admin_stub):
    # Create a new signing profile
    profile_name = "fake_signing_profile_{}".format(uuid.uuid1())
    create_signing_profile_response = admin_stub.CreateSigningProfile(
        squeak_admin_pb2.CreateSigningProfileRequest(
            profile_name=profile_name,
        )
    )
    profile_id = create_signing_profile_response.profile_id
    yield profile_id


@pytest.fixture
def contact_profile_id(server_stub, admin_stub):
    # Create a new contact profile
    contact_name = "fake_contact_profile_{}".format(uuid.uuid1())
    contact_signing_key = generate_signing_key()
    contact_address = get_address(contact_signing_key)
    create_contact_profile_response = admin_stub.CreateContactProfile(
        squeak_admin_pb2.CreateContactProfileRequest(
            profile_name=contact_name,
            address=contact_address,
        )
    )
    contact_profile_id = create_contact_profile_response.profile_id
    yield contact_profile_id


@pytest.fixture
def saved_squeak_hash(server_stub, admin_stub, signing_profile_id):
    # Create a new squeak using the new profile
    make_squeak_content = "Hello from the profile on the server!"
    make_squeak_response = admin_stub.MakeSqueak(
        squeak_admin_pb2.MakeSqueakRequest(
            profile_id=signing_profile_id,
            content=make_squeak_content,
        )
    )
    squeak_hash = make_squeak_response.squeak_hash
    yield squeak_hash


@pytest.fixture
def peer_id(server_stub, admin_stub):
    # Create a new peer
    create_peer_response = admin_stub.CreatePeer(
        squeak_admin_pb2.CreatePeerRequest(
            host="fake_host",
            port=1234,
        )
    )
    peer_id = create_peer_response.peer_id
    yield peer_id
