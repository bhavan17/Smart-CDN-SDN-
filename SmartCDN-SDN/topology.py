"""Mininet topology for the Smart Content Delivery System.

Switch port map (used by controller.py):
  s1-eth1 <-> h1 (client 1)
  s1-eth2 <-> h2 (client 2)
  s1-eth3 <-> h3 (content server A)
  s1-eth4 <-> h4 (content server B)
"""
from mininet.topo import Topo


class CDNTopo(Topo):
    def build(self):
        # Keep these links in this order: the controller uses ports 3 and 4
        # for the two backends in this fixed lab topology.
        s1 = self.addSwitch(
            "s1",
            dpid="0000000000000001",
            protocols="OpenFlow13",
        )

        h1 = self.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")
        h3 = self.addHost("h3", ip="10.0.0.3/24", mac="00:00:00:00:00:03")
        h4 = self.addHost("h4", ip="10.0.0.4/24", mac="00:00:00:00:00:04")

        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)
        self.addLink(h4, s1)


topos = {"cdntopo": (lambda: CDNTopo())}
