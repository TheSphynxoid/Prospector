"""Importing this module registers every source adapter with the registry."""
from prospector.sources.adzuna import Adzuna
from prospector.sources.alerts import AlertsSource
from prospector.sources.arbeitnow import Arbeitnow
from prospector.sources.codeur import Codeur
from prospector.sources.freelancer import Freelancer
from prospector.sources.github_bounties import GitHubBounties
from prospector.sources.golangprojects import Golangprojects
from prospector.sources.gsoc import GSoC
from prospector.sources.hn import HackerNewsHiring
from prospector.sources.himalayas import Himalayas
from prospector.sources.jobicy import Jobicy
from prospector.sources.keejob import Keejob
from prospector.sources.company_boards import CompanyBoards
from prospector.sources.outreachy import Outreachy
from prospector.sources.registry import register
from prospector.store.companies import CompanyRepo
from prospector.sources.remoteok import RemoteOK
from prospector.sources.remotive import Remotive
from prospector.sources.tunisietravail import TunisieTravail
from prospector.sources.weworkremotely import WeWorkRemotely

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
register("weworkremotely")(lambda s, m: WeWorkRemotely())
register("jobicy")(lambda s, m: Jobicy())
register("golangprojects")(lambda s, m: Golangprojects())
register("tunisietravail")(lambda s, m: TunisieTravail())
register("codeur")(lambda s, m: Codeur())
register("gsoc")(lambda s, m: GSoC())
register("outreachy")(lambda s, m: Outreachy())
register("company_boards")(lambda s, m: CompanyBoards(CompanyRepo(m.conn)))
