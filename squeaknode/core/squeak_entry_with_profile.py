from typing import NamedTuple
from typing import Optional

from squeaknode.core.squeak_entry import SqueakEntry
from squeaknode.core.squeak_profile import SqueakProfile


class SqueakEntryWithProfile(NamedTuple):
    squeak_entry: SqueakEntry
    squeak_profile: Optional[SqueakProfile]
