"""Ryu/OpenFlow 1.3 controller for the Smart Content Delivery System.

Ports: h1=1, h2=2, h3=3, h4=4. Clients use VIP 10.0.0.100:8080. The controller
proxies ARP for the VIP, picks a backend per new TCP connection, and installs
forward/reverse flows that rewrite the VIP <-> backend addresses.

Backend eligibility = manually enabled AND healthy (monitor).  The two are
tracked separately so a health heartbeat never undoes a manual disable.
When a backend turns unhealthy its installed flows are deleted immediately.

Selection policies (POST /smartcdn/policy/<name>):
  roundrobin : rotate across eligible backends            (default)
  adaptive   : rotate across eligible backends whose probe latency is not
               degraded (> DEGRADED_FACTOR x best + DEGRADED_MARGIN_MS)
  static     : always the first eligible backend, h3 first (no balancing;
               use as the baseline in experiments)

REST:
  GET  /smartcdn/status
  POST /smartcdn/health            {"server":"h3","healthy":true,"latency_ms":1.2}
  POST /smartcdn/policy/{roundrobin|adaptive|static}
  POST /smartcdn/server/{h3|h4}/{up|down}      (manual, graceful)
"""
import json
import math
import threading
import time

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.lib.packet import arp, ethernet, ether_types, ipv4, packet, tcp
from ryu.app.wsgi import ControllerBase, WSGIApplication, route
from webob import Response
from ryu.ofproto import ofproto_v1_3


VIP = "10.0.0.100"
VIP_MAC = "00:00:00:00:00:64"
CDN_PORT = 8080

BACKENDS = {
    "h3": {"ip": "10.0.0.3", "mac": "00:00:00:00:00:03", "port": 3},
    "h4": {"ip": "10.0.0.4", "mac": "00:00:00:00:00:04", "port": 4},
}

POLICIES = ("roundrobin", "adaptive", "static")
LATENCY_ALPHA = 0.5          # smoothing for probe latency
DEGRADED_FACTOR = 2.0
DEGRADED_MARGIN_MS = 5.0
HEALTH_STALE_SECONDS = 6.0  # Healthy reports arrive every ~1 second from monitor.py
HEALTH_WATCH_INTERVAL = 1.0


