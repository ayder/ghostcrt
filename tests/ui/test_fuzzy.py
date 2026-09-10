from ghostcrt.models import Host
from ghostcrt.ui.widgets.fuzzy import filter_hosts, subsequence_match


def test_subsequence():
    assert subsequence_match("pd", "prod-db")
    assert subsequence_match("PD", "prod-db")
    assert not subsequence_match("xd", "prod-db")
    assert subsequence_match("", "anything")


def test_filter_hosts():
    hosts = [
        Host(alias="prod-db", hostname="10.0.0.1"),
        Host(alias="web", hostname="web.example.com"),
    ]
    assert [h.alias for h in filter_hosts(hosts, "pd")] == ["prod-db"]
    assert [h.alias for h in filter_hosts(hosts, "web.ex")] == ["web"]
    assert len(filter_hosts(hosts, "")) == 2
