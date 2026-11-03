"""Importing this module registers every source adapter with the registry."""
from prospector.sources.adzuna import Adzuna
from prospector.sources.alerts import AlertsSource
from prospector.sources.arbeitnow import Arbeitnow
from prospector.sources.freelancer import Freelancer
from prospector.sources.github_bounties import GitHubBounties
from prospector.sources.hn import HackerNewsHiring
from prospector.sources.himalayas import Himalayas
from prospector.sources.keejob import Keejob
from prospector.sources.registry import register
from prospector.sources.remoteok import RemoteOK
from prospector.sources.remotive import Remotive

register("remotive")(lambda s, m: Remotive())
register("remoteok")(lambda s, m: RemoteOK())
register("himalayas")(lambda s, m: Himalayas())
register("arbeitnow")(lambda s, m: Arbeitnow())
register("adzuna")(lambda s, m: Adzuna(s.adzuna_app_id, s.adzuna_app_key)
                   if s.adzuna_app_id and s.adzuna_app_key else None)
register("hn")(lambda s, m: HackerNewsHiring())
register("github_bounties")(lambda s, m: GitHubBounties(s.github_token.get_secret_value())
                            if s.github_token else None)
register("freelancer")(lambda s, m: Freelancer())
register("alerts")(lambda s, m: AlertsSource(m))
register("keejob")(lambda s, m: Keejob())