class SmartCDNController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {"wsgi": WSGIApplication}

    def __init__(self, *args, **kwargs):
        super(SmartCDNController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.backend_enabled = {n: True for n in BACKENDS}    # manual switch
        self.backend_healthy = {n: False for n in BACKENDS}   # unknown until verified by monitor
        self.backend_selections = {n: 0 for n in BACKENDS}
        self.backend_latency_ms = {n: None for n in BACKENDS}
        self.backend_last_check = {n: None for n in BACKENDS}
        self.backend_last_report_monotonic = {n: None for n in BACKENDS}
        self.round_robin_index = 0
        self.policy = "roundrobin"
        self.state_lock = threading.RLock()

        wsgi = kwargs["wsgi"]
        wsgi.register(SmartCDNRestController, {"smart_cdn_app": self})
        self.health_watch = hub.spawn(self._health_freshness_loop)
        self.logger.info("Smart CDN controller started; VIP %s:%s", VIP, CDN_PORT)

    def _health_freshness_loop(self):
        """Fail closed if a previously healthy backend stops reporting health."""
        while True:
            hub.sleep(HEALTH_WATCH_INTERVAL)
            now = time.monotonic()
            stale = []
            with self.state_lock:
                for name in BACKENDS:
                    last = self.backend_last_report_monotonic[name]
                    if (self.backend_healthy[name] and last is not None
                            and now - last > HEALTH_STALE_SECONDS):
                        self.backend_healthy[name] = False
                        self.backend_latency_ms[name] = None
                        self.backend_last_check[name] = time.strftime("%Y-%m-%d %H:%M:%S")
                        stale.append(name)
            for name in stale:
                self.logger.error("Backend %s health report stale; marking UNHEALTHY", name)
                self.flush_backend_flows(name)

    # ---------------------------------------------------------- state / REST
    def eligible_backends(self):
        return [n for n in BACKENDS
                if self.backend_enabled[n] and self.backend_healthy[n]]

    def status_report(self):
        with self.state_lock:
            eligible = self.eligible_backends()
            return {
                "virtual_service": {"ip": VIP, "port": CDN_PORT, "mac": VIP_MAC},
                "policy": self.policy,
                "eligible": eligible,
                "backends": {
                    name: {
                        "ip": c["ip"], "port": c["port"],
                        "enabled": self.backend_enabled[name],
                        "healthy": self.backend_healthy[name],
                        "eligible": name in eligible,
                        "latency_ms": self.backend_latency_ms[name],
                        "last_health_check": self.backend_last_check[name],
                        "selections": self.backend_selections[name],
                    } for name, c in BACKENDS.items()
                },
            }

    def set_policy(self, policy):
        if policy not in POLICIES:
            raise ValueError("Policy must be one of: " + ", ".join(POLICIES))
        with self.state_lock:
            self.policy = policy
        self.logger.warning("Selection policy set to %s", policy)
        return self.status_report()

    def set_backend_enabled(self, server_id, enabled):
        if server_id not in BACKENDS:
            raise ValueError("Unknown backend. Use h3 or h4.")
        with self.state_lock:
            self.backend_enabled[server_id] = enabled
        self.logger.warning("Backend %s manually %s (existing connections kept)",
                            server_id, "ENABLED" if enabled else "DISABLED")
        return self.status_report()

    def report_backend_health(self, server_id, healthy, latency_ms=None):
        if server_id not in BACKENDS:
            raise ValueError("Unknown backend. Use h3 or h4.")
        healthy = bool(healthy)
        with self.state_lock:
            was_healthy = self.backend_healthy[server_id]
            self.backend_healthy[server_id] = healthy
            self.backend_last_report_monotonic[server_id] = time.monotonic()
            if healthy and latency_ms is not None:
                old = self.backend_latency_ms[server_id]
                self.backend_latency_ms[server_id] = (
                    float(latency_ms) if old is None else
                    LATENCY_ALPHA * float(latency_ms) + (1 - LATENCY_ALPHA) * old)
            elif not healthy:
                self.backend_latency_ms[server_id] = None
            self.backend_last_check[server_id] = time.strftime("%Y-%m-%d %H:%M:%S")

        if was_healthy != healthy:
            self.logger.warning("Backend %s is now %s", server_id,
                                "HEALTHY" if healthy else "UNHEALTHY")
            if not healthy:
                self.flush_backend_flows(server_id)
        return self.status_report()

    def flush_backend_flows(self, name):
        """Delete flows steering traffic to/from a failed backend."""
        b = BACKENDS[name]
        for dp in list(self.datapaths.values()):
            ofp, p = dp.ofproto, dp.ofproto_parser
            # Everything that outputs to the backend's switch port (forward
            # CDN flows and learned flows).
            dp.send_msg(p.OFPFlowMod(
                datapath=dp, table_id=ofp.OFPTT_ALL, command=ofp.OFPFC_DELETE,
                out_port=b["port"], out_group=ofp.OFPG_ANY, match=p.OFPMatch()))
            # Reverse CDN flows (backend -> client) match the backend IP.
            dp.send_msg(p.OFPFlowMod(
                datapath=dp, table_id=ofp.OFPTT_ALL, command=ofp.OFPFC_DELETE,
                out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                match=p.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                 ipv4_src=b["ip"])))
        self.logger.warning("Flushed flows for failed backend %s", name)

    def choose_backend(self):
        with self.state_lock:
            eligible = self.eligible_backends()
            if not eligible:
                return None
            pool = eligible
            if self.policy == "static":
                pool = eligible[:1]
            elif self.policy == "adaptive":
                known = {
                    n: self.backend_latency_ms[n]
                    for n in eligible
                    if self.backend_latency_ms[n] is not None
                }
                if known:
                    best = min(known.values())
                    limit = best * DEGRADED_FACTOR + DEGRADED_MARGIN_MS

                    # Do not treat an unknown latency as 0 ms (the fastest).
                    # Prefer measured backends until a missing measurement arrives.
                    pool = [
                        n for n in eligible
                        if n in known and known[n] <= limit
                    ]

                    # The best measured backend should always pass this threshold,
                    # but retain a safe fallback if numeric edge cases arise.
                    if not pool:
                        pool = [min(known, key=known.get)]

                    self.logger.info(
                        "Adaptive selector: measured_latency_ms=%s "
                        "threshold_ms=%.2f pool=%s",
                        {n: round(v, 2) for n, v in known.items()},
                        limit,
                        pool,
                    )
                else:
                    # No latency data yet: do not invent a latency ranking.
                    pool = eligible
                    self.logger.warning(
                        "Adaptive latency unavailable; using all eligible "
                        "backends until measurements arrive: %s",
                        pool,
                    )
            selected = pool[self.round_robin_index % len(pool)]
            self.round_robin_index += 1
            self.backend_selections[selected] += 1
            return selected, dict(BACKENDS[selected])

    # ------------------------------------------------------------ OpenFlow
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self.datapaths[datapath.id] = datapath
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)
        self.logger.info("Switch connected: dpid=%s", datapath.id)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        instructions = [parser.OFPInstructionActions(
            ofproto.OFPIT_APPLY_ACTIONS, actions)]
        datapath.send_msg(parser.OFPFlowMod(
            datapath=datapath, priority=priority, match=match,
            instructions=instructions, idle_timeout=idle_timeout))

    def proxy_arp(self, datapath, in_port, eth, arp_packet):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        reply = packet.Packet()
        reply.add_protocol(ethernet.ethernet(
            dst=eth.src, src=VIP_MAC, ethertype=ether_types.ETH_TYPE_ARP))
        reply.add_protocol(arp.arp(
            hwtype=1, proto=ether_types.ETH_TYPE_IP, hlen=6, plen=4,
            opcode=arp.ARP_REPLY, src_mac=VIP_MAC, src_ip=VIP,
            dst_mac=arp_packet.src_mac, dst_ip=arp_packet.src_ip))
        reply.serialize()
        datapath.send_msg(parser.OFPPacketOut(
            datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=[parser.OFPActionOutput(in_port)], data=reply.data))

    def install_cdn_flows(self, datapath, client_ip, client_mac, client_port,
                          client_tcp_port, backend_name, backend):
        parser = datapath.ofproto_parser
        ip_type = ether_types.ETH_TYPE_IP
        forward_match = parser.OFPMatch(
            eth_type=ip_type, ip_proto=6, ipv4_src=client_ip, ipv4_dst=VIP,
            tcp_src=client_tcp_port, tcp_dst=CDN_PORT)
        self.add_flow(datapath, 100, forward_match, [
            parser.OFPActionSetField(ipv4_dst=backend["ip"]),
            parser.OFPActionSetField(eth_dst=backend["mac"]),
            parser.OFPActionOutput(backend["port"])], idle_timeout=120)
        reverse_match = parser.OFPMatch(
            eth_type=ip_type, ip_proto=6, ipv4_src=backend["ip"],
            ipv4_dst=client_ip, tcp_src=CDN_PORT, tcp_dst=client_tcp_port)
        self.add_flow(datapath, 100, reverse_match, [
            parser.OFPActionSetField(ipv4_src=VIP),
            parser.OFPActionSetField(eth_src=VIP_MAC),
            parser.OFPActionOutput(client_port)], idle_timeout=120)
        self.logger.info("Installed CDN flows: client=%s:%s backend=%s (%s)",
                         client_ip, client_tcp_port, backend_name, backend["ip"])

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})
        self.mac_to_port[dpid][eth.src] = in_port

        arp_packet = pkt.get_protocol(arp.arp)
        if (arp_packet is not None and arp_packet.opcode == arp.ARP_REQUEST
                and arp_packet.dst_ip == VIP):
            self.proxy_arp(datapath, in_port, eth, arp_packet)
            return

        ip_packet = pkt.get_protocol(ipv4.ipv4)
        tcp_packet = pkt.get_protocol(tcp.tcp)
        if (ip_packet is not None and tcp_packet is not None
                and ip_packet.dst == VIP and tcp_packet.dst_port == CDN_PORT):
            # Only a new SYN may create a backend mapping.
            if (not (tcp_packet.bits & tcp.TCP_SYN)
                    or (tcp_packet.bits & tcp.TCP_ACK)) :
                self.logger.warning("Dropping non-SYN packet without flow from %s",
                                    ip_packet.src)
                return
            selected = self.choose_backend()
            if selected is None:
                self.logger.error("No eligible backend; dropping request from %s",
                                  ip_packet.src)
                return
            backend_name, backend = selected
            self.logger.info("New CDN connection %s:%s -> VIP selected %s [%s]",
                             ip_packet.src, tcp_packet.src_port, backend_name,
                             self.policy)
            self.install_cdn_flows(datapath, ip_packet.src, eth.src, in_port,
                                   tcp_packet.src_port, backend_name, backend)
            datapath.send_msg(parser.OFPPacketOut(
                datapath=datapath, buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=in_port,
                actions=[parser.OFPActionSetField(ipv4_dst=backend["ip"]),
                         parser.OFPActionSetField(eth_dst=backend["mac"]),
                         parser.OFPActionOutput(backend["port"])],
                data=msg.data))
            return

        # Learning-switch fallback for all other traffic.
        dst = eth.dst
        out_port = self.mac_to_port[dpid].get(dst, ofproto.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]
        if out_port != ofproto.OFPP_FLOOD:
            self.add_flow(datapath, 1,
                          parser.OFPMatch(in_port=in_port, eth_dst=dst),
                          actions, idle_timeout=120)
        data = msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        datapath.send_msg(parser.OFPPacketOut(
            datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port,
            actions=actions, data=data))


