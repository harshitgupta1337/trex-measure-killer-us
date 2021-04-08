#!/usr/bin/python
import sys, getopt
import argparse;
import time
import stl_path
from trex_stl_lib.api import *

H_VER = "trex-x v0.1 "

class t_global(object):
     args=None;


import time
import json
import string

ip_range = {'src': {'start': "16.0.0.1", 'end': "16.0.0.254"},
            'dst': {'start': "48.0.0.1",  'end': "48.0.0.254"}}

def create_pkt (size, vm, vlan):
    # Create base packet and pad it to size
    if vlan:
        base_pkt = Ether()/Dot1Q(vlan = vlan)/IP()
    else:
        base_pkt = Ether()/IP()
    pad = max(0, size - len(base_pkt)) * 'x'
    pkt = STLPktBuilder(pkt = base_pkt/pad,
                        vm = vm)
    return pkt

def single_run(client, streams, rate, duration):
    return stats

def get_opackets(stats):
    opackets = stats[0]["opackets"] + stats[1]["opackets"]
    return opackets

def get_drops(stats):
    opackets = stats[0]["opackets"] + stats[1]["opackets"]
    ipackets = stats[0]["ipackets"] + stats[1]["ipackets"]
    drops = opackets - ipackets
    return drops

def get_vm(direction):
    if direction == 0:
        src = ip_range["src"]
        dst = ip_range["dst"]
    else:
        src = ip_range["dst"]
        dst = ip_range["src"]

    vm = STLVM()
    # define two vars (src and dst)
    vm.var(name="src",min_value=src['start'],max_value=src['end'],size=4,op="inc")
    vm.var(name="dst",min_value=dst['start'],max_value=dst['end'],size=4,op="inc")
    # write them
    vm.write(fv_name="src",pkt_offset= "IP.src")
    vm.write(fv_name="dst",pkt_offset= "IP.dst")
    # fix checksum
    vm.fix_chksum()

    return vm
    
def start_experiment(rate, duration, profile, outfile, kpps, bidir=True, vlan=None):
    client = STLClient(server=t_global.args.ip)
    client.connect()

    if bidir:
        directions = [0,1]
    else:
        directions = [0]

    client.reset(ports=directions)
    client.set_port_attr(ports = directions, promiscuous = False)

    latency_pgids = []
    for direction in directions:
        vm = get_vm(direction)
        streams = []
        total_pps = 1000
        for i in range(len(profile)):
            x = profile[i]
            pps = total_pps * x['ratio']
            pkt = create_pkt(x["size"], vm, vlan)
            streams.append(STLStream(packet=pkt, mode=STLTXCont(pps = pps), isg=x['isg']))

        latency_pgid = 12+direction
        lat_stream = STLStream(packet = create_pkt(256, vm, vlan), mode = STLTXCont(pps=1000), 
                            flow_stats = STLFlowLatencyStats(pg_id = latency_pgid))
        streams.append(lat_stream)
        latency_pgids.append(latency_pgid)

        client.add_streams(streams, ports=[direction])

    if rate:
        mult = "%d%%"%rate
    elif kpps:
        mult = "%fkpps"%kpps

    # Launch warmup traffic
    client.start(ports = directions, mult=mult, duration=30) # warmup duration is 30 secs # TODO Make this config
    client.wait_on_traffic(ports = directions)

    client.clear_stats()
    client.start(ports = directions, mult=mult, duration=duration)
    client.wait_on_traffic(ports = directions)

    stats = client.get_stats()
    with open(outfile, "w") as f:
        f.write(json.dumps(stats))
        f.close()

    # TODO only processing 1 direction
    pgid_stats = client.get_pgid_stats(latency_pgids[0])
    global_lat_stats = pgid_stats["latency"]
    print (global_lat_stats)

    client.disconnect()
 
def process_options ():
    parser = argparse.ArgumentParser(
        usage="""
        Start trex daemon sudo ./t-rex-64 -c 4 -i

        This script is meant to find the traffic load that is able to fully load the DUT. 
        A traffic profile is provided and the script increases the PPS for the traffic profile starting from 

    """,
    description="example for TRex api",
    epilog=" written by harshitg@gatech.edu");

    parser.add_argument("--outfile",
                        dest="outfile",
                        help='Path where trex stats need to be written',
                        type = str,
                        default = "/tmp/trex_metrics.out"
                        )

    parser.add_argument("--imix-profile",
                        dest="imix_profile",
                        help='IMIX profile path',
                        type = str,
                        required = True
                        )

    parser.add_argument("--ip",
                        dest="ip",
                        help='remote trex ip default local',
                        default="127.0.0.1",
                        type = str
                        )

    parser.add_argument("--kpps",
                        dest="kpps",
                        help='Kilo packets per second',
                        default=None,
                        type = float
                        )

    parser.add_argument("--vlan",
                        dest="vlan",
                        help='VLAN ID',
                        default=None,
                        type = int
                        )

    parser.add_argument("--rate",
                        dest="rate",
                        help='rate in %% that is sent to this function',
                        default=None,
                        type = int
                        )

    parser.add_argument("--bidirectional",
                        dest="bidir",
                        help='Generate traffic in both directions',
                        action='store_true'
                        )

    parser.add_argument("--duration",
                        dest="duration",
                        help='Seconds for running single run',
                        default=15,
                        type = int
                        )

    t_global.args = parser.parse_args();
    print(t_global.args)

def read_profile(profilePath):
    x = None
    with open(profilePath, "r") as f:
        x = json.load(f)
    f.close()
    return x

def main():
    process_options()
    if t_global.args.rate and t_global.args.kpps:
        print ("Can't specify both %% rate and kpps at the same time. Aborting")
        exit(1)
    profile = read_profile(t_global.args.imix_profile)
    if profile:
        start_experiment(t_global.args.rate, t_global.args.duration, profile, t_global.args.outfile, t_global.args.kpps, t_global.args.bidir, t_global.args.vlan)
            
if __name__ == "__main__":
    main()
