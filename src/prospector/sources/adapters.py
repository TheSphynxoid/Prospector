"""Importing this module registers every source adapter with the registry."""
from prospector.sources.arbeitnow import Arbeitnow
from prospector.sources.himalayas import Himalayas
from prospector.sources.registry import register
from prospector.sources.remoteok import RemoteOK
from prospector.sources.remotive import Remotive

register("remotive")(lambda s, m: Remotive())
register("remoteok")(lambda s, m: RemoteOK())
register("himalayas")(lambda s, m: Himalayas())
register("arbeitnow")(lambda s, m: Arbeitnow())