def _json(obj, status=200):
    return Response(status=status, content_type="application/json",
                    body=json.dumps(obj, indent=2).encode("utf-8"))


class SmartCDNRestController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(SmartCDNRestController, self).__init__(req, link, data, **config)
        self.app = data["smart_cdn_app"]

    @route("smartcdn", "/smartcdn/status", methods=["GET"])
    def get_status(self, req, **kwargs):
        return _json(self.app.status_report())

    @route("smartcdn", "/smartcdn/health", methods=["POST"])
    def report_health(self, req, **kwargs):
        try:
            d = json.loads(req.body.decode("utf-8"))
            healthy = d.get("healthy")
            if not isinstance(healthy, bool):
                raise ValueError("'healthy' must be true or false")
            lat = d.get("latency_ms")
            if lat is not None:
                lat = float(lat)
                if not math.isfinite(lat) or lat < 0:
                    raise ValueError("'latency_ms' must be a finite, non-negative number")
            return _json(self.app.report_backend_health(d.get("server"), healthy, lat))
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            return _json({"error": str(exc)}, 400)

    @route("smartcdn", "/smartcdn/policy/{policy}", methods=["POST"])
    def set_policy(self, req, **kwargs):
        try:
            return _json(self.app.set_policy(kwargs.get("policy", "").lower()))
        except ValueError as exc:
            return _json({"error": str(exc)}, 400)

    @route("smartcdn", "/smartcdn/server/{server_id}/{state}", methods=["POST"])
    def set_server_state(self, req, **kwargs):
        state = kwargs.get("state", "").lower()
        if state not in ("up", "down"):
            return _json({"error": "state must be up or down"}, 400)
        try:
            return _json(self.app.set_backend_enabled(
                kwargs.get("server_id", ""), state == "up"))
        except ValueError as exc:
            return _json({"error": str(exc)}, 404)
